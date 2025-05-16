import asyncio
import time
import pyperclip
from typing import Dict, Optional
import flet
from flet import Page, TextField, ListView, Text, Colors, Container, Column, MainAxisAlignment, CrossAxisAlignment, Row, IconButton, ElevatedButton, Card, SnackBar, padding

from config_manager import ConfigurationManager
from logger import Logger
from tunnel_protocol import PackageType, pack_package, unpack_package, ProtocolError


class TunnelWindow:
    def __init__(self, page: Page, username: str, password: str, server_info: dict, local_port: int, config_manager: ConfigurationManager):
        self.page = page

        self.username = username
        self.password = password
        self.server_address = server_info["address"]
        self.server_port = server_info["port"]
        self.local_port = local_port

        self.config_manager = config_manager

        self.logger = Logger(self.config_manager.config["logging"]["file"], self.config_manager.config["logging"]["level"])

        self.page.window.width = 500
        self.page.window.height = 440
        self.page.window.resizable = False
        self.page.window.maximizable = False
        self.page.window.center()
        self.page.title = "Nigarok | Connected"

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

        self.running = False
        self.reconnecting = False

        self.connection_map: Dict[int, tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}
        self.tasks: list[asyncio.Task] = []

        self.traffic_upload = 0
        self.traffic_download = 0
        self.max_queue_size = 100
        self.remote_address_field = TextField(value="—", read_only=True, width=300)
        self.log_view = ListView(height=140, expand=True, auto_scroll=True, padding=padding.symmetric(horizontal=10, vertical=10))
        self.traffic_label = Text(value="↑ 0 B   ↓ 0 B")

        self.ping_indicator = Container(width=12, height=12, bgcolor="grey", border_radius=6, tooltip="Ping: —", right=10, bottom=10)
        self.page.overlay.append(self.ping_indicator)

    def build(self):
        self.page.clean()
        self.page.add(
            Container(
                content=Column(
                    [
                        Card(content=self.log_view, width=400, height=200, elevation=4),
                        Row([self.remote_address_field, IconButton(icon="CONTENT_COPY", on_click=self.copy_address)],
                            alignment=MainAxisAlignment.CENTER),
                        self.traffic_label,
                        Container(height=1),
                        ElevatedButton(text="Stop", on_click=self.stop, width=150, bgcolor=Colors.DEEP_ORANGE_900)
                    ],
                    alignment=MainAxisAlignment.CENTER,
                    horizontal_alignment=CrossAxisAlignment.CENTER,
                    spacing=12
                ),
                padding=30,
                alignment=flet.alignment.center,
                bgcolor=self.page.theme.color_scheme.background
            )
        )

    async def log(self, message: str, level: str = "info"):
        message = message + "." if not message.endswith(".") else message
        timestamp = time.strftime("[%H:%M:%S] ")
        full_message = timestamp + message

        color_map = {
            "info": self.page.theme.color_scheme.on_surface,
            "success": "#8BC34A",
            "warning": "#FFCA28",
            "error": "#EF5350"
        }

        logger_level_map = {
            "info": "info",
            "success": "info",
            "warning": "warning",
            "error": "error"
        }

        color = color_map.get(level, self.page.theme.color_scheme.on_surface)
        self.log_view.controls.append(Text(full_message, size=12, color=color))
        self.page.update()

        await self.logger.log(message, logger_level_map.get(level, "info"))

    async def copy_address(self, event=None):
        pyperclip.copy(self.remote_address_field.value)

        self.page.open(SnackBar(Text("Copied to clipboard!"), bgcolor="green", show_close_icon=True, duration=1000))
        self.page.update()

    async def update_traffic(self):
        def format_size(size: int) -> str:
            if size >= 1_000_000:
                return f"{size / 1_048_576:.1f} MB"
            elif size >= 1000:
                return f"{size / 1024:.1f} KB"
            return f"{size} B"

        self.traffic_label.value = f"↑ {format_size(self.traffic_upload)}   ↓ {format_size(self.traffic_download)}"
        self.traffic_label.update()

    async def connect(self) -> bool:
        try:
            self.reader, self.writer = await asyncio.wait_for(asyncio.open_connection(self.server_address, self.server_port), timeout=5)
            self.writer.write(f"{self.username}:{self.password}\n".encode())
            await self.writer.drain()

            await self.log("Connection to server established.", "success")
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError, ConnectionError) as error:
            await self.log(f"Connection failed: {error}", "error")
            return False

    async def server_listener_loop(self):
        while self.running:
            try:
                package_type, connection_id, payload = await asyncio.wait_for(unpack_package(self.reader), timeout=10)

                await self.handle_incoming_package(package_type, connection_id, payload)
            except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
                if self.running:
                    await self.log("Connection to server lost.", "error")
                    await self.reconnect()
                break
            except ProtocolError as error:
                if self.running:
                    await self.log(f"Server sent invalid package: {error}", "warning")
                break
            except asyncio.TimeoutError:
                continue

    async def handle_incoming_package(self, package_type: PackageType, connection_id: int, payload: bytes):
        if package_type == PackageType.PONG:
            try:
                ms = int((time.time() - float(payload.decode())) * 1000)
                color = (
                    "lightgreen" if ms < 30 else
                    "lime" if ms < 60 else
                    "yellow" if ms < 120 else
                    "amber" if ms < 160 else
                    "orange" if ms < 200 else
                    "deeporange" if ms < 300 else
                    "redaccent" if ms < 400 else
                    "red"
                )

                self.ping_indicator.bgcolor = color
                self.ping_indicator.tooltip = f"Ping: {ms} ms"
            except:
                self.ping_indicator.bgcolor = "grey"
                self.ping_indicator.tooltip = "Ping: ?"
            self.ping_indicator.update()

        elif package_type == PackageType.NEW_CONNECTION:
            remote_port = int.from_bytes(payload, byteorder="big")

            if connection_id == 0:
                self.remote_address_field.value = f"{self.server_address}:{remote_port}"
                self.page.update()
                return

            await self.log(f"New connection #{connection_id}.", "success")
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", self.local_port), timeout=0.3)

                self.connection_map[connection_id] = (reader, writer)
                self.tasks.append(asyncio.create_task(self.pipe_local_to_server(connection_id, reader)))
            except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
                await self.log("Failed to connect to local port.", "error")

                self.writer.write(pack_package(PackageType.CLOSE, connection_id))
                await self.writer.drain()

        elif package_type == PackageType.DATA:
            self.traffic_download += len(payload)
            await self.update_traffic()

            if connection_id in self.connection_map:
                try:
                    reader, writer = self.connection_map[connection_id]

                    writer.write(payload)
                    await writer.drain()
                except (ConnectionResetError, OSError):
                    await self.close_connection(connection_id)

        elif package_type == PackageType.CLOSE:
            await self.log(f"Connection #{connection_id} closed.", "warning")
            await self.close_connection(connection_id)

    async def pipe_local_to_server(self, connection_id: int, reader: asyncio.StreamReader):
        queue = asyncio.Queue(maxsize=self.max_queue_size)

        async def read_local():
            try:
                while self.running:
                    data = await asyncio.wait_for(reader.read(4096), timeout=5)
                    if not data:
                        break

                    self.traffic_upload += len(data)
                    await self.update_traffic()
                    try:
                        if queue.full():
                            queue.get_nowait()

                            await self.log(f"Queue full, data dropped (#{connection_id}).", "warning")
                        await asyncio.wait_for(queue.put(data), timeout=1)
                    except asyncio.TimeoutError:
                        await self.log(f"Queue full, data dropped (#{connection_id}).", "warning")
                        break
            except (ConnectionResetError, OSError):
                await self.log(f"Local socket closed connection #{connection_id}.", "warning")
            except Exception as error:
                await self.log(f"Error reading from local socket: {error}", "error")
            finally:
                queue.put_nowait(None)

        async def write_to_server():
            try:
                while self.running:
                    data = await queue.get()
                    if not data:
                        break

                    try:
                        self.writer.write(pack_package(PackageType.DATA, connection_id, data))
                        await self.writer.drain()
                    except (ConnectionResetError, OSError) as error:
                        await self.log(f"Error sending data to server: {error}", "error")
                        break
            finally:
                try:
                    self.writer.write(pack_package(PackageType.CLOSE, connection_id))
                    await self.writer.drain()
                except:
                    pass
                await self.close_connection(connection_id)

        self.tasks.append(asyncio.create_task(read_local()))
        self.tasks.append(asyncio.create_task(write_to_server()))

    async def close_connection(self, connection_id: int):
        if connection_id in self.connection_map:
            reader, writer = self.connection_map.pop(connection_id)
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
            await self.log(f"Connection #{connection_id} closed.", "warning")

    async def ping_loop(self):
        while self.running:
            try:
                self.writer.write(pack_package(PackageType.PING, 0, str(time.time()).encode()))
                await self.writer.drain()
            except (ConnectionResetError, OSError):
                self.ping_indicator.bgcolor = "grey"
                self.ping_indicator.tooltip = "Ping: -1"
                self.ping_indicator.update()
                break
            await asyncio.sleep(2)

    async def start(self):
        self.running = True
        self.build()

        if await self.connect():
            self.tasks = [asyncio.create_task(self.server_listener_loop()), asyncio.create_task(self.ping_loop())]

    async def stop(self, event=None):
        await self.log("Stopping client.", "warning")

        self.running = False
        for task in self.tasks:
            task.cancel()
        try:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass

        self.tasks.clear()
        for connection_id in list(self.connection_map):
            await self.close_connection(connection_id)
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except:
                pass
            self.writer = None

        self.remote_address_field.value = "—"
        self.page.clean()
        self.page.overlay.clear()

        from ui.login_window import LoginWindow
        LoginWindow(self.page, self.config_manager).build()

    async def reconnect(self):
        if not self.reconnecting:
            self.reconnecting = True

            await self.log("Reconnecting...", "info")
            await self.stop()

            max_attempts = 10
            for attempt in range(max_attempts):
                if await self.connect():
                    self.tasks = [asyncio.create_task(self.server_listener_loop()), asyncio.create_task(self.ping_loop())]
                    self.reconnecting = False
                    return

                await self.log(f"Retry {attempt + 1}/{max_attempts} in 5 seconds...", "warning")
                await asyncio.sleep(5)

            await self.log("Failed to reconnect.", "error")
            await self.stop()
