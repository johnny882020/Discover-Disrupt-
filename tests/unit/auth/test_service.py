import uuid

import pytest
from tests.fakes import FakeApiKeys, FakeOrganizations

from dndlabs.auth.service import FREE_TIER_KEY_ID, FREE_TIER_ORG_ID, AuthService
from dndlabs.core.exceptions import InvalidApiKeyError, NotFoundError
from dndlabs.core.schemas import Organization


@pytest.fixture
def service() -> AuthService:
    return AuthService(FakeOrganizations(), FakeApiKeys())


def _make_org(service: AuthService) -> Organization:
    orgs: FakeOrganizations = service._organizations  # type: ignore[attr-defined]
    org = Organization(name="Acme")
    orgs.create(org)
    return org


def test_issue_and_resolve(service: AuthService) -> None:
    org = _make_org(service)
    created = service.issue_key(org)
    ctx = service.resolve(created.raw_key)
    assert ctx.org_id == org.id
    assert ctx.org_name == "Acme"


def test_resolve_missing_key(service: AuthService) -> None:
    with pytest.raises(InvalidApiKeyError):
        service.resolve("")


def test_resolve_unknown_key(service: AuthService) -> None:
    with pytest.raises(InvalidApiKeyError):
        service.resolve("ddl_live_doesnotexist")


def test_resolve_wrong_secret_same_prefix_shape(service: AuthService) -> None:
    org = _make_org(service)
    created = service.issue_key(org)
    tampered = created.raw_key[:-4] + "xxxx"
    with pytest.raises(InvalidApiKeyError):
        service.resolve(tampered)


def test_revoked_key_is_rejected(service: AuthService) -> None:
    org = _make_org(service)
    created = service.issue_key(org)
    service.revoke_key(org.id, created.id)
    with pytest.raises(InvalidApiKeyError):
        service.resolve(created.raw_key)


def test_revoke_wrong_org_raises_not_found(service: AuthService) -> None:
    org = _make_org(service)
    created = service.issue_key(org)
    with pytest.raises(NotFoundError):
        service.revoke_key(uuid.uuid4(), created.id)


def test_two_orgs_get_distinct_keys(service: AuthService) -> None:
    org_a = _make_org(service)
    org_b_orgs: FakeOrganizations = service._organizations  # type: ignore[attr-defined]
    org_b = Organization(name="OtherCo")
    org_b_orgs.create(org_b)
    key_a = service.issue_key(org_a)
    key_b = service.issue_key(org_b)
    assert service.resolve(key_a.raw_key).org_id == org_a.id
    assert service.resolve(key_b.raw_key).org_id == org_b.id


def test_shared_password_disabled_by_default_rejects_it_as_a_normal_key() -> None:
    service = AuthService(FakeOrganizations(), FakeApiKeys())
    with pytest.raises(InvalidApiKeyError):
        service.resolve("freetier2026")


def test_shared_password_resolves_to_fixed_free_tier_identity() -> None:
    service = AuthService(FakeOrganizations(), FakeApiKeys(), shared_password="freetier2026")
    ctx = service.resolve("freetier2026")
    assert ctx.org_id == FREE_TIER_ORG_ID
    assert ctx.api_key_id == FREE_TIER_KEY_ID


def test_shared_password_wrong_value_is_rejected() -> None:
    service = AuthService(FakeOrganizations(), FakeApiKeys(), shared_password="freetier2026")
    with pytest.raises(InvalidApiKeyError):
        service.resolve("not-the-shared-password")


def test_shared_password_empty_string_disables_bypass() -> None:
    service = AuthService(FakeOrganizations(), FakeApiKeys(), shared_password="")
    with pytest.raises(InvalidApiKeyError):
        service.resolve("freetier2026")


def test_shared_password_provisions_org_row_for_downstream_fk_writes() -> None:
    organizations = FakeOrganizations()
    service = AuthService(organizations, FakeApiKeys(), shared_password="freetier2026")
    service.resolve("freetier2026")
    org = organizations.get(FREE_TIER_ORG_ID)
    assert org.name == "Free Tier (shared, insecure)"
    # A second resolve must not fail or duplicate the row.
    service.resolve("freetier2026")
    assert organizations.get(FREE_TIER_ORG_ID).id == org.id


def test_shared_password_still_authenticates_when_storage_is_unavailable() -> None:
    class BrokenOrganizations:
        def get(self, org_id: uuid.UUID) -> Organization:
            raise RuntimeError('relation "organizations" does not exist')

        def create(self, org: Organization) -> Organization:
            raise RuntimeError('relation "organizations" does not exist')

    service = AuthService(BrokenOrganizations(), FakeApiKeys(), shared_password="freetier2026")
    ctx = service.resolve("freetier2026")
    assert ctx.org_id == FREE_TIER_ORG_ID


def test_shared_password_authenticates_when_org_row_missing_and_create_also_fails() -> None:
    class UncreatableOrganizations:
        def get(self, org_id: uuid.UUID) -> Organization:
            raise NotFoundError(f"organization {org_id} not found")

        def create(self, org: Organization) -> Organization:
            raise RuntimeError("insert failed")

    service = AuthService(UncreatableOrganizations(), FakeApiKeys(), shared_password="freetier2026")
    ctx = service.resolve("freetier2026")
    assert ctx.org_id == FREE_TIER_ORG_ID


def test_shared_password_key_cannot_be_revoked(service: AuthService) -> None:
    with pytest.raises(InvalidApiKeyError):
        service.revoke_key(FREE_TIER_ORG_ID, FREE_TIER_KEY_ID)
