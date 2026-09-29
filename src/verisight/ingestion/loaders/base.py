"""Base interface for VeriSight document loaders."""

from abc import ABC, abstractmethod
from pathlib import Path

from verisight.ingestion.models import LoadedTable


class BaseTableLoader(ABC):
    """Interface implemented by tabular data loaders."""

    @abstractmethod
    def load(self, path: str | Path) -> LoadedTable:
        """Load a tabular dataset from the supplied path."""
