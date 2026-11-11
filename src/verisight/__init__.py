"""Public API for VeriSight."""

from verisight.service import VeriSight

# Kept equal to pyproject.toml and frontend/package.json by a test.
__version__ = "0.4.0"

__all__ = ["VeriSight", "__version__"]
