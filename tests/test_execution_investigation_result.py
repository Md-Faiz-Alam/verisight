import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import (
    AnalysisResultBuilder,
    DatasetAnalysisResult,
)
from verisight.execution.investigation_result import InvestigationResult
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile


def _build_analysis_result() -> DatasetAnalysisResult:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    return AnalysisResultBuilder().build(analysis)


def test_investigation_result_preserves_completed_investigation() -> None:
    observation = QueryObservation(
        question="What is revenue by month?",
        sql="SELECT month, SUM(revenue) FROM sales GROUP BY month",
        result=QueryResult(
            columns=("month", "revenue"),
            rows=(
                ("January", 1000),
                ("February", 800),
            ),
        ),
    )

    analysis = _build_analysis_result()

    result = InvestigationResult(
        question="Why did revenue decline?",
        conclusion="Revenue declined from January to February.",
        analysis=analysis,
        observations=(observation,),
    )

    assert result.question == "Why did revenue decline?"
    assert result.conclusion == ("Revenue declined from January to February.")
    assert result.analysis is analysis
    assert result.observations == (observation,)
    assert result.observation_count == 1


def test_investigation_result_can_have_no_observations() -> None:
    result = InvestigationResult(
        question="Are there data-quality concerns?",
        conclusion="The deterministic analysis is sufficient.",
        analysis=_build_analysis_result(),
    )

    assert result.observations == ()
    assert result.observation_count == 0


@pytest.mark.parametrize(
    "question",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_investigation_result_rejects_empty_question(
    question: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="Investigation question must not be empty.",
    ):
        InvestigationResult(
            question=question,
            conclusion="The investigation is complete.",
            analysis=_build_analysis_result(),
        )


@pytest.mark.parametrize(
    "conclusion",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_investigation_result_rejects_empty_conclusion(
    conclusion: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="Investigation conclusion must not be empty.",
    ):
        InvestigationResult(
            question="Why did revenue decline?",
            conclusion=conclusion,
            analysis=_build_analysis_result(),
        )
