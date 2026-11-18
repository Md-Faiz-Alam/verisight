"""Keep every test away from the developer's own .env file and environment.

Settings read ``.env`` from the working directory. A local file can set a key
or a model for the second query, which changed outcomes on one computer that
CI, with no such file, never saw. Tests that check ``.env`` loading pass
``_env_file`` themselves.
"""

import os

import pytest

from verisight.config import Settings
from verisight.web.config import WebSettings


@pytest.fixture(autouse=True)
def _no_local_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.upper().startswith("VERISIGHT_"):
            monkeypatch.delenv(name)
    for settings in (Settings, WebSettings):
        monkeypatch.setitem(settings.model_config, "env_file", None)
