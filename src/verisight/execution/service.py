"""High-level analytical execution services for VeriSight."""

from verisight.execution.context import QueryContext, QueryContextBuilder
from verisight.execution.engine import DuckDBExecutor
from verisight.execution.formatting import QueryContextFormatter
from verisight.execution.models import QueryResult
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.schema import SchemaInferer


class AnalyticalExecutionService:
    """Execute analytical queries against a loaded dataset."""

    def __init__(self, dataset: LoadedDataset) -> None:
        """Initialize the service for a loaded dataset."""

        self._dataset = dataset
        self._executor = DuckDBExecutor()

        schema = SchemaInferer().infer_dataset(dataset)
        self._context = QueryContextBuilder().build(schema)
        self._formatted_context = QueryContextFormatter().format(self._context)

    @property
    def context(self) -> QueryContext:
        """Return the deterministic context for the loaded dataset."""

        return self._context

    @property
    def formatted_context(self) -> str:
        """Return the formatted deterministic query context."""

        return self._formatted_context

    def execute(self, query: str) -> QueryResult:
        """Execute an analytical query against the loaded dataset."""

        return self._executor.execute(
            self._dataset,
            query,
        )
