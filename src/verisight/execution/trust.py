"""How far one answer can be trusted, and which named checks decided that."""

from dataclasses import dataclass
from enum import StrEnum


class TrustLevel(StrEnum):
    """What the checks together support, from strongest to weakest."""

    COMPUTED = "computed"
    VERIFIED = "verified"
    NUMBER_MATCHED = "number_matched"
    NEEDS_REVIEW = "needs_review"
    NOT_VERIFIED = "not_verified"


class CheckStatus(StrEnum):
    """Result of one named check."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_ASSESSED = "not_assessed"


@dataclass(frozen=True, slots=True)
class TrustCheck:
    """One step of an answer's evidence trail."""

    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True, slots=True)
class TrustReport:
    """The level an answer earned and every check behind it."""

    level: TrustLevel
    checks: tuple[TrustCheck, ...]
