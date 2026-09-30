from verisight.analysis.models import DatasetAnalysis
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.quality.models import (
    QualityIssue,
    QualityIssueType,
    QualityScope,
    QualitySeverity,
)


def test_dataset_analysis_stores_analysis_components() -> None:
    schema = DatasetSchema(tables=())
    profile = DatasetProfile(tables=())

    issue = QualityIssue(
        issue_type=QualityIssueType.DUPLICATE_ROWS,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.TABLE,
        table_name="orders",
        relation_name="orders",
        message="Table contains duplicate rows.",
    )

    analysis = DatasetAnalysis(
        schema=schema,
        profile=profile,
        issues=(issue,),
    )

    assert analysis.schema is schema
    assert analysis.profile is profile
    assert analysis.issues == (issue,)
    assert analysis.issue_count == 1


def test_dataset_analysis_supports_no_quality_issues() -> None:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    assert analysis.issues == ()
    assert analysis.issue_count == 0
