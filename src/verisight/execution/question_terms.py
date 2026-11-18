"""How a question names categories, values and conditions, read from its wording.

These are English lexical rules shared by the population review and the SQL
audit. They never decide SQL safety.
"""

import re
from collections.abc import Iterable

from sqlglot import exp

# A reporting instruction's "as ..." complement describes the answer's form
# ("Report it as a single number"), not the population being measured.
_FORMAT_COMPLEMENT = re.compile(
    r"\b(?:report|return|give|express|present|provide|answer)\b[^.?!;]*?"
    r"(\bas\b[^.?!;]*)",
    re.IGNORECASE,
)


def _without_format_complements(question: str) -> str:
    """Blank reporting-format complements while keeping character offsets."""
    return _FORMAT_COMPLEMENT.sub(
        lambda match: (
            match.group(0)[: match.start(1) - match.start(0)]
            + " " * len(match.group(1))
        ),
        question,
    )


_MAX_CODE_LENGTH = 3
# "How many of the deaths" names the whole set, not a kind of row.
_PARTITIVE = re.compile(r"\bhow many of the\s+\w+", re.IGNORECASE)


def question_mentions_category(question: str, value: str) -> bool:
    """Exact case-insensitive words only; direct negative mentions are skipped.

    Words inside a reporting-format complement are not category mentions. A short
    capitalised code must be written in capitals, so the word "in" does not name
    the code ``IN``.
    """
    if not value.strip():
        return False
    question = _PARTITIVE.sub("", _without_format_complements(question))
    literal = _plural_pattern(value)
    short_code = value.isupper() and len(value.strip()) <= _MAX_CODE_LENGTH
    case = 0 if short_code else re.IGNORECASE
    if not re.search(rf"(?<!\w){literal}(?!\w)", question, case):
        return False
    negative = (
        rf"\b(?:exclude|excluding|except|without|not|non[- ])\s*"
        rf"(?:all\s+)?['\"]?{literal}(?!\w)"
    )
    return not re.search(negative, question, re.IGNORECASE)


def names_every_row(
    question: str, relations: Iterable[str], column: str, value: str
) -> bool:
    """A value that is a table's own subject word names every row, not a kind.

    When a table is called ``races``, "how many races" counts its rows even if a
    column of any loaded table holds the label ``RACE``. Saying "circuit type is
    RACE" still names the label.
    """
    words = {
        word.casefold()
        for relation in relations
        for word in re.findall(r"[A-Za-z]+", relation)
    }
    subjects = words | {word[:-1] for word in words if word.endswith("s")}
    subjects |= {f"{word[:-3]}y" for word in words if word.endswith("ies")}
    return value.strip().casefold() in subjects and not question_assigns_category(
        question, column, value
    )


def _plural_pattern(value: str) -> str:
    """Match a value or a regular English plural of its last word.

    ``Earthquake`` also matches ``earthquakes``, ``Flood`` matches ``floods``
    and ``Category`` matches ``categories``. Only values ending in a letter of
    a word of at least three letters get plural forms.
    """
    literal = re.escape(value)
    if not re.search(r"[A-Za-z]{3}$", value):
        return literal
    if value[-1] in "yY" and value[-2] not in "aeiouAEIOU":
        return rf"(?:{literal}|{re.escape(value[:-1])}ies)"
    return rf"{literal}(?:s|es)?"


def question_assigns_category(question: str, column: str, value: str) -> bool:
    """Recognize an explicit column/value statement such as ``loan is yes``.

    Up to two words may separate the column name from the verb, as in
    ``default status is no``. Underscores in the column name match spaces.
    """
    parts = [part for part in re.split(r"[\s_]+", column) if part]
    if not parts or not value.strip():
        return False
    name = r"[\s_]+".join(re.escape(part) for part in parts)
    pattern = (
        rf"(?<!\w){name}(?!\w)(?:\s+\w+){{0,2}}?"
        rf"(?:\s+(?:is|equals|equal\s+to)\s+|\s*==?\s*)"
        rf"['\"]?{re.escape(value)}(?!\w)"
    )
    return (
        re.search(pattern, _without_format_complements(question), re.IGNORECASE)
        is not None
    )


def population_terms(expression: exp.Expression) -> list[exp.Expression]:
    """Only top-level conjunctions establish an explicit inclusion here."""
    pending = [expression]
    terms = []
    while pending:
        term = pending.pop()
        if isinstance(term, exp.Paren):
            pending.append(term.this)
        elif isinstance(term, exp.And):
            pending.extend((term.expression, term.this))
        else:
            terms.append(term)
    return terms
