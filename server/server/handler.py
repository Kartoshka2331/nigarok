import asyncio
import socket
import random
import logging
from typing import Dict, Optional, List

from config.types import Config
from protocol.tunnel_protocol import PackageType, pack_package, unpack_package, ProtocolError


class TunnelClientHandler:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, config: Config, clients_lock: asyncio.Lock, clients: Dict, used_ports: set):
        self.reader = reader
        self.writer = writer
        self.config = config
        self.clients_lock = clients_lock
        self.clients = clients
        self.used_ports = used_ports
        self.sock = writer.get_extra_info("socket")
        self.client_ip = self.sock.getpeername()[0] if self.sock else "unknown"
        self.connection_map: Dict[int, asyncio.StreamWriter] = {}
        self.lock = asyncio.Lock()
        self.remote_port: Optional[int] = None
        self.login: Optional[str] = None
        self.running = True
        self.tasks: List[asyncio.Task] = []
        self.logger = logging.getLogger(__name__)

    def allocate_port(self) -> int:
        allowed_range = self.config["allowed_port_range"]
        for _ in range(100):
            port = random.randint(allowed_range[0], allowed_range[1])
            if port not in self.used_ports:
                self.used_ports.add(port)
                return port

        raise RuntimeError("Failed to allocate port after maximum attempts")

    async def close_writer(self) -> None:
        if self.writer and not self.writer.is_closing():
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except (ConnectionResetError, OSError):
                pass

        self.writer = None

    async def close_connection(self, connection_id: int) -> None:
        async with self.lock:
            writer = self.connection_map.pop(connection_id, None)
            if writer:
                try:
                    if not writer.is_closing():
                        writer.close()
                        await writer.wait_closed()
                except (ConnectionResetError, OSError):
                    pass

                self.logger.info(f"Connection {self.login}|{connection_id} closed.", extra={"client_ip": self.client_ip})

    async def cleanup(self) -> None:
        self.logger.debug(f"Starting cleanup for {self.client_ip}, tasks: {len(self.tasks)}, connections: {len(self.connection_map)}.", extra={"client_ip": self.client_ip})

        self.running = False
        for task in self.tasks:
            if not task.done():
                task.cancel()

        if self.tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*self.tasks, return_exceptions=True), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        self.tasks.clear()

        async with self.lock:
            for connection_id in list(self.connection_map):
                await self.close_connection(connection_id)
            self.connection_map.clear()

        if self.remote_port:
            async with self.clients_lock:
                self.used_ports.discard(self.remote_port)
            self.remote_port = None

        async with self.clients_lock:
            self.clients.pop(self.sock, None)

        await self.close_writer()
        self.logger.debug(f"Cleanup completed for client {self.login or "unknown"}.", extra={"client_ip": self.client_ip})

    async def authenticate(self) -> bool:
        try:
            auth_data = (await asyncio.wait_for(self.reader.read(self.config["limits"]["max_auth_size"]), timeout=self.config["timeouts"]["auth"])).decode().strip()

            if len(auth_data) > self.config["limits"]["max_auth_size"]:
                self.logger.warning("Auth data exceeds maximum size.", extra={"client_ip": self.client_ip})
                return False

            if self.writer is None or self.writer.is_closing():
                self.logger.warning("Writer is closed or None before authentication.", extra={"client_ip": self.client_ip})
                return False

            if auth_data.startswith("__test__:"):
                parts = auth_data.split(":", 2)
                if len(parts) != 3:
                    return False

                login, password = parts[1], parts[2]
                self.login = login

                if not isinstance(self.config["accounts"], list):
                    self.logger.error("Invalid accounts configuration: expected list.", extra={"client_ip": self.client_ip})
                    return False

                if any(account.get("login") == login and account.get("password") == password for account in self.config["accounts"]):
                    self.logger.debug(f"Test credentials successful for {login}.", extra={"client_ip": self.client_ip})
                    try:
                        self.writer.write(b"OK")
                        await self.writer.drain()
                    except (ConnectionResetError, OSError) as error:
                        self.logger.warning(f"Failed to send response for test auth: {error}", extra={"client_ip": self.client_ip})
                    finally:
                        await self.close_writer()

                    return False

                return False

            if ":" not in auth_data:
                self.logger.warning("Invalid authentication format: missing colon.", extra={"client_ip": self.client_ip})
                return False

            login, password = auth_data.split(":", 1)

            if not isinstance(self.config["accounts"], list):
                self.logger.error("Invalid accounts configuration: expected list.", extra={"client_ip": self.client_ip})
                return False

            for account in self.config["accounts"]:
                if not isinstance(account, dict):
                    self.logger.error(f"Invalid account entry: {account}.", extra={"client_ip": self.client_ip})
                    return False

                if account.get("login") == login and account.get("password") == password:
                    self.login = login
                    try:
                        self.remote_port = self.allocate_port()
                    except RuntimeError as error:
                        self.logger.error(f"Failed to allocate port: {error}", extra={"client_ip": self.client_ip})
                        return False

                    try:
                        self.writer.write(pack_package(PackageType.NEW_CONNECTION, 0, self.remote_port.to_bytes(4, "big"), max_payload_size=self.config["limits"]["max_data_size"]))
                        await self.writer.drain()
                    except (ConnectionResetError, OSError) as error:
                        self.logger.warning(f"Failed to send NEW_CONNECTION test package: {error}", extra={"client_ip": self.client_ip})
                        return False

                    self.logger.info(f"Authentication successful for {self.login}.", extra={"client_ip": self.client_ip})
                    return True

            self.logger.warning(f"Invalid credentials for login: {login}.", extra={"client_ip": self.client_ip})
            return False

        except (asyncio.TimeoutError, UnicodeDecodeError, ConnectionResetError, OSError) as error:
            self.logger.warning(f"Authentication failed: {error}", extra={"client_ip": self.client_ip})
            return False
        except Exception as error:
            self.logger.error(f"Unexpected error during authentication: {error}", exc_info=True, extra={"client_ip": self.client_ip})
            return False

    async def listen_loop(self) -> None:
        try:
            if not await self.authenticate():
                await self.cleanup()
                return

            if self.writer is None or self.writer.is_closing():
                self.logger.warning("Writer closed after authentication, stopping listen_loop.", extra={"client_ip": self.client_ip})
                await self.cleanup()
                return

            self.tasks.append(asyncio.create_task(self.handle_listener()))
            while self.running:
                try:
                    package_type, connection_id, payload = await asyncio.wait_for(unpack_package(self.reader, max_payload_size=self.config["limits"]["max_data_size"]), timeout=self.config["timeouts"]["read"])
                    if not self.running:
                        break

                    if package_type == PackageType.PING:
                        async with self.lock:
                            if self.writer is None or self.writer.is_closing():
                                self.logger.warning("Writer closed during PING processing.", extra={"client_ip": self.client_ip})
                                break

                            self.writer.write(pack_package(PackageType.PONG, connection_id, payload, max_payload_size=self.config["limits"]["max_data_size"]))
                            await asyncio.wait_for(self.writer.drain(), timeout=self.config["timeouts"]["write"])
                    elif package_type == PackageType.DATA:
                        async with self.lock:
                            if connection_id in self.connection_map:
                                try:
                                    self.connection_map[connection_id].write(payload)
                                    await self.connection_map[connection_id].drain()
                                except (ConnectionResetError, OSError):
                                    await self.close_connection(connection_id)
                    elif package_type == PackageType.CLOSE:
                        await self.close_connection(connection_id)
                    else:
                        self.logger.warning(f"Unexpected package type: {package_type}.", extra={"client_ip": self.client_ip})
                except asyncio.TimeoutError:
                    self.logger.debug("Read timeout in listen_loop.", extra={"client_ip": self.client_ip})
                    continue
                except ProtocolError as error:
                    if isinstance(error.__cause__, asyncio.IncompleteReadError):
                        self.logger.info(f"Client {self.login} disconnected.", extra={"client_ip": self.client_ip})
                        break

                    self.logger.debug(f"Protocol error in listen_loop: {error}", extra={"client_ip": self.client_ip})
                    continue
                except (ConnectionResetError, ConnectionAbortedError, OSError) as error:
                    self.logger.info(f"Client {self.login} disconnected.", extra={"client_ip": self.client_ip})
                    break
                except Exception as error:
                    self.logger.error(f"Unexpected error in listen_loop: {error}", exc_info=True, extra={"client_ip": self.client_ip})
                    break
        except Exception as error:
            self.logger.error(f"Critical error in listen_loop: {error}", exc_info=True, extra={"client_ip": self.client_ip})
        finally:
            await self.cleanup()

    async def handle_listener(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        listener.settimeout(1.0)

        try:
            listener.bind((self.config["host"], self.remote_port))
            listener.listen()
            self.logger.info(f"Listening on {self.config["host"]}:{self.remote_port} for {self.login}.", extra={"client_ip": self.client_ip})

            async with await asyncio.start_server(self.handle_connection, sock=listener) as server:
                while self.running:
                    await asyncio.sleep(1)
        except Exception as error:
            self.logger.error(f"Failed to start listener on {self.config["host"]}:{self.remote_port}: {error}", extra={"client_ip": self.client_ip})
        finally:
            listener.close()

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection_id = random.randint(1, 2 ** 31 - 1)

        async with self.lock:
            if connection_id in self.connection_map:
                connection_id = random.randint(1, 2 ** 31 - 1)

            self.connection_map[connection_id] = writer

        peername = writer.get_extra_info("peername") or ("unknown", 0)
        try:
            self.logger.info(f"New incoming connection from {peername[0]}:{peername[1]} ({self.login}|{connection_id}).", extra={"client_ip": self.client_ip})

            if self.writer is None or self.writer.is_closing():
                self.logger.warning(f"Writer closed before sending NEW_CONNECTION package for {self.login}|{connection_id}.", extra={"client_ip": self.client_ip})

                await self.close_connection(connection_id)
                return

            self.writer.write(pack_package(PackageType.NEW_CONNECTION, connection_id, self.remote_port.to_bytes(4, "big"), max_payload_size=self.config["limits"]["max_data_size"]))
            await asyncio.wait_for(self.writer.drain(), timeout=self.config["timeouts"]["write"])

            self.tasks.append(asyncio.create_task(self.forward_data(reader, connection_id)))
        except (ConnectionResetError, OSError) as error:
            self.logger.info(f"Connection {self.login}|{connection_id} disconnected during initialization: {error}", extra={"client_ip": self.client_ip})
            await self.close_connection(connection_id)
        except Exception as error:
            self.logger.error(f"Connection initialization error {self.login}|{connection_id}: {error}", exc_info=True, extra={"client_ip": self.client_ip})
            await self.close_connection(connection_id)

    async def forward_data(self, reader: asyncio.StreamReader, connection_id: int) -> None:
        queue = asyncio.Queue(maxsize=self.config["limits"]["queue_size"])
        send_task = None

        async def send_loop():
            while self.running:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=5.0)
                    if data is None or not self.running:
                        break

                    async with self.lock:
                        if not self.running or self.writer is None or self.writer.is_closing():
                            break

                        try:
                            self.writer.write(pack_package(PackageType.DATA, connection_id, data, max_payload_size=self.config["limits"]["max_data_size"]))

                            await asyncio.wait_for(self.writer.drain(), timeout=self.config["timeouts"]["write"])
                        except (asyncio.TimeoutError, ConnectionResetError, OSError) as error:
                            self.logger.warning(f"Send failed for {self.login}|{connection_id}: {error}", extra={"client_ip": self.client_ip})
                            break
                except asyncio.TimeoutError:
                    continue
                except Exception as error:
                    self.logger.error(f"Data send error for {self.login}|{connection_id}: {error}", exc_info=True, extra={"client_ip": self.client_ip})
                    break

        try:
            send_task = asyncio.create_task(send_loop())
            self.tasks.append(send_task)

            while self.running:
                try:
                    data = await asyncio.wait_for(reader.read(self.config["limits"]["max_data_size"]), timeout=self.config["timeouts"]["read"])
                    if not data:
                        break

                    if len(data) > self.config["limits"]["max_data_size"]:
                        self.logger.warning(f"Data packet too large ({len(data)} bytes) from {self.login}|{connection_id}.", extra={"client_ip": self.client_ip})
                        break

                    try:
                        await asyncio.wait_for(queue.put(data), timeout=1.0)
                    except asyncio.TimeoutError:
                        self.logger.warning(f"Buffer overflow, data dropped for {self.login}|{connection_id}.", extra={"client_ip": self.client_ip})
                        break

                except asyncio.TimeoutError:
                    continue
                except (ConnectionResetError, ConnectionAbortedError, OSError) as error:
                    self.logger.info(f"Connection {self.login}|{connection_id} reset: {error}", extra={"client_ip": self.client_ip})
                    break
                except Exception as error:
                    self.logger.error(f"Unexpected error in forward_data for {self.login}|{connection_id}: {error}", extra={"client_ip": self.client_ip})
                    break

        finally:
            try:
                await queue.put(None)
            except asyncio.QueueFull:
                queue.get_nowait()
                await queue.put(None)

            while not queue.empty():
                queue.get_nowait()

            if send_task and not send_task.done():
                try:
                    await asyncio.wait_for(send_task, timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    send_task.cancel()
                    await send_task

            await self.close_connection(connection_id)
            self.logger.debug(f"Forward data stopped for {self.login}|{connection_id}.", extra={"client_ip": self.client_ip})
