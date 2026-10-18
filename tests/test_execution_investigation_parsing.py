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


@pytest.mark.parametrize(
    "response",
    [
        (
            '{"action":"finish","action":"investigate",'
            '"reasoning":"Done.","question":null}'
        ),
        (
            '{"action":"finish","reasoning":"Done.",'
            '"question":null,"metadata":{"key":1,"key":2}}'
        ),
    ],
)
def test_rejects_duplicate_json_fields(response: str) -> None:
    with pytest.raises(
        InvestigationError,
        match="Investigator returned invalid JSON.",
    ):
        InvestigationResponseParser().parse(response)


@pytest.mark.parametrize(
    "constant",
    ["NaN", "Infinity", "-Infinity"],
)
def test_rejects_nonstandard_json_constants(constant: str) -> None:
    response = (
        '{"action":"finish","reasoning":"Done.",'
        f'"question":null,"metadata":{constant}' + "}"
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator returned invalid JSON.",
    ):
        InvestigationResponseParser().parse(response)


def test_accepts_escaped_json_field_content() -> None:
    response = json.dumps(
        {
            "action": "investigate",
            "reasoning": 'Compare revenue for "North" and "South".',
            "question": "What is revenue by region?\nInclude totals.",
        }
    )

    decision = InvestigationResponseParser().parse(response)

    assert decision.action is InvestigationAction.INVESTIGATE
    assert decision.reasoning == 'Compare revenue for "North" and "South".'
    assert decision.question == "What is revenue by region?\nInclude totals."


@pytest.mark.parametrize("label", ["json", "JSON", ""])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("action", ["finish", "investigate"])
def test_accepts_single_complete_json_fence(
    label: str, newline: str, action: str
) -> None:
    payload = json.dumps(
        {
            "action": action,
            "reasoning": "Check the evidence.",
            "question": "How many rows?" if action == "investigate" else None,
        }
    )
    response = f"  ```{label}{newline}{payload}{newline}```  "
    parser = InvestigationResponseParser()

    assert parser.parse(response) == parser.parse(payload)


@pytest.mark.parametrize(
    "template",
    [
        "Here is the result:\n```json\n{payload}\n```",
        "```json\n{payload}\n```\nExplanation follows.",
        "```json\n{payload}\n```\n```json\n{payload}\n```",
        "```python\n{payload}\n```",
        "```json\n{payload}",
        "{payload}\n```",
        "```json {payload}```",
    ],
)
def test_rejects_ambiguous_or_incomplete_fences(template: str) -> None:
    payload = '{"action":"finish","reasoning":"Done.","question":null}'

    with pytest.raises(InvestigationError, match="invalid JSON"):
        InvestigationResponseParser().parse(template.format(payload=payload))


@pytest.mark.parametrize(
    "payload",
    [
        "",
        '{"action":',
        '{"action":"finish","reasoning":"Done.","question":null} {}',
        '{"action":"finish","action":"investigate","reasoning":"Done.","question":null}',
        '{"action":"finish","reasoning":"Done.","question":NaN}',
        '{"action":"finish","reasoning":"Done.","question":Infinity}',
        '{"action":"finish","reasoning":"Done.","question":-Infinity}',
        "[]",
        '{"action":"finish","reasoning":"Done."}',
        '{"action":"finish","reasoning":"Done.","question":null,"extra":1}',
        '{"action":"investigate","reasoning":"Done.","question":null}',
        '{"action":"finish","reasoning":"","question":null}',
    ],
)
def test_fences_do_not_bypass_json_or_decision_validation(payload: str) -> None:
    with pytest.raises(InvestigationError):
        InvestigationResponseParser().parse(f"```json\n{payload}\n```")
