"""High-level ingestion services for VeriSight."""

import re
from collections.abc import Iterable
from pathlib import Path

from verisight.config import Settings
from verisight.ingestion.dispatcher import FileLoader
from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    LoadedWorkbook,
)

_NON_IDENTIFIER_PATTERN = re.compile(r"[^a-z0-9]+")

_RESERVED_RELATION_NAMES = frozenset(
    {
        "all",
        "and",
        "as",
        "by",
        "case",
        "create",
        "delete",
        "distinct",
        "drop",
        "else",
        "end",
        "from",
        "group",
        "having",
        "insert",
        "into",
        "join",
        "limit",
        "not",
        "null",
        "on",
        "or",
        "order",
        "select",
        "table",
        "then",
        "union",
        "update",
        "values",
        "when",
        "where",
        "with",
    }
)


class DatasetLoader:
    """Load one or more files into a normalized dataset."""

    def __init__(self, settings: Settings) -> None:
        self._file_loader = FileLoader(settings)

    def load(self, paths: Iterable[str | Path]) -> LoadedDataset:
        """Load files and normalize their tables into one dataset."""

        tables: list[LoadedTable] = []

        for path in paths:
            result = self._file_loader.load(path)

            if isinstance(result, LoadedWorkbook):
                tables.extend(result.tables)
            else:
                tables.append(result)

        self._assign_relation_names(tables)

        return LoadedDataset(tables=tables)

    @classmethod
    def _assign_relation_names(
        cls,
        tables: list[LoadedTable],
    ) -> None:
        """Assign deterministic, dataset-unique relation names."""

        used_names: set[str] = set()

        for table in tables:
            base_name = cls._sanitize_relation_name(table.name)
            relation_name = base_name
            suffix = 2

            while relation_name in used_names:
                relation_name = f"{base_name}_{suffix}"
                suffix += 1

            table.relation_name = relation_name
            used_names.add(relation_name)

    @staticmethod
    def _sanitize_relation_name(name: str) -> str:
        """Convert a display name into a safe relation identifier."""

        normalized = name.strip().lower()
        normalized = _NON_IDENTIFIER_PATTERN.sub("_", normalized)
        normalized = normalized.strip("_")

        if not normalized:
            return "table"

        if normalized[0].isdigit():
            normalized = f"table_{normalized}"

        if normalized in _RESERVED_RELATION_NAMES:
            normalized = f"table_{normalized}"

        return normalized
