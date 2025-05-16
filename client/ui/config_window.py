import asyncio
import flet
from flet import Page, TextField, ElevatedButton, Container, Column, MainAxisAlignment, CrossAxisAlignment, SnackBar, Text

from config_manager import ConfigurationManager
from logger import Logger
from ui.tunnel_window import TunnelWindow


class ConfigWindow:
    def __init__(self, page: Page, username: str, password: str, server_info: dict, config_manager: ConfigurationManager):
        self.page = page

        self.username = username
        self.password = password
        self.server_info = server_info

        self.config_manager = config_manager

        self.logger = Logger(self.config_manager.config["logging"]["file"], self.config_manager.config["logging"]["level"])

        self.page.window.width = 275
        self.page.window.height = 200
        self.page.window.resizable = False
        self.page.window.maximizable = False
        self.page.window.center()
        self.page.title = "Nigarok | Configuration"

        self.port_field = TextField(label="Enter port", on_change=self.filter_numbers, width=200)
        self.launch_button = ElevatedButton(text="Launch", on_click=self.handle_launch, width=150)

    def build(self):
        self.page.clean()
        self.page.add(
            Container(
                content=Column(
                    [
                        self.port_field,
                        Container(height=2),
                        self.launch_button
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

    def filter_numbers(self, event=None):
        self.port_field.value = "".join(filter(str.isdigit, self.port_field.value))
        self.page.update()

    @staticmethod
    async def test_local_port(port: int) -> bool:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout=0.3)
            writer.close()

            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
            return False

    async def handle_launch(self, event=None):
        try:
            port = int(self.port_field.value)

            if not await self.test_local_port(port):
                self.page.open(SnackBar(Text("Port is unavailable"), bgcolor="red", show_close_icon=True, duration=1000))
                self.page.update()
                return
            self.page.clean()

            await TunnelWindow(self.page, self.username, self.password, self.server_info, port, self.config_manager).start()
        except ValueError:
            self.page.open(SnackBar(Text("Enter a valid port"), bgcolor="red", show_close_icon=True, duration=1000))
            self.page.update()
