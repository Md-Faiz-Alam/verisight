"""Conservative numeric-token matching without certifying narrative meaning."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext
from typing import Literal

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

# A word that mixes letters and digits, such as VVS1 or Q4, is a label when it
# is copied from the question or the evidence, not a quantity. Hyphenated
# words such as PG-13 or COVID-19 are compared whole, so their digits are not
# mistaken for a separate number.
_WORD = re.compile(r"\w+")
_COMPOUND = re.compile(r"\w+(?:-\w+)+")

NumberLink = Literal[
    "claim_value", "cited_cell", "rounded_claim_value", "rounded_cited_cell"
]

# This is a contract-format restriction, not a natural-language number parser.
# Unicode word boundaries avoid matching inside identifiers such as someone,
# one_source, or one2. Hyphenated cardinals contain separate matching words.
_ENGLISH_CARDINAL_WORD = re.compile(
    r"(?<!\w)(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundreds?|thousands?|millions?|billions?|trillions?)(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class NarrativeNumberToken:
    """One detected token, its text span, and exact matching claim indexes.

    Indexes refer to submitted claim values, regardless of their verdicts.
    A null value indicates unsupported syntax or a conversion limit. ``link``
    names the strongest match: the claim's expected value, a numeric cell the
    claim cites, or either one rounded half up to the token's decimal places.
    """

    text: str
    start: int
    end: int
    value: Decimal | None
    claim_indexes: tuple[int, ...]
    link: NumberLink | None = None


@dataclass(frozen=True, slots=True)
class NarrativeDigitCoverage:
    """Character coverage only, independent of claim support or narrative truth.

    Digits are characters recognized by str.isdigit(), including Unicode digits.
    all_digits_parsed means every such character falls within a token with a
    parsed numerical value. It does not validate signs, units, meaning, or
    number words. no_digits does not establish the absence of numerical claims.
    Digits inside supplied label words, such as VVS1, are excluded from all
    counts because they name data rather than state quantities.
    """

    total_digit_count: int
    parsed_digit_count: int
    unparsed_digit_count: int
    status: Literal["no_digits", "all_digits_parsed", "unparsed_digits"]


def label_words(texts: Iterable[str]) -> frozenset[str]:
    """Collect words mixing letters and digits, compared case-insensitively."""
    return frozenset(
        word.casefold()
        for text in texts
        for pattern in (_WORD, _COMPOUND)
        for word in pattern.findall(text)
        if any(c.isalpha() for c in word) and any(c.isdigit() for c in word)
    )


def audit_narrative_digit_coverage(
    text: str,
    tokens: tuple[NarrativeNumberToken, ...],
    labels: frozenset[str] = frozenset(),
) -> NarrativeDigitCoverage:
    """Measure coverage using tokens returned for this text by the lexer.

    Rejected token syntax and conversion limits count as unparsed. No Unicode
    normalization or interpretation of suffixes, ranges, or units is performed.
    Digits inside a whole word found in ``labels`` are not counted.
    """
    label_positions: set[int] = set()
    for pattern in (_WORD, _COMPOUND):
        for match in pattern.finditer(text):
            if match.group().casefold() in labels:
                label_positions.update(range(match.start(), match.end()))
    digit_positions = {
        index
        for index, character in enumerate(text)
        if character.isdigit() and index not in label_positions
    }
    parsed_positions: set[int] = set()
    for token in tokens:
        if token.value is not None:
            parsed_positions.update(range(token.start, token.end))
    total = len(digit_positions)
    parsed = len(digit_positions & parsed_positions)
    unparsed = total - parsed
    status: Literal["no_digits", "all_digits_parsed", "unparsed_digits"]
    if total == 0:
        status = "no_digits"
    elif unparsed:
        status = "unparsed_digits"
    else:
        status = "all_digits_parsed"
    return NarrativeDigitCoverage(total, parsed, unparsed, status)


_LINK_ORDER: tuple[NumberLink, ...] = (
    "claim_value",
    "cited_cell",
    "rounded_claim_value",
    "rounded_cited_cell",
)


def _rounds_to(candidate: Decimal, value: Decimal) -> bool:
    """True when candidate, rounded half up to value's places, equals value.

    Only tokens written with at least one decimal place qualify, so integers
    and question numbers never link by rounding.
    """
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent >= 0:
        return False
    try:
        with localcontext() as context:
            context.prec = 60
            return (
                candidate.quantize(Decimal(1).scaleb(exponent), ROUND_HALF_UP) == value
            )
    except DecimalException:
        return False


def _link(
    value: Decimal, expected: Decimal, cited: tuple[Decimal, ...]
) -> NumberLink | None:
    if value == expected:
        return "claim_value"
    if value in cited:
        return "cited_cell"
    if _rounds_to(expected, value):
        return "rounded_claim_value"
    if any(_rounds_to(cell, value) for cell in cited):
        return "rounded_cited_cell"
    return None


def find_narrative_numbers(
    text: str,
    expected_values: tuple[Decimal, ...],
    cited_values: tuple[tuple[Decimal, ...], ...] = (),
) -> tuple[NarrativeNumberToken, ...]:
    """Match supported ASCII numerical tokens against finite expected values.

    ``cited_values[i]`` holds the evidence cells that claim ``i`` references.
    A token links to a claim through its expected value, one of those cells,
    or either one rounded to the token's own decimal places.
    """
    tokens: list[NarrativeNumberToken] = []
    for match in _CANDIDATE.finditer(text):
        raw = match.group()
        value = _parse_number(raw)
        links: dict[int, NumberLink] = {}
        if value is not None:
            for index, expected in enumerate(expected_values):
                cited = cited_values[index] if index < len(cited_values) else ()
                link = _link(value, expected, cited)
                if link is not None:
                    links[index] = link
        best = min(links.values(), key=_LINK_ORDER.index) if links else None
        tokens.append(
            NarrativeNumberToken(
                raw, match.start(), match.end(), value, tuple(links), best
            )
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


def contains_english_cardinal_words(text: str) -> bool:
    """Detect a fixed set of whole-word English cardinals for contract mode.

    This rejects even matching values and nonquantitative uses of these words.
    It neither parses their values nor checks truth, direction, fractions,
    ordinals, other number words, or other languages.
    """
    return _ENGLISH_CARDINAL_WORD.search(text) is not None
