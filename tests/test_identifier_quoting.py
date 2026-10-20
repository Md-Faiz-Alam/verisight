"""Quoted identifiers survive planning, repair, validation, and SQL execution."""

from pathlib import Path

import pandas as pd
import pytest

from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_repair import GenerativeQueryRepairer
from verisight.execution.service import AnalyticalExecutionService
from verisight.ingestion.models import LoadedDataset, LoadedTable, SourceMetadata


class RecordingClient:
    """Return scripted SQL without claiming to measure model behavior."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


@pytest.mark.parametrize("repair", [False, True], ids=["planning", "repair"])
@pytest.mark.parametrize(
    ("column", "quoted"),
    [
        pytest.param("order total", '"order total"', id="space"),
        pytest.param("select", '"select"', id="keyword"),
        pytest.param('gross"amount', '"gross""amount"', id="embedded-quote"),
        pytest.param("order.total", '"order.total"', id="literal-dot"),
        pytest.param(
            'x"; DROP TABLE orders; --',
            '"x""; DROP TABLE orders; --"',
            id="sql-looking-name",
        ),
    ],
)
def test_quoted_identifiers_execute_through_planning_and_repair(
    column: str, quoted: str, repair: bool
) -> None:
    source = SourceMetadata(
        path=Path("synthetic.csv"),
        file_name="synthetic.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )
    table = LoadedTable(
        name="Sales display name",
        data=pd.DataFrame(
            {
                column: [10, 20, 900],
                "total": [100, 200, 300],
                "customer name": ["O'Brien", "O'Brien", "Other"],
            }
        ),
        source=source,
    )
    table.relation_name = "orders"
    dataset = LoadedDataset(tables=[table])
    sql = (
        f'SELECT SUM("o".{quoted}) AS "metric total" '
        'FROM "orders" AS "o" '
        "WHERE \"o\".\"customer name\" = 'O''Brien'"
    )
    failed_sql = 'SELECT "missing_metric" FROM "orders"'
    planner_client = RecordingClient(failed_sql if repair else sql)
    repair_client = RecordingClient(sql)
    service = AnalyticalExecutionService(
        dataset,
        planner=GenerativeQueryPlanner(planner_client),
        repairer=GenerativeQueryRepairer(repair_client),
    )

    execution = service.run("Sum the selected measure for customer O'Brien.")

    assert execution.plan.sql == sql
    assert execution.result.columns == ("metric total",)
    assert execution.result.rows == ((30,),)
    assert len(planner_client.prompts) == 1
    assert len(repair_client.prompts) == int(repair)
    prompts = planner_client.prompts + repair_client.prompts
    for prompt in prompts:
        assert "Identifier quoting:" in prompt
        assert (
            "Use double quotes for relation names, column names, and aliases" in prompt
        )
        assert (
            "Use the RELATION identifier from AVAILABLE DATA, not DISPLAY NAME"
            in prompt
        )
        assert "Preserve each supplied identifier exactly" in prompt
        assert 'gross"amount becomes "gross""amount"' in prompt
        assert '"o"."order total"' in prompt
        assert '"order.total", not "order"."total"' in prompt
        assert "Single quotes delimit string values, not identifiers" in prompt
        assert "Quoting a name does not authorize an unavailable relation" in prompt
        assert "RELATION orders\nDISPLAY NAME: Sales display name" in prompt
        assert f"- {column} |" in prompt
        assert prompt.index("Identifier quoting:") < prompt.index("AVAILABLE DATA:\n")
    if repair:
        assert f"FAILED SQL:\n{failed_sql}" in repair_client.prompts[0]
        assert "RUNTIME ERROR:\nSQL execution failed.\n" in repair_client.prompts[0]
    # A SQL-looking column name remains data; the relation is still queryable.
    assert service.execute('SELECT COUNT(*) AS "n" FROM "orders"').rows == ((3,),)
