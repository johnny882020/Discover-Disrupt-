"""Issuing, verifying and revoking API keys, and resolving auth context."""

import uuid

from dndlabs.auth.models import generate_key, hash_key, key_prefix, verify_key
from dndlabs.core.exceptions import InvalidApiKeyError
from dndlabs.core.protocols import ApiKeyRepository, OrganizationRepository
from dndlabs.core.schemas import ApiKeyCreated, Organization, OrgContext


class AuthService:
    """Issues and verifies API keys against the auth repositories."""

    def __init__(self, organizations: OrganizationRepository, api_keys: ApiKeyRepository) -> None:
        """Create the service.

        Args:
            organizations: Organization repository (used to resolve org name on auth).
            api_keys: Key repository.
        """
        self._organizations = organizations
        self._api_keys = api_keys

    def issue_key(self, org: Organization) -> ApiKeyCreated:
        """Issue a new API key for an organization.

        Args:
            org: The organization to issue a key for.

        Returns:
            The one-time reveal of the new key.
        """
        raw_key, prefix = generate_key()
        record = self._api_keys.create(org.id, prefix, hash_key(raw_key))
        return ApiKeyCreated(id=record.id, org_id=org.id, raw_key=raw_key, prefix=prefix)

    def resolve(self, raw_key: str) -> OrgContext:
        """Authenticate a raw API key and resolve its org context.

        Args:
            raw_key: The key presented in the ``X-API-Key`` header.

        Returns:
            The authenticated context.

        Raises:
            InvalidApiKeyError: If the key is missing, unknown, malformed or revoked.
        """
        if not raw_key:
            raise InvalidApiKeyError("missing API key")
        prefix = key_prefix(raw_key)
        record = self._api_keys.get_by_prefix(prefix)
        get_hash = getattr(self._api_keys, "get_hash", None)
        stored_hash = get_hash(prefix) if get_hash and record else None
        if record is None or stored_hash is None or not verify_key(raw_key, stored_hash):
            raise InvalidApiKeyError("invalid API key")
        if record.revoked_at is not None:
            raise InvalidApiKeyError("API key has been revoked")
        self._api_keys.touch_last_used(record.id)
        org = self._organizations.get(record.org_id)
        return OrgContext(org_id=org.id, org_name=org.name, api_key_id=record.id)

    def revoke_key(self, org_id: uuid.UUID, key_id: uuid.UUID) -> None:
        """Revoke a key belonging to an organization.

        Args:
            org_id: Owning organization.
            key_id: Key to revoke.

        Raises:
            NotFoundError: If the key does not exist for this org.
        """
        self._api_keys.revoke(org_id, key_id)
