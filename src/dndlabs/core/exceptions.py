"""Custom exception hierarchy for D&D Labs."""


class DndLabsError(Exception):
    """Base class for all D&D Labs errors."""


class ConfigurationError(DndLabsError):
    """Raised when configuration is missing or invalid."""


class IngestionError(DndLabsError):
    """Raised when a connector cannot fetch or parse its source."""


class ConnectorNotFoundError(IngestionError):
    """Raised when no connector is registered for a requested source."""


class ValidationError(DndLabsError):
    """Raised when the validation machinery itself fails (not for bad records)."""


class StorageError(DndLabsError):
    """Raised when a persistence operation fails."""


class NotFoundError(StorageError):
    """Raised when a requested entity does not exist (or is not owned by the caller's org)."""


class AuthError(DndLabsError):
    """Raised when authentication or key management fails."""


class InvalidApiKeyError(AuthError):
    """Raised when a request presents a missing, malformed or revoked API key."""


class PipelineError(DndLabsError):
    """Raised when the pipeline orchestrator cannot complete a run."""


class ExportError(DndLabsError):
    """Raised when a dataset cannot be exported."""


class EnrichmentError(DndLabsError):
    """Raised when the enrichment client's own machinery fails (not a single bad record)."""
