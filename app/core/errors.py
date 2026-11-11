"""Project exception hierarchy: callers catch KQLError to fail in a controlled way."""


class KQLError(Exception):
    """Base class for all expected, reportable failures."""


class DataValidationError(KQLError):
    """Market data is missing, malformed or not usable for the requested window."""


class ModelUnavailableError(KQLError):
    """Model code, weights or runtime (torch / device) are not available."""


class ForecastError(KQLError):
    """Inference ran but failed or returned something outside the contract."""


class OverwriteRefusedError(KQLError):
    """An existing result would have been overwritten without permission."""
