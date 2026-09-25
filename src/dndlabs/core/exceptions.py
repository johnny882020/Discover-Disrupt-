"""Custom exception hierarchy for D&D Labs.

Every error raised deliberately by application code derives from
:class:`DndLabsError`, so delivery layers can map them to exit codes or HTTP
responses in one place.
"""


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
    """Raised when a requested entity does not exist."""


class PipelineError(DndLabsError):
    """Raised when the pipeline orchestrator cannot complete a run."""


class ExportError(DndLabsError):
    """Raised when a dataset cannot be exported."""
