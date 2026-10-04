"""High-level analytical execution services for VeriSight."""

from verisight.execution.context import QueryContext, QueryContextBuilder
from verisight.execution.engine import DuckDBExecutor
from verisight.execution.exceptions import (
    QueryPlanningError,
    QueryRuntimeError,
)
from verisight.execution.execution import QueryExecution
from verisight.execution.formatting import QueryContextFormatter
from verisight.execution.models import QueryResult
from verisight.execution.planning import (
    QueryPlan,
    QueryPlanner,
    QueryRequest,
)
from verisight.execution.repair import QueryRepairer, QueryRepairRequest
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.schema import SchemaInferer


class AnalyticalExecutionService:
    """Execute analytical queries against a loaded dataset."""

    def __init__(
        self,
        dataset: LoadedDataset,
        planner: QueryPlanner | None = None,
        repairer: QueryRepairer | None = None,
        *,
        max_result_rows: int = 10_000,
        memory_limit_mb: int = 512,
    ) -> None:
        """Initialize the service for a loaded dataset."""

        self._dataset = dataset
        self._executor = DuckDBExecutor(
            max_result_rows=max_result_rows,
            memory_limit_mb=memory_limit_mb,
        )
        self._planner = planner
        self._repairer = repairer

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

        self._validate_plan(
            plan,
            expected_question=question,
            source="Query planner",
        )

        return plan

    def run(self, question: str) -> QueryExecution:
        """Plan and execute an analytical question with provenance."""

        plan = self.plan(question)

        try:
            result = self.execute(plan.sql)
        except QueryRuntimeError as exc:
            return self._repair_and_run(
                question=question,
                failed_plan=plan,
                error=exc,
            )

        return QueryExecution(
            plan=plan,
            result=result,
        )

    def ask(self, question: str) -> QueryResult:
        """Plan and execute an analytical natural-language question."""

        return self.run(question).result

    def _repair_and_run(
        self,
        *,
        question: str,
        failed_plan: QueryPlan,
        error: QueryRuntimeError,
    ) -> QueryExecution:
        """Repair one failed runtime query and execute the replacement."""

        if self._repairer is None:
            raise error

        request = QueryRepairRequest(
            question=question,
            failed_sql=failed_plan.sql,
            error=str(error),
            context=self._context,
        )

        repaired_plan = self._repairer.repair(request)

        self._validate_plan(
            repaired_plan,
            expected_question=question,
            source="Query repairer",
        )

        result = self.execute(repaired_plan.sql)

        return QueryExecution(
            plan=repaired_plan,
            result=result,
        )

    @staticmethod
    def _validate_plan(
        plan: QueryPlan,
        *,
        expected_question: str,
        source: str,
    ) -> None:
        """Validate invariants shared by planned and repaired queries."""

        if not plan.sql.strip():
            raise QueryPlanningError(f"{source} returned an empty SQL query.")

        if plan.question != expected_question:
            raise QueryPlanningError(
                f"{source} returned a plan for a different question."
            )
