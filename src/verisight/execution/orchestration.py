"""Orchestration for autonomous analytical investigations."""

from verisight.analysis.result import DatasetAnalysisResult
from verisight.execution.analytical import AnalyticalQueryRunner
from verisight.execution.decisions import InvestigationAction
from verisight.execution.exceptions import (
    InvestigationError,
    QueryExecutionError,
    QueryPlanningError,
    QueryValidationError,
)
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.investigation import (
    FailedQueryAttempt,
    InvestigationState,
)
from verisight.execution.investigation_result import InvestigationResult
from verisight.execution.investigator import Investigator
from verisight.execution.observations import QueryObservation
from verisight.execution.synthesis import InvestigationSynthesizer


class InvestigationOrchestrator:
    """Coordinate bounded autonomous analytical investigations."""

    def __init__(
        self,
        *,
        execution_service: AnalyticalQueryRunner,
        investigator: Investigator,
        synthesizer: InvestigationSynthesizer,
        max_steps: int = 5,
    ) -> None:
        """Initialize the investigation orchestrator."""

        if max_steps <= 0:
            raise ValueError("Maximum investigation steps must be positive.")

        self._execution_service = execution_service
        self._investigator = investigator
        self._synthesizer = synthesizer
        self._max_steps = max_steps

    def investigate(
        self,
        *,
        question: str,
        analysis: DatasetAnalysisResult,
    ) -> InvestigationResult:
        """Run a bounded autonomous investigation."""

        if not question.strip():
            raise InvestigationError("Investigation question must not be empty.")

        state = InvestigationState(
            question=question,
            analysis=analysis,
        )

        attempted_questions: set[str] = set()
        attempt_count = 0

        while True:
            decision = self._investigator.decide(state)

            if decision.action is InvestigationAction.FINISH:
                conclusion = self._synthesizer.synthesize(state)

                return InvestigationResult(
                    question=state.question,
                    conclusion=conclusion,
                    analysis=state.analysis,
                    observations=state.observations,
                )

            # Permit a final FINISH decision after the query budget
            # is exhausted, but never execute another query.
            if attempt_count >= self._max_steps:
                raise InvestigationError(
                    "Investigation exceeded the maximum number of steps."
                )

            investigation_question = decision.question

            if investigation_question is None:
                raise InvestigationError(
                    "Investigator did not provide an analytical question."
                )

            normalized_question = self._normalize_question(investigation_question)

            if normalized_question in attempted_questions:
                raise InvestigationError(
                    "Investigator requested a repeated analytical question."
                )

            attempted_questions.add(normalized_question)
            attempt_count += 1

            try:
                execution = self._execution_service.run(investigation_question)

            except QueryValidationError:
                # Preserve the existing SQL safety contract.
                # Prohibited SQL must not be treated as recoverable.
                raise

            except (QueryExecutionError, QueryPlanningError) as exc:
                if isinstance(exc, QueryPlanningError) and isinstance(
                    exc.__cause__, GeminiGenerationError
                ):
                    raise

                state = state.add_failed_attempt(
                    FailedQueryAttempt(
                        question=investigation_question,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
                continue

            observation = QueryObservation(
                question=execution.plan.question,
                sql=execution.plan.sql,
                result=execution.result,
            )

            state = state.add_observation(observation)

    @staticmethod
    def _normalize_question(question: str) -> str:
        """Normalize an analytical question for repetition detection."""

        return " ".join(question.split()).casefold()
