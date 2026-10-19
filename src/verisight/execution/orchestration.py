"""Orchestration for autonomous analytical investigations."""

from verisight.analysis.result import DatasetAnalysisResult
from verisight.error_reporting import to_public_error
from verisight.execution.analytical import AnalyticalQueryRunner
from verisight.execution.decisions import InvestigationAction
from verisight.execution.exceptions import (
    InvestigationError,
    QueryExecutionError,
    QueryPlanningError,
    QueryValidationError,
)
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.incomplete_evidence import IncompleteEvidenceError
from verisight.execution.investigation import FailedQueryAttempt, InvestigationState
from verisight.execution.investigation_result import (
    InvestigationResult,
    InvestigationStatus,
    SynthesisFailure,
)
from verisight.execution.investigator import Investigator
from verisight.execution.observations import QueryObservation
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.execution.synthesis import InvestigationSynthesizer, StructuredSynthesis


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

        state = InvestigationState(question=question, analysis=analysis)
        attempted_questions: set[str] = set()
        attempt_count = 0

        while True:
            try:
                decision = self._investigator.decide(state)
            except (PromptBudgetExceededError, IncompleteEvidenceError):
                return self._incomplete(state)

            if decision.action is InvestigationAction.FINISH:
                if state.observation_count == 0:
                    reason = (
                        "all attempted analytical queries failed"
                        if state.failed_attempt_count > 0
                        else "no analytical observations were collected"
                    )
                    return self._incomplete(state, reason=reason)

                try:
                    synthesis = self._synthesizer.synthesize(state)
                except (PromptBudgetExceededError, IncompleteEvidenceError):
                    return self._incomplete(state)
                except (InvestigationError, GeminiGenerationError) as exc:
                    return self._incomplete(
                        state,
                        reason="final synthesis could not be completed",
                        synthesis_failure=SynthesisFailure.from_exception(exc),
                    )

                return InvestigationResult(
                    question=state.question,
                    conclusion=(
                        synthesis.conclusion
                        if isinstance(synthesis, StructuredSynthesis)
                        else synthesis
                    ),
                    generated_claims=(
                        synthesis.claims
                        if isinstance(synthesis, StructuredSynthesis)
                        else ()
                    ),
                    analysis=state.analysis,
                    observations=state.observations,
                )

            if attempt_count >= self._max_steps:
                return self._incomplete(
                    state,
                    reason="the maximum number of analytical steps was reached",
                )

            investigation_question = decision.question
            if investigation_question is None:
                raise InvestigationError(
                    "Investigator did not provide an analytical question."
                )

            normalized_question = self._normalize_question(investigation_question)
            if normalized_question in attempted_questions:
                return self._incomplete(
                    state,
                    reason="the investigator repeated an analytical question",
                )

            attempted_questions.add(normalized_question)
            attempt_count += 1

            try:
                execution = self._execution_service.run(investigation_question)
            except (
                QueryValidationError,
                QueryExecutionError,
                QueryPlanningError,
            ) as exc:
                if isinstance(exc, QueryPlanningError) and isinstance(
                    exc.__cause__, GeminiGenerationError
                ):
                    raise

                state = state.add_failed_attempt(
                    FailedQueryAttempt(
                        question=investigation_question,
                        error_type=type(exc).__name__,
                        message=to_public_error(exc).message,
                    )
                )
                continue

            state = state.add_observation(
                QueryObservation(
                    question=execution.plan.question,
                    sql=execution.plan.sql,
                    result=execution.result,
                )
            )

    @staticmethod
    def _incomplete(
        state: InvestigationState,
        *,
        reason: str | None = None,
        synthesis_failure: SynthesisFailure | None = None,
    ) -> InvestigationResult:
        """Preserve observations without presenting unsupported conclusions."""

        if reason is None:
            reason = (
                "the available evidence could not be fully evaluated "
                "within the configured prompt budget"
            )

        return InvestigationResult(
            question=state.question,
            conclusion=(
                f"Investigation incomplete: {reason}. "
                "No analytical conclusion has been established."
            ),
            analysis=state.analysis,
            observations=state.observations,
            status=InvestigationStatus.INCOMPLETE,
            synthesis_failure=synthesis_failure,
        )

    @staticmethod
    def _normalize_question(question: str) -> str:
        """Normalize a question for repetition detection."""

        return " ".join(question.split()).casefold()
