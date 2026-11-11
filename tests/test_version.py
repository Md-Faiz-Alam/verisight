"""One version number across the Python package, the website and its API."""

import json
import tomllib
from pathlib import Path

import verisight
from verisight.config import Settings
from verisight.web import create_app

ROOT = Path(__file__).parent.parent


def test_every_part_reports_the_same_version() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    frontend = json.loads((ROOT / "frontend" / "package.json").read_text("utf-8"))
    app = create_app(settings=Settings(gemini_api_key=None))

    assert project["project"]["version"] == verisight.__version__
    assert frontend["version"] == verisight.__version__
    assert app.version == verisight.__version__
