"""Conservative, fully reported clean-up of common messy values.

A column changes only when every present value fits one clear pattern, and
each change is recorded as a ``ValueNote``. Anything uncertain stays as loaded.
"""

import re
from collections import defaultdict
from decimal import Decimal
from typing import Any

import pandas as pd

from verisight.ingestion.footers import remove_footer_rows, remove_non_data_rows
from verisight.ingestion.loaders.csv import CsvLoader
from verisight.ingestion.models import LoadedTable, NoteRule, ValueNote
from verisight.ingestion.temporal import (
    has_ambiguous_dates,
    parse_flexible_dates,
    parse_iso_datetimes,
)

# Spreadsheet and export placeholders for a missing value. They are treated as
# missing only in a column whose other values are all numbers or ISO dates, so
# a label such as "NA" (North America) in a text column is never removed.
MISSING_MARKERS = frozenset(
    {
        "N/A",
        "n/a",
        "N/a",
        "NA",
        "na",
        "#N/A",
        "null",
        "NULL",
        "Null",
        "None",
        "none",
        "NaN",
        "nan",
        "-",
        "--",
        "?",
    }
)
# In a text column these can only mean "no value". Words that can be real
# categories are kept and reported instead.
_TEXT_MISSING = frozenset(
    {"N/A", "n/a", "N/a", "#N/A", "null", "NULL", "Null", "NaN", "nan", "--"}
)
_POSSIBLY_MISSING = frozenset(
    {"unknown", "Unknown", "UNKNOWN", "none", "None", "NONE", "-", "?", "TBD", "tbd"}
)
CURRENCY_SYMBOLS = ("$", "€", "£", "₹", "¥")
_CURRENCY_CODES = ("USD", "EUR", "GBP", "INR", "JPY", "CAD", "AUD", "CHF", "CNY")
_CURRENCY = "|".join(re.escape(mark) for mark in (*CURRENCY_SYMBOLS, *_CURRENCY_CODES))
_CURRENCY_FIRST = re.compile(rf"(-?)\s*({_CURRENCY})\s*(.+)")
_CURRENCY_LAST = re.compile(rf"(.+?)\s*({_CURRENCY})")
_GROUPED = re.compile(
    r"[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,2}(?:,[0-9]{2})+,[0-9]{3})(?:\.[0-9]+)?"
)
_ODD_MINUS = re.compile("[\u2212\u2013]")
_TRAILING_MINUS = re.compile(r"[0-9][0-9.,]*-")
_BRACKETED = re.compile(r"\(([^()]+)\)")
_PLAIN = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?")
_ABBREVIATED = re.compile(r"([+-]?[0-9]+(?:\.[0-9]+)?)\s*([KkMB])")
_MULTIPLIERS = {"K": 1_000, "k": 1_000, "M": 1_000_000, "B": 1_000_000_000}
_WITH_UNIT = re.compile(r"([+-]?[0-9][0-9.,]*)\s*([A-Za-z°µ²³/]{1,8})")
_COMMA_DECIMAL = re.compile(r"[+-]?[0-9]{1,3}(?:\.[0-9]{3})*,[0-9]+")
_DOT_GROUPED = re.compile(r"[+-]?[0-9]{1,3}(?:\.[0-9]{3})+")
_THREE_AFTER_COMMA = re.compile(r"[+-]?[0-9]{1,3},[0-9]{3}")
_NUMBER_SHAPE = (
    rf"[(+\u2212\u2013-]?(?:{_CURRENCY})?\s*[0-9][0-9.,]*-?\s*(?:%|{_CURRENCY})?\)?"
)
_DATE_SHAPE = r"[0-9]{1,4}[/.-][0-9]{1,2}[/.-][0-9]{1,4}.*"
_MIN_ROWS_FOR_STRAYS = 20
_MAX_STRAY_SHARE = 0.05
_MAX_STRAY_LABELS = 5
_NAME_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
_LEADING_ZERO = re.compile(r"[+-]?0[0-9]")
_IDENTIFIER_WORDS = frozenset(
    {
        "id",
        "uuid",
        "guid",
        "code",
        "sku",
        "zip",
        "phone",
        "key",
        "ref",
        "reference",
        "serial",
    }
)
# A letter after a number is often part of a code: shoe size 10M, seat 12A,
# SKU 120B. Columns named like this are never read as quantities that way.
_LABEL_WORDS = _IDENTIFIER_WORDS | {
    "size",
    "seat",
    "room",
    "gate",
    "flight",
    "part",
    "lot",
    "batch",
    "model",
    "version",
    "release",
    "grade",
    "class",
    "level",
    "tier",
    "rank",
}
# Names that say K, M and B are amounts, as in a salary of 50K.
_AMOUNT_WORDS = frozenset(
    {
        "amount",
        "revenue",
        "sale",
        "salary",
        "salaries",
        "wage",
        "income",
        "earning",
        "price",
        "cost",
        "budget",
        "spend",
        "spending",
        "profit",
        "turnover",
        "gross",
        "funding",
        "valuation",
        "capital",
        "asset",
        "fee",
        "fare",
        "follower",
        "subscriber",
        "view",
        "like",
        "download",
        "install",
        "impression",
        "click",
        "vote",
        "user",
        "member",
        "visitor",
        "stream",
        "comment",
        "review",
        "listener",
        "population",
        "volume",
    }
)
# Names that say a one-letter ending is a unit, as in a voltage of 12V.
_MEASURE_WORDS = frozenset(
    {
        "weight",
        "mass",
        "height",
        "width",
        "length",
        "depth",
        "distance",
        "duration",
        "time",
        "voltage",
        "power",
        "current",
        "temperature",
        "temp",
        "volume",
        "capacity",
        "speed",
        "energy",
        "pressure",
        "area",
        "dose",
    }
)
_ONE_LETTER_UNITS = frozenset("gmlLshtVWACF")
# Compared without case. K, M and B are handled as abbreviations instead.
_UNITS = frozenset(
    unit
    for group in (
        "kg mg lb lbs oz ton tons tonne tonnes gram grams kilo kilos pound pounds",
        "km cm mm mi ft yd metre metres meter meters mile miles feet inch inches",
        "ml cl gal cc litre litres liter liters m³ cm³ ha sqft sqm m² km²",
        "ms sec secs second seconds min mins minute minutes hr hrs hour hours",
        "day days wk wks week weeks month months yr yrs year years",
        "wh kwh mwh gwh kw mw gw kv mv ma mah hz khz mhz ghz kcal cal kj",
        "kb mb gb tb pb kbps mbps gbps °c °f mph kph km/h m/s",
        "psi bar kpa mpa hpa ppm ppb mg/l g/l mg/dl pcs items units",
    )
    for unit in group.split()
)
_MAX_EXAMPLES = 3
_MAX_SAFE_INTEGER = 2**53 - 1
_MAX_VARIANT_GROUPS = 5

_Parsed = tuple[pd.Series, NoteRule | None, str | None, pd.Series]


def clean_table(table: LoadedTable) -> None:
    """Drop summary rows and trim headers, then convert or report messy values.

    Notes a loader already recorded, such as generated header names, are kept.
    """
    notes: list[ValueNote] = list(table.value_notes)
    notes.extend(remove_non_data_rows(table))
    notes.extend(remove_footer_rows(table))
    notes.extend(_trim_headers(table))
    semicolons = table.source.csv_delimiter == ";"
    for column in table.data.columns:
        notes.extend(_clean_column(table.data, str(column), semicolons))
    table.value_notes = tuple(notes)


def _trim_headers(table: LoadedTable) -> list[ValueNote]:
    """Strip outer spaces from names when the result stays distinct."""
    names = [str(column) for column in table.data.columns]
    trimmed = [name.strip() for name in names]
    if trimmed == names:
        return []
    keys = [name.lower() for name in trimmed]
    renames: dict[str, str] = {}
    for original, new, key in zip(names, trimmed, keys, strict=True):
        if new != original and new and keys.count(key) == 1:
            renames[original] = new
    if not renames:
        return []
    table.data = table.data.rename(columns=renames)
    table.validate_column_names()
    return [
        ValueNote(
            column=new,
            rule="trimmed_column_name",
            affected_count=1,
            examples=(original,),
        )
        for original, new in renames.items()
    ]


def _clean_column(data: pd.DataFrame, column: str, semicolons: bool) -> list[ValueNote]:
    series = data[column]
    if series.dtype != object:
        return []
    present = series.dropna()
    if present.empty:
        return []
    if all(type(value) is str for value in present):
        return _clean_text(data, column, series, semicolons)
    return _clean_mixed(data, column, series, present)


def _clean_text(
    data: pd.DataFrame, column: str, series: pd.Series, semicolons: bool
) -> list[ValueNote]:
    stripped = series.str.strip()
    markers = stripped.isin(MISSING_MARKERS) | stripped.eq("")
    candidate = series.mask(markers)
    if candidate.dropna().empty:
        return _label_variants(column, series)
    words = _name_words(column)
    converted = _parse_text(candidate, semicolons, words)
    strays = pd.Series(False, index=series.index)
    if converted is None:
        found = _stray_values(words, candidate)
        if found is not None:
            converted = _parse_text(candidate.mask(found), semicolons, words)
            strays = found if converted is not None else strays
    if converted is None:
        # Beside numbers or dates, "unknown" or "TBD" can only mean no value.
        possible = stripped.isin(_POSSIBLY_MISSING)
        if possible.any() and candidate.mask(possible).notna().any():
            converted = _parse_text(candidate.mask(possible), semicolons, words)
            markers = markers | possible if converted is not None else markers
    if converted is None:
        return _text_column(data, column, series, words)
    typed, rule, detail, formatted = converted
    notes: list[ValueNote] = []
    if markers.any():
        notes.append(_note(column, "missing_value_markers", series[markers]))
    if rule is not None:
        notes.append(_note(column, rule, series[formatted], detail))
    if strays.any():
        notes.append(_note(column, "non_numeric_values", series[strays]))
    if not notes:
        # Plain numbers or dates stored as text are left exactly as loaded.
        return _label_variants(column, series)
    data[column] = typed
    return notes


def _name_words(column: str) -> set[str]:
    """Split a column name, so ``order_id`` and ``OrderID`` both contain ``id``."""
    words = {word.casefold() for word in _NAME_WORD.findall(column)}
    return words | {word.removesuffix("s") for word in words}


def _stray_values(words: set[str], candidate: pd.Series) -> pd.Series | None:
    """Mark a few values that stop an otherwise numeric or date column.

    Identifier columns are excluded, where a code such as ``A12`` is as real
    as ``123``. The caller still requires the remaining values to parse.
    """
    present = candidate.dropna().str.strip()
    if words & _IDENTIFIER_WORDS or len(present) < _MIN_ROWS_FOR_STRAYS:
        return None
    shaped = present.str.fullmatch(_NUMBER_SHAPE) | present.str.fullmatch(_DATE_SHAPE)
    outliers = present[~shaped]
    if (
        outliers.empty
        or len(outliers) > _MAX_STRAY_SHARE * len(present)
        or outliers.nunique() > _MAX_STRAY_LABELS
    ):
        return None
    return pd.Series(candidate.index.isin(outliers.index), index=candidate.index)


def _text_column(
    data: pd.DataFrame, column: str, series: pd.Series, words: set[str]
) -> list[ValueNote]:
    """Clear placeholders from a text column and report what could not be read."""
    stripped = series.str.strip()
    notes: list[ValueNote] = []
    placeholders = stripped.isin(_TEXT_MISSING) | stripped.eq("")
    cleared = series.mask(placeholders)
    if placeholders.any():
        data[column] = cleared
        notes.append(_note(column, "text_missing_labels", series[placeholders]))
    possible = stripped.isin(_POSSIBLY_MISSING)
    if possible.any():
        notes.append(_note(column, "possible_missing_labels", series[possible]))
    if has_ambiguous_dates(cleared):
        notes.append(_note(column, "ambiguous_dates", cleared.dropna()))
    if _could_be_quantities(cleared, words):
        notes.append(_note(column, "ambiguous_numbers", cleared.dropna()))
    return notes + _label_variants(column, cleared)


def _could_be_quantities(values: pd.Series, words: set[str]) -> bool:
    """Whether values look abbreviated, or are numbers with one ending, as 12A."""
    if words & _IDENTIFIER_WORDS:
        return False
    present = values.dropna().str.strip()
    short = present.str.fullmatch(_ABBREVIATED)
    if short.any() and (short | present.str.fullmatch(_PLAIN)).all():
        return True
    endings = present.str.extract(_WITH_UNIT.pattern + "$")[1]
    return bool(endings.notna().all()) and endings.nunique() == 1


def _parse_text(values: pd.Series, semicolons: bool, words: set[str]) -> _Parsed | None:
    """Type strings as dates or numbers, removing consistent formatting.

    Returns the typed column, the first format rule applied, a description of
    every step, and a mask of the values that carried a format.
    """
    present = values.notna()
    none = pd.Series(False, index=values.index)
    dates = parse_iso_datetimes(values)
    if dates is not None:
        return dates, None, None, none
    flexible = parse_flexible_dates(values)
    if flexible is not None:
        return flexible[0], "date_format", flexible[1], present
    text = values.str.strip()
    steps: list[tuple[NoteRule, str]] = []
    text = _standard_minus(text, steps, words)
    text = _bracketed_negatives(text, steps, words)
    if all(value.endswith("%") for value in text.dropna()):
        text = text.str.removesuffix("%").str.strip()
        steps.append(("percent_sign", "values are percent points; 10% became 10"))
    else:
        text = _without_currency(text, steps, words)
    text = _european(text, semicolons, steps)
    text = _expanded(text, steps, words)
    text = _without_unit(text, steps, words)
    grouped = text.str.fullmatch(_GROUPED, na=False).astype(bool)
    if grouped.any():
        text = text.mask(grouped, text.str.replace(",", "", regex=False))
        steps.append(("thousands_separators", _grouping_detail(values)))
    typed = CsvLoader._infer_safe_column_types(pd.DataFrame({"value": text}))["value"]
    if typed.dtype == object:
        return None
    typed.name = values.name
    if not steps:
        padded = present & values.ne(values.str.strip())
        if not padded.any():
            return typed, None, None, none
        return typed, "padded_numbers", "outer spaces removed", padded
    only_groups = len(steps) == 1 and steps[0][0] == "thousands_separators"
    marked = grouped if only_groups else present
    return typed, steps[0][0], "; ".join(detail for _, detail in steps), marked


def _grouping_detail(values: pd.Series) -> str:
    """Flag the one reading that could really be a European decimal."""
    present = values.dropna().str.strip()
    if present.str.fullmatch(_THREE_AFTER_COMMA).all():
        return (
            "comma group separators removed; 1,234 was read as 1234, so check "
            "this if the file uses commas as decimal marks"
        )
    return "comma group separators removed"


def _standard_minus(
    text: pd.Series, steps: list[tuple[NoteRule, str]], words: set[str]
) -> pd.Series:
    """Rewrite the true minus sign, the en dash and the trailing minus as ``-``."""
    if words & _IDENTIFIER_WORDS:
        return text
    standard = text.str.replace(_ODD_MINUS, "-", regex=True)
    trailing = standard.str.fullmatch(_TRAILING_MINUS, na=False).astype(bool)
    standard = standard.mask(trailing, "-" + standard.str[:-1])
    if standard.dropna().eq(text.dropna()).all():
        return text
    steps.append(("minus_signs", "minus signs written another way read as negative"))
    return standard


def _bracketed_negatives(
    text: pd.Series, steps: list[tuple[NoteRule, str]], words: set[str]
) -> pd.Series:
    bracketed = text.str.fullmatch(_BRACKETED, na=False).astype(bool)
    if not bracketed.any() or words & _IDENTIFIER_WORDS:
        return text
    # A column of nothing but (123) may hold codes rather than negative amounts.
    formatted = text.dropna().str.contains(rf"[.,]|{_CURRENCY}").any()
    if bracketed[text.notna()].all() and not formatted:
        return text
    steps.append(("accounting_negatives", "numbers in brackets read as negative"))
    return text.mask(bracketed, "-" + text.str[1:-1])


def _split_currency(value: str) -> tuple[str, str] | None:
    """Return the currency mark and the number written with it."""
    first = _CURRENCY_FIRST.fullmatch(value)
    if first is not None:
        return first[2], first[1] + first[3]
    last = _CURRENCY_LAST.fullmatch(value)
    return None if last is None else (last[2], last[1])


def _without_currency(
    text: pd.Series, steps: list[tuple[NoteRule, str]], words: set[str]
) -> pd.Series:
    """Remove one currency mark, shown on some or all of a column's numbers."""
    present = text.dropna()
    parts = present.map(_split_currency)
    marked = parts.notna()
    bare = present[~marked]
    if (
        not marked.any()
        or words & _LABEL_WORDS
        or not (bare.str.fullmatch(_PLAIN) | bare.str.fullmatch(_GROUPED)).all()
    ):
        return text
    carried = parts[marked]
    marks = {part[0] for part in carried}
    if len(marks) != 1:
        return text
    mark = next(iter(marks))
    # GBP100 may be a voucher code; GBP 100, GBP100.50 and £100 read as money.
    if mark.isalpha() and not present[marked].str.contains(r"[\s.,]").all():
        return text
    steps.append(("currency_symbol", f"{mark} removed"))
    numbers = carried.map(lambda part: part[1])
    return text.mask(text.index.isin(numbers.index), numbers.reindex(text.index))


def _european(
    text: pd.Series, semicolons: bool, steps: list[tuple[NoteRule, str]]
) -> pd.Series:
    """Read comma decimals only when the column's own values prove them.

    A comma followed by anything but three digits cannot be a group separator.
    ``1,234`` alone is ambiguous, and counts only in a semicolon-separated file.
    """
    present = text.dropna()
    decimal = present.str.fullmatch(_COMMA_DECIMAL)
    fits = (
        decimal
        | present.str.fullmatch(_DOT_GROUPED)
        | present.str.fullmatch(r"[+-]?[0-9]+")
    )
    proof = decimal & (semicolons | ~present.str.fullmatch(_THREE_AFTER_COMMA))
    if not fits.all() or not proof.any():
        return text
    steps.append(("european_numbers", "commas read as decimal marks"))
    return text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)


def _shows_amounts(
    present: pd.Series,
    short: pd.Series,
    steps: list[tuple[NoteRule, str]],
    words: set[str],
) -> bool:
    """Tell amounts such as 1.2K from codes that only look abbreviated, as 10M.

    The column's name can decide. Otherwise the values must show it, with a
    currency mark or a decimal. Whole numbers with these letters stay unproven:
    reading a code as an amount is far worse than leaving it as text.
    """
    if words & _LABEL_WORDS or present.str.match(_LEADING_ZERO).any():
        return False
    return bool(
        words & _AMOUNT_WORDS
        or any(rule == "currency_symbol" for rule, _ in steps)
        or present[short].str.contains(".", regex=False).any()
    )


def _expanded(
    text: pd.Series, steps: list[tuple[NoteRule, str]], words: set[str]
) -> pd.Series:
    present = text.dropna()
    short = present.str.fullmatch(_ABBREVIATED)
    if not short.any() or not (short | present.str.fullmatch(_PLAIN)).all():
        return text
    if not _shows_amounts(present, short, steps, words):
        return text

    def expand(value: str) -> str:
        match = _ABBREVIATED.fullmatch(value)
        if match is None:
            return value
        return format(Decimal(match[1]) * _MULTIPLIERS[match[2]], "f")

    steps.append(("abbreviated_numbers", "K, M and B expanded"))
    return text.map(expand, na_action="ignore")


def _is_unit(unit: str, spaced: bool, words: set[str]) -> bool:
    """A known unit, on a column not named as a label or code.

    One letter proves little, since 12A is as likely a seat as 12 amperes, so
    it also needs a space before it or a measurement in the column's name.
    """
    if words & _LABEL_WORDS:
        return False
    if len(unit) > 1:
        return unit.casefold() in _UNITS
    return unit in _ONE_LETTER_UNITS and (spaced or bool(words & _MEASURE_WORDS))


def _without_unit(
    text: pd.Series, steps: list[tuple[NoteRule, str]], words: set[str]
) -> pd.Series:
    """Remove a unit only when every value carries the same known one."""
    present = text.dropna()
    matches = present.str.extract(_WITH_UNIT.pattern + "$")
    full = present.str.fullmatch(_WITH_UNIT)
    units = set(matches[1].dropna())
    if not full.all() or len(units) != 1:
        return text
    unit = next(iter(units))
    if not _is_unit(unit, bool(present.str.contains(r"\s").all()), words):
        return text
    steps.append(("unit_suffix", f"{unit} removed"))
    return matches[0].reindex(text.index)


def _clean_mixed(
    data: pd.DataFrame, column: str, series: pd.Series, present: pd.Series
) -> list[ValueNote]:
    """Numbers mixed only with missing markers, as in spreadsheets and JSON."""
    numbers = [value for value in present if type(value) in (int, float)]
    markers = series.map(lambda value: type(value) is str and value in MISSING_MARKERS)
    if (
        not numbers
        or not markers.any()
        or len(numbers) + int(markers.sum()) != len(present)
        # Integers beyond exact float range keep their exact, untouched values.
        or any(
            type(value) is int and abs(value) > _MAX_SAFE_INTEGER for value in numbers
        )
    ):
        return []
    cleaned = series.mask(markers)
    if all(type(value) is int for value in numbers):
        typed: Any = pd.array(cleaned.tolist(), dtype="Int64")
    else:
        typed = pd.to_numeric(cleaned, errors="raise")
    data[column] = pd.Series(typed, index=series.index, name=series.name)
    return [_note(column, "missing_value_markers", series[markers])]


def _label_variants(column: str, series: pd.Series) -> list[ValueNote]:
    """Report labels that differ only by letter case or outer spaces."""
    spellings: dict[str, set[str]] = defaultdict(set)
    for value in series.dropna():
        spellings[value.strip().casefold()].add(value)
    groups = [sorted(group) for group in spellings.values() if len(group) > 1]
    if not groups:
        return []
    affected = series.isin({value for group in groups for value in group})
    examples = tuple(
        " / ".join(repr(value) for value in group[:_MAX_EXAMPLES])
        for group in groups[:_MAX_VARIANT_GROUPS]
    )
    return [
        ValueNote(
            column=column,
            rule="label_variants",
            affected_count=int(affected.sum()),
            examples=examples,
            detail="values differ only by letter case or surrounding spaces",
        )
    ]


def _note(
    column: str, rule: NoteRule, values: pd.Series, detail: str | None = None
) -> ValueNote:
    unique = list(dict.fromkeys(str(value) for value in values))
    return ValueNote(
        column=column,
        rule=rule,
        affected_count=len(values),
        examples=tuple(unique[:_MAX_EXAMPLES]),
        detail=detail,
    )
