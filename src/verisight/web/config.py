"""Web server settings, read from ``VERISIGHT_WEB_*`` environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebSettings(BaseSettings):
    """Limits that protect a shared or public deployment.

    The Gemini key itself stays in the core settings
    (``VERISIGHT_GEMINI_API_KEY``). When no server key is configured, each
    visitor supplies their own key, which is used for that request only and is
    never stored or logged.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VERISIGHT_WEB_",
        case_sensitive=False,
        extra="ignore",
    )

    max_upload_mb: int = Field(default=20, gt=0, le=1024)
    max_files: int = Field(default=5, gt=0, le=20)
    dataset_ttl_seconds: int = Field(default=3600, gt=0)
    max_datasets: int = Field(default=100, gt=0)
    max_concurrent_questions: int = Field(default=2, gt=0, le=32)
    questions_per_hour: int = Field(default=30, gt=0)
    uploads_per_hour: int = Field(default=60, gt=0)
    max_question_chars: int = Field(default=1000, gt=0, le=10_000)
    max_investigation_seconds: float = Field(
        default=180.0, gt=0, le=900, allow_inf_nan=False
    )
    provider_retries: int = Field(default=3, ge=0, le=5)
    provider_retry_delay_seconds: float = Field(
        default=2.0, gt=0, le=60, allow_inf_nan=False
    )
    max_result_rows: int = Field(default=20, gt=0, le=1000)
    # Expired uploads are deleted on this schedule even when no one visits.
    cleanup_interval_seconds: float = Field(
        default=60.0, gt=0, le=3600, allow_inf_nan=False
    )
    # Behind one load balancer (AWS Lightsail or ALB), the client address is
    # the right-most X-Forwarded-For entry, which that proxy appends. Enable
    # only when such a proxy is always in front of the server.
    trust_forwarded_for: bool = False
