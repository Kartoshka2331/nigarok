import asyncio
import flet
from flet import Page, AppView

from ui.login_window import LoginWindow
from ui.theme_manager import ThemeManager
from config_manager import ConfigurationManager


async def main(page: Page):
    configuration_manager = ConfigurationManager()

    theme_manager = ThemeManager(page, configuration_manager)
    theme_manager.apply_theme()

    login_window = LoginWindow(page, configuration_manager)
    login_window.build()

if __name__ == "__main__":
    flet.app(target=lambda page: asyncio.run(main(page)), view=AppView.FLET_APP)
