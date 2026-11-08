"""Date detection for text-based file formats.

A column becomes dates only when every present value fits one reading. A date
that could be day-first or month-first is never guessed.
"""

import re
from typing import Any

import pandas as pd

_ISO_BODY = (
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,9})?)?)?"
)
# Calendar dates, optionally with a time of day. Week and ordinal dates are
# deliberately excluded.
_ISO_DATETIME = re.compile(_ISO_BODY)
_ISO_WITH_ZONE = re.compile(_ISO_BODY + r"(?:Z|[+-][0-9]{2}:?[0-9]{2})")
_NUMERIC_DATE = re.compile(
    r"([0-9]{1,2})([/.-])([0-9]{1,2})\2([0-9]{4}|[0-9]{2})"
    r"( [0-9]{2}:[0-9]{2}(:[0-9]{2})?)?"
)
_NAMED_MONTH_FORMATS = (
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
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


def _numeric_matches(present: pd.Series) -> list[re.Match[str]] | None:
    matches = [_NUMERIC_DATE.fullmatch(value) for value in present]
    if not all(matches):
        return None
    return [match for match in matches if match is not None]


def _is_day_first(matches: list[re.Match[str]]) -> bool | None:
    """True or False when some value proves the order; None when none does."""
    first_is_day = any(int(match[1]) > 12 for match in matches)
    second_is_day = any(int(match[3]) > 12 for match in matches)
    if first_is_day == second_is_day:
        return None
    return first_is_day


def has_ambiguous_dates(values: pd.Series) -> bool:
    """Whether every value is a numeric date whose day and month cannot be told."""
    present = values.dropna().str.strip()
    matches = _numeric_matches(present)
    return matches is not None and _is_day_first(matches) is None


def _parse(values: pd.Series, date_format: str) -> pd.Series | None:
    try:
        parsed: Any = pd.to_datetime(values, format=date_format, errors="raise")
    except (ValueError, OverflowError):
        return None
    return pd.Series(parsed, index=values.index, name=values.name)


def _numeric_format(match: re.Match[str], day_first: bool) -> str:
    separator = match[2]
    year = "%Y" if len(match[4]) == 4 else "%y"
    parts = ("%d", "%m") if day_first else ("%m", "%d")
    time = ""
    if match[5]:
        time = " %H:%M:%S" if match[6] else " %H:%M"
    return f"{parts[0]}{separator}{parts[1]}{separator}{year}{time}"


def parse_flexible_dates(values: pd.Series) -> tuple[pd.Series, str] | None:
    """Read one unambiguous non-ISO format, returning the column and a description.

    Understands ISO dates with a time zone, which are converted to UTC, numeric
    dates when some value proves the day and month order, and dates that spell
    out the month. Anything else returns ``None``.
    """
    stripped = values.str.strip()
    present = stripped.dropna()
    if present.empty:
        return None
    if all(_ISO_WITH_ZONE.fullmatch(value) for value in present):
        try:
            parsed: Any = pd.to_datetime(
                stripped, format="ISO8601", utc=True, errors="raise"
            )
        except (ValueError, OverflowError):
            return None
        return (
            pd.Series(
                parsed.dt.tz_localize(None), index=values.index, name=values.name
            ),
            "time zones converted to UTC",
        )
    matches = _numeric_matches(present)
    if matches is not None:
        day_first = _is_day_first(matches)
        if day_first is None:
            return None
        result = _parse(stripped, _numeric_format(matches[0], day_first))
        order = "day first" if day_first else "month first"
        return None if result is None else (result, f"read as {order}")
    for date_format in _NAMED_MONTH_FORMATS:
        result = _parse(stripped, date_format)
        if result is not None:
            return result, "month names read as dates"
    return None
