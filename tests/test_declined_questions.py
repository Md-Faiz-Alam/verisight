"""Questions the investigator declines instead of answering with a made-up query."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from verisight import VeriSight
from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.config import Settings
from verisight.execution.cross_check import CROSS_CHECK_REFUSAL_COLUMN
from verisight.execution.decisions import InvestigationAction, InvestigationDecision
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_compaction import InvestigationCompaction
from verisight.execution.investigation_parsing import (
    INVESTIGATION_DECISION_JSON_SCHEMA,
    InvestigationResponseParser,
)
from verisight.execution.investigation_prompting import InvestigationPromptBuilder
from verisight.execution.investigation_result import (
    DeclinedQuestion,
    InvestigationResult,
    InvestigationStatus,
)
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.web import create_app
from verisight.web.config import WebSettings

ROWS = "variety,area\nBesni,90000\nKecimen,60000\nBesni,95000\n"
ANALYSIS = AnalysisResultBuilder().build(
    DatasetAnalysis(
        sources=(),
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )
)


class _Script:
    def __init__(self, items: list[str]) -> None:
        self.items = list(items)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.items.pop(0)


def _decision(action: str, reasoning: str, question: str | None = None) -> str:
    return json.dumps({"action": action, "reasoning": reasoning, "question": question})


def _ask(
    tmp_path: Path, question: str, decisions: list[str], sql: list[str]
) -> tuple[dict[str, Any], _Script]:
    planner = _Script(sql)

    def factory(settings: Settings) -> VeriSight:
        return VeriSight(
            settings=settings.model_copy(update={"gemini_cross_check_model": None}),
            planner=GenerativeQueryPlanner(planner),
            investigator=GenerativeInvestigator(_Script(decisions)),
            synthesizer=StructuredInvestigationSynthesizer(_Script([])),
        )

    app = create_app(
        settings=Settings(gemini_api_key=None), web=WebSettings(), factory=factory
    )
    with TestClient(app) as client:
        upload = client.post(
            "/api/datasets", files=[("files", ("data.csv", ROWS.encode("utf-8")))]
        )
        reply = client.post(
            f"/api/datasets/{upload.json()['dataset_id']}/ask",
            json={"question": question, "consent": True, "api_key": "k"},
        ).json()
    return reply, planner


def test_a_quantity_the_data_lacks_gets_no_query_and_no_number(tmp_path: Path) -> None:
    reply, planner = _ask(
        tmp_path,
        "What is the average sugar content of the Besni raisins?",
        [_decision("not_in_data", "No column records sugar content.")],
        [],
    )

    assert planner.prompts == []
    assert reply["steps"] == []
    assert reply["claims"] == []
    assert reply["outcome"] == "unverified"
    assert reply["trust"]["level"] == "not_verified"
    assert reply["failure"] == {"kind": "measure_not_in_data"}
    assert reply["answer"] == (
        "No number is shown. The data does not appear to hold what the question "
        "asks for. No column records sugar content."
    )


def test_an_undefined_word_is_declined_after_looking_at_the_data(
    tmp_path: Path,
) -> None:
    reply, planner = _ask(
        tmp_path,
        "How many raisins are large?",
        [
            _decision("investigate", "r", "Which varieties are there?"),
            _decision("needs_definition", "It could mean 90000 or more."),
        ],
        ["SELECT DISTINCT variety FROM data"],
    )

    assert len(planner.prompts) == 1
    assert len(reply["steps"]) == 1
    assert reply["trust"]["level"] == "not_verified"
    assert reply["failure"] == {"kind": "undefined_in_question"}
    # The model's reason named a threshold nothing checked, so it is dropped.
    assert reply["answer"] == (
        "No number is shown. The question depends on a word or comparison that "
        "it does not define. Say what it means to get a number."
    )


def test_the_python_api_reports_a_declined_question(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text(ROWS, encoding="utf-8")
    engine = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=True),
        planner=GenerativeQueryPlanner(_Script([])),
        investigator=GenerativeInvestigator(
            _Script([_decision("not_in_data", "Nothing records it.")])
        ),
        synthesizer=StructuredInvestigationSynthesizer(_Script([])),
    )

    result = engine.investigate(path, "What is the average sugar content?")

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.declined == DeclinedQuestion(
        InvestigationAction.NOT_IN_DATA, "Nothing records it."
    )
    assert result.trust is None
    assert result.observations == ()
    assert result.conclusion.startswith("No number is shown. The data does not")


@pytest.mark.parametrize(
    ("reasoning", "kept"),
    [
        ("No column records sugar content.", "No column records sugar content."),
        ("  Spread over\n several lines. ", "Spread over several lines."),
        ("Area above 100000 could be meant.", None),
        ("Only three columns exist.", None),
        ("   ", None),
    ],
)
def test_a_reason_is_kept_only_when_it_states_no_number(
    reasoning: str, kept: str | None
) -> None:
    declined = DeclinedQuestion.from_reasoning(
        InvestigationAction.NOT_IN_DATA, reasoning, "What is the sugar content?"
    )

    assert declined.explanation == kept


def test_a_number_word_from_the_question_may_be_repeated() -> None:
    declined = DeclinedQuestion.from_reasoning(
        InvestigationAction.NEEDS_DEFINITION,
        "The two groups are not named.",
        "How much higher is it across the two groups?",
    )

    assert declined.explanation == "The two groups are not named."


def test_only_declining_actions_decline() -> None:
    with pytest.raises(ValueError, match="declining action"):
        DeclinedQuestion(InvestigationAction.FINISH)


def test_a_declining_decision_carries_no_question() -> None:
    with pytest.raises(ValueError, match="declining decision"):
        InvestigationDecision(
            action=InvestigationAction.NOT_IN_DATA, reasoning="r", question="Count?"
        )


def test_a_declined_result_is_never_complete() -> None:
    with pytest.raises(ValueError, match="declined question requires"):
        InvestigationResult(
            question="q",
            conclusion="c",
            analysis=ANALYSIS,
            declined=DeclinedQuestion(InvestigationAction.NOT_IN_DATA),
        )

    result = InvestigationResult(
        question="q",
        conclusion="c",
        analysis=ANALYSIS,
        status=InvestigationStatus.INCOMPLETE,
        declined=DeclinedQuestion(InvestigationAction.NOT_IN_DATA),
    )
    assert result.declined is not None


@pytest.mark.parametrize("action", ["not_in_data", "needs_definition"])
def test_the_parser_and_both_prompts_know_the_declining_actions(action: str) -> None:
    decision = InvestigationResponseParser().parse(_decision(action, "r"))
    state = InvestigationState(question="How many are large?", analysis=ANALYSIS)
    properties = INVESTIGATION_DECISION_JSON_SCHEMA["properties"]

    assert decision.action is InvestigationAction(action)
    assert isinstance(properties, dict)
    assert action in properties["action"]["enum"]
    assert f"- {action}: stop without a number" in InvestigationPromptBuilder().build(
        state
    )
    assert f"- {action}: stop without a number" in (
        InvestigationCompaction().investigator_prompt(state)
    )


def test_a_refused_second_query_takes_verified_away(tmp_path: Path) -> None:
    written = json.dumps(
        {
            "conclusion": "The total is 245000.",
            "claims": [
                {
                    "operation": "value",
                    "expected": "245000",
                    "left": {"observation_index": 0, "row_index": 0, "column": "total"},
                    "right": None,
                }
            ],
        }
    )
    refusal = f"SELECT 'refused' AS {CROSS_CHECK_REFUSAL_COLUMN}"
    planner = _Script(["SELECT SUM(area) AS total FROM data", refusal])

    def factory(settings: Settings) -> VeriSight:
        return VeriSight(
            settings=settings.model_copy(update={"gemini_cross_check_model": None}),
            planner=GenerativeQueryPlanner(planner),
            investigator=GenerativeInvestigator(
                _Script(
                    [
                        _decision("investigate", "r", "Total area"),
                        _decision("finish", "r"),
                    ]
                )
            ),
            synthesizer=StructuredInvestigationSynthesizer(_Script([written])),
        )

    app = create_app(
        settings=Settings(gemini_api_key=None), web=WebSettings(), factory=factory
    )
    with TestClient(app) as client:
        upload = client.post(
            "/api/datasets", files=[("files", ("data.csv", ROWS.encode("utf-8")))]
        )
        reply = client.post(
            f"/api/datasets/{upload.json()['dataset_id']}/ask",
            json={
                "question": "Adding every row together, what does area come to?",
                "consent": True,
                "api_key": "k",
            },
        ).json()

    assert "INDEPENDENT CROSS-CHECK" in planner.prompts[1]
    assert CROSS_CHECK_REFUSAL_COLUMN in planner.prompts[1]
    assert reply["outcome"] == "unverified"
    assert reply["trust"]["level"] == "needs_review"
    assert reply["cross_check"]["reason"] == "second_query_refused"
    assert reply["cross_check"]["independent_value"] is None
    failed = [c for c in reply["trust"]["checks"] if c["status"] == "failed"]
    assert [c["name"] for c in failed] == ["second_query"]
    assert "a second query was refused" in failed[0]["detail"]
