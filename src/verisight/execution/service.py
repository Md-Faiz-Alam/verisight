"""High-level analytical execution services for VeriSight."""

from verisight.execution.context import QueryContext, QueryContextBuilder
from verisight.execution.engine import DuckDBExecutor
from verisight.execution.exceptions import QueryPlanningError
from verisight.execution.formatting import QueryContextFormatter
from verisight.execution.models import QueryResult
from verisight.execution.planning import QueryPlan, QueryPlanner, QueryRequest
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.schema import SchemaInferer


class AnalyticalExecutionService:
    """Execute analytical queries against a loaded dataset."""

    def __init__(
        self,
        dataset: LoadedDataset,
        planner: QueryPlanner | None = None,
    ) -> None:
        """Initialize the service for a loaded dataset."""

        self._dataset = dataset
        self._executor = DuckDBExecutor()
        self._planner = planner

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

    def plan(self, question: str) -> QueryPlan:
        """Plan an analytical query from a natural-language question."""

        if not question.strip():
            raise QueryPlanningError("Analytical question must not be empty.")

        if self._planner is None:
            raise QueryPlanningError("No query planner is configured.")

        request = QueryRequest(
            question=question,
            context=self._context,
        )

        plan = self._planner.plan(request)

        if not plan.sql.strip():
            raise QueryPlanningError("Query planner returned an empty SQL query.")

        if plan.question != question:
            raise QueryPlanningError(
                "Query planner returned a plan for a different question."
            )

        return plan

    def ask(self, question: str) -> QueryResult:
        """Plan and execute an analytical natural-language question."""

        plan = self.plan(question)

        return self.execute(plan.sql)
