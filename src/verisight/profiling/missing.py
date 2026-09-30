"""Missing-value analysis for VeriSight tables."""

import pandas as pd

from verisight.profiling.models import MissingValueStatistics


class MissingValueAnalyzer:
    """Compute deterministic table-level missing-value measurements."""

    def analyze(self, data: pd.DataFrame) -> MissingValueStatistics:
        """Analyze missing values without modifying the source data."""

        row_count = len(data)
        column_count = len(data.columns)
        total_cell_count = row_count * column_count

        missing_mask = data.isna()

        missing_cell_count = int(missing_mask.to_numpy().sum())
        missing_cell_ratio = (
            missing_cell_count / total_cell_count if total_cell_count > 0 else 0.0
        )

        if column_count > 0:
            rows_with_missing_count = int(missing_mask.any(axis=1).sum())
            fully_missing_row_count = int(missing_mask.all(axis=1).sum())
        else:
            rows_with_missing_count = 0
            fully_missing_row_count = 0

        rows_with_missing_ratio = (
            rows_with_missing_count / row_count if row_count > 0 else 0.0
        )

        fully_missing_row_ratio = (
            fully_missing_row_count / row_count if row_count > 0 else 0.0
        )

        if row_count > 0:
            columns_with_missing_count = int(missing_mask.any(axis=0).sum())
        else:
            columns_with_missing_count = 0

        columns_with_missing_ratio = (
            columns_with_missing_count / column_count if column_count > 0 else 0.0
        )

        return MissingValueStatistics(
            total_cell_count=total_cell_count,
            missing_cell_count=missing_cell_count,
            missing_cell_ratio=missing_cell_ratio,
            rows_with_missing_count=rows_with_missing_count,
            rows_with_missing_ratio=rows_with_missing_ratio,
            fully_missing_row_count=fully_missing_row_count,
            fully_missing_row_ratio=fully_missing_row_ratio,
            columns_with_missing_count=columns_with_missing_count,
            columns_with_missing_ratio=columns_with_missing_ratio,
        )
