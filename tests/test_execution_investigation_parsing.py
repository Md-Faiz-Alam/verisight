import json

import pytest

from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import InvestigationError
from verisight.execution.investigation_parsing import (
    InvestigationResponseParser,
)


def test_parses_investigate_decision() -> None:
    response = """
    {
        "action": "investigate",
        "reasoning": "Revenue needs to be compared over time.",
        "question": "What is total revenue by month?"
    }
    """

    decision = InvestigationResponseParser().parse(response)

    assert decision == InvestigationDecision(
        action=InvestigationAction.INVESTIGATE,
        reasoning="Revenue needs to be compared over time.",
        question="What is total revenue by month?",
    )


def test_parses_finish_decision() -> None:
    response = """
    {
        "action": "finish",
        "reasoning": "The existing evidence is sufficient.",
        "question": null
    }
    """

    decision = InvestigationResponseParser().parse(response)

    assert decision == InvestigationDecision(
        action=InvestigationAction.FINISH,
        reasoning="The existing evidence is sufficient.",
    )


def test_strips_surrounding_whitespace() -> None:
    response = (
        '  \n{"action":"finish",'
        '"reasoning":"The evidence is sufficient.",'
        '"question":null}\n  '
    )

    decision = InvestigationResponseParser().parse(response)

    assert decision.action is InvestigationAction.FINISH


@pytest.mark.parametrize("response", ["", " ", "\n\t"])
def test_rejects_empty_response(response: str) -> None:
    with pytest.raises(
        InvestigationError,
        match="Investigator returned an empty response.",
    ):
        InvestigationResponseParser().parse(response)


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '{"action":',
        ('```json\n{"action":"finish","reasoning":"Done.","question":null}\n```'),
    ],
)
def test_rejects_invalid_json(response: str) -> None:
    with pytest.raises(
        InvestigationError,
        match="Investigator returned invalid JSON.",
    ):
        InvestigationResponseParser().parse(response)


@pytest.mark.parametrize(
    "response",
    ["[]", '"finish"', "42", "null"],
)
def test_rejects_non_object_json(response: str) -> None:
    with pytest.raises(
        InvestigationError,
        match="Investigator response must be a JSON object.",
    ):
        InvestigationResponseParser().parse(response)


@pytest.mark.parametrize(
    "response",
    [
        '{"action":"finish","reasoning":"Done."}',
        ('{"action":"finish","reasoning":"Done.","question":null,"extra":"value"}'),
    ],
)
def test_requires_exact_response_fields(response: str) -> None:
    with pytest.raises(
        InvestigationError,
        match=(
            "Investigator response must contain exactly "
            "action, reasoning, and question."
        ),
    ):
        InvestigationResponseParser().parse(response)


def test_rejects_non_string_action() -> None:
    response = (
        '{"action":1,"reasoning":"More evidence is required.",'
        '"question":"What is revenue by month?"}'
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator action must be a string.",
    ):
        InvestigationResponseParser().parse(response)


def test_rejects_unsupported_action() -> None:
    response = (
        '{"action":"continue","reasoning":"More evidence is required.",'
        '"question":"What is revenue by month?"}'
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator returned an unsupported action.",
    ):
        InvestigationResponseParser().parse(response)


def test_rejects_non_string_reasoning() -> None:
    response = json.dumps(
        {
            "action": "finish",
            "reasoning": 123,
            "question": None,
        }
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator reasoning must be a string.",
    ):
        InvestigationResponseParser().parse(response)


def test_rejects_non_string_question() -> None:
    response = json.dumps(
        {
            "action": "investigate",
            "reasoning": "More evidence is required.",
            "question": 123,
        }
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator question must be a string or null.",
    ):
        InvestigationResponseParser().parse(response)


@pytest.mark.parametrize(
    "reasoning",
    ["", " ", "\n\t"],
)
def test_rejects_empty_reasoning(reasoning: str) -> None:
    response = json.dumps(
        {
            "action": "finish",
            "reasoning": reasoning,
            "question": None,
        }
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator returned an invalid decision:",
    ):
        InvestigationResponseParser().parse(response)


@pytest.mark.parametrize(
    "question",
    [None, "", " ", "\n\t"],
)
def test_investigate_requires_question(
    question: str | None,
) -> None:
    response = json.dumps(
        {
            "action": "investigate",
            "reasoning": "More evidence is required.",
            "question": question,
        }
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator returned an invalid decision:",
    ):
        InvestigationResponseParser().parse(response)


def test_finish_rejects_question() -> None:
    response = json.dumps(
        {
            "action": "finish",
            "reasoning": "The investigation is complete.",
            "question": "What is revenue by month?",
        }
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator returned an invalid decision:",
    ):
        InvestigationResponseParser().parse(response)
