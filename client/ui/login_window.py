import asyncio
import flet
from flet import Page, TextField, Dropdown, ElevatedButton, Container, Column, MainAxisAlignment, CrossAxisAlignment, SnackBar, Text, dropdown

from config_manager import ConfigurationManager
from logger import Logger
from ui.config_window import ConfigWindow


class LoginWindow:
    def __init__(self, page: Page, config_manager: ConfigurationManager):
        self.page = page

        self.config_manager = config_manager

        self.logger = Logger(self.config_manager.config["logging"]["file"], self.config_manager.config["logging"]["level"])

        self.page.window.width = 480
        self.page.window.height = 320
        self.page.window.resizable = False
        self.page.window.maximizable = False
        self.page.window.center()
        self.page.title = "Nigarok | Login"

        credentials = self.config_manager.load_credentials()
        self.username_field = TextField(label="Username", value=credentials["username"], width=450)
        self.password_field = TextField(label="Password", value=credentials["password"], password=True, can_reveal_password=True, width=450)
        self.server_dropdown = Dropdown(label="Server", options=[dropdown.Option(server["name"]) for server in self.config_manager.servers], value=self.config_manager.servers[0]["name"], width=225)
        self.continue_button = ElevatedButton(text="Continue", on_click=self.handle_continue, width=200)

    def build(self):
        self.page.clean()
        self.page.add(
            Container(
                content=Column(
                    [
                        self.username_field,
                        self.password_field,
                        self.server_dropdown,
                        Container(height=2),
                        self.continue_button
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

    @staticmethod
    async def test_credentials(username: str, password: str, server_info: dict) -> str:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(server_info["address"], server_info["port"]), timeout=2)
            writer.write(f"__test__:{username}:{password}\n".encode())
            await writer.drain()

            response = await asyncio.wait_for(reader.read(10), timeout=2)

            writer.close()
            await writer.wait_closed()

            return "valid" if bool(response) else "invalid"
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return "unavailable"

    async def handle_continue(self, event=None):
        username = self.username_field.value
        password = self.password_field.value
        server_info = self.config_manager.get_server(self.server_dropdown.value)

        if not username or not password:
            self.page.open(SnackBar(Text("Username or password is empty"), bgcolor="red", show_close_icon=True, duration=1000))
            self.page.update()
            return

        server_answer = await self.test_credentials(username, password, server_info)
        if server_answer == "valid":
            self.config_manager.save_credentials(username, password)
            self.page.clean()

            ConfigWindow(self.page, username, password, server_info, self.config_manager).build()
        elif server_answer == "unavailable":
            self.page.open(SnackBar(Text("Server is unavailable"), bgcolor="red", show_close_icon=True, duration=1000))
            self.page.update()
        else:
            self.page.open(SnackBar(Text("Invalid credentials"), bgcolor="red", show_close_icon=True, duration=1000))
            self.page.update()
