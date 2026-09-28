"""Custom exception hierarchy for D&D Labs.

Every domain error subclasses :class:`DndLabsError`. ``api/errors.py`` maps
some subclasses to 4xx responses whose body is the exception's message, so
those messages must be client-safe; every other ``DndLabsError`` becomes a
generic 500 and its message is only logged.
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
    """Raised when a requested entity does not exist (or is not owned by the caller's org)."""


class AuthError(DndLabsError):
    """Raised when authentication or key management fails."""


class NotAuthenticatedError(AuthError):
    """Raised when a request carries no valid credential (API key or session token)."""


class InvalidApiKeyError(NotAuthenticatedError):
    """Raised when a request presents a missing, malformed or revoked API key."""


class InvalidCredentialsError(AuthError):
    """Raised when a sign-in presents an unknown email or a wrong password."""


class RateLimitedError(AuthError):
    """Raised when a client exceeds a sign-in or authentication-failure limit (HTTP 429).

    The API answers with a fixed body and ``Retry-After``, never this
    exception's message, so the response does not say which limit (client
    IP, email, or email and IP) refused the request.
    """

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        """Create the error.

        Args:
            message: Detail for server-side logs only.
            retry_after_seconds: Seconds until the refusing limit's window ends.
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
    """Raised when a change conflicts with existing accounts (HTTP 409).

    For example: an account with the email already exists, or the change
    would leave an organization without an admin.
    """


class PipelineError(DndLabsError):
    """Raised when the pipeline orchestrator cannot complete a run."""


class RunInterruptedError(PipelineError):
    """Raised when a run stops early because its worker is shutting down or lost it.

    It is not a failure: after a clean stop the worker returns the run to
    ``pending``; after a lost lease the queue resumes it once the lease expires.
    """


class RunDeletedError(PipelineError):
    """Raised when a run's organization data was deleted while the run executed.

    Nothing is recorded for the run (its row is gone) and whatever it stored
    has been removed; the worker simply moves on.
    """


class ExportError(DndLabsError):
    """Raised when a dataset cannot be exported."""


class EnrichmentError(DndLabsError):
    """Raised when the enrichment client's own machinery fails (not a single bad record)."""
