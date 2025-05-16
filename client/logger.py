import logging


class Logger:
    _configured: bool = False

    def __init__(self, log_file: str, log_level: str):
        self.logger = logging.getLogger("Nigarok")

        if not Logger._configured:
            self.logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

            self.logger.handlers.clear()

            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
            self.logger.addHandler(file_handler)

            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
            self.logger.addHandler(console_handler)

            self.logger.propagate = False

            Logger._configured = True

    async def log(self, message: str, level: str = "info"):
        logger_method = getattr(self.logger, level.lower(), self.logger.info)
        logger_method(message)
