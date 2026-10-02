"""High-level analytical execution services for VeriSight."""

from verisight.execution.engine import DuckDBExecutor
from verisight.execution.models import QueryResult
from verisight.ingestion.models import LoadedDataset


class AnalyticalExecutionService:
    """Execute analytical queries against a loaded dataset."""

    def __init__(self, dataset: LoadedDataset) -> None:
        """Initialize the service for a loaded dataset."""

        self._dataset = dataset
        self._executor = DuckDBExecutor()

    def execute(self, query: str) -> QueryResult:
        """Execute an analytical query against the loaded dataset."""

        return self._executor.execute(
            self._dataset,
            query,
        )
