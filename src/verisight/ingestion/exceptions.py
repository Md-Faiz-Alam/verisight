"""Exceptions raised by the VeriSight ingestion subsystem."""

from verisight.exceptions import VeriSightError


class IngestionError(VeriSightError):
    """Base exception for expected ingestion failures."""


class UnsupportedFileTypeError(IngestionError):
    """Raised when VeriSight does not support the input file type."""


class FileValidationError(IngestionError):
    """Raised when an input file fails ingestion validation."""


class DataLoadError(IngestionError):
    """Raised when a validated file cannot be loaded successfully."""
