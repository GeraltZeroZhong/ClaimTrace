"""Public exception hierarchy."""


class ClaimTraceError(Exception):
    """Base exception for ClaimTrace failures."""


class ValidationError(ClaimTraceError):
    """Raised when validation blocks an operation."""


class SecurityError(ClaimTraceError):
    """Raised when path, archive or privacy checks block an operation."""


class SchemaVersionError(ClaimTraceError):
    """Raised when a CAL schema version is unsupported."""


class PackageError(ClaimTraceError):
    """Raised when a package directory is malformed."""
