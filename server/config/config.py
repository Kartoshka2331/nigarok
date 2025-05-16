from pathlib import Path
import json
import logging
from typing import Dict, Any

from .types import Config


def load_config(file_path: str = "config.json") -> Config:
    default_config: Config = {
        "host": "0.0.0.0",
        "port": 13882,
        "allowed_port_range": [1024, 65535],
        "accounts": [],
        "timeouts": {"auth": 3.0, "read": 5.0, "write": 5.0},
        "limits": {"max_auth_size": 1024, "max_data_size": 65536, "queue_size": 1000},
        "logging": {"level": "INFO", "file": "logs.txt"}
    }

    try:
        with Path(file_path).open("r") as file:
            config = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as error:
        logging.critical(f"Configuration load error: {error}", extra={"client_ip": "server"})
        raise RuntimeError(f"Configuration load error: {error}")

    def merge_defaults(target: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in defaults.items():
            if key not in target:
                target[key] = value
            elif isinstance(value, dict):
                target[key] = merge_defaults(target.get(key, {}), value)
        return target

    config = merge_defaults(config, default_config)

    if not config["accounts"]:
        raise ValueError("Accounts list cannot be empty")
    if not (0 < config["port"] <= 65535):
        raise ValueError("Port must be in range 1-65535")
    if not (0 < config["allowed_port_range"][0] <= config["allowed_port_range"][1] <= 65535):
        raise ValueError("Invalid port range")
    for account in config["accounts"]:
        if not (account.get("login") and account.get("password")):
            raise ValueError("Each account must contain login and password")
    for timeout in config["timeouts"].values():
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("Timeouts must be positive numbers")
    for limit in config["limits"].values():
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("Limits must be positive integers")
    if config["logging"]["level"] not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("Invalid logging level")

    return config
