"""Issuing, verifying and revoking API keys, and resolving auth context."""

import uuid

from dndlabs.auth.models import generate_key, hash_key, key_prefix, verify_key
from dndlabs.core.exceptions import InvalidApiKeyError, NotFoundError
from dndlabs.core.logging import get_logger
from dndlabs.core.protocols import ApiKeyRepository, OrganizationRepository
from dndlabs.core.schemas import ApiKeyCreated, Organization, OrgContext

logger = get_logger(__name__)

# Fixed identity for the free-tier shared-password path (see AuthService.resolve).
# Deterministic so logs/tests are stable across restarts; never persisted.
FREE_TIER_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
FREE_TIER_KEY_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
FREE_TIER_ORG_NAME = "Free Tier (shared, insecure)"


class AuthService:
    """Issues and verifies API keys against the auth repositories."""

    def __init__(
        self,
        organizations: OrganizationRepository,
        api_keys: ApiKeyRepository,
        shared_password: str | None = None,
    ) -> None:
        """Create the service.

        Args:
            organizations: Organization repository (used to resolve org name on auth).
            api_keys: Key repository.
            shared_password: Optional temporary bypass credential (see
                ``resolve``). ``None`` or empty disables it.
        """
        self._organizations = organizations
        self._api_keys = api_keys
        self._shared_password = shared_password or None

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
        if self._shared_password is not None and raw_key == self._shared_password:
            # Temporary bypass: every caller using this password shares one
            # fixed, insecure identity. Authentication itself never depends
            # on storage; provisioning the org row is best-effort so
            # FK-scoped writes (runs, datasets) work once storage is healthy.
            self._ensure_free_tier_org()
            return OrgContext(
                org_id=FREE_TIER_ORG_ID, org_name=FREE_TIER_ORG_NAME, api_key_id=FREE_TIER_KEY_ID
            )
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
            InvalidApiKeyError: If ``key_id`` is the shared free-tier identity
                (see ``resolve``) — there is no per-org key to revoke.
            NotFoundError: If the key does not exist for this org.
        """
        if key_id == FREE_TIER_KEY_ID:
            raise InvalidApiKeyError("the shared free-tier credential cannot be revoked")
        self._api_keys.revoke(org_id, key_id)

    def _ensure_free_tier_org(self) -> None:
        """Best-effort: persist the free-tier org row so FK-scoped writes work.

        Swallows every error. The shared password must authenticate even
        when storage is unreachable or unmigrated; any write that actually
        needs the org row will fail on its own terms in that case.
        """
        try:
            self._organizations.get(FREE_TIER_ORG_ID)
        except NotFoundError:
            try:
                self._organizations.create(
                    Organization(id=FREE_TIER_ORG_ID, name=FREE_TIER_ORG_NAME)
                )
            except Exception:  # noqa: BLE001 - best-effort provisioning, see docstring
                logger.warning("free_tier_org_create_failed", exc_info=True)
        except Exception:  # noqa: BLE001 - storage unavailable; auth still succeeds
            logger.warning("free_tier_org_lookup_failed", exc_info=True)
