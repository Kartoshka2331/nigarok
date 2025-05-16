import json
from pathlib import Path
from typing import Dict, Any


class ConfigurationManager:
    def __init__(self):
        self.config_path = Path("config.json")
        self.credentials_path = Path("credentials.json")

        self.config = self.load_config()
        self.servers = self.config["servers"]

    def load_config(self) -> Dict[str, Any]:
        if self.config_path.exists():
            with self.config_path.open("r", encoding="utf-8") as file:
                return json.load(file)

        return {
          "servers": [
            {
              "name": "Server 1",
              "address": "127.0.0.1",
              "port": 13882
            },
            {
              "name": "Server 2",
              "address": "example.com",
              "port": 13882
            }
          ],
          "theme": "dark",
          "themes": {
            "dark": {
              "dark": True,
              "font_family": "Segoe UI",
              "background_color": "#2b2b2b",
              "primary_color": "white",
              "secondary_color": "#03dac6",
              "on_primary": "white",
              "on_secondary": "white"
            },
            "light": {
              "dark": False,
              "font_family": "Roboto",
              "background_color": "#e0f2f1",
              "primary_color": "#2e3033",
              "color_scheme": {
                "primary": "tealAccent700",
                "background": "teal50",
                "on_primary": "white",
                "primary_container": "pink",
                "on_primary_container": "white",
                "secondary": "pink",
                "on_secondary": "white",
                "on_background": "black",
                "on_surface": "teal100",
                "surface_variant": "teal200"
              }
            }
          },
          "logging": {
            "file": "logs.txt",
            "level": "INFO"
          }
        }

    def save_config(self, config: Dict[str, Any]):
        with self.config_path.open("w", encoding="utf-8") as file:
            json.dump(config, file, indent=4)

    def load_credentials(self) -> Dict[str, str]:
        if self.credentials_path.exists():
            with self.credentials_path.open("r", encoding="utf-8") as file:
                return json.load(file)

        return {"username": "", "password": ""}

    def save_credentials(self, username: str, password: str):
        with self.credentials_path.open("w", encoding="utf-8") as file:
            json.dump({"username": username, "password": password}, file, indent=4)

    def get_server(self, server_name: str) -> Dict[str, Any]:
        return next(server for server in self.servers if server["name"] == server_name)
