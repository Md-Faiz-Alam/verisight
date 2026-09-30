"""Unified deterministic analysis results for VeriSight."""

from dataclasses import dataclass

from verisight.analysis.insights import AnalysisInsight, InsightGenerator
from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.summary import AnalysisSummarizer, AnalysisSummary


@dataclass(frozen=True, slots=True)
class DatasetAnalysisResult:
    """Complete deterministic result produced from a dataset analysis."""

    analysis: DatasetAnalysis
    summary: AnalysisSummary
    insights: tuple[AnalysisInsight, ...]

    @property
    def issue_count(self) -> int:
        """Return the total number of quality issues."""

        return self.analysis.issue_count

    @property
    def insight_count(self) -> int:
        """Return the total number of generated insights."""

        return len(self.insights)


class AnalysisResultBuilder:
    """Build unified deterministic results from dataset analyses."""

    def __init__(self) -> None:
        self._summarizer = AnalysisSummarizer()
        self._insight_generator = InsightGenerator()

    def build(self, analysis: DatasetAnalysis) -> DatasetAnalysisResult:
        """Build a unified result from an existing dataset analysis."""

        return DatasetAnalysisResult(
            analysis=analysis,
            summary=self._summarizer.summarize(analysis),
            insights=self._insight_generator.generate(analysis),
        )
