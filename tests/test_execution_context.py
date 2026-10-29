import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from verisight.execution.context import (
    PopulationFilter,
    QueryContext,
    QueryContextBuilder,
    _complete_string_values,
    validate_population,
)
from verisight.execution.exceptions import QueryValidationError
from verisight.ingestion.models import LoadedDataset, LoadedTable, SourceMetadata
from verisight.ingestion.schema import (
    ColumnSchema,
    DatasetSchema,
    LogicalType,
    TableSchema,
)


def test_builds_query_context_from_dataset_schema() -> None:
    schema = DatasetSchema(
        tables=(
            TableSchema(
                name="Orders",
                relation_name="orders",
                row_count=3,
                column_count=2,
                columns=(
                    ColumnSchema(
                        name="order_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                        missing_count=0,
                    ),
                    ColumnSchema(
                        name="amount",
                        physical_dtype="float64",
                        logical_type=LogicalType.FLOAT,
                        nullable=True,
                        missing_count=1,
                    ),
                ),
            ),
        )
    )

    context = QueryContextBuilder().build(schema)

    assert context.relation_count == 1

    relation = context.relations[0]

    assert relation.name == "Orders"
    assert relation.relation_name == "orders"
    assert relation.row_count == 3

    assert relation.columns[0].name == "order_id"
    assert relation.columns[0].physical_dtype == "int64"
    assert relation.columns[0].logical_type is LogicalType.INTEGER
    assert relation.columns[0].nullable is False

    assert relation.columns[1].name == "amount"
    assert relation.columns[1].logical_type is LogicalType.FLOAT
    assert relation.columns[1].nullable is True


def test_builds_context_for_multiple_relations() -> None:
    schema = DatasetSchema(
        tables=(
            TableSchema(
                name="Customers",
                relation_name="customers",
                row_count=2,
                column_count=1,
                columns=(
                    ColumnSchema(
                        name="customer_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                        missing_count=0,
                    ),
                ),
            ),
            TableSchema(
                name="Orders",
                relation_name="orders",
                row_count=3,
                column_count=1,
                columns=(
                    ColumnSchema(
                        name="order_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                        missing_count=0,
                    ),
                ),
            ),
        )
    )

    context = QueryContextBuilder().build(schema)

    assert context.relation_count == 2
    assert tuple(relation.relation_name for relation in context.relations) == (
        "customers",
        "orders",
    )


def test_builds_empty_query_context() -> None:
    context = QueryContextBuilder().build(DatasetSchema(tables=()))

    assert context.relations == ()
    assert context.relation_count == 0


@pytest.mark.parametrize(
    "relation,column,values",
    [
        ("", "state", ("active",)),
        (None, "state", ("active",)),
        ("data", " ", ("active",)),
        ("data", None, ("active",)),
        ("data", "state", ()),
        ("data", "state", ["active"]),
        ("data", "state", (None,)),
        ("data", "state", ("active", 1)),
        ("data", "state", (True, 1)),
        ("data", "state", (1.0,)),
        ("data", "state", (2**63,)),
        ("data", "state", (-(2**63) - 1,)),
    ],
)
def test_rejects_invalid_population_contracts(
    relation: Any, column: Any, values: Any
) -> None:
    with pytest.raises(QueryValidationError):
        PopulationFilter(relation, column, values)


@pytest.mark.parametrize("population", [[], ("filter",)])
def test_population_collection_must_be_immutable_and_typed(population: Any) -> None:
    with pytest.raises(QueryValidationError):
        validate_population(population, QueryContext(relations=()))


@pytest.fixture
def categorical_dataset() -> LoadedDataset:
    source = SourceMetadata(Path("data.csv"), "data.csv", ".csv", 1)
    table = LoadedTable(
        "data",
        pd.DataFrame(
            {
                "state": ["waitlisted", "active", None, "cancelled", "active"],
                "amount": [1, 2, 3, 4, 5],
            }
        ),
        source,
    )
    return LoadedDataset([table])


def test_categories_are_complete_original_values_without_source_mutation(
    categorical_dataset: LoadedDataset,
) -> None:
    original = categorical_dataset.tables[0].data.copy(deep=True)
    population = (PopulationFilter("data", "state", ("active",)),)
    context = QueryContextBuilder().build_from_dataset(
        categorical_dataset, population=population
    )
    assert context.population == population
    assert len(context.observed_categories) == 1
    category = context.observed_categories[0]
    assert (category.relation, category.column) == ("data", "state")
    assert category.observed_nonmissing_values == ("active", "cancelled", "waitlisted")
    pd.testing.assert_frame_equal(categorical_dataset.tables[0].data, original)


@pytest.mark.parametrize(
    "values,expected",
    [
        (["b", "a", "b", None], ("a", "b")),
        ([""], ("",)),
        ([str(i) for i in range(8)], tuple(str(i) for i in range(8))),
        ([str(i) for i in range(9)], None),
        (["x" * 128], ("x" * 128,)),
        (["x" * 129], None),
        ([None, pd.NA], None),
        (["a", 1], None),
    ],
)
def test_complete_category_limits_never_return_a_sample(
    values: list[Any], expected: tuple[str, ...] | None
) -> None:
    assert _complete_string_values(pd.Series(values, dtype=object)) == expected


def test_category_array_budget_counts_escaped_values_and_keeps_later_small_columns(
    categorical_dataset: LoadedDataset,
) -> None:
    table = categorical_dataset.tables[0]
    table.data = pd.DataFrame(
        {
            **{f"large_{i}": ["\n" * 128 + str(j) for j in range(8)] for i in range(3)},
            "small": ["ok"] * 8,
        }
    )
    # Each value below is 128 characters but requires much more JSON space.
    for column in ("large_0", "large_1", "large_2"):
        table.data[column] = ["\x01" * 127 + str(j) for j in range(8)]
    context = QueryContextBuilder().build_from_dataset(categorical_dataset)
    encoded = json.dumps(
        [asdict(c) for c in context.observed_categories], ensure_ascii=False
    )
    assert len(encoded) <= 8_192
    assert [c.column for c in context.observed_categories] == ["large_0", "small"]
    assert len(context.observed_categories[0].observed_nonmissing_values) == 8


def test_dataset_builder_omits_high_cardinality_and_all_missing_columns(
    categorical_dataset: LoadedDataset,
) -> None:
    categorical_dataset.tables[0].data = pd.DataFrame(
        {
            "id": [str(i) for i in range(9)],
            "long": ["x" * 129] * 9,
            "missing": pd.Series([pd.NA] * 9, dtype="string"),
        }
    )
    assert (
        QueryContextBuilder()
        .build_from_dataset(categorical_dataset)
        .observed_categories
        == ()
    )


def test_planning_and_repair_share_original_categories(
    categorical_dataset: LoadedDataset,
) -> None:
    from verisight.execution.generative import GenerativeQueryPlanner
    from verisight.execution.generative_repair import GenerativeQueryRepairer
    from verisight.execution.service import AnalyticalExecutionService

    class Client:
        def __init__(self, response: str) -> None:
            self.response = response
            self.prompts: list[str] = []

        def generate(self, prompt: str) -> str:
            self.prompts.append(prompt)
            return self.response

    planning = Client("SELECT missing FROM data")
    repair = Client("SELECT SUM(amount) FROM data")
    service = AnalyticalExecutionService(
        categorical_dataset,
        planner=GenerativeQueryPlanner(planning),
        repairer=GenerativeQueryRepairer(repair),
        population=(PopulationFilter("data", "state", ("active",)),),
    )
    assert service.run("Total amount?").result.rows == ((7,),)
    assert len(planning.prompts) == len(repair.prompts) == 1
    for prompt in planning.prompts + repair.prompts:
        assert (
            '"observed_nonmissing_values": ["active", "cancelled", "waitlisted"]'
            in prompt
        )
        assert "before caller-selected population filters" in prompt


def test_category_budget_is_shared_across_relations(
    categorical_dataset: LoadedDataset,
) -> None:
    table = categorical_dataset.tables[0]
    table.data = pd.DataFrame({"state": ["\x01" * 127 + str(i) for i in range(8)]})
    categorical_dataset.tables.append(
        LoadedTable("other", table.data.copy(), table.source)
    )
    context = QueryContextBuilder().build_from_dataset(categorical_dataset)
    assert len(context.observed_categories) == 1
    assert context.observed_categories[0].relation == "data"
    assert (
        len(
            json.dumps(
                [asdict(c) for c in context.observed_categories], ensure_ascii=False
            )
        )
        <= 8_192
    )
