"""Automatic dashboards: domain recognition, column roles and exact figures."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from verisight import VeriSight
from verisight.analytics.dashboard import (
    Dashboard,
    DashboardBuilder,
    DashboardFilter,
    DashboardRequestError,
)
from verisight.analytics.domains import detect_domain, name_tokens
from verisight.config import Settings
from verisight.execution.engine import DuckDBExecutor
from verisight.execution.exceptions import QueryRuntimeError
from verisight.execution.models import QueryResult
from verisight.ingestion.models import LoadedDataset

SETTINGS = Settings(
    _env_file=None,  # type: ignore[call-arg]
    gemini_api_key=None,
    allow_llm_data_disclosure=False,
)
ORDERS = (
    "order_id,customer_id,region,status,amount,unit_price,order_date\n"
    "1,c1,East,Shipped,100,10,2024-01-05\n"
    "2,c1,East,shipped ,50,5,2024-01-20\n"
    "3,c2,West,SHIPPED,25,5,2024-02-03\n"
    "4,c3,West,Pending,25,25,2024-03-09\n"
)


def _builder(tmp_path: Path, name: str, text: str) -> DashboardBuilder:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return VeriSight(settings=SETTINGS).dashboard_builder(path)


def _dashboard(tmp_path: Path, text: str, name: str = "data.csv") -> Dashboard:
    return _builder(tmp_path, name, text).build()


def _kpis(dashboard: Dashboard) -> dict[str, object]:
    return {tile.label: tile.value for tile in dashboard.kpis}


class _Failing(DuckDBExecutor):
    """Fail the queries chosen by a test and run the rest."""

    def __init__(self, fails: Callable[[str], bool]) -> None:
        super().__init__()
        self._fails = fails

    def execute(self, dataset: LoadedDataset, query: str) -> QueryResult:
        if self._fails(query):
            raise QueryRuntimeError("no")
        return super().execute(dataset, query)


def _failing(
    tmp_path: Path, text: str, fails: Callable[[str], bool]
) -> DashboardBuilder:
    path = tmp_path / "data.csv"
    path.write_text(text, encoding="utf-8")
    dataset = VeriSight(settings=SETTINGS)._load_dataset(path)
    return DashboardBuilder(dataset, _Failing(fails))


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("customerName", ["customer", "name"]),
        ("order_totals", ["order", "total"]),
        ("CO2 level", ["co2", "level"]),
        ("gross", ["gross"]),
        ("diagnosis status", ["diagnosis", "status"]),
        ("HTTPCode", ["http", "code"]),
    ],
)
def test_names_split_into_singular_words(name: str, tokens: list[str]) -> None:
    assert name_tokens(name) == tokens


@pytest.mark.parametrize(
    ("names", "key", "confidence"),
    [
        (["patient_id", "diagnosis", "hospital"], "healthcare", "strong"),
        (["order_id", "customer"], "retail", "likely"),
        (["species", "island"], "general", "general"),
        (["order_id"], "general", "general"),
        (["student", "exam", "salary", "manager"], "general", "general"),
        (
            ["order", "customer", "product", "payment", "invoice"],
            "retail",
            "likely",
        ),
    ],
)
def test_domain_needs_clear_evidence(
    names: list[str], key: str, confidence: str
) -> None:
    domain, match = detect_domain(names)

    assert domain.key == key
    assert (match.key, match.confidence) == (key, confidence)
    assert bool(match.matched) is (key != "general")


def test_retail_dashboard_figures_are_exact(tmp_path: Path) -> None:
    dashboard = _dashboard(tmp_path, ORDERS, "orders.csv")

    assert dashboard.relation == "orders"
    assert dashboard.domain.key == "retail"
    assert dashboard.computed_by == "sql_without_model"
    assert _kpis(dashboard) == {
        "Rows": 4,
        "Distinct customer id": 3,
        "Total amount": 200,
        "Average unit price": 11.25,
    }
    assert dashboard.trend is not None
    assert dashboard.trend.title == "Total amount by month"
    assert [(p.period, p.value, p.rows) for p in dashboard.trend.points] == [
        ("2024-01", 150, 2),
        ("2024-02", 25, 1),
        ("2024-03", 25, 1),
    ]
    status = next(b for b in dashboard.breakdowns if b.column == "status")
    assert status.categories == 2
    assert [(b.key, b.value, b.rows) for b in status.bars] == [
        ("shipped", 175, 3),
        ("pending", 25, 1),
    ]
    assert status.bars[0].label.casefold() == "shipped"
    assert "SELECT" in dashboard.kpis[0].sql
    assert all(tile.sql for tile in dashboard.kpis)
    assert dashboard.suggestions[1] == "What is the total amount?"
    assert any("makes up" in insight.text for insight in dashboard.insights)


def test_filter_narrows_figures_but_keeps_its_own_categories(tmp_path: Path) -> None:
    builder = _builder(tmp_path, "orders.csv", ORDERS)

    filtered = builder.build(filters=[DashboardFilter("status", "shipped")])

    assert _kpis(filtered)["Total amount"] == 175
    assert filtered.filters == (DashboardFilter("status", "shipped"),)
    status = next(b for b in filtered.breakdowns if b.column == "status")
    assert len(status.bars) == 2
    region = next(b for b in filtered.breakdowns if b.column == "region")
    assert [(b.label, b.value) for b in region.bars] == [("East", 150), ("West", 25)]


def test_share_compares_a_category_with_its_own_rows(tmp_path: Path) -> None:
    builder = _builder(tmp_path, "orders.csv", ORDERS)

    one = builder.build(filters=[DashboardFilter("status", "pending")])
    both = builder.build(
        filters=[
            DashboardFilter("status", "shipped"),
            DashboardFilter("region", "east"),
        ]
    )

    # Status keeps all its categories when filtered, so it cannot be divided
    # by a filtered total. Region can, and shows West as all of Pending.
    shares = [i.text for i in one.insights if "makes up" in i.text]
    assert shares == ["West makes up 100% of total amount, the largest region."]
    assert not any("makes up" in i.text for i in both.insights)


def test_filter_value_is_escaped_as_text(tmp_path: Path) -> None:
    builder = _builder(tmp_path, "orders.csv", ORDERS)

    filtered = builder.build(filters=[DashboardFilter("status", "x' OR '1'='1")])

    assert _kpis(filtered)["Rows"] == 0
    assert filtered.histograms == ()


@pytest.mark.parametrize(
    ("relation", "filters", "message"),
    [
        ("missing", [], "not in this dataset"),
        (None, [DashboardFilter("amount", "1")], "cannot be filtered"),
    ],
)
def test_unknown_requests_are_refused(
    tmp_path: Path,
    relation: str | None,
    filters: list[DashboardFilter],
    message: str,
) -> None:
    with pytest.raises(DashboardRequestError, match=message):
        _builder(tmp_path, "orders.csv", ORDERS).build(relation, filters)


def test_empty_dataset_is_refused() -> None:
    builder = DashboardBuilder(LoadedDataset(tables=[]), DuckDBExecutor())

    with pytest.raises(DashboardRequestError, match="no rows"):
        builder.build()


def test_largest_table_leads_and_others_can_be_chosen(tmp_path: Path) -> None:
    small = tmp_path / "small.csv"
    small.write_text("kind,cost\na,1\nb,2\n", encoding="utf-8")
    large = tmp_path / "large.csv"
    large.write_text("kind,cost\na,1\nb,2\na,3\n", encoding="utf-8")
    builder = VeriSight(settings=SETTINGS).dashboard_builder([small, large])

    assert builder.build().relation == "large"
    chosen = builder.build("small")
    assert chosen.relation == "small"
    assert [item.name for item in chosen.relations] == ["large", "small"]
    assert builder.build("small").relation == "small"


def test_total_rows_are_left_out_of_every_figure(tmp_path: Path) -> None:
    lines = ["region,month,amount"]
    for month in ("Jan", "Feb", "Mar"):
        lines += [
            f"East,{month},10",
            f"West,{month},20",
            f"North,{month},30",
            f"Total,{month},60",
        ]
    dashboard = _dashboard(tmp_path, "\n".join(lines) + "\n")

    assert dashboard.excluded_totals == ("region = Total",)
    assert _kpis(dashboard) == {"Rows": 9, "Total amount": 180}
    region = next(b for b in dashboard.breakdowns if b.column == "region")
    assert [bar.label for bar in region.bars] == ["North", "West", "East"]


def test_only_named_quantities_are_added_up(tmp_path: Path) -> None:
    dashboard = _dashboard(
        tmp_path,
        "total_cost,unit_price,widget,tax_rate\n10,1,3,5\n20,3,5,7\n30,5,7,9\n",
    )

    assert _kpis(dashboard) == {
        "Rows": 3,
        "Total total cost": 60,
        "Average unit price": 3.0,
        "Average widget": 5.0,
    }


def test_percent_sign_columns_are_averaged(tmp_path: Path) -> None:
    dashboard = _dashboard(tmp_path, "total\n10%\n20%\n")

    assert _kpis(dashboard) == {"Rows": 2, "Average total": 15.0}


@pytest.mark.parametrize(
    ("dates", "grain", "periods"),
    [
        (("2024-01-01", "2024-01-03"), "day", ["2024-01-01", "2024-01-03"]),
        (("2024-01-01", "2025-03-03"), "month", ["2024-01", "2025-03"]),
        (("2010-01-01", "2024-03-03"), "year", ["2010", "2024"]),
    ],
)
def test_trend_grain_follows_the_date_span(
    tmp_path: Path, dates: tuple[str, str], grain: str, periods: list[str]
) -> None:
    dashboard = _dashboard(tmp_path, f"day,cost\n{dates[0]},1\n{dates[1]},2\n")

    assert dashboard.trend is not None
    assert dashboard.trend.grain == grain
    assert [point.period for point in dashboard.trend.points] == periods


def test_year_column_is_time_not_a_measure(tmp_path: Path) -> None:
    dashboard = _dashboard(tmp_path, "year,deaths\n2001,5\n2001,6\n2002,7\n2003,1\n")

    assert _kpis(dashboard) == {"Rows": 4, "Total deaths": 19}
    assert dashboard.trend is not None
    assert [(p.period, p.value) for p in dashboard.trend.points] == [
        ("2001", 11),
        ("2002", 7),
        ("2003", 1),
    ]
    assert any("peaked in 2001 at 11" in insight.text for insight in dashboard.insights)
    assert dashboard.suggestions[-1] == "What is the total deaths in 2003?"


def test_year_like_name_outside_a_calendar_is_a_measure(tmp_path: Path) -> None:
    dashboard = _dashboard(tmp_path, "year,cost\n1,5\n2,6\n")

    assert dashboard.trend is None
    assert "Average year" in _kpis(dashboard)


def test_single_date_has_no_trend(tmp_path: Path) -> None:
    dashboard = _dashboard(tmp_path, "day,cost\n2024-01-01,1\n2024-01-01,2\n")

    assert dashboard.trend is None


def test_trend_without_rows_is_omitted(tmp_path: Path) -> None:
    builder = _builder(
        tmp_path,
        "data.csv",
        "day,kind,cost\n2024-01-01,a,1\n2024-01-02,b,2\n",
    )

    assert builder.build(filters=[DashboardFilter("kind", "a")]).trend is None


def test_identifiers_are_counted_not_summed(tmp_path: Path) -> None:
    rows = "\n".join(f"{i},{i % 3},{i % 2},{i * 2}" for i in range(1, 26))
    dashboard = _dashboard(tmp_path, f"seq,group_id,branch_code,cost\n{rows}\n")

    assert _kpis(dashboard) == {
        "Rows": 25,
        "Distinct group id": 3,
        "Total cost": 650,
    }


def test_unique_identifier_is_not_a_kpi(tmp_path: Path) -> None:
    dashboard = _dashboard(tmp_path, "id,cost\na,1\nb,2\nc,3\n")

    assert _kpis(dashboard) == {"Rows": 3, "Total cost": 6}


def test_columns_that_cannot_be_charted_are_skipped(tmp_path: Path) -> None:
    labels = "\n".join(f"name{i},same,5" for i in range(60))
    dashboard = _dashboard(tmp_path, f"name,flag,constant\n{labels}\n")

    assert dashboard.breakdowns == ()
    assert _kpis(dashboard) == {"Rows": 60}
    assert dashboard.histograms == ()
    assert dashboard.suggestions == ("How many rows does data have?",)


def test_nested_json_columns_are_ignored(tmp_path: Path) -> None:
    data = [{"kind": "a", "extra": {"x": 1}}, {"kind": "b", "extra": {"x": 2}}]
    dashboard = _dashboard(tmp_path, json.dumps(data), "data.json")

    assert [b.column for b in dashboard.breakdowns] == ["kind"]
    bar = dashboard.breakdowns[0].bars[0]
    assert bar.value == 1
    assert dashboard.suggestions == (
        "How many rows does data have?",
        "How many rows have kind equal to a?",
    )


def test_boolean_columns_become_categories(tmp_path: Path) -> None:
    data = [{"paid": True, "fee": 1}, {"paid": False, "fee": 2}]
    dashboard = _dashboard(tmp_path, json.dumps(data), "data.json")

    assert [bar.key for bar in dashboard.breakdowns[0].bars] == ["false", "true"]


def test_small_category_columns_come_first(tmp_path: Path) -> None:
    rows = "\n".join(f"v{i},k{i % 2},{i}" for i in range(20))
    dashboard = _dashboard(tmp_path, f"wide,small,cost\n{rows}\n")

    assert [b.column for b in dashboard.breakdowns] == ["small", "wide"]
    wide = dashboard.breakdowns[1]
    assert (len(wide.bars), wide.categories) == (8, 20)


def test_histogram_fills_empty_ranges_and_includes_the_maximum(tmp_path: Path) -> None:
    dashboard = _dashboard(tmp_path, "cost\n0\n0\n12\n")

    bins = dashboard.histograms[0].bins
    assert len(bins) == 12
    assert (bins[0].low, bins[0].high, bins[0].rows) == (0.0, 1.0, 2)
    assert bins[5].rows == 0
    assert (bins[-1].high, bins[-1].rows) == (12.0, 1)


def test_constant_values_under_a_filter_have_no_histogram(tmp_path: Path) -> None:
    builder = _builder(tmp_path, "data.csv", "kind,cost\na,1\na,1\nb,3\n")

    assert builder.build().histograms != ()
    assert builder.build(filters=[DashboardFilter("kind", "a")]).histograms == ()


def _correlated(sign: int, rows: int = 40) -> str:
    return "cost,fee\n" + "\n".join(
        f"{i * 3},{sign * i * 2 + (i % 3)}" for i in range(1, rows + 1)
    )


@pytest.mark.parametrize(("sign", "word"), [(1, "rises"), (-1, "falls")])
def test_strong_relationship_is_reported_without_claiming_cause(
    tmp_path: Path, sign: int, word: str
) -> None:
    dashboard = _dashboard(tmp_path, _correlated(sign) + "\n")

    text = next(i.text for i in dashboard.insights if "correlation" in i.text)
    assert f"{word} as" in text
    assert "does not show" in text


@pytest.mark.parametrize(
    "text",
    [
        # Too few rows to mean anything.
        _correlated(1, rows=5) + "\n",
        # Unrelated columns.
        "cost,fee\n" + "\n".join(f"{i * 3},{(i * 7) % 2}" for i in range(40)) + "\n",
    ],
)
def test_weak_or_thin_relationships_are_not_reported(tmp_path: Path, text: str) -> None:
    dashboard = _dashboard(tmp_path, text)

    assert not any("correlation" in i.text for i in dashboard.insights)


def test_undefined_correlation_is_not_reported(tmp_path: Path) -> None:
    rows = "\n".join(f"a,{i},{5}" for i in range(40)) + "\nb,1,2\n"
    builder = _builder(tmp_path, "data.csv", f"kind,cost,fee\n{rows}")

    filtered = builder.build(filters=[DashboardFilter("kind", "a")])

    assert not any("correlation" in i.text for i in filtered.insights)


def test_negative_totals_have_no_share_insight(tmp_path: Path) -> None:
    dashboard = _dashboard(tmp_path, "kind,amount\na,-5\nb,-1\na,2\n")

    assert not any("makes up" in i.text for i in dashboard.insights)


def test_measure_without_values_has_no_peak(tmp_path: Path) -> None:
    days = ["2024-01-01,a,", "2024-01-02,a,", "2024-01-03,a,"]
    days += ["2024-01-04,b,5", "2024-01-05,b,7"]
    rows = "\n".join(["day,kind,cost", *days]) + "\n"
    builder = _builder(tmp_path, "data.csv", rows)
    builder.build()

    filtered = builder.build(filters=[DashboardFilter("kind", "a")])

    assert filtered.trend is not None
    assert not any("peaked" in i.text for i in filtered.insights)


def test_failed_figures_do_not_cost_the_page(tmp_path: Path) -> None:
    dashboard = _failing(tmp_path, _correlated(1), lambda _: True).build()

    assert dashboard.kpis == ()
    assert dashboard.breakdowns == ()
    assert dashboard.histograms == ()
    assert dashboard.insights == ()


def test_each_figure_can_fail_alone(tmp_path: Path) -> None:
    text = (
        "day,kind,cost,fee\n"
        + "\n".join(
            f"2024-01-{i:02d},k{i % 2},{i * 3},{i * 2 + 1}" for i in range(1, 32)
        )
        + "\n"
    )

    no_total = _failing(
        tmp_path, text, lambda sql: sql.startswith('SELECT SUM("cost") AS value')
    ).build()
    assert not any("makes up" in i.text for i in no_total.insights)
    assert no_total.breakdowns != ()

    no_trend = _failing(tmp_path, text, lambda sql: "AS period" in sql).build()
    assert no_trend.trend is None

    no_correlation = _failing(tmp_path, text, lambda sql: "CORR(" in sql).build()
    assert not any("correlation" in i.text for i in no_correlation.insights)
    assert no_correlation.kpis != ()
