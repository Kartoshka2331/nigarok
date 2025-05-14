import socket
import threading
import random
import signal
import logging
import os
import queue as queue_lib
import json
from tunnel_protocol import *


with open("config.json", "r") as file: CONFIG = json.load(file)
BIND_HOST = CONFIG.get("host", "0.0.0.0")
BIND_PORT = CONFIG.get("port", 13882)
ALLOWED_PORT_RANGE = CONFIG.get("allowed_port_range", [1024, 65535])
ACCOUNTS = CONFIG.get("accounts", [])

if os.path.exists("logs.txt"): os.remove("logs.txt")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("logs.txt", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

shutdown_event = threading.Event()
used_ports = set()
clients = {}
clients_lock = threading.Lock()


class TunnelClientHandler:
    def __init__(self, sock):
        self.sock = sock
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.sock.settimeout(5.0)

        self.connection_map = {}
        self.lock = threading.Lock()
        self.remote_port = self.allocate_port()
        self.login = None
        self.running = True

        threading.Thread(target=self.listen_loop, daemon=True).start()

    @staticmethod
    def allocate_port():
        while True:
            port = random.randint(*ALLOWED_PORT_RANGE)
            if port not in used_ports:
                used_ports.add(port)
                return port

    def listen_loop(self):
        try:
            auth_data = self.sock.recv(1024).decode().strip()

            if auth_data.startswith("__test__:"):
                parts = auth_data.split(":", 2)
                if len(parts) == 3:
                    _, login, password = parts
                    if any(account["login"] == login and account["password"] == password for account in ACCOUNTS):
                        self.sock.sendall(b"OK")
                self.sock.close()
                return

            if ":" not in auth_data:
                logging.warning("Неверный формат авторизации. Отключение.")

                self.sock.close()
                return

            self.login, password = auth_data.split(":", 1)
            if not any(account["login"] == self.login and account["password"] == password for account in ACCOUNTS):
                logging.warning(f"Неверные данные авторизации для логина: {self.login}.")

                self.sock.close()
                return

            self.sock.sendall(pack_message(NEW_CONNECTION, 0, self.remote_port.to_bytes(4, "big")))

            logging.info(f"Клиент подключился с адреса {self.sock.getpeername()}.")
            logging.info(f"Авторизация успешна: {self.login}.")

            threading.Thread(target=self.handle_listener, daemon=True).start()
        except Exception as error:
            logging.error(f"Ошибка авторизации клиента: {error}")

            self.running = False
            return

        while self.running:
            try:
                message_type, connection_id, payload = unpack_message(self.sock)

                if message_type == PING:
                    self.sock.sendall(pack_message(PONG, connection_id, payload))
                elif message_type == DATA:
                    if connection_id in self.connection_map:
                        self.connection_map[connection_id].sendall(payload)
                elif message_type == CLOSE:
                    if connection_id in self.connection_map:
                        self.connection_map[connection_id].close()
                        del self.connection_map[connection_id]
            except (BrokenPipeError, ConnectionResetError, OSError) as error:
                if isinstance(error, ConnectionResetError) or (isinstance(error, OSError) and error.errno in {104, 10054}):
                    logging.info(f"Клиент {self.login} отключился.")
                else:
                    logging.warning(f"Проблема с клиентом {self.login}: {error}")

                self.running = False
                with clients_lock:
                    clients.pop(self.sock, None)

                break
            except Exception as error:
                logging.error(f"Ошибка при получении данных от {self.login}: {error}")

                self.running = False
                with clients_lock:
                    if self.sock in clients:
                        del clients[self.sock]
                break

    def handle_listener(self):
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        listener.settimeout(1.0)

        try:
            listener.bind((BIND_HOST, self.remote_port))
            listener.listen()

            logging.info(f"Прослушка порта {self.remote_port} запущена для {self.login}.")

            while self.running:
                try:
                    connection, address = listener.accept()
                    connection_id = random.randint(1, 2 ** 31 - 1)

                    with self.lock:
                        self.connection_map[connection_id] = connection

                    logging.info(f"Новое входящее соединение от {address} ({self.login}|{connection_id}).")
                    self.sock.sendall(pack_message(NEW_CONNECTION, connection_id, self.remote_port.to_bytes(4, "big")))
                    threading.Thread(target=self.forward_data, args=(connection, connection_id), daemon=True).start()

                except socket.timeout:
                    continue

                except (BrokenPipeError, ConnectionResetError, OSError) as error:
                    logging.warning(f"Ошибка слушателя для {self.login}: {error}")
                    self.running = False
                    with clients_lock:
                        clients.pop(self.sock, None)
                    break

                except Exception as error:
                    logging.error(f"Ошибка при обработке входящего соединения: {error}")
                    break

        except Exception as error:
            logging.error(f"Не удалось запустить слушатель порта: {error}")
            self.running = False

    def forward_data(self, connection, connection_id):
        queue = queue_lib.Queue(maxsize=1000)

        def send_loop():
            while self.running:
                try:
                    data = queue.get(timeout=5)
                    if data is None:
                        break

                    self.sock.sendall(pack_message(DATA, connection_id, data))
                except queue_lib.Empty:
                    continue
                except Exception as error:
                    logging.error(f"Ошибка отправки данных на клиент {self.login}: {error}")
                    break

        threading.Thread(target=send_loop, daemon=True).start()

        try:
            connection.settimeout(10.0)
            while True:
                try:
                    data = connection.recv(4096)
                    if not data:
                        break

                    try:
                        queue.put(data, timeout=1)
                    except queue_lib.Full:
                        logging.warning(f"Буфер переполнен, данные отброшены ({self.login}|{connection_id}).")
                        break
                except socket.timeout:
                    logging.warning(f"Таймаут чтения из локального соединения ({self.login}|{connection_id}).")
                    break
        except Exception as error:
            if not (isinstance(error, OSError) and error.errno == 9):
                logging.error(f"Ошибка чтения из локального соединения ({self.login}|{connection_id}): {error}")
        finally:
            queue.put(None)

            try: connection.shutdown(socket.SHUT_RDWR)
            except: pass

            connection.close()
            try: self.sock.sendall(pack_message(CLOSE, connection_id))
            except: pass
            with self.lock: self.connection_map.pop(connection_id, None)
            logging.info(f"Соединение {self.login}|{connection_id} закрыто.")


signal.signal(signal.SIGINT, lambda s, f: shutdown_event.set())
signal.signal(signal.SIGTERM, lambda s, f: shutdown_event.set())

def main():
    try:
        server_sock = socket.socket()
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((BIND_HOST, BIND_PORT))
        server_sock.listen()
        server_sock.settimeout(1.0)

        logging.info(f"Сервер запущен на {BIND_HOST}:{BIND_PORT}.")

        while not shutdown_event.is_set():
            try:
                client_sock, address = server_sock.accept()

                threading.Thread(target=lambda: TunnelClientHandler(client_sock), daemon=True).start()

                with clients_lock:
                    clients[client_sock] = True
            except socket.timeout:
                continue
            except Exception as error:
                logging.error(f"Ошибка при подключении клиента: {error}")

        logging.info("Остановка сервера...")

        server_sock.close()
    except Exception as error:
        logging.critical(f"Критическая ошибка запуска сервера: {error}")

if __name__ == "__main__":
    main()
