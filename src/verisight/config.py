from functools import lru_cache
from pathlib import Path
from threading import TIMEOUT_MAX
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VERISIGHT_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"

    log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    data_dir: Path = Path("data")

    max_upload_size_mb: int = Field(
        default=100,
        gt=0,
    )

    max_query_result_rows: int = Field(
        default=10_000,
        gt=0,
    )

    max_query_result_bytes: int = Field(
        default=1_048_576,
        gt=0,
    )

    max_query_memory_mb: int = Field(
        default=512,
        gt=0,
    )

    max_query_execution_seconds: float = Field(
        default=30.0,
        gt=0,
        le=TIMEOUT_MAX,
        allow_inf_nan=False,
    )

    max_query_temp_storage_mb: int = Field(
        default=1_024,
        gt=0,
    )

    # Orchestration budget; loading and profiling precede this deadline.
    max_investigation_seconds: float = Field(
        default=300.0,
        gt=0,
        allow_inf_nan=False,
    )

    gemini_api_key: str | None = Field(default=None, repr=False, exclude=True)

    allow_llm_data_disclosure: bool = False

    gemini_model: str = "gemini-3.1-flash-lite"

    gemini_request_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        allow_inf_nan=False,
    )

    gemini_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
    )

    gemini_retry_base_delay_seconds: float = Field(
        default=1.0,
        gt=0,
        allow_inf_nan=False,
    )


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""

    return Settings()
