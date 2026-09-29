"""Logging configuration for VeriSight."""

import logging
import sys

from verisight.config import Settings

LOGGER_NAME = "verisight"

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(settings: Settings) -> None:
    """Configure the VeriSight application logger."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(settings.log_level)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(settings.log_level)

    formatter = logging.Formatter(
        fmt=LOG_FORMAT,
        datefmt=DATE_FORMAT,
    )
    handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a logger within the VeriSight logging hierarchy."""

    if name == LOGGER_NAME or name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)

    return logging.getLogger(f"{LOGGER_NAME}.{name}")
