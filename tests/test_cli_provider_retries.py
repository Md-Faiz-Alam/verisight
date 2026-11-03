"""The CLI exposes provider retries and records them in the request."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from verisight.cli import main


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "orders.csv"
    path.write_text("state,amount\nactive,5\nclosed,7\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("options", "retries", "delay"),
    [
        ((), 1, 1.0),
        (("--provider-retries", "4", "--provider-retry-delay-seconds", "2.5"), 4, 2.5),
        (("--provider-retries", "0"), 0, 1.0),
    ],
    ids=["default", "custom", "none"],
)
def test_retry_options_are_applied_and_recorded(
    source: Path,
    capsys: pytest.CaptureFixture[str],
    options: tuple[str, ...],
    retries: int,
    delay: float,
) -> None:
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=AssertionError("Network forbidden"),
    ):
        code = main(
            ["investigate", str(source), "--question", "Sum amounts", "--preview"]
            + list(options)
        )

    assert code == 0
    request = json.loads(capsys.readouterr().out)["request"]
    assert request["provider_retries"] == retries
    assert request["provider_retry_base_delay_seconds"] == delay


@pytest.mark.parametrize(
    "options",
    [
        ("--provider-retries", "6"),
        ("--provider-retries", "-1"),
        ("--provider-retry-delay-seconds", "0"),
        ("--provider-retry-delay-seconds", "nan"),
    ],
)
def test_invalid_retry_options_are_rejected(
    source: Path, options: tuple[str, ...]
) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["investigate", str(source), "--question", "Sum amounts", *options])

    assert caught.value.code == 2
