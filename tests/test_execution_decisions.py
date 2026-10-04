import pytest

from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)


def test_creates_investigate_decision() -> None:
    decision = InvestigationDecision(
        action=InvestigationAction.INVESTIGATE,
        reasoning="Revenue should first be compared across time periods.",
        question="What is total revenue by month?",
    )

    assert decision.action is InvestigationAction.INVESTIGATE
    assert decision.reasoning == (
        "Revenue should first be compared across time periods."
    )
    assert decision.question == "What is total revenue by month?"


def test_creates_finish_decision() -> None:
    decision = InvestigationDecision(
        action=InvestigationAction.FINISH,
        reasoning="The existing observations explain the revenue decline.",
    )

    assert decision.action is InvestigationAction.FINISH
    assert decision.reasoning == (
        "The existing observations explain the revenue decline."
    )
    assert decision.question is None


@pytest.mark.parametrize(
    "reasoning",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_rejects_empty_reasoning(reasoning: str) -> None:
    with pytest.raises(
        ValueError,
        match="Investigation reasoning must not be empty.",
    ):
        InvestigationDecision(
            action=InvestigationAction.FINISH,
            reasoning=reasoning,
        )


@pytest.mark.parametrize(
    "question",
    [
        None,
        "",
        " ",
        "\n\t",
    ],
)
def test_investigate_decision_requires_question(
    question: str | None,
) -> None:
    with pytest.raises(
        ValueError,
        match="An investigate decision must include an analytical question.",
    ):
        InvestigationDecision(
            action=InvestigationAction.INVESTIGATE,
            reasoning="More evidence is required.",
            question=question,
        )


@pytest.mark.parametrize(
    "question",
    [
        "",
        "What is revenue by month?",
    ],
)
def test_finish_decision_rejects_question(
    question: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="A finish decision must not include an analytical question.",
    ):
        InvestigationDecision(
            action=InvestigationAction.FINISH,
            reasoning="The investigation is complete.",
            question=question,
        )
