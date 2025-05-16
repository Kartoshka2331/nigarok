from flet import Page, Theme, ThemeMode, AppBarTheme, ColorScheme

from config_manager import ConfigurationManager


class ThemeManager:
    def __init__(self, page: Page, config_manager: ConfigurationManager):
        self.page = page
        self.config_manager = config_manager
        self.current_theme_name = self.config_manager.config.get("theme", "dark")

    def apply_theme(self):
        themes = self.config_manager.config.get("themes", {})
        theme_config = themes.get(self.current_theme_name, {})

        self.page.theme_mode = ThemeMode.DARK if theme_config.get("dark", True) else ThemeMode.LIGHT

        self.page.theme = Theme(
            color_scheme_seed=theme_config.get("color_scheme_seed"),
            primary_swatch=theme_config.get("primary_swatch"),
            font_family=theme_config.get("font_family"),
            use_material3=theme_config.get("use_material3", True),
            appbar_theme=AppBarTheme(bgcolor=theme_config.get("appbar_bgcolor")) if theme_config.get("appbar_bgcolor") else None,
            color_scheme=ColorScheme(primary=theme_config.get("primary_color"), secondary=theme_config.get("secondary_color"), background=theme_config.get("background_color")) if any(theme_config.get(k) for k in ("primary_color", "secondary_color", "background_color")) else None,
        )

        self.page.bgcolor = theme_config.get("background_color", "#121212")

        self.page.update()
