"""Conservative ISO 8601 date detection for text-based file formats."""

import re
from typing import Any

import pandas as pd

# Calendar dates, optionally with a time of day. Offsets, week dates, ordinal
# dates and regional formats such as 03/04/2026 are deliberately excluded.
_ISO_DATETIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,9})?)?)?"
)


def parse_iso_datetimes(values: pd.Series) -> pd.Series | None:
    """Return a datetime column only when every present value is an ISO date.

    Every non-missing value must be a string in ``YYYY-MM-DD`` form, optionally
    followed by ``T`` or a space and ``HH:MM``, ``HH:MM:SS`` or fractional
    seconds. Each must also be a real calendar date inside pandas' timestamp
    range. Otherwise the column is returned unchanged as ``None``, so a single
    ambiguous or invalid value keeps the whole column as text. Missing values
    stay missing. No time zone is attached or inferred.
    """
    present = values.dropna()
    if present.empty or not all(type(value) is str for value in present):
        return None
    if not all(_ISO_DATETIME.fullmatch(value) for value in present):
        return None
    try:
        parsed: Any = pd.to_datetime(values, format="ISO8601", errors="raise")
    except (ValueError, OverflowError):
        return None
    return pd.Series(parsed, index=values.index, name=values.name)
