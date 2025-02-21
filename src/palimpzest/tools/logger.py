import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logger(name):
    pz_logger = PZLogger()
    logger = pz_logger.get_logger(name)
    logger.setLevel(logging.DEBUG)
    logger.info(f"Initialized logger for {name}")
    return logger


class JsonFormatter(logging.Formatter):
    """Format logs as JSON for easier parsing"""

    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "stats"):
            log_data["stats"] = record.stats
        if hasattr(record, "exc_info"):
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


LOG_FILE = "logs/palimpzest"


class PZLogger:
    """Central logging class for Palimpzest"""

    _instance = None

    def __new__(
        cls,
        file_log_level: str = "ERROR",
        streaming_log_level: str = "ERROR",
        log_file: str | None = None,
        log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        json_format: bool = True,
    ):
        if cls._instance is None:
            instance = super().__new__(cls)

            # Initialize all attributes
            instance.root_logger = logging.getLogger("palimpzest")
            instance.root_logger.setLevel(logging.DEBUG)  # Set root logger to capture all levels
            instance.streaming_log_level = streaming_log_level
            instance.file_log_level = file_log_level
            if log_file is None:
                # TODO: Save by day for now.
                log_dir = Path(".pz_logs")
                log_dir.mkdir(exist_ok=True)
                date_str = datetime.now().strftime("%Y-%m-%d")
                instance.log_file = f"{LOG_FILE}_{date_str}.log"
            else:
                instance.log_file = log_file
            instance.log_format = log_format
            instance.json_format = json_format

            # Setup logging
            instance._setup_root_logging()

            cls._instance = instance
        return cls._instance

    def _setup_root_logging(self):
        """Configure logging based on config"""
        self.root_logger.handlers.clear()

        if self.log_file:
            # TODO: consider to use rotating file handler to prevent huge log files
            self.file_handler = logging.FileHandler(self.log_file)
            self.file_handler.setLevel(self.file_log_level)
            if self.json_format:
                self.file_handler.setFormatter(JsonFormatter())
            else:
                self.file_handler.setFormatter(logging.Formatter(self.log_format))
            self.root_logger.addHandler(self.file_handler)

        self.console_handler = logging.StreamHandler()
        self.console_handler.setLevel(self.streaming_log_level)
        self.console_handler.setFormatter(logging.Formatter(self.log_format))
        self.root_logger.addHandler(self.console_handler)

    # TODO: we save everything into file when verbose is on.
    def set_console_level(self, level: str):
        self.streaming_log_level = level
        self.console_handler.setLevel(level)
        self.file_handler.setLevel(level)

    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger for a specific component"""
        logger = logging.getLogger(f"palimpzest.{name}")
        logger.pz_logger = self
        logger.setLevel(logging.DEBUG)
        return logger
