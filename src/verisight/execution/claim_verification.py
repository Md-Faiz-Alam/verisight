"""Deterministic verification of numerical claims against query observations."""

import math
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import TypeAlias, cast

from verisight.execution.observations import QueryObservation

NumericValue: TypeAlias = int | float | Decimal


class ClaimOperation(StrEnum):
    """Supported operations for evidence-linked numerical claims."""

    VALUE = "value"
    DIFFERENCE = "difference"


class VerificationStatus(StrEnum):
    """Outcome of deterministic numerical claim verification."""

    SUPPORTED = "supported"
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
            raise ValueError("A difference claim requires right-hand evidence.")

        _decimal_number(self.expected, name="Expected value")

        tolerance = _decimal_number(
            self.absolute_tolerance,
            name="Absolute tolerance",
        )
        if tolerance < 0:
            raise ValueError("Absolute tolerance must not be negative.")


@dataclass(frozen=True, slots=True)
class ClaimVerificationResult:
    """Deterministic outcome with computed value when evidence is usable."""

    status: VerificationStatus
    actual: Decimal | None
    expected: Decimal
    absolute_tolerance: Decimal
    reason: str


class NumericalClaimVerifier:
    """Check numerical claims without generating or executing new queries."""

    def verify(
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
            # DIFFERENCE operation during construction.
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

            try:
                actual = left - right
            except DecimalException:
                return ClaimVerificationResult(
                    status=VerificationStatus.UNVERIFIABLE,
                    actual=None,
                    expected=expected,
                    absolute_tolerance=tolerance,
                    reason="Numerical evidence cannot be combined safely.",
                )

        try:
            difference = abs(actual - expected)
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

        return ClaimVerificationResult(
            status=VerificationStatus.CONTRADICTED,
            actual=actual,
            expected=expected,
            absolute_tolerance=tolerance,
            reason="The numerical evidence contradicts the claimed value.",
        )

    @staticmethod
    def _resolve(
        reference: EvidenceReference,
        observations: tuple[QueryObservation, ...],
    ) -> Decimal | None:
        """Resolve one reference, rejecting missing or ambiguous values."""

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

        try:
            return _decimal_number(value, name="Evidence value")
        except (TypeError, ValueError):
            return None


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
