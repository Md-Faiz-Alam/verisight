"""Orchestration for autonomous analytical investigations."""

from dataclasses import dataclass, replace
from typing import Literal

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
    ClaimOutputContract,
    InvestigationFailure,
    InvestigationResult,
    InvestigationStatus,
    SynthesisFailure,
    SynthesisRecovery,
)
from verisight.execution.investigator import Investigator
from verisight.execution.observations import QueryObservation
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.execution.synthesis import InvestigationSynthesizer, StructuredSynthesis

RecoveryTrigger = Literal[
    "invalid_claim_reference", "claim_value_mismatch", "empty_claims"
]

_RECOVERY_INSTRUCTION = (
    "The evidence collected so far does not contain the requested final value "
    "as a numeric SQL result cell. Compute each value the requested claim needs "
    "directly in SQL, each as its own numeric result column, instead of only "
    "counts or other components."
)


@dataclass(frozen=True, slots=True)
class _PendingRecovery:
    trigger: RecoveryTrigger
    repair_attempted: bool | None
    baseline_observations: int
    fallback: InvestigationResult


class InvestigationOrchestrator:
    """Coordinate bounded autonomous analytical investigations.

    A one-attempt investigation plans the caller's original task. With more
    attempts, investigator subquestions remain the planning tasks. The
    investigator controls whether to query. After a successful one-attempt
    query, synthesis runs directly; multi-step investigations still require
    a finish decision. Neither path establishes full task acceptance.

    A finish decision before any query was attempted plans the original
    question once instead, because conclusions require SQL evidence; the
    result records this as ``initial_query_required``.

    With a claim output contract, a finished synthesis that cites a missing
    or inconsistent cell, or returns no claims, may use one remaining step
    for a recovery query that asks for the final value as its own result
    cell. Synthesis then runs once more on all evidence; this happens at
    most once per investigation and is recorded as ``synthesis_recovery``.
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
        claim_output_contract: ClaimOutputContract | None = None,
    ) -> None:
        """Initialize the investigation orchestrator."""

        if max_steps <= 0:
            raise ValueError("Maximum investigation steps must be positive.")

        if not 0 < timeout_seconds < float("inf"):
            raise ValueError("Investigation timeout must be finite and positive.")

        self._population = population
        self._claim_output_contract = claim_output_contract
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
        """Attach run records to whichever result ends the run."""

        pending: list[_PendingRecovery] = []
        initial_query: list[bool] = []
        result = self._run(
            question=question,
            analysis=analysis,
            pending=pending,
            initial_query=initial_query,
        )
        if initial_query:
            result = replace(result, initial_query_required=True)
        if pending and result.synthesis_recovery is None:
            result = replace(
                result,
                synthesis_recovery=SynthesisRecovery(
                    trigger=pending[0].trigger,
                    repair_attempted=pending[0].repair_attempted,
                    query_succeeded=False,
                ),
            )
        return result

    def _run(
        self,
        *,
        question: str,
        analysis: DatasetAnalysisResult,
        pending: list[_PendingRecovery],
        initial_query: list[bool],
    ) -> InvestigationResult:
        """Keep the latest state available if any stage exhausts the budget."""

        state = InvestigationState(
            question=question,
            analysis=analysis,
            population=self._population,
            remaining_steps=self._max_steps,
            claim_output_contract=self._claim_output_contract,
        )
        attempted_questions: set[str] = set()
        attempt_count = 0

        try:
            while True:
                check_deadline()
                if pending:
                    recovery = pending[0]
                    if state.observation_count == recovery.baseline_observations:
                        # Keep the failed recovery attempt in the reported history.
                        return replace(
                            recovery.fallback, failed_attempts=state.failed_attempts
                        )
                    return replace(
                        self._synthesize(state),
                        synthesis_recovery=SynthesisRecovery(
                            trigger=recovery.trigger,
                            repair_attempted=recovery.repair_attempted,
                            query_succeeded=True,
                        ),
                    )
                if self._max_steps == 1 and state.observation_count == 1:
                    return self._synthesize(state)

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

                if (
                    decision.action is InvestigationAction.FINISH
                    and state.observation_count == 0
                    and state.failed_attempt_count == 0
                ):
                    # Profiling context can make a question look answered, but
                    # conclusions need SQL evidence. Query the original task
                    # once instead of finishing with nothing to verify.
                    initial_query.append(True)
                    investigation_question = state.question
                elif decision.action is InvestigationAction.FINISH:
                    if state.observation_count == 0:
                        return self._incomplete(
                            state, reason="all attempted analytical queries failed"
                        )

                    result = self._synthesize(state)
                    trigger = self._recovery_trigger(result)
                    if trigger is None or attempt_count >= self._max_steps:
                        return result
                    pending.append(
                        _PendingRecovery(
                            trigger=trigger,
                            repair_attempted=(
                                None
                                if result.synthesis_failure is None
                                else result.synthesis_failure.repair_attempted
                            ),
                            baseline_observations=state.observation_count,
                            fallback=result,
                        )
                    )
                    investigation_question = (
                        f"{state.question}\n\n{_RECOVERY_INSTRUCTION}"
                    )
                else:
                    if attempt_count >= self._max_steps:
                        return self._incomplete(
                            state,
                            reason="the maximum number of analytical steps was reached",
                        )

                    planned_question = decision.question
                    if planned_question is None:
                        raise InvestigationError(
                            "Investigator did not provide an analytical question."
                        )

                    # With one attempt, a rewritten subquestion cannot be followed
                    # by a query for the actual requested metric. Plan the caller's
                    # task directly; multi-step investigations retain subquestions.
                    investigation_question = (
                        state.question if self._max_steps == 1 else planned_question
                    )

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
                        population_review=execution.population_review,
                        grain_review=execution.grain_review,
                    )
                )
        except InvestigationDeadlineExceeded:
            return self._incomplete(
                state,
                reason="the investigation time budget was exhausted",
            )

    def _recovery_trigger(self, result: InvestigationResult) -> RecoveryTrigger | None:
        """Identify a contract result whose evidence lacks the final value."""

        if self._claim_output_contract is None:
            return None
        failure = result.synthesis_failure
        if failure is not None:
            if failure.validation_reason == "invalid_claim_reference":
                return "invalid_claim_reference"
            if failure.validation_reason == "claim_value_mismatch":
                return "claim_value_mismatch"
            return None
        if result.status is InvestigationStatus.COMPLETE and not (
            result.generated_claims
        ):
            return "empty_claims"
        return None

    def _synthesize(self, state: InvestigationState) -> InvestigationResult:
        """Evaluate collected evidence through the existing synthesis boundary."""

        try:
            synthesis = self._synthesizer.synthesize(state)
            check_deadline()
        except PromptBudgetExceededError as exc:
            return self._incomplete(
                state,
                reason=("final synthesis exceeded the configured prompt budget"),
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
                synthesis.claims if isinstance(synthesis, StructuredSynthesis) else ()
            ),
            analysis=state.analysis,
            observations=state.observations,
            failed_attempts=state.failed_attempts,
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
