"""Precise conclusion-number linking: labels, rounded display, difference cells."""

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.execution.claim_verification import (
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
)
from verisight.execution.exceptions import SynthesisValidationError
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
    SynthesisFailure,
)
from verisight.execution.models import QueryResult
from verisight.execution.narrative_audit import (
    audit_narrative_digit_coverage,
    find_narrative_numbers,
    label_words,
)
from verisight.execution.observations import QueryObservation
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile

QUESTION = (
    "For VVS1-clarity diamonds, compute each diamond's price per carat, then "
    "report the mean of those per-diamond values as a single number."
)
MEAN = 3851.4105577450546
ADELIE = 189.95364238410596
CHINSTRAP = 195.8235294117647


class _Sequence:
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


def _observation(
    columns: tuple[str, ...], row: tuple[str | int | float, ...]
) -> QueryObservation:
    return QueryObservation(
        question="Measure",
        sql="SELECT 1",
        result=QueryResult(columns=columns, rows=(row,)),
    )


def _state(
    observation: QueryObservation,
    operation: ClaimOperation = ClaimOperation.VALUE,
    question: str = QUESTION,
) -> InvestigationState:
    return InvestigationState(
        question=question,
        analysis=_analysis(),
        claim_output_contract=ClaimOutputContract((operation,)),
    ).add_observation(observation)


def _ref(column: str) -> dict[str, object]:
    return {"observation_index": 0, "row_index": 0, "column": column}


def _value_response(conclusion: str, expected: str = str(MEAN)) -> str:
    return json.dumps(
        {
            "conclusion": conclusion,
            "claims": [
                {
                    "operation": "value",
                    "expected": expected,
                    "left": _ref("mean_price_per_carat"),
                    "right": None,
                }
            ],
        }
    )


def _difference_response(conclusion: str) -> str:
    return json.dumps(
        {
            "conclusion": conclusion,
            "claims": [
                {
                    "operation": "difference",
                    "expected": "-5.869887027658734",
                    "left": _ref("adelie"),
                    "right": _ref("chinstrap"),
                }
            ],
        }
    )


MEAN_STATE = _state(_observation(("mean_price_per_carat",), (MEAN,)))
FLIPPER_STATE = _state(
    _observation(("adelie", "chinstrap"), (ADELIE, CHINSTRAP)),
    ClaimOperation.DIFFERENCE,
    "Report the Adelie mean flipper length minus the Chinstrap mean.",
)


@pytest.mark.parametrize(
    "conclusion",
    [
        f"The mean price per carat of VVS1-clarity diamonds is {MEAN}.",
        "The mean price per carat of vvs1 diamonds is 3851.41.",
        "The mean price per carat is 3851.4.",
        "The mean price per carat is 3851.4106.",
    ],
    ids=["question-label", "label-any-case", "rounded-1dp", "rounded-4dp"],
)
def test_contract_accepts_labels_and_rounded_display(conclusion: str) -> None:
    client = _Sequence([_value_response(conclusion)])

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(MEAN_STATE)

    assert len(client.prompts) == 1
    result = InvestigationResult(
        question=QUESTION,
        conclusion=synthesis.conclusion,
        analysis=_analysis(),
        observations=MEAN_STATE.observations,
        generated_claims=synthesis.claims,
    )
    assessment = result.assess_output(ClaimOutputContract((ClaimOperation.VALUE,)))
    assert assessment.accepted is True


@pytest.mark.parametrize(
    "conclusion,values",
    [
        ("The mean price per carat is 3851.42.", ["3851.42"]),
        ("The mean price per carat is 3851.", ["3851"]),
        ("In Q4 the mean price per carat is 3851.41.", []),
        ("The mean price per carat over 53940 diamonds is 3851.41.", ["53940"]),
    ],
    ids=["wrong-rounding", "integer-rounding", "unknown-label", "uncited-count"],
)
def test_contract_still_rejects_unsupported_numbers(
    conclusion: str, values: list[str]
) -> None:
    client = _Sequence([_value_response(conclusion), _value_response(conclusion)])

    with pytest.raises(SynthesisValidationError) as caught:
        StructuredInvestigationSynthesizer(client).synthesize(MEAN_STATE)

    assert caught.value.reason == "unlinked_narrative_number"
    assert caught.value.repair_attempted is True
    assert list(caught.value.unlinked_numeric_values) == values
    failure = SynthesisFailure.from_exception(caught.value)
    assert list(failure.unlinked_numeric_values) == values


def test_difference_operands_may_be_stated() -> None:
    conclusion = (
        "Adelie penguins average 189.95 and Chinstrap penguins 195.82, so the "
        "Adelie mean minus the Chinstrap mean is -5.87."
    )
    client = _Sequence([_difference_response(conclusion)])

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(FLIPPER_STATE)

    assert len(client.prompts) == 1
    result = InvestigationResult(
        question=FLIPPER_STATE.question,
        conclusion=synthesis.conclusion,
        analysis=_analysis(),
        observations=FLIPPER_STATE.observations,
        generated_claims=synthesis.claims,
    )
    assert [token.link for token in result.narrative_numbers] == [
        "rounded_cited_cell",
        "rounded_cited_cell",
        "rounded_claim_value",
    ]
    assessment = result.assess_output(ClaimOutputContract((ClaimOperation.DIFFERENCE,)))
    assert assessment.accepted is True


def test_difference_does_not_allow_uncited_numbers() -> None:
    conclusion = "Across 344 penguins the difference is -5.87."
    client = _Sequence([_difference_response(conclusion)] * 2)

    with pytest.raises(SynthesisValidationError) as caught:
        StructuredInvestigationSynthesizer(client).synthesize(FLIPPER_STATE)

    assert caught.value.unlinked_numeric_values == ("344",)


def test_value_claims_link_only_their_stated_value() -> None:
    observation = _observation(("metric",), (11,))
    claim = NumericalClaim(ClaimOperation.VALUE, 10, EvidenceReference(0, 0, "metric"))
    result = InvestigationResult(
        question="Read the metric.",
        conclusion="The value is 11.",
        analysis=_analysis(),
        observations=(observation,),
        generated_claims=(claim,),
    )

    assert result.unlinked_numbers == ("11",)


def test_difference_with_a_missing_cell_links_only_available_values() -> None:
    observation = _observation(("left",), (5,))
    claim = NumericalClaim(
        ClaimOperation.DIFFERENCE,
        2,
        EvidenceReference(0, 0, "left"),
        EvidenceReference(0, 0, "missing"),
    )
    result = InvestigationResult(
        question="Compare.",
        conclusion="Left 5, right 3, difference 2.",
        analysis=_analysis(),
        observations=(observation,),
        generated_claims=(claim,),
    )

    assert result.unlinked_numbers == ("3",)


def test_labels_come_from_question_columns_and_text_cells() -> None:
    observation = _observation(("grade_q4",), ("basic.4y",))

    labels = label_words(
        ["VVS1-clarity in 2019", *observation.result.columns, "basic.4y"]
    )

    assert labels == frozenset({"vvs1", "vvs1-clarity", "grade_q4", "4y"})


@pytest.mark.parametrize(
    ("text", "unparsed"),
    [
        ("Movies rated PG-13 grossed 5 in total.", 0),
        ("Movies rated pg-13 grossed 5 in total.", 0),
        ("Movies rated PG-14 grossed 5 in total.", 2),
        ("COVID-19 cases were 5.", 2),
    ],
)
def test_hyphenated_labels_from_the_question_are_not_numbers(
    text: str, unparsed: int
) -> None:
    labels = label_words(["What is the total for movies rated PG-13?"])
    tokens = find_narrative_numbers(text, (Decimal(5),))

    coverage = audit_narrative_digit_coverage(text, tokens, labels)

    assert "pg-13" in labels
    assert coverage.unparsed_digit_count == unparsed


def test_digit_only_hyphen_ranges_are_never_labels() -> None:
    assert label_words(["Between 2010-2012 and 3-4 times"]) == frozenset()


def test_digits_outside_labels_are_still_counted() -> None:
    text = "VVS1 rose 2019 and Q4"
    tokens = find_narrative_numbers(text, ())

    coverage = audit_narrative_digit_coverage(text, tokens, frozenset({"vvs1"}))

    # "2019" is a parsed number; the Q4 digit is unparsed; VVS1 is not counted.
    assert coverage.total_digit_count == 5
    assert coverage.parsed_digit_count == 4
    assert coverage.unparsed_digit_count == 1


def test_label_only_text_has_no_digits() -> None:
    coverage = audit_narrative_digit_coverage("VVS1", (), frozenset({"vvs1"}))

    assert coverage.status == "no_digits"
    assert coverage.total_digit_count == 0


def test_rounding_never_links_beyond_the_decimal_context() -> None:
    tokens = find_narrative_numbers(
        "Value 1.5.", (Decimal("1E+400"),), ((Decimal("1E-400"),),)
    )

    assert tokens[0].claim_indexes == ()
    assert tokens[0].link is None


def test_non_contract_mode_keeps_question_numbers_and_rounding() -> None:
    state = replace(MEAN_STATE, claim_output_contract=None)
    conclusion = "For the 2 requested grades, the mean price per carat is 3851.41."
    question_state = replace(state, question=QUESTION + " Compare 2 grades.")
    client = _Sequence([_value_response(conclusion)])

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(question_state)

    assert synthesis.conclusion == conclusion
    assert len(client.prompts) == 1
