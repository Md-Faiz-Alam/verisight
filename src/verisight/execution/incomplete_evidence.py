"""Signals for investigations with insufficient visible evidence."""

from verisight.execution.exceptions import InvestigationError


class IncompleteEvidenceError(InvestigationError):
    """Evidence cannot safely support a completed investigation."""
