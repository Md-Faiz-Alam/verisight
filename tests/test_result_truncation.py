"""A result longer than the row limit is cut and marked, only when asked."""

from pathlib import Path

import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.exceptions import QueryResultLimitError
from verisight.execution.investigation_formatting import InvestigationStateFormatter
from verisight.execution.models import QueryResult

QUERY = "SELECT n FROM numbers ORDER BY n"


def _app(*, truncate: bool) -> VeriSight:
    return VeriSight(
        settings=Settings(
            _env_file=None,  # type: ignore[call-arg]
            allow_llm_data_disclosure=False,
            max_query_result_rows=2,
            truncate_query_results=truncate,
        )
    )


def _numbers(tmp_path: Path) -> Path:
    path = tmp_path / "numbers.csv"
    path.write_text("n\n3\n1\n2\n", encoding="utf-8")
    return path


def test_a_long_result_keeps_its_first_rows_when_truncation_is_on(
    tmp_path: Path,
) -> None:
    result = _app(truncate=True).execute([_numbers(tmp_path)], QUERY)

    assert result.rows == ((1,), (2,))
    assert result.truncated is True


def test_a_result_within_the_limit_is_not_marked(tmp_path: Path) -> None:
    result = _app(truncate=True).execute(
        [_numbers(tmp_path)], "SELECT COUNT(*) AS n FROM numbers"
    )

    assert result.rows == ((3,),)
    assert result.truncated is False


def test_a_long_result_is_still_refused_by_default(tmp_path: Path) -> None:
    with pytest.raises(QueryResultLimitError):
        _app(truncate=False).execute([_numbers(tmp_path)], QUERY)


@pytest.mark.parametrize("truncated", [False, True])
def test_the_investigator_is_told_when_rows_are_missing(truncated: bool) -> None:
    text = InvestigationStateFormatter()._format_result(
        QueryResult(("n",), ((1,), (2,)), truncated=truncated)
    )

    assert ("Result truncated" in text) is truncated
