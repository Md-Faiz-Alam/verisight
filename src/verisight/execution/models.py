"""Domain models for analytical execution."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TypeAlias
from uuid import UUID

QueryScalar: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | date
    | datetime
    | time
    | timedelta
    | Decimal
    | UUID
)

QueryRow: TypeAlias = tuple[QueryScalar, ...]


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Structured result produced by an analytical query."""

    columns: tuple[str, ...]
    rows: tuple[QueryRow, ...]

    @property
    def row_count(self) -> int:
        """Return the number of result rows."""

        return len(self.rows)

    @property
    def column_count(self) -> int:
        """Return the number of result columns."""

        return len(self.columns)

    @property
    def is_empty(self) -> bool:
        """Return whether the query produced no rows."""

        return self.row_count == 0
