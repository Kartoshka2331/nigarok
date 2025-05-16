import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.types import Config


class SafeFormatter(logging.Formatter):
    def format(self, record):
        record.__dict__.setdefault("client_ip", "-")
        return super().format(record)


def setup_logging(logging_config: Config["logging"]) -> None:
    log_file = Path(logging_config["file"])
    if log_file.exists():
        log_file.unlink()

    formatter = SafeFormatter(
        fmt="%(asctime)s [%(levelname)s] [%(client_ip)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logging.basicConfig(level=getattr(logging, logging_config["level"]), handlers=[file_handler, stream_handler])
