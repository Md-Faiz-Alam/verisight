from datetime import datetime

import pandas as pd

from verisight.ingestion.dtypes import infer_types


def test_text_stays_in_object_columns_and_numbers_are_inferred() -> None:
    data = pd.DataFrame(
        {
            "name": pd.Series(["Alice", None], dtype=object),
            "count": pd.Series([1, 2], dtype=object),
        }
    )

    typed = infer_types(data)

    assert typed["name"].dtype == object
    assert typed["name"].tolist() == ["Alice", None]
    assert str(typed["count"].dtype) == "int64"


def test_dates_are_kept_in_nanoseconds() -> None:
    data = pd.DataFrame(
        {"day": pd.Series([datetime(2026, 1, 1), datetime(2200, 1, 1)], dtype=object)}
    )

    typed = infer_types(data)

    assert str(typed["day"].dtype) == "datetime64[ns]"
    assert typed["day"].tolist() == [pd.Timestamp(2026, 1, 1), pd.Timestamp(2200, 1, 1)]


def test_dates_outside_the_nanosecond_range_stay_as_objects() -> None:
    values = [datetime(1, 1, 1), datetime(2026, 1, 1)]
    data = pd.DataFrame({"day": pd.Series(values, dtype=object)})

    typed = infer_types(data)

    assert typed["day"].dtype == object
    assert typed["day"].tolist() == values
