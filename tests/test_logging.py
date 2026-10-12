import logging

from _pytest.capture import CaptureFixture

from verisight.config import Settings
from verisight.logging import (
    LOGGER_NAME,
    configure_logging,
    get_logger,
    redact_secrets,
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


def test_redacts_configured_api_key_from_logs(
    capfd: CaptureFixture[str],
) -> None:
    secret = "synthetic-gemini-secret-123456"

    configure_logging(
        Settings(
            log_level="INFO",
            gemini_api_key=secret,
        )
    )

    logger = get_logger("security")
    logger.error("Gemini rejected key %s", secret)

    output = capfd.readouterr().out

    assert secret not in output
    assert "[REDACTED]" in output
    assert "Gemini rejected key" in output


def test_redacts_api_key_from_exception_traceback(
    capfd: CaptureFixture[str],
) -> None:
    secret = "synthetic-gemini-secret-123456"

    configure_logging(
        Settings(
            log_level="ERROR",
            gemini_api_key=secret,
        )
    )

    logger = get_logger("security")

    try:
        raise RuntimeError(f"Provider error: {secret}")
    except RuntimeError:
        logger.exception("Gemini request failed")

    output = capfd.readouterr().out

    assert secret not in output
    assert "[REDACTED]" in output
    assert "Gemini request failed" in output


def test_redacts_common_credential_formats() -> None:
    message = (
        "Authorization: Bearer bearer-secret-123 "
        "x-goog-api-key: header-secret-456 "
        "https://example.com?key=query-secret-789"
    )

    result = redact_secrets(message)

    assert "bearer-secret-123" not in result
    assert "header-secret-456" not in result
    assert "query-secret-789" not in result
    assert result.count("[REDACTED]") == 3


def test_redaction_preserves_safe_messages() -> None:
    message = "Query execution completed successfully."

    assert redact_secrets(message) == message


def test_redaction_ignores_empty_configured_secrets() -> None:
    message = "Normal diagnostic message."

    assert (
        redact_secrets(
            message,
            secrets=("",),
        )
        == message
    )


def test_redaction_replaces_configured_secrets_longest_first() -> None:
    result = redact_secrets(
        "token-123456",
        secrets=("token-123", "token-123456"),
    )

    assert result == "[REDACTED]"
