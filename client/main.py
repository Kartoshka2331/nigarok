import flet
import tkinter.messagebox as messagebox
import tkinter
import socket
import asyncio
import threading
import time
import pyperclip
import os
import json
from tunnel_protocol import *


with open("config.json", "r") as file: CONFIG = json.load(file)
SERVER_LIST = CONFIG["servers"]

with open("logs.txt", "w", encoding="utf-8") as file: file.write("")
def write_log_file(text):
    with open("logs.txt", "a", encoding="utf-8") as file:
        file.write(text + "\n")

def load_credentials():
    if os.path.exists("credentials.json"):
        with open("credentials.json", "r") as f:
            return json.load(f)
    return {"login": "", "password": ""}
def save_credentials(login, password):
    with open("credentials.json", "w") as f:
        json.dump({"login": login, "password": password}, f)

def show_error(message):
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    tkinter.messagebox.showerror("Ошибка", message)
    root.destroy()


class LoginWindow:
    def __init__(self, page: flet.Page):
        page.window.width = 510
        page.window.height = 330
        page.window.resizable = False
        page.window.maximizable = False
        page.update()
        page.window.center()

        self.page = page
        self.page.title = "Nigarok | Вход"

        credentials = load_credentials()
        self.login_field = flet.TextField(label="Логин", value=credentials.get("login", ""), width=450)
        self.password_field = flet.TextField(label="Пароль", value=credentials.get("password", ""), password=True, can_reveal_password=True, width=450)
        self.server_dropdown = flet.Dropdown(label="Сервер", options=[flet.dropdown.Option(server["name"]) for server in SERVER_LIST], value=SERVER_LIST[0]["name"], width=225)
        self.continue_button = flet.ElevatedButton(text="Продолжить", on_click=self.next, width=200)

    def build(self):
        self.page.clean()
        self.page.add(
            flet.Container(
                content=flet.Column(
                    [
                        self.login_field,
                        self.password_field,
                        flet.Container(height=2),
                        self.server_dropdown,
                        flet.Container(height=8),
                        self.continue_button
                    ],
                    alignment=flet.MainAxisAlignment.CENTER,
                    horizontal_alignment=flet.CrossAxisAlignment.CENTER,
                    spacing=10
                ),
                alignment=flet.alignment.center,
                expand=True
            )
        )

    def next(self, event=None):
        login = self.login_field.value
        password = self.password_field.value
        server_info = next(server for server in SERVER_LIST if server["name"] == self.server_dropdown.value)

        if not login or not password:
            show_error("Вы не ввели логин или пароль")
            return

        try:
            if self.test_credentials(login, password, server_info):
                save_credentials(login, password)
                self.page.clean()
                ConfigWindow(self.page, login, password, server_info)
            else:
                show_error("Неверный логин или пароль")
        except (socket.timeout, ConnectionRefusedError, OSError):
            show_error("Сервер недоступен")

    @staticmethod
    def test_credentials(login, password, server_info):
        with socket.create_connection((server_info["ip"], server_info["port"]), timeout=2) as sock:
            sock.sendall(f"__test__:{login}:{password}\n".encode())
            response = sock.recv(10)
            return bool(response)

class ConfigWindow:
    def __init__(self, page: flet.Page, login, password, server_info):
        page.window.width = 275
        page.window.height = 200
        page.window.resizable = False
        page.window.maximizable = False
        page.update()
        page.window.center()

        self.page = page
        self.page.title = "Nigarok | Конфигурация"

        self.login = login
        self.password = password
        self.server_info = server_info

        self.port_field = flet.TextField(label="Введите порт", on_change=self.filter_numbers, width=200)
        self.launch_button = flet.ElevatedButton(text="Запустить", on_click=self.launch, width=150)

        self.page.add(
            flet.Container(
                content=flet.Column(
                    [
                        self.port_field,
                        flet.Container(height=8),
                        self.launch_button
                    ],
                    alignment=flet.MainAxisAlignment.CENTER,
                    horizontal_alignment=flet.CrossAxisAlignment.CENTER,
                    spacing=10
                ),
                alignment=flet.alignment.center,
                expand=True
            )
        )

    def filter_numbers(self, event=None):
        self.port_field.value = "".join(filter(str.isdigit, self.port_field.value))
        self.page.update()

    def launch(self, event=None):
        try:
            port = int(self.port_field.value)
            if not self.test_local_port(port):
                show_error("Порт недоступен")
                self.page.update()
                return

            self.page.clean()

            TunnelWindow(self.page, self.login, self.password, self.server_info, port)
        except:
            show_error("Введите корректный порт")
            self.page.update()

    @staticmethod
    def test_local_port(port):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            return False

class TunnelWindow:
    def __init__(self, page: flet.Page, login, password, server_info, local_port):
        page.window.width = 460
        page.window.height = 430
        page.window.resizable = False
        page.window.maximizable = False
        page.update()
        page.window.center()

        self.page = page
        self.page.title = "Nigarok | Подключено"

        self.login = login
        self.password = password
        self.server_ip = server_info["ip"]
        self.server_port = server_info["port"]
        self.local_port = local_port

        self.loop = None
        self.async_tasks = []

        self.sock = None
        self.reader = None
        self.writer = None

        self.running = False
        self.reconnecting = False

        self.connection_map = {}

        self.remote_address = flet.TextField(value="—", read_only=True)
        self.traffic_up = 0
        self.traffic_down = 0

        self.log_view = flet.ListView(height=140, expand=True, auto_scroll=True, padding=flet.Padding(left=10, top=10, right=10, bottom=10))

        self.copy_status = flet.Text(value="", color="green")
        self.traffic_label = flet.Text(value="↑ 0 Б   ↓ 0 Б")

        self.ping_dot = flet.Container(width=12, height=12, bgcolor=flet.Colors.GREY, border_radius=6, tooltip="Пинг: —", right=10, bottom=10, alignment=flet.alignment.center)
        self.page.overlay.append(self.ping_dot)
        self.page.update()

        self.page.add(
            flet.Container(
                content=flet.Column(
                    [
                        flet.Card(content=self.log_view, width=390, height=175),
                        flet.Row([self.remote_address, flet.IconButton(icon=flet.Icons.CONTENT_COPY, on_click=self.copy_ip)], alignment=flet.MainAxisAlignment.CENTER),
                        self.copy_status,
                        self.traffic_label,
                        flet.Container(height=8),
                        flet.ElevatedButton(text="Остановить", on_click=self.stop, width=150, bgcolor="red")
                    ],
                    alignment=flet.MainAxisAlignment.CENTER,
                    horizontal_alignment=flet.CrossAxisAlignment.CENTER,
                    spacing=10
                ),
                alignment=flet.alignment.center,
                expand=True
            )
        )

        self.start()

    def log(self, text: str, level: str = "info"):
        text = text + "." if not text.endswith(".") else text

        prefix = time.strftime("[%H:%M:%S] ")

        color_map = {
            "info": flet.Colors.WHITE,
            "success": flet.Colors.LIGHT_GREEN,
            "warning": flet.Colors.AMBER,
            "error": flet.Colors.RED,
        }

        color = color_map.get(level, flet.Colors.WHITE)
        full = prefix + text

        self.log_view.controls.append(flet.Text(full, size=12, color=color))
        self.page.update()

        print(full)
        write_log_file(full)

    def copy_ip(self, event=None):
        def clear_copy(self):
            self.copy_status.value = ""
            self.page.update()

        pyperclip.copy(self.remote_address.value)
        self.copy_status.value = "Скопировано!"
        self.page.update()

        threading.Timer(1, lambda: clear_copy(self)).start()

    def update_traffic(self):
        def frm(x):
            if x >= 1_000_000:
                return f"{x / 1_048_576:.1f} МБ"
            elif x >= 1000:
                return f"{x / 1024:.1f} КБ"
            else:
                return f"{x} Б"

        self.traffic_label.value = f"↑ {frm(self.traffic_up)}   ↓ {frm(self.traffic_down)}"
        self.traffic_label.update()

    def connect_loop(self):
        self.log("Попытка подключения к серверу...", "info")

        def run():
            while not self.running:
                if self.sock:
                    try: self.sock.shutdown(socket.SHUT_RDWR)
                    except: pass

                    try: self.sock.close()
                    except: pass

                try:
                    self.sock = socket.create_connection((self.server_ip, self.server_port))
                    self.sock.settimeout(5.0)
                    self.sock.sendall(f"{self.login}:{self.password}\n".encode())

                    loop = asyncio.new_event_loop()
                    threading.Thread(target=loop.run_forever, daemon=True).start()

                    reader, writer = asyncio.run_coroutine_threadsafe(asyncio.open_connection(sock=self.sock), loop).result()

                    self.loop = loop
                    self.reader = reader
                    self.writer = writer

                    self.running = True
                    self.log("Соединение с сервером установлено.", "success")

                    self.async_tasks = []
                    self.async_tasks.append(asyncio.run_coroutine_threadsafe(self.server_listener_loop(), self.loop))
                    self.async_tasks.append(asyncio.run_coroutine_threadsafe(self.ping_loop(), self.loop))

                    break
                except Exception as error:
                    self.log(f"Ошибка подключения: {error}", "error")
                    self.log("Повторная попытка через 5 секунд...", "warning")
                    time.sleep(5)

        threading.Thread(target=run, daemon=True).start()

    async def server_listener_loop(self):
        self.log("Слушатель сервера запущен.", "info")

        while self.running:
            try:
                message_type, connection_id, payload = await unpack_message(self.reader)

                try:
                    await self.handle_incoming_message(message_type, connection_id, payload)
                except Exception as error:
                    self.log(f"Ошибка обработки пакета: {error}", "error")
            except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
                if self.running:
                    self.log("Соединение с сервером потеряно.", "error")

                self.reconnect()
                break

    async def handle_incoming_message(self, message_type, connection_id, payload):
        if message_type == PONG:
            try:
                ms = int((time.time() - float(payload.decode())) * 1000)

                if ms < 30: color = flet.Colors.LIGHT_GREEN
                elif ms < 60: color = flet.Colors.LIME
                elif ms < 120: color = flet.Colors.YELLOW
                elif ms < 160: color = flet.Colors.AMBER
                elif ms < 200: color = flet.Colors.ORANGE
                elif ms < 300: color = flet.Colors.DEEP_ORANGE
                elif ms < 400: color = flet.Colors.RED_ACCENT
                else: color = flet.Colors.RED

                self.ping_dot.bgcolor = color
                self.ping_dot.tooltip = f"Пинг: {ms} мс"
            except:
                self.ping_dot.bgcolor = flet.Colors.GREY
                self.ping_dot.tooltip = "Пинг: ?"

            self.ping_dot.update()

        elif message_type == NEW_CONNECTION:
            remote_port = int.from_bytes(payload, byteorder="big")
            if connection_id == 0:
                self.remote_address.value = f"{self.server_ip}:{remote_port}"
                self.page.update()

                return

            self.log(f"Новое соединение #{connection_id}.", "success")

            local_sock = socket.socket()
            try:
                local_sock.connect(("127.0.0.1", self.local_port))
            except Exception:
                self.log("Ошибка подключения к локальному порту.", "error")
                self.sock.sendall(pack_message(CLOSE, connection_id))

                return

            self.connection_map[connection_id] = local_sock
            await self.pipe_local_to_server(connection_id, local_sock)

        elif message_type == DATA:
            self.traffic_down += len(payload)
            self.update_traffic()
            if connection_id in self.connection_map:
                try:
                    self.connection_map[connection_id].sendall(payload)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    if connection_id in self.connection_map:
                        try: self.connection_map[connection_id].shutdown(socket.SHUT_RDWR)
                        except: pass
                        try: self.connection_map[connection_id].close()
                        except: pass

                        del self.connection_map[connection_id]

        elif message_type == CLOSE:
            self.log(f"Соединение #{connection_id} закрыто.", "warning")

            if connection_id in self.connection_map:
                try: self.connection_map[connection_id].shutdown(socket.SHUT_RDWR)
                except: pass
                try: self.connection_map[connection_id].close()
                except: pass

                del self.connection_map[connection_id]

    async def pipe_local_to_server(self, connection_id, local_sock):
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue(maxsize=10000)

        async def reader():
            try:
                while self.running:
                    if local_sock.fileno() == -1:
                        break

                    data = await loop.sock_recv(local_sock, 4096)
                    if not data:
                        break

                    self.traffic_up += len(data)
                    self.update_traffic()

                    try:
                        await asyncio.wait_for(queue.put(data), timeout=1)
                    except asyncio.TimeoutError:
                        break
            except Exception as error:
                self.log(f"Ошибка чтения из локального сокета: {error}", "error")
            finally:
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass

        async def writer():
            try:
                while self.running:
                    data = await queue.get()
                    if not data:
                        break

                    try:
                        if self.sock.fileno() == -1:
                            break

                        message = pack_message(DATA, connection_id, data)
                        await loop.sock_sendall(self.sock, message)
                    except Exception as error:
                        self.log(f"Ошибка отправки данных серверу: {error}", "error")
                        break
            finally:
                try:
                    message = pack_message(CLOSE, connection_id)
                    await loop.sock_sendall(self.sock, message)
                except:
                    pass

                try: local_sock.shutdown(socket.SHUT_RDWR)
                except: pass
                local_sock.close()

                if connection_id in self.connection_map:
                    self.connection_map.pop(connection_id, None)

        asyncio.create_task(reader())
        asyncio.create_task(writer())

    async def ping_loop(self):
        while self.running:
            try:
                ts = str(time.time()).encode()
                self.sock.sendall(pack_message(PING, 0, ts))
            except:
                self.ping_dot.bgcolor = flet.Colors.GREY
                self.ping_dot.tooltip = "Пинг: -1"
                self.ping_dot.update()

                break

            await asyncio.sleep(2)

    def start(self):
        threading.Thread(target=self.connect_loop, daemon=True).start()

    def stop(self, event=None):
        self.log("Остановка клиента.", "warning")

        self.running = False

        try:
            if self.writer:
                self.writer.close()
        except:
            pass

        try:
            if self.sock:
                try: self.sock.close()
                except: pass
        except:
            pass

        for async_task in self.async_tasks:
            try: async_task.cancel()
            except: pass

        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

        self.remote_address.value = "—"
        self.page.clean()
        self.page.overlay.clear()
        LoginWindow(self.page).build()

    def reconnect(self):
        if not self.running:
            return

        self.reconnecting = True
        self.running = False

        self.log("Переподключение...", "info")

        try:
            if self.writer:
                self.writer.close()
        except:
            pass

        try:
            if self.sock:
                try: self.sock.close()
                except: pass
        except:
            pass

        for async_task in self.async_tasks:
            try: async_task.cancel()
            except: pass

        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

        self.connect_loop()

        self.reconnecting = False


def main(page: flet.Page):
    page.theme = flet.Theme(
        font_family="Roboto",
        color_scheme=flet.ColorScheme(
            primary=flet.Colors.TEAL_ACCENT_700,
            background=flet.Colors.TEAL_50,
            on_primary=flet.Colors.TEAL_800,
            primary_container=flet.Colors.PINK,
            on_primary_container=flet.Colors.PINK_300,
            secondary=flet.Colors.PINK,
            on_background=flet.Colors.BLACK,
            on_secondary=flet.Colors.BLACK,
            on_surface=flet.Colors.TEAL_100,
            surface_variant=flet.Colors.TEAL_200,
        )
    )
    if page.theme_mode == flet.ThemeMode.DARK: page.bgcolor = flet.Colors.BROWN_500
    else: page.bgcolor = flet.Colors.BLUE_GREY_900

    LoginWindow(page).build()

if __name__ == "__main__":
    flet.app(target=main, view=flet.AppView.FLET_APP)
