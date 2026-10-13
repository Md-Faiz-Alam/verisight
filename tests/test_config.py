from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from verisight.config import Settings, get_settings


class SettingsWithoutEnvFile(Settings):
    """Settings variant that does not read from a local .env file."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_prefix="VERISIGHT_",
        case_sensitive=False,
        extra="ignore",
    )


def test_settings_have_expected_defaults() -> None:
    settings = SettingsWithoutEnvFile()

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.data_dir == Path("data")
    assert settings.max_upload_size_mb == 100
    assert settings.max_query_result_rows == 10_000
    assert settings.max_query_memory_mb == 512
    assert settings.max_query_execution_seconds == 30.0
    assert settings.max_query_temp_storage_mb == 1_024
    assert settings.gemini_api_key is None
    assert settings.allow_llm_data_disclosure is False
    assert settings.gemini_model == "gemini-3.1-flash-lite"
    assert settings.gemini_request_timeout_seconds == 30.0
    assert settings.gemini_max_retries == 2
    assert settings.gemini_retry_base_delay_seconds == 1.0


def test_settings_load_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VERISIGHT_ENVIRONMENT",
        "test",
    )
    monkeypatch.setenv(
        "VERISIGHT_LOG_LEVEL",
        "DEBUG",
    )
    monkeypatch.setenv(
        "VERISIGHT_DATA_DIR",
        "custom-data",
    )
    monkeypatch.setenv(
        "VERISIGHT_MAX_UPLOAD_SIZE_MB",
        "250",
    )
    monkeypatch.setenv(
        "VERISIGHT_MAX_QUERY_RESULT_ROWS",
        "2500",
    )
    monkeypatch.setenv(
        "VERISIGHT_MAX_QUERY_MEMORY_MB",
        "768",
    )
    monkeypatch.setenv(
        "VERISIGHT_MAX_QUERY_EXECUTION_SECONDS",
        "45.5",
    )
    monkeypatch.setenv(
        "VERISIGHT_MAX_QUERY_TEMP_STORAGE_MB",
        "256",
    )
    monkeypatch.setenv(
        "VERISIGHT_GEMINI_API_KEY",
        "test-api-key",
    )
    monkeypatch.setenv(
        "VERISIGHT_GEMINI_MODEL",
        "test-model",
    )
    monkeypatch.setenv(
        "VERISIGHT_ALLOW_LLM_DATA_DISCLOSURE",
        "true",
    )

    settings = SettingsWithoutEnvFile()

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.data_dir == Path("custom-data")
    assert settings.max_upload_size_mb == 250
    assert settings.max_query_result_rows == 2500
    assert settings.max_query_memory_mb == 768
    assert settings.max_query_execution_seconds == 45.5
    assert settings.max_query_temp_storage_mb == 256
    assert settings.gemini_api_key == "test-api-key"
    assert settings.allow_llm_data_disclosure is True
    assert settings.gemini_model == "test-model"


def test_settings_reject_invalid_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VERISIGHT_ENVIRONMENT",
        "invalid",
    )

    with pytest.raises(ValidationError):
        SettingsWithoutEnvFile()


def test_settings_reject_non_positive_upload_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VERISIGHT_MAX_UPLOAD_SIZE_MB",
        "0",
    )

    with pytest.raises(ValidationError):
        SettingsWithoutEnvFile()


def test_get_settings_returns_cached_instance() -> None:
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert first is second

    get_settings.cache_clear()


def test_settings_load_query_result_row_limit_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VERISIGHT_MAX_QUERY_RESULT_ROWS",
        "2500",
    )

    settings = SettingsWithoutEnvFile()

    assert settings.max_query_result_rows == 2500


def test_settings_reject_non_positive_query_result_row_limit() -> None:
    with pytest.raises(ValidationError):
        SettingsWithoutEnvFile(
            max_query_result_rows=0,
        )


def test_settings_load_query_memory_limit_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VERISIGHT_MAX_QUERY_MEMORY_MB",
        "768",
    )

    settings = SettingsWithoutEnvFile()

    assert settings.max_query_memory_mb == 768


def test_settings_reject_non_positive_query_memory_limit() -> None:
    with pytest.raises(ValidationError):
        SettingsWithoutEnvFile(
            max_query_memory_mb=0,
        )


def test_settings_load_query_execution_timeout_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VERISIGHT_MAX_QUERY_EXECUTION_SECONDS",
        "12.5",
    )

    settings = SettingsWithoutEnvFile()

    assert settings.max_query_execution_seconds == 12.5


def test_settings_reject_non_positive_query_execution_timeout() -> None:
    with pytest.raises(ValidationError):
        SettingsWithoutEnvFile(
            max_query_execution_seconds=0,
        )


def test_settings_load_query_temp_storage_limit_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VERISIGHT_MAX_QUERY_TEMP_STORAGE_MB",
        "128",
    )

    settings = SettingsWithoutEnvFile()

    assert settings.max_query_temp_storage_mb == 128


@pytest.mark.parametrize("limit", [0, -1])
def test_settings_reject_non_positive_query_temp_storage_limit(
    limit: int,
) -> None:
    with pytest.raises(ValidationError):
        SettingsWithoutEnvFile(
            max_query_temp_storage_mb=limit,
        )


def test_settings_load_gemini_reliability_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VERISIGHT_GEMINI_REQUEST_TIMEOUT_SECONDS",
        "12.5",
    )
    monkeypatch.setenv(
        "VERISIGHT_GEMINI_MAX_RETRIES",
        "3",
    )
    monkeypatch.setenv(
        "VERISIGHT_GEMINI_RETRY_BASE_DELAY_SECONDS",
        "0.5",
    )

    settings = SettingsWithoutEnvFile()

    assert settings.gemini_request_timeout_seconds == 12.5
    assert settings.gemini_max_retries == 3
    assert settings.gemini_retry_base_delay_seconds == 0.5


@pytest.mark.parametrize(
    ("environment_variable", "value"),
    [
        ("VERISIGHT_GEMINI_REQUEST_TIMEOUT_SECONDS", "0"),
        ("VERISIGHT_GEMINI_REQUEST_TIMEOUT_SECONDS", "-1"),
        ("VERISIGHT_GEMINI_REQUEST_TIMEOUT_SECONDS", "inf"),
        ("VERISIGHT_GEMINI_REQUEST_TIMEOUT_SECONDS", "nan"),
        ("VERISIGHT_GEMINI_MAX_RETRIES", "-1"),
        ("VERISIGHT_GEMINI_MAX_RETRIES", "6"),
        ("VERISIGHT_GEMINI_RETRY_BASE_DELAY_SECONDS", "0"),
        ("VERISIGHT_GEMINI_RETRY_BASE_DELAY_SECONDS", "-1"),
        ("VERISIGHT_GEMINI_RETRY_BASE_DELAY_SECONDS", "inf"),
        ("VERISIGHT_GEMINI_RETRY_BASE_DELAY_SECONDS", "nan"),
    ],
)
def test_settings_reject_invalid_gemini_reliability_options(
    monkeypatch: pytest.MonkeyPatch,
    environment_variable: str,
    value: str,
) -> None:
    monkeypatch.setenv(environment_variable, value)

    with pytest.raises(ValidationError):
        SettingsWithoutEnvFile()


def test_gemini_api_key_is_hidden_from_settings_repr() -> None:
    secret = "synthetic-gemini-secret-123456"

    settings = SettingsWithoutEnvFile(
        gemini_api_key=secret,
    )

    assert settings.gemini_api_key == secret
    assert secret not in repr(settings)
    assert "gemini_api_key=" not in repr(settings)


@pytest.mark.parametrize("value", ["invalid", "sometimes", ""])
def test_settings_reject_invalid_llm_disclosure_permission(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv(
        "VERISIGHT_ALLOW_LLM_DATA_DISCLOSURE",
        value,
    )

    with pytest.raises(ValidationError):
        SettingsWithoutEnvFile()
