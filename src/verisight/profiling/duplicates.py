"""Duplicate-row analysis for VeriSight tables."""

import pandas as pd

from verisight.profiling.models import DuplicateStatistics


class DuplicateAnalyzer:
    """Compute deterministic table-level duplicate-row measurements."""

    def analyze(self, data: pd.DataFrame) -> DuplicateStatistics:
        """Analyze duplicate rows without modifying the source data."""

        row_count = len(data)

        if row_count == 0 or len(data.columns) == 0:
            return DuplicateStatistics(
                duplicate_row_count=0,
                duplicate_row_ratio=0.0,
                duplicate_group_row_count=0,
                duplicate_group_row_ratio=0.0,
            )

        duplicate_mask = data.duplicated(keep="first")
        duplicate_group_mask = data.duplicated(keep=False)

        duplicate_row_count = int(duplicate_mask.sum())
        duplicate_group_row_count = int(duplicate_group_mask.sum())

        return DuplicateStatistics(
            duplicate_row_count=duplicate_row_count,
            duplicate_row_ratio=duplicate_row_count / row_count,
            duplicate_group_row_count=duplicate_group_row_count,
            duplicate_group_row_ratio=duplicate_group_row_count / row_count,
        )
