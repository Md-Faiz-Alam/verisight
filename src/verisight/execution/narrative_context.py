"""Shared narrative-number context for synthesis checks and final reports."""

from dataclasses import dataclass
from decimal import Decimal

import sqlglot
import sqlglot.errors
from sqlglot import exp

from verisight.execution.claim_verification import (
    ClaimOperation,
    NumericalClaim,
    NumericalClaimVerifier,
)
from verisight.execution.narrative_audit import (
    NarrativeDigitCoverage,
    NarrativeNumberToken,
    audit_narrative_digit_coverage,
    find_narrative_numbers,
    label_words,
)
from verisight.execution.observations import QueryObservation


@dataclass(frozen=True, slots=True)
class NarrativeAudit:
    """Numeric tokens in one conclusion and their digit coverage."""

    tokens: tuple[NarrativeNumberToken, ...]
    coverage: NarrativeDigitCoverage

    @property
    def unlinked(self) -> tuple[NarrativeNumberToken, ...]:
        return tuple(token for token in self.tokens if not token.claim_indexes)


def audit_conclusion(
    conclusion: str,
    claims: tuple[NumericalClaim, ...],
    observations: tuple[QueryObservation, ...],
    question: str,
    *,
    extra_values: tuple[Decimal, ...] = (),
) -> NarrativeAudit:
    """Link conclusion numbers to claims, the cells they cite, and labels.

    A number links to a claim through its expected value or, for a difference,
    one of the two numeric cells it subtracts, exactly or rounded to the
    number's own decimal places.
    Words mixing letters and digits count as labels only when they appear in
    the question, result column names, or text result cells. ``extra_values``
    are matched exactly after the claims, such as question numbers outside
    contract mode.
    """
    verifier = NumericalClaimVerifier()
    cited: list[tuple[Decimal, ...]] = []
    for claim in claims:
        # Only a difference has operand cells distinct from its stated value.
        if claim.right is None:
            cited.append(())
            continue
        references = (claim.left, claim.right)
        values = []
        for reference in references:
            actual = verifier.verify(
                NumericalClaim(ClaimOperation.VALUE, Decimal(0), reference),
                observations,
            ).actual
            if actual is not None:
                values.append(actual)
        cited.append(tuple(values))
    texts = [question]
    for observation in observations:
        texts.extend(observation.result.columns)
        texts.extend(
            value
            for row in observation.result.rows
            for value in row
            if isinstance(value, str)
        )
    expected = tuple(Decimal(str(claim.expected)) for claim in claims) + extra_values
    tokens = find_narrative_numbers(conclusion, expected, tuple(cited))
    labels = label_words(texts) | _columns_read(observations)
    return NarrativeAudit(
        tokens, audit_narrative_digit_coverage(conclusion, tokens, labels)
    )


def _columns_read(observations: tuple[QueryObservation, ...]) -> frozenset[str]:
    """Name the data columns the queries read, such as a ``2015-16`` column.

    A wide export often names columns by period. Repeating such a name only
    says which column was read; any number in the conclusion still has to link.
    """
    names: set[str] = set()
    for observation in observations:
        try:
            tree = sqlglot.parse_one(observation.sql, read="duckdb")
        except sqlglot.errors.ParseError:
            continue
        names.update(
            column.name.casefold()
            for column in tree.find_all(exp.Column)
            if any(character.isdigit() for character in column.name)
        )
    return frozenset(names)
