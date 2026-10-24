"""Orchestration for autonomous analytical investigations."""

from verisight.analysis.result import DatasetAnalysisResult
from verisight.error_reporting import to_public_error
from verisight.execution.analytical import AnalyticalQueryRunner
from verisight.execution.context import PopulationFilter
from verisight.execution.deadline import (
    InvestigationDeadlineExceeded,
    check_deadline,
    investigation_deadline,
)
from verisight.execution.decisions import InvestigationAction
from verisight.execution.exceptions import (
    InvestigationError,
    QueryExecutionError,
    QueryPlanningError,
    QueryValidationError,
)
from verisight.execution.execution import capture_query_repairs
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.incomplete_evidence import IncompleteEvidenceError
from verisight.execution.investigation import FailedQueryAttempt, InvestigationState
from verisight.execution.investigation_result import (
    InvestigationFailure,
    InvestigationResult,
    InvestigationStatus,
    SynthesisFailure,
)
from verisight.execution.investigator import Investigator
from verisight.execution.observations import QueryObservation
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.execution.synthesis import InvestigationSynthesizer, StructuredSynthesis


class InvestigationOrchestrator:
    """Coordinate bounded autonomous analytical investigations.

    A one-attempt investigation plans the caller's original task. With more
    attempts, investigator subquestions remain the planning tasks. The
    investigator still controls whether to query and when to finish; neither
    policy establishes that the collected evidence answers the original task.
    """

    def __init__(
        self,
        *,
        execution_service: AnalyticalQueryRunner,
        investigator: Investigator,
        synthesizer: InvestigationSynthesizer,
        max_steps: int = 5,
        timeout_seconds: float = 300.0,
        population: tuple[PopulationFilter, ...] = (),
    ) -> None:
        """Initialize the investigation orchestrator."""

        if max_steps <= 0:
            raise ValueError("Maximum investigation steps must be positive.")

        if not 0 < timeout_seconds < float("inf"):
            raise ValueError("Investigation timeout must be finite and positive.")

        self._population = population
        self._timeout_seconds = timeout_seconds
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
        """Bound orchestration after dataset loading and profiling.

        The shared budget limits cancellable SDK/SQL work. Synchronous
        setup, custom callbacks, and cleanup may overrun until they return.
        """

        if not question.strip():
            raise InvestigationError("Investigation question must not be empty.")

        with investigation_deadline(self._timeout_seconds):
            return self._investigate(question=question, analysis=analysis)

    def _investigate(
        self,
        *,
        question: str,
        analysis: DatasetAnalysisResult,
    ) -> InvestigationResult:
        """Keep the latest state available if any stage exhausts the budget."""

        state = InvestigationState(
            question=question, analysis=analysis, population=self._population
        )
        attempted_questions: set[str] = set()
        attempt_count = 0

        try:
            while True:
                check_deadline()
                try:
                    decision = self._investigator.decide(state)
                    check_deadline()
                except (PromptBudgetExceededError, IncompleteEvidenceError):
                    return self._incomplete(state)

                except InvestigationDeadlineExceeded:
                    raise
                except (InvestigationError, GeminiGenerationError) as exc:
                    if state.observation_count == 0:
                        raise
                    return self._incomplete(
                        state,
                        reason="the next investigation decision could not be completed",
                        investigation_failure=InvestigationFailure.from_exception(
                            "investigator", exc
                        ),
                    )

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
                        check_deadline()
                    except PromptBudgetExceededError as exc:
                        return self._incomplete(
                            state,
                            reason=(
                                "final synthesis exceeded the configured prompt budget"
                            ),
                            synthesis_failure=SynthesisFailure.from_exception(exc),
                        )
                    except IncompleteEvidenceError:
                        return self._incomplete(state)
                    except InvestigationDeadlineExceeded:
                        raise
                    except (InvestigationError, GeminiGenerationError) as exc:
                        return self._incomplete(
                            state,
                            reason="final synthesis could not be completed",
                            synthesis_failure=SynthesisFailure.from_exception(exc),
                        )

                    return InvestigationResult(
                        population=state.population,
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
                        failed_attempts=state.failed_attempts,
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

                # With one attempt, a rewritten subquestion cannot be followed
                # by a query for the actual requested metric. Plan the caller's
                # task directly; multi-step investigations retain subquestions.
                if self._max_steps == 1:
                    investigation_question = state.question

                normalized_question = self._normalize_question(investigation_question)
                if normalized_question in attempted_questions:
                    return self._incomplete(
                        state,
                        reason="the investigator repeated an analytical question",
                    )

                attempted_questions.add(normalized_question)
                attempt_count += 1

                with capture_query_repairs() as repairs:
                    try:
                        execution = self._execution_service.run(
                            investigation_question, original_question=state.question
                        )
                    except InvestigationDeadlineExceeded:
                        state = state.add_failed_attempt(
                            FailedQueryAttempt(
                                question=investigation_question,
                                error_type="InvestigationDeadlineExceeded",
                                message="Investigation time budget was exhausted.",
                                repair_history=tuple(repairs),
                            )
                        )
                        raise
                    except (GeminiGenerationError, PromptBudgetExceededError) as exc:
                        state = state.add_failed_attempt(
                            FailedQueryAttempt(
                                question=investigation_question,
                                error_type=type(exc).__name__,
                                message=to_public_error(exc).message,
                                repair_history=tuple(repairs),
                            )
                        )
                        if state.observation_count == 0:
                            raise
                        return self._incomplete(
                            state,
                            reason=(
                                "a subsequent analytical attempt could not be completed"
                            ),
                            investigation_failure=InvestigationFailure.from_exception(
                                "query_execution", exc
                            ),
                        )
                    except (
                        QueryValidationError,
                        QueryExecutionError,
                        QueryPlanningError,
                    ) as exc:
                        state = state.add_failed_attempt(
                            FailedQueryAttempt(
                                question=investigation_question,
                                error_type=type(exc).__name__,
                                message=to_public_error(exc).message,
                                repair_history=tuple(repairs),
                            )
                        )
                        if isinstance(exc, QueryPlanningError):
                            failure = InvestigationFailure.from_exception(
                                "query_execution", exc
                            )
                            if failure.kind in {
                                "provider_error",
                                "provider_unavailable",
                            }:
                                if state.observation_count == 0:
                                    raise
                                return self._incomplete(
                                    state,
                                    reason=(
                                        "a subsequent analytical attempt "
                                        "could not be completed"
                                    ),
                                    investigation_failure=failure,
                                )

                        continue

                state = state.add_observation(
                    QueryObservation(
                        question=execution.plan.question,
                        sql=execution.plan.sql,
                        result=execution.result,
                        repair_history=tuple(execution.repair_history),
                    )
                )
        except InvestigationDeadlineExceeded:
            return self._incomplete(
                state,
                reason="the investigation time budget was exhausted",
            )

    @staticmethod
    def _incomplete(
        state: InvestigationState,
        *,
        reason: str | None = None,
        synthesis_failure: SynthesisFailure | None = None,
        investigation_failure: InvestigationFailure | None = None,
    ) -> InvestigationResult:
        """Preserve observations without presenting unsupported conclusions."""

        if reason is None:
            reason = (
                "the available evidence could not be fully evaluated "
                "within the configured prompt budget"
            )

        return InvestigationResult(
            population=state.population,
            question=state.question,
            conclusion=(
                f"Investigation incomplete: {reason}. "
                "No analytical conclusion has been established."
            ),
            analysis=state.analysis,
            observations=state.observations,
            failed_attempts=state.failed_attempts,
            status=InvestigationStatus.INCOMPLETE,
            synthesis_failure=synthesis_failure,
            investigation_failure=investigation_failure,
        )

    @staticmethod
    def _normalize_question(question: str) -> str:
        """Normalize a question for repetition detection."""

        return " ".join(question.split()).casefold()
