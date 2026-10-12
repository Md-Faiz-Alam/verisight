"""Logging configuration for VeriSight."""

import logging
import re
import sys
from collections.abc import Sequence

from verisight.config import Settings

LOGGER_NAME = "verisight"

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

REDACTED = "[REDACTED]"

_CREDENTIAL_PATTERNS = (
    re.compile(
        r"(?i)(\b(?:authorization)\s*[:=]\s*"
        r"(?:bearer|basic)\s+)[^\s,;\"']+"
    ),
    re.compile(
        r"(?i)(\b(?:x-goog-api-key|x-api-key|api_key|"
        r"apikey|access_token|client_secret)\s*[:=]\s*"
        r"[\"']?)[^\s,;\"'&]+"
    ),
    re.compile(
        r"(?i)([?&](?:key|api_key|access_token|token)="
        r")[^&#\s]+"
    ),
)


def redact_secrets(
    value: str,
    *,
    secrets: Sequence[str] = (),
) -> str:
    """Mask configured secrets and common credential-bearing text."""

    result = value

    for secret in sorted(
        (item for item in secrets if item),
        key=len,
        reverse=True,
    ):
        result = result.replace(secret, REDACTED)

    for pattern in _CREDENTIAL_PATTERNS:
        result = pattern.sub(
            lambda match: match.group(1) + REDACTED,
            result,
        )

    return result


class SecretRedactingFormatter(logging.Formatter):
    """Redact secrets after formatting messages and exceptions."""

    def __init__(
        self,
        *,
        secrets: Sequence[str] = (),
    ) -> None:
        super().__init__(
            fmt=LOG_FORMAT,
            datefmt=DATE_FORMAT,
        )
        self._secrets = tuple(secrets)

    def format(self, record: logging.LogRecord) -> str:
        """Format and sanitize the final log output."""

        formatted = super().format(record)
        return redact_secrets(
            formatted,
            secrets=self._secrets,
        )


def configure_logging(settings: Settings) -> None:
    """Configure the VeriSight application logger."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(settings.log_level)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(settings.log_level)

    secrets = (settings.gemini_api_key,) if settings.gemini_api_key else ()

    handler.setFormatter(SecretRedactingFormatter(secrets=secrets))

    logger.handlers.clear()
    logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a logger within the VeriSight logging hierarchy."""

    if name == LOGGER_NAME or name.startswith(f"{LOGGER_NAME}."):
        return logging.getLogger(name)

    return logging.getLogger(f"{LOGGER_NAME}.{name}")
