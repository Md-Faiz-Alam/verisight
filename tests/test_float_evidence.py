"""Floating-point SQL evidence: binary noise is accepted, real rounding is not."""

import json
from decimal import Decimal

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.execution.claim_verification import (
    FLOAT_SIGNIFICANT_DIGITS,
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
    NumericalClaimVerifier,
    VerificationStatus,
)
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile

# A live SUM over currency amounts (evaluation v2, run 2).
NOISY_SUM = 333819.64000000036
LEFT_MEAN = 1521.2574407582945
RIGHT_MEAN = 1560.5287542662106


def _observation(*cells: int | float | Decimal) -> QueryObservation:
    columns = tuple(f"c{index}" for index in range(len(cells)))
    return QueryObservation(
        question="Measure",
        sql="SELECT 1",
        result=QueryResult(columns=columns, rows=(cells,)),
    )


def _ref(column: str = "c0") -> EvidenceReference:
    return EvidenceReference(observation_index=0, row_index=0, column=column)


def _value(expected: str, cell: int | float | Decimal) -> VerificationStatus:
    claim = NumericalClaim(ClaimOperation.VALUE, Decimal(expected), _ref())
    return NumericalClaimVerifier().verify(claim, (_observation(cell),)).status


def test_rounded_display_of_a_noisy_sum_is_supported() -> None:
    claim = NumericalClaim(ClaimOperation.VALUE, Decimal("333819.64"), _ref())

    result = NumericalClaimVerifier().verify(claim, (_observation(NOISY_SUM),))

    assert FLOAT_SIGNIFICANT_DIGITS == 12
    assert result.status is VerificationStatus.SUPPORTED
    assert result.actual == Decimal("333819.64000000036")
    assert result.reason == (
        "The claimed value equals the floating-point evidence to 12 significant digits."
    )


@pytest.mark.parametrize(
    "expected",
    ["333819.6", "333820", "333819.65", "333819.640001", "333819.640000000001"],
    ids=["one-decimal", "integer", "wrong-cent", "12th-digit", "too-many-digits"],
)
def test_real_rounding_and_wrong_values_are_still_contradicted(expected: str) -> None:
    assert _value(expected, NOISY_SUM) is VerificationStatus.CONTRADICTED


@pytest.mark.parametrize(
    ("expected", "cell"),
    [
        ("333819.64", Decimal("333819.64000000036")),
        ("1000.00000001", 1000),
        ("0.00000000000000000001", 0.0),
    ],
    ids=["decimal-cell", "integer-cell", "zero-float"],
)
def test_exact_evidence_stays_exact(expected: str, cell: int | float | Decimal) -> None:
    assert _value(expected, cell) is VerificationStatus.CONTRADICTED


@pytest.mark.parametrize(
    ("expected", "status"),
    [
        ("-39.2713135079", VerificationStatus.SUPPORTED),
        ("-39.27", VerificationStatus.CONTRADICTED),
        ("39.2713135079", VerificationStatus.CONTRADICTED),
    ],
    ids=["noise", "rounded", "wrong-direction"],
)
def test_difference_of_float_cells(expected: str, status: VerificationStatus) -> None:
    claim = NumericalClaim(
        ClaimOperation.DIFFERENCE, Decimal(expected), _ref("c0"), _ref("c1")
    )

    result = NumericalClaimVerifier().verify(
        claim, (_observation(LEFT_MEAN, RIGHT_MEAN),)
    )

    assert result.status is status


class _Script:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses[len(self.prompts) - 1]


def _analysis() -> DatasetAnalysisResult:
    return AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )


def test_contract_mode_accepts_a_clean_display_of_a_noisy_sum() -> None:
    question = (
        "What is the total amount of orders placed by customers in the NA region?"
    )
    contract = ClaimOutputContract((ClaimOperation.VALUE,))
    observation = QueryObservation(
        question=question,
        sql="SELECT SUM(amount) FROM orders",
        result=QueryResult(columns=("sum(T1.Amount)",), rows=((NOISY_SUM,),)),
    )
    state = InvestigationState(
        question=question, analysis=_analysis(), claim_output_contract=contract
    ).add_observation(observation)
    response = json.dumps(
        {
            "conclusion": "The total amount of orders placed by customers in the NA "
            "region is 333819.64.",
            "claims": [
                {
                    "operation": "value",
                    "expected": "333819.64",
                    "left": {
                        "observation_index": 0,
                        "row_index": 0,
                        "column": "sum(T1.Amount)",
                    },
                    "right": None,
                }
            ],
        }
    )
    client = _Script([response])

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(state)
    result = InvestigationResult(
        question=question,
        conclusion=synthesis.conclusion,
        analysis=_analysis(),
        observations=state.observations,
        generated_claims=synthesis.claims,
    )

    assert len(client.prompts) == 1
    assert result.assess_output(contract).accepted is True
    assert result.verified_claims[0].verification.status is VerificationStatus.SUPPORTED


def test_planner_prompt_asks_for_derived_numbers_in_sql() -> None:
    from verisight.execution.context import QueryContext
    from verisight.execution.planning import QueryRequest
    from verisight.execution.prompting import QueryPromptBuilder

    prompt = QueryPromptBuilder().build(
        QueryRequest(
            question="How many days passed between the first and the last order?",
            context=QueryContext(relations=()),
        )
    )

    assert "including the days between two dates, compute it in SQL" in prompt
    assert "date_diff" in prompt
