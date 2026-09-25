import uuid

import pytest
from tests.fakes import FakeApiKeys, FakeOrganizations

from dndlabs.auth.service import AuthService
from dndlabs.core.exceptions import InvalidApiKeyError
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
    from dndlabs.core.exceptions import NotFoundError

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
