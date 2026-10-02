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
    assert settings.gemini_api_key is None
    assert settings.gemini_model == "gemini-3.1-flash-lite"


def test_settings_load_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERISIGHT_ENVIRONMENT", "test")
    monkeypatch.setenv("VERISIGHT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("VERISIGHT_DATA_DIR", "custom-data")
    monkeypatch.setenv("VERISIGHT_MAX_UPLOAD_SIZE_MB", "250")
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "test-api-key")
    monkeypatch.setenv("VERISIGHT_GEMINI_MODEL", "test-model")

    settings = SettingsWithoutEnvFile()

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.data_dir == Path("custom-data")
    assert settings.max_upload_size_mb == 250
    assert settings.gemini_api_key == "test-api-key"
    assert settings.gemini_model == "test-model"


def test_settings_reject_invalid_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERISIGHT_ENVIRONMENT", "invalid")

    with pytest.raises(ValidationError):
        SettingsWithoutEnvFile()


def test_settings_reject_non_positive_upload_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERISIGHT_MAX_UPLOAD_SIZE_MB", "0")

    with pytest.raises(ValidationError):
        SettingsWithoutEnvFile()


def test_get_settings_returns_cached_instance() -> None:
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert first is second

    get_settings.cache_clear()
