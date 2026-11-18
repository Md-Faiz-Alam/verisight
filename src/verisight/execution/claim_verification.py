"""Deterministic verification of numerical claims against query observations."""

import math
from dataclasses import dataclass, field, replace
from decimal import (
    ROUND_HALF_UP,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    localcontext,
)
from enum import StrEnum
from typing import TypeAlias, cast

from verisight.execution.observations import QueryObservation

NumericValue: TypeAlias = int | float | Decimal
# Significant digits at which floating-point evidence and a claim must agree.
FLOAT_SIGNIFICANT_DIGITS = 12


class ClaimOperation(StrEnum):
    """Supported operations for evidence-linked numerical claims.

    ``RATIO`` is left divided by right, ``PERCENT`` is 100 times that, and
    ``PERCENT_CHANGE`` is 100 times (left minus right) divided by right, with
    right as the reference value. These three are derived: computed exactly
    from two SQL cells, then compared with the claim at its own decimal places.
    """

    VALUE = "value"
    DIFFERENCE = "difference"
    RATIO = "ratio"
    PERCENT = "percent"
    PERCENT_CHANGE = "percent_change"


DERIVED_OPERATIONS = frozenset(
    {ClaimOperation.RATIO, ClaimOperation.PERCENT, ClaimOperation.PERCENT_CHANGE}
)
# A rounded derived claim must keep this many significant digits, so a quotient
# of 0.333... is never accepted as "0". With fewer, only an exact value matches.
MIN_DERIVED_SIGNIFICANT_DIGITS = 3
# Working precision for derived quotients, far beyond any displayed rounding.
_DERIVED_PRECISION = 50


def contract_kind(operation: ClaimOperation) -> ClaimOperation:
    """The answer slot a claim fills: one number, or a difference.

    A derived claim states one final number, so it fills a VALUE slot.
    """
    if operation is ClaimOperation.DIFFERENCE:
        return ClaimOperation.DIFFERENCE
    return ClaimOperation.VALUE


MAX_ROUNDED_PLACES = 12


class VerificationStatus(StrEnum):
    """Outcome of deterministic numerical claim verification."""

    SUPPORTED = "supported"
    SUPPORTED_ROUNDED = "supported_rounded"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """Locate one numerical cell in an executed query observation."""

    observation_index: int
    row_index: int
    column: str

    def __post_init__(self) -> None:
        """Validate reference structure without requiring evidence to exist."""

        if type(self.observation_index) is not int:
            raise TypeError("Observation index must be an integer.")

        if type(self.row_index) is not int:
            raise TypeError("Row index must be an integer.")

        if not isinstance(self.column, str):
            raise TypeError("Evidence column must be a string.")

        if not self.column:
            raise ValueError("Evidence column must not be empty.")


@dataclass(frozen=True, slots=True)
class NumericalClaim:
    """An expected numerical value derived from explicit evidence."""

    operation: ClaimOperation
    expected: NumericValue
    left: EvidenceReference
    right: EvidenceReference | None = None
    absolute_tolerance: NumericValue = 0

    def __post_init__(self) -> None:
        """Validate supported operations and numerical comparison settings."""

        if not isinstance(self.operation, ClaimOperation):
            raise TypeError("Claim operation must be a ClaimOperation.")

        if not isinstance(self.left, EvidenceReference):
            raise TypeError("Left evidence must be an EvidenceReference.")

        if self.operation is ClaimOperation.VALUE:
            if self.right is not None:
                raise ValueError("A value claim must have one evidence reference.")
        elif not isinstance(self.right, EvidenceReference):
            raise ValueError(
                f"A {self.operation.value} claim requires right-hand evidence."
            )

        _decimal_number(self.expected, name="Expected value")

        tolerance = _decimal_number(
            self.absolute_tolerance,
            name="Absolute tolerance",
        )
        if tolerance < 0:
            raise ValueError("Absolute tolerance must not be negative.")


@dataclass(frozen=True, slots=True)
class DecimalRoundingPolicy:
    """Application-selected decimal places; never inferred from a model claim.

    This policy rounds in the evidence cell's existing units. It does not
    convert percentages or currencies, infer units, or validate SQL semantics.
    Values round to nearest; exact ties round away from zero, matching
    DuckDB ROUND for exact decimal inputs.
    """

    decimal_places: int
    rounding_mode: str = field(default=ROUND_HALF_UP, init=False)

    def __post_init__(self) -> None:
        if type(self.decimal_places) is not int:
            raise TypeError("Decimal places must be an integer.")
        if not 0 <= self.decimal_places <= 12:
            raise ValueError("Decimal places must be between 0 and 12.")


@dataclass(frozen=True, slots=True)
class ClaimVerificationResult:
    """Deterministic outcome with computed value when evidence is usable."""

    status: VerificationStatus
    actual: Decimal | None
    expected: Decimal
    absolute_tolerance: Decimal
    reason: str
    rounding_policy: DecimalRoundingPolicy | None = None
    rounded_actual: Decimal | None = None


class NumericalClaimVerifier:
    """Check numerical claims without generating or executing new queries."""

    def __init__(self, *, rounding_policy: DecimalRoundingPolicy | None = None) -> None:
        if rounding_policy is not None and not isinstance(
            rounding_policy, DecimalRoundingPolicy
        ):
            raise TypeError("Rounding policy must be a DecimalRoundingPolicy.")
        self._rounding_policy = rounding_policy

    def verify(
        self,
        claim: NumericalClaim,
        observations: tuple[QueryObservation, ...],
    ) -> ClaimVerificationResult:
        """Check evidence, optionally applying an explicit presentation policy."""
        policy = self._rounding_policy
        if policy is not None and claim.absolute_tolerance != 0:
            raise ValueError("Rounding cannot be combined with absolute tolerance.")
        result = self._verify_exact(claim, observations)
        if policy is None:
            return result
        if result.status is not VerificationStatus.CONTRADICTED:
            return replace(result, rounding_policy=policy)
        actual = cast(Decimal, result.actual)
        try:
            rounded = _round_for_policy(actual, policy)
        except DecimalException:
            return replace(
                result,
                status=VerificationStatus.UNVERIFIABLE,
                rounding_policy=policy,
                reason="Numerical evidence cannot be rounded safely.",
            )
        matches = rounded == result.expected
        return replace(
            result,
            status=(
                VerificationStatus.SUPPORTED_ROUNDED
                if matches
                else VerificationStatus.CONTRADICTED
            ),
            rounding_policy=policy,
            rounded_actual=rounded,
            reason=(
                "The claimed value matches evidence under the rounding policy."
                if matches
                else "The claimed value differs under the rounding policy."
            ),
        )

    def _verify_exact(
        self,
        claim: NumericalClaim,
        observations: tuple[QueryObservation, ...],
    ) -> ClaimVerificationResult:
        """Verify a claim against previously executed observations."""

        expected = _decimal_number(claim.expected, name="Expected value")
        tolerance = _decimal_number(
            claim.absolute_tolerance,
            name="Absolute tolerance",
        )

        left = self._resolve(claim.left, observations)

        if left is None:
            return ClaimVerificationResult(
                status=VerificationStatus.UNVERIFIABLE,
                actual=None,
                expected=expected,
                absolute_tolerance=tolerance,
                reason="Left-hand numerical evidence is unavailable.",
            )

        if claim.operation is ClaimOperation.VALUE:
            actual = left
        else:
            # NumericalClaim validates the right-hand reference for every
            # two-cell operation during construction.
            right_reference = cast(EvidenceReference, claim.right)
            right = self._resolve(right_reference, observations)

            if right is None:
                return ClaimVerificationResult(
                    status=VerificationStatus.UNVERIFIABLE,
                    actual=None,
                    expected=expected,
                    absolute_tolerance=tolerance,
                    reason="Right-hand numerical evidence is unavailable.",
                )

            if claim.operation in DERIVED_OPERATIONS:
                return self._verify_derived(claim, left, right, expected, tolerance)
            try:
                actual = _subtract_exact(left, right)
            except DecimalException:
                return ClaimVerificationResult(
                    status=VerificationStatus.UNVERIFIABLE,
                    actual=None,
                    expected=expected,
                    absolute_tolerance=tolerance,
                    reason="Numerical evidence cannot be combined safely.",
                )

        try:
            difference = _subtract_exact(actual, expected).copy_abs()
        except DecimalException:
            return ClaimVerificationResult(
                status=VerificationStatus.UNVERIFIABLE,
                actual=None,
                expected=expected,
                absolute_tolerance=tolerance,
                reason="Numerical evidence cannot be compared safely.",
            )

        if difference <= tolerance:
            return ClaimVerificationResult(
                status=VerificationStatus.SUPPORTED,
                actual=actual,
                expected=expected,
                absolute_tolerance=tolerance,
                reason="The numerical evidence supports the claimed value.",
            )

        floating = self._floating_difference(claim, observations)
        if floating is not None and abs(floating - expected) <= tolerance:
            return ClaimVerificationResult(
                status=VerificationStatus.SUPPORTED,
                actual=floating,
                expected=expected,
                absolute_tolerance=tolerance,
                reason=(
                    "The claimed value equals the double-precision difference "
                    "of the floating-point evidence cells."
                ),
            )

        bound = self._float_noise_bound(claim, observations)
        if (
            bound is not None
            and difference <= bound
            and len(expected.normalize().as_tuple().digits) <= FLOAT_SIGNIFICANT_DIGITS
        ):
            return ClaimVerificationResult(
                status=VerificationStatus.SUPPORTED,
                actual=actual,
                expected=expected,
                absolute_tolerance=tolerance,
                reason=(
                    "The claimed value equals the floating-point evidence to "
                    f"{FLOAT_SIGNIFICANT_DIGITS} significant digits."
                ),
            )

        if self._sql_rounded_difference(claim, observations, actual, expected):
            return ClaimVerificationResult(
                status=VerificationStatus.SUPPORTED,
                actual=expected,
                expected=expected,
                absolute_tolerance=tolerance,
                reason=(
                    "The claimed value equals the difference as rounded by SQL "
                    "in the same result row."
                ),
            )

        return ClaimVerificationResult(
            status=VerificationStatus.CONTRADICTED,
            actual=actual,
            expected=expected,
            absolute_tolerance=tolerance,
            reason="The numerical evidence contradicts the claimed value.",
        )

    @staticmethod
    def _verify_derived(
        claim: NumericalClaim,
        left: Decimal,
        right: Decimal,
        expected: Decimal,
        tolerance: Decimal,
    ) -> ClaimVerificationResult:
        """Compute a ratio or percentage exactly, then compare at the claim's places.

        A zero reference cannot be divided by, so the claim is unverifiable.
        """
        try:
            actual = _derive(claim.operation, left, right)
        except DecimalException:
            return ClaimVerificationResult(
                status=VerificationStatus.UNVERIFIABLE,
                actual=None,
                expected=expected,
                absolute_tolerance=tolerance,
                reason="The right-hand evidence is zero, so it cannot divide.",
            )
        if abs(actual - expected) <= tolerance or _rounds_to(actual, expected):
            return ClaimVerificationResult(
                status=VerificationStatus.SUPPORTED,
                actual=actual,
                expected=expected,
                absolute_tolerance=tolerance,
                reason=(
                    f"The claimed {claim.operation.value} equals the one computed "
                    "from the evidence cells, rounded to the claim's decimal places."
                ),
            )
        return ClaimVerificationResult(
            status=VerificationStatus.CONTRADICTED,
            actual=actual,
            expected=expected,
            absolute_tolerance=tolerance,
            reason=(
                f"The {claim.operation.value} computed from the evidence cells "
                "contradicts the claimed value."
            ),
        )

    @classmethod
    def _sql_rounded_difference(
        cls,
        claim: NumericalClaim,
        observations: tuple[QueryObservation, ...],
        actual: Decimal,
        expected: Decimal,
    ) -> bool:
        """Whether SQL itself returned this difference, rounded, beside its parts.

        The two cited cells must be in one row, the claim must equal their exact
        difference at the claim's own decimal places, and another cell of that row
        must hold exactly the claimed number. So the number still comes from an
        executed query, and a rounding the query did not make is still rejected.
        """
        right = claim.right
        if right is None or (
            (claim.left.observation_index, claim.left.row_index)
            != (right.observation_index, right.row_index)
        ):
            return False
        places = -cast(int, expected.as_tuple().exponent)
        if not 0 <= places <= MAX_ROUNDED_PLACES:
            return False
        try:
            rounded = _round_for_policy(actual, DecimalRoundingPolicy(places))
        except DecimalException:
            return False
        if rounded != expected:
            return False
        # Both references resolved already, so this row exists.
        result = observations[right.observation_index].result
        cited = (claim.left.column, right.column)
        return any(
            name not in cited
            and type(cell) in (int, float, Decimal)
            and _decimal_number(cell, name="Evidence value") == expected
            for name, cell in zip(
                result.columns, result.rows[right.row_index], strict=False
            )
        )

    @classmethod
    def _floating_difference(
        cls,
        claim: NumericalClaim,
        observations: tuple[QueryObservation, ...],
    ) -> Decimal | None:
        """Return SQL's own double subtraction when both cells are floats.

        SQL computes a difference of two DOUBLE cells in binary floating point,
        so its result can differ from the exact decimal difference in the last
        significant digit. Only that one IEEE-754 result is accepted in
        addition to the exact difference; no tolerance is introduced.
        """
        if claim.operation is not ClaimOperation.DIFFERENCE:
            return None
        left = cls._resolve_cell(claim.left, observations)
        right = cls._resolve_cell(cast(EvidenceReference, claim.right), observations)
        if type(left) is not float or type(right) is not float:
            return None
        result = left - right
        if not math.isfinite(result):
            return None
        return Decimal(repr(result))

    @classmethod
    def _float_noise_bound(
        cls,
        claim: NumericalClaim,
        observations: tuple[QueryObservation, ...],
    ) -> Decimal | None:
        """Return the binary rounding margin when the evidence is floating point.

        SQL aggregates DOUBLE values in binary floating point, so a sum of
        decimal amounts such as 333819.64 can arrive as 333819.64000000036.
        When any cited cell is a float, a claim written with at most
        ``FLOAT_SIGNIFICANT_DIGITS`` significant digits that agrees with the
        evidence to that many digits of the largest cited cell is accepted. A
        double carries 15 to 17 significant digits, so this margin sits far
        below any real rounding: 333819.6 is still rejected, and so is a claim
        with more digits than that, which is not a display of the evidence.
        Integer and Decimal evidence stays exact.
        """
        references = [claim.left]
        if claim.right is not None:
            references.append(claim.right)
        cells = [cls._resolve_cell(reference, observations) for reference in references]
        if not any(type(cell) is float for cell in cells):
            return None
        scale = max(
            abs(_decimal_number(cell, name="Evidence value"))
            for cell in cells
            if cell is not None
        )
        if scale == 0:
            return None
        return Decimal(5).scaleb(scale.adjusted() - FLOAT_SIGNIFICANT_DIGITS)

    @classmethod
    def _resolve(
        cls,
        reference: EvidenceReference,
        observations: tuple[QueryObservation, ...],
    ) -> Decimal | None:
        """Resolve one reference, rejecting missing or ambiguous values."""

        value = cls._resolve_cell(reference, observations)
        if value is None:
            return None
        try:
            return _decimal_number(value, name="Evidence value")
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _resolve_cell(
        reference: EvidenceReference,
        observations: tuple[QueryObservation, ...],
    ) -> int | float | Decimal | None:
        """Return the referenced numeric cell exactly as SQL produced it."""

        if not 0 <= reference.observation_index < len(observations):
            return None

        result = observations[reference.observation_index].result

        if not 0 <= reference.row_index < len(result.rows):
            return None

        matches = [
            index
            for index, column in enumerate(result.columns)
            if column == reference.column
        ]

        if len(matches) != 1:
            return None

        column_index = matches[0]
        row = result.rows[reference.row_index]

        if column_index >= len(row):
            return None

        value = row[column_index]

        if type(value) not in (int, float, Decimal):
            return None

        return cast(int | float | Decimal, value)


def _decimal_number(value: object, *, name: str) -> Decimal:
    """Convert a supported finite scalar to Decimal without float coercion."""

    if type(value) is int:
        return Decimal(value)

    if type(value) is Decimal:
        if not value.is_finite():
            raise ValueError(f"{name} must be finite.")
        return value

    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite.")
        return Decimal(str(value))

    raise TypeError(f"{name} must be an int, float, or Decimal.")


def _subtract_exact(left: Decimal, right: Decimal) -> Decimal:
    """Fail closed if the active precision cannot represent the difference."""
    with localcontext() as context:
        context.traps[Inexact] = True
        context.traps[InvalidOperation] = True
        context.traps[Overflow] = True
        return left - right


def _derive(operation: ClaimOperation, left: Decimal, right: Decimal) -> Decimal:
    """Divide precisely enough for any display; dividing by zero raises."""
    with localcontext() as context:
        context.prec = _DERIVED_PRECISION
        context.traps[DivisionByZero] = True
        context.traps[InvalidOperation] = True
        if operation is ClaimOperation.RATIO:
            return left / right
        if operation is ClaimOperation.PERCENT:
            return left * 100 / right
        return (left - right) * 100 / right


def _rounds_to(actual: Decimal, expected: Decimal) -> bool:
    """Whether ``expected`` is ``actual`` rounded to ``expected``'s own places.

    It must keep ``MIN_DERIVED_SIGNIFICANT_DIGITS`` significant digits; a
    shorter claim matches only when it is exact.
    """
    _, digits, exponent = expected.as_tuple()
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if places > MAX_ROUNDED_PLACES or len(digits) < MIN_DERIVED_SIGNIFICANT_DIGITS:
        return actual == expected
    try:
        return _round_for_policy(actual, DecimalRoundingPolicy(places)) == expected
    except DecimalException:
        # Too many digits to round at that many places: not a display of it.
        return False


def _round_for_policy(value: Decimal, policy: DecimalRoundingPolicy) -> Decimal:
    """Allow deliberate quantization while keeping caller context unchanged."""
    quantum = Decimal((0, (1,), -policy.decimal_places))
    with localcontext() as context:
        context.traps[Inexact] = False
        context.traps[Rounded] = False
        context.traps[InvalidOperation] = True
        context.traps[Overflow] = True
        return value.quantize(quantum, rounding=policy.rounding_mode)
