"""Conservative numeric-token matching without certifying narrative meaning."""

import re
from dataclasses import dataclass
from decimal import Decimal, DecimalException

# Exclude word identifiers, dotted versions, and contiguous ASCII dates or
# arithmetic expressions. This lexer deliberately supports a limited syntax.
_CANDIDATE = re.compile(
    r"(?<![\w.,+\-/\u2212])[+-]?"
    r"(?:[0-9](?:[0-9,]*[0-9])?(?:\.[0-9]+)?|\.[0-9]+)"
    r"(?:[eE][+-]?[0-9]+)?%?"
    r"(?!\w|\.[0-9]|[-/][0-9])"
)
_NUMBER = re.compile(
    r"[+-]?(?:(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)"
    r"(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
)


@dataclass(frozen=True, slots=True)
class NarrativeNumberToken:
    """One detected token, its text span, and exact matching claim indexes.

    Indexes refer to submitted claim values, regardless of their verdicts.
    A null value indicates unsupported syntax or a conversion limit.
    """

    text: str
    start: int
    end: int
    value: Decimal | None
    claim_indexes: tuple[int, ...]


def find_narrative_numbers(
    text: str, expected_values: tuple[Decimal, ...]
) -> tuple[NarrativeNumberToken, ...]:
    """Match supported ASCII numerical tokens against finite expected values."""
    tokens: list[NarrativeNumberToken] = []
    for match in _CANDIDATE.finditer(text):
        raw = match.group()
        value = _parse_number(raw)
        indexes = (
            tuple(
                index
                for index, expected in enumerate(expected_values)
                if value == expected
            )
            if value is not None
            else ()
        )
        tokens.append(
            NarrativeNumberToken(raw, match.start(), match.end(), value, indexes)
        )
    return tuple(tokens)


def _parse_number(raw: str) -> Decimal | None:
    """Apply a fixed syntax and size limit before exact decimal conversion."""
    number = raw.removesuffix("%")
    if len(raw) > 128 or _NUMBER.fullmatch(number) is None:
        return None
    try:
        value = Decimal(number.replace(",", ""))
    except DecimalException:
        return None
    return value if value.is_finite() else None
