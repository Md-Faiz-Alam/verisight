"""Schema models and inference for ingested VeriSight tables."""

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_float_dtype,
    is_integer_dtype,
    is_object_dtype,
    is_string_dtype,
)

from verisight.ingestion.models import LoadedDataset, LoadedTable


class LogicalType(StrEnum):
    """Logical data types recognized during schema inference."""

    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    STRING = "string"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ColumnSchema:
    """Inferred schema information for one column."""

    name: str
    physical_dtype: str
    logical_type: LogicalType
    nullable: bool
    missing_count: int


@dataclass(frozen=True, slots=True)
class TableSchema:
    """Inferred schema information for one table."""

    name: str
    relation_name: str
    row_count: int
    column_count: int
    columns: tuple[ColumnSchema, ...]


@dataclass(frozen=True, slots=True)
class DatasetSchema:
    """Inferred schemas for all tables in a dataset."""

    tables: tuple[TableSchema, ...]

    @property
    def table_count(self) -> int:
        """Return the number of table schemas."""

        return len(self.tables)


class SchemaInferer:
    """Infer conservative structural schemas from loaded tables."""

    def infer_table(self, table: LoadedTable) -> TableSchema:
        """Infer the schema of one loaded table."""

        columns = tuple(
            self._infer_column(
                name=str(column_name),
                series=table.data[column_name],
            )
            for column_name in table.data.columns
        )

        return TableSchema(
            name=table.name,
            relation_name=table.relation_name,
            row_count=table.row_count,
            column_count=table.column_count,
            columns=columns,
        )

    def infer_dataset(self, dataset: LoadedDataset) -> DatasetSchema:
        """Infer schemas for all tables in a loaded dataset."""

        return DatasetSchema(
            tables=tuple(self.infer_table(table) for table in dataset.tables)
        )

    @staticmethod
    def _infer_column(
        *,
        name: str,
        series: pd.Series,
    ) -> ColumnSchema:
        """Infer structural information for one column."""

        missing_count = int(series.isna().sum())

        return ColumnSchema(
            name=name,
            physical_dtype=str(series.dtype),
            logical_type=SchemaInferer._infer_logical_type(series),
            nullable=missing_count > 0,
            missing_count=missing_count,
        )

    @staticmethod
    def _infer_logical_type(series: pd.Series) -> LogicalType:
        """Map a pandas series to a conservative VeriSight logical type."""

        dtype = series.dtype

        if is_bool_dtype(dtype):
            return LogicalType.BOOLEAN

        if is_integer_dtype(dtype):
            return LogicalType.INTEGER

        if is_float_dtype(dtype):
            return LogicalType.FLOAT

        if is_datetime64_any_dtype(dtype):
            return LogicalType.DATETIME

        if is_object_dtype(dtype):
            non_missing = series.dropna()

            if non_missing.empty:
                return LogicalType.UNKNOWN

            if non_missing.map(lambda value: isinstance(value, str)).all():
                return LogicalType.STRING

            return LogicalType.UNKNOWN

        if is_string_dtype(dtype):
            return LogicalType.STRING

        return LogicalType.UNKNOWN
