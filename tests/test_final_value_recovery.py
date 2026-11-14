"""Contract-mode recovery when evidence lacks the requested final value."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from verisight import VeriSight
from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.config import Settings
from verisight.execution.claim_verification import (
    ClaimOperation,
    ClaimVerificationResult,
    EvidenceReference,
    NumericalClaim,
    NumericalClaimVerifier,
    VerificationStatus,
)
from verisight.execution.exceptions import SynthesisValidationError
from verisight.execution.gemini import GeminiTransientError, ProviderFailureDiagnostics
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.generative_repair import GenerativeQueryRepairer
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
    InvestigationStatus,
    SynthesisRecovery,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.orchestration import _RECOVERY_INSTRUCTION
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile

QUESTION = "Among team a, what percentage of results are yes?"
COUNT_SQL = (
    "SELECT SUM(CASE WHEN result = 'yes' THEN 1 ELSE 0 END) AS yes_count, "
    "COUNT(*) AS total_count FROM outcomes WHERE team = 'a'"
)
PERCENT_SQL = (
    "SELECT 100.0 * SUM(CASE WHEN result = 'yes' THEN 1 ELSE 0 END) / COUNT(*) "
    "AS yes_percentage FROM outcomes WHERE team = 'a'"
)


class _Script:
    """Scripted text generation; exceptions in the script are raised."""

    def __init__(self, items: list[str | Exception]) -> None:
        self.items = list(items)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _decision(question: str | None) -> str:
    action = "finish" if question is None else "investigate"
    return json.dumps({"action": action, "reasoning": "r", "question": question})


def _synthesis(conclusion: str, column: str | None, observation: int = 0) -> str:
    claims = (
        []
        if column is None
        else [
            {
                "operation": "value",
                "expected": "50",
                "left": {
                    "observation_index": observation,
                    "row_index": 0,
                    "column": column,
                },
                "right": None,
            }
        ]
    )
    return json.dumps({"conclusion": conclusion, "claims": claims})


INVENTED = _synthesis("The percentage is 50.", "yes_percentage")
MISMATCH = _synthesis("The percentage is 50.", "yes_count")
EMPTY = _synthesis("Only counts were collected; the percentage is missing.", None)
GOOD = _synthesis("The percentage is 50.", "yes_percentage", observation=1)


def _run(
    tmp_path: Path,
    *,
    decide: list[str | Exception],
    plan: list[str | Exception],
    synth: list[str | Exception],
    repair: list[str | Exception] | None = None,
    max_steps: int = 3,
    contract: bool = True,
) -> tuple[InvestigationResult, _Script, _Script, _Script]:
    source = tmp_path / "outcomes.csv"
    source.write_text(
        "team,result\na,yes\na,no\na,yes\na,no\nb,yes\n", encoding="utf-8"
    )
    investigator, planner, synthesizer = _Script(decide), _Script(plan), _Script(synth)
    app = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False),
        planner=GenerativeQueryPlanner(planner),
        investigator=GenerativeInvestigator(investigator),
        repairer=GenerativeQueryRepairer(_Script(repair or [])),
        synthesizer=StructuredInvestigationSynthesizer(synthesizer),
    )
    result = app.investigate(
        source,
        QUESTION,
        max_steps=max_steps,
        claim_output_contract=(
            ClaimOutputContract((ClaimOperation.VALUE,)) if contract else None
        ),
    )
    return result, investigator, planner, synthesizer


@pytest.mark.parametrize(
    ("first", "trigger", "repaired"),
    [
        ([INVENTED, INVENTED], "invalid_claim_reference", True),
        ([MISMATCH, MISMATCH], "claim_value_mismatch", True),
        ([EMPTY], "empty_claims", None),
    ],
    ids=["invented-cell", "count-cited-as-percentage", "limitation"],
)
def test_missing_final_value_uses_one_recovery_query(
    tmp_path: Path, first: list[str | Exception], trigger: str, repaired: bool | None
) -> None:
    result, investigator, planner, synthesizer = _run(
        tmp_path,
        decide=[_decision("Count yes results and all results"), _decision(None)],
        plan=[COUNT_SQL, PERCENT_SQL],
        synth=[*first, GOOD],
    )

    assert result.status is InvestigationStatus.COMPLETE
    assert result.synthesis_failure is None
    assert [item.sql for item in result.observations] == [COUNT_SQL, PERCENT_SQL]
    assert result.verified_claims[0].verification.status is (
        VerificationStatus.SUPPORTED
    )
    assert result.synthesis_recovery == SynthesisRecovery(
        trigger=trigger,  # type: ignore[arg-type]
        repair_attempted=repaired,
        query_succeeded=True,
    )
    # The recovery query plans the original question; no extra decision call.
    assert QUESTION in planner.prompts[1]
    assert _RECOVERY_INSTRUCTION in planner.prompts[1]
    assert len(investigator.prompts) == 2
    assert len(synthesizer.prompts) == len(first) + 1


def test_recovery_happens_at_most_once(tmp_path: Path) -> None:
    result, _, planner, synthesizer = _run(
        tmp_path,
        decide=[_decision("Count yes results and all results"), _decision(None)],
        plan=[COUNT_SQL, COUNT_SQL],
        synth=[MISMATCH, MISMATCH, MISMATCH, MISMATCH],
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.synthesis_failure is not None
    assert result.synthesis_failure.validation_reason == "claim_value_mismatch"
    assert result.synthesis_recovery == SynthesisRecovery(
        "claim_value_mismatch", True, True
    )
    assert len(planner.prompts) == 2
    assert len(synthesizer.prompts) == 4


def test_no_recovery_without_a_remaining_step(tmp_path: Path) -> None:
    result, _, planner, _ = _run(
        tmp_path,
        decide=[
            _decision("Count yes results"),
            _decision("Count all results"),
            _decision(None),
        ],
        plan=[COUNT_SQL, COUNT_SQL],
        synth=[INVENTED, INVENTED],
        max_steps=2,
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.synthesis_recovery is None
    assert len(planner.prompts) == 2


@pytest.mark.parametrize(
    ("synth", "contract"),
    [([EMPTY], False), (["not json", "not json"], True)],
    ids=["no-contract", "unrelated-format-failure"],
)
def test_other_outcomes_do_not_trigger_recovery(
    tmp_path: Path, synth: list[str | Exception], contract: bool
) -> None:
    result, _, planner, _ = _run(
        tmp_path,
        decide=[_decision("Count yes results and all results"), _decision(None)],
        plan=[COUNT_SQL],
        synth=synth,
        contract=contract,
    )

    assert result.synthesis_recovery is None
    assert len(planner.prompts) == 1


BY_TEAM_SQL = "SELECT team, COUNT(*) AS n FROM outcomes GROUP BY team ORDER BY team"
TOTAL_SQL = "SELECT COUNT(*) AS total FROM outcomes WHERE team = 'a'"


def _claim(
    expected: str, row: int, column: str, observation: int = 0
) -> dict[str, object]:
    return {
        "operation": "value",
        "expected": expected,
        "left": {"observation_index": observation, "row_index": row, "column": column},
        "right": None,
    }


TWO_CLAIMS = json.dumps(
    {
        "conclusion": "Team a has 4 and team b has 1.",
        "claims": [_claim("4", 0, "n"), _claim("1", 1, "n")],
    }
)


def test_a_total_split_over_rows_uses_the_recovery_query(tmp_path: Path) -> None:
    single = json.dumps(
        {"conclusion": "Team a has 4.", "claims": [_claim("4", 0, "total", 1)]}
    )

    result, _, planner, _ = _run(
        tmp_path,
        decide=[_decision("Count results for each team"), _decision(None)],
        plan=[BY_TEAM_SQL, TOTAL_SQL],
        synth=[TWO_CLAIMS, TWO_CLAIMS, single],
    )

    assert result.status is InvestigationStatus.COMPLETE
    assert result.synthesis_recovery == SynthesisRecovery(
        "claim_output_contract_mismatch", True, True
    )
    assert "return one row with that number" in planner.prompts[1]


def test_parts_of_a_percentage_in_one_row_use_the_recovery_query(
    tmp_path: Path,
) -> None:
    two = json.dumps(
        {
            "conclusion": "There are 2 yes results of 4.",
            "claims": [_claim("2", 0, "yes_count"), _claim("4", 0, "total_count")],
        }
    )

    result, _, planner, _ = _run(
        tmp_path,
        decide=[_decision("Count yes results and all results"), _decision(None)],
        plan=[COUNT_SQL, PERCENT_SQL],
        synth=[two, two, GOOD],
    )

    assert result.status is InvestigationStatus.COMPLETE
    assert result.synthesis_recovery == SynthesisRecovery(
        "claim_output_contract_mismatch", True, True
    )
    assert "each as its own numeric result column" in planner.prompts[1]
    assert [item.verification.actual for item in result.verified_claims] == [
        Decimal("50.0")
    ]


def test_failed_recovery_query_returns_the_first_outcome(tmp_path: Path) -> None:
    bad = "SELECT missing_column FROM outcomes"
    result, _, planner, synthesizer = _run(
        tmp_path,
        decide=[_decision("Count yes results and all results"), _decision(None)],
        plan=[COUNT_SQL, bad],
        repair=[bad, bad, bad],
        synth=[INVENTED, INVENTED],
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.synthesis_failure is not None
    assert result.synthesis_failure.validation_reason == "invalid_claim_reference"
    assert result.failed_attempt_count == 1
    assert result.synthesis_recovery == SynthesisRecovery(
        "invalid_claim_reference", True, False
    )
    assert len(planner.prompts) == 2
    assert len(synthesizer.prompts) == 2


def test_provider_failure_during_recovery_is_recorded(tmp_path: Path) -> None:
    unavailable = GeminiTransientError(
        "unavailable",
        diagnostics=ProviderFailureDiagnostics(503, True, 2, "text_generation", 2),
    )
    result, _, _, _ = _run(
        tmp_path,
        decide=[_decision("Count yes results and all results"), _decision(None)],
        plan=[COUNT_SQL, unavailable],
        synth=[EMPTY],
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.investigation_failure is not None
    assert result.synthesis_recovery == SynthesisRecovery("empty_claims", None, False)


def _state(columns: tuple[str, ...], row: tuple[float, ...]) -> InvestigationState:
    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )
    return InvestigationState(
        question="What is the rate?",
        analysis=analysis,
        claim_output_contract=ClaimOutputContract((ClaimOperation.VALUE,)),
    ).add_observation(
        QueryObservation(
            question="Rate",
            sql="SELECT 1",
            result=QueryResult(columns=columns, rows=(row,)),
        )
    )


@pytest.mark.parametrize("expected", ["30.84", "30.8", "31", "30.8386"])
def test_rounded_values_still_reach_verification(expected: str) -> None:
    response = json.dumps(
        {
            "conclusion": f"The rate is {expected}.",
            "claims": [
                {
                    "operation": "value",
                    "expected": expected,
                    "left": {"observation_index": 0, "row_index": 0, "column": "rate"},
                    "right": None,
                }
            ],
        }
    )
    client = _Script([response])

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(
        _state(("rate",), (30.8386,))
    )

    assert synthesis.claims[0].expected == Decimal(expected)
    assert len(client.prompts) == 1


@pytest.mark.parametrize("expected", ["30.85", "3083.86", "30.8386000000000001"])
def test_values_that_are_not_a_rounding_are_repaired(expected: str) -> None:
    response = json.dumps(
        {
            "conclusion": f"The rate is {expected}.",
            "claims": [
                {
                    "operation": "value",
                    "expected": expected,
                    "left": {"observation_index": 0, "row_index": 0, "column": "rate"},
                    "right": None,
                }
            ],
        }
    )
    client = _Script([response, response])

    with pytest.raises(SynthesisValidationError) as caught:
        StructuredInvestigationSynthesizer(client).synthesize(
            _state(("rate",), (30.8386,))
        )

    assert caught.value.reason == "claim_value_mismatch"
    assert caught.value.repair_attempted is True


def _difference(
    expected: str, left: float | int, right: float | int
) -> ClaimVerificationResult:
    observation = QueryObservation(
        question="Compare",
        sql="SELECT 1",
        result=QueryResult(columns=("left", "right"), rows=((left, right),)),
    )
    claim = NumericalClaim(
        operation=ClaimOperation.DIFFERENCE,
        expected=Decimal(expected),
        left=EvidenceReference(0, 0, "left"),
        right=EvidenceReference(0, 0, "right"),
    )
    return NumericalClaimVerifier().verify(claim, (observation,))


RETIRED = 25.232558139534884
BLUE_COLLAR = 6.894315971471796


def test_difference_accepts_sqls_own_floating_point_result() -> None:
    # SQL computed this difference cell as 18.33824216806309, while the exact
    # decimal difference of the two cells is 18.338242168063088.
    floating = _difference("18.33824216806309", RETIRED, BLUE_COLLAR)
    exact = _difference("18.338242168063088", RETIRED, BLUE_COLLAR)
    # Both representations of one floating-point subtraction are accepted.
    tenths = _difference("0.19999999999999998", 0.3, 0.1)

    assert floating.status is VerificationStatus.SUPPORTED
    assert floating.actual == Decimal("18.33824216806309")
    assert "double-precision" in floating.reason
    assert exact.status is VerificationStatus.SUPPORTED
    assert exact.actual == Decimal("18.338242168063088")
    assert tenths.status is VerificationStatus.SUPPORTED


@pytest.mark.parametrize(
    ("expected", "left", "right"),
    [
        ("18.3382421680631", RETIRED, BLUE_COLLAR),
        ("18.34", RETIRED, BLUE_COLLAR),
        ("1", 3, 1),
        ("1", 3.5, 1),
        ("3.5E+308", 1.7e308, -1.7e308),
    ],
    ids=[
        "neither-result",
        "rounded",
        "integers",
        "mixed",
        "overflow",
    ],
)
def test_difference_floating_point_rule_is_narrow(
    expected: str, left: float | int, right: float | int
) -> None:
    result = _difference(expected, left, right)

    assert result.status is VerificationStatus.CONTRADICTED


def test_a_number_no_cell_holds_uses_the_recovery_query(tmp_path: Path) -> None:
    # The answer cites the count it found, then states a percentage worked out
    # in its own words, as an answer converting milliseconds to minutes would.
    converted = json.dumps(
        {
            "conclusion": "2 results were yes, which is 50 percent.",
            "claims": [
                {
                    "operation": "value",
                    "expected": "2",
                    "left": {
                        "observation_index": 0,
                        "row_index": 0,
                        "column": "yes_count",
                    },
                    "right": None,
                }
            ],
        }
    )

    result, _, planner, _ = _run(
        tmp_path,
        decide=[_decision("Count yes results and all results"), _decision(None)],
        plan=[COUNT_SQL, PERCENT_SQL],
        synth=[converted, converted, GOOD],
    )

    assert result.status is InvestigationStatus.COMPLETE
    assert result.synthesis_recovery == SynthesisRecovery(
        "unlinked_narrative_number", True, True
    )
    assert "in the unit and scale the question asks for" in planner.prompts[1]
    assert [item.verification.actual for item in result.verified_claims] == [
        Decimal("50.0")
    ]
