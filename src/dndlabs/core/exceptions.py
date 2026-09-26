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


class NotAuthenticatedError(AuthError):
    """Raised when a request carries no valid credential (API key or session token)."""


class InvalidApiKeyError(NotAuthenticatedError):
    """Raised when a request presents a missing, malformed or revoked API key."""


class InvalidCredentialsError(AuthError):
    """Raised when a sign-in presents an unknown email or a wrong password."""


class AccountLockedError(AuthError):
    """Raised when sign-in is refused because of too many recent failures."""

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        """Create the error.

        Args:
            message: Client-safe message.
            retry_after_seconds: Seconds until sign-in may be retried.
        """
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class InvitationInvalidError(AuthError):
    """Raised when an invitation token is unknown, expired or already used."""


class PasswordPolicyError(AuthError):
    """Raised when a new password does not meet the password policy."""


class ForbiddenError(AuthError):
    """Raised when an authenticated caller lacks the role or credential type required."""


class ConflictError(AuthError):
    """Raised when an account for the requested email already exists."""


class PipelineError(DndLabsError):
    """Raised when the pipeline orchestrator cannot complete a run."""


class ExportError(DndLabsError):
    """Raised when a dataset cannot be exported."""


class EnrichmentError(DndLabsError):
    """Raised when the enrichment client's own machinery fails (not a single bad record)."""
