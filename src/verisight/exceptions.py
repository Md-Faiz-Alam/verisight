"""Application-specific exceptions for VeriSight."""


class VeriSightError(Exception):
    """Base exception for all expected VeriSight application errors."""


class ConfigurationError(VeriSightError):
    """Raised when application configuration is invalid or unusable."""
