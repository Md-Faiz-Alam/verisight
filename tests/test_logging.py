import logging

from _pytest.capture import CaptureFixture

from verisight.config import Settings
from verisight.logging import (
    LOGGER_NAME,
    configure_logging,
    get_logger,
)


def test_configure_logging_sets_expected_level() -> None:
    settings = Settings(log_level="DEBUG")

    configure_logging(settings)

    logger = logging.getLogger(LOGGER_NAME)

    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1
    assert logger.handlers[0].level == logging.DEBUG


def test_configure_logging_does_not_duplicate_handlers() -> None:
    settings = Settings(log_level="INFO")

    configure_logging(settings)
    configure_logging(settings)

    logger = logging.getLogger(LOGGER_NAME)

    assert len(logger.handlers) == 1


def test_get_logger_adds_verisight_namespace() -> None:
    logger = get_logger("analytics")

    assert logger.name == "verisight.analytics"


def test_get_logger_preserves_existing_verisight_namespace() -> None:
    logger = get_logger("verisight.analytics")

    assert logger.name == "verisight.analytics"


def test_configured_logger_writes_message_to_stdout(
    capfd: CaptureFixture[str],
) -> None:
    settings = Settings(log_level="INFO")
    configure_logging(settings)

    logger = get_logger("test")
    logger.info("VeriSight logging works")

    captured = capfd.readouterr()

    assert "INFO" in captured.out
    assert "verisight.test" in captured.out
    assert "VeriSight logging works" in captured.out
