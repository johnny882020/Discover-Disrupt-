"""HTTP contract of the sign-in, session and invitation endpoints."""

import uuid
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient

from dndlabs.api.app import create_app
from dndlabs.api.dependencies import ApiServices
from dndlabs.auth.service import AuthPolicy, AuthService
from dndlabs.core.schemas import ApiKeyCreated, Organization

ADMIN = {"X-Admin-Secret": "test-admin-secret-0123456789"}
PASSWORD = "correct horse battery"


def _bootstrap(client: TestClient, email: str = "ada@acme.com") -> tuple[dict, str]:  # type: ignore[type-arg]
    """Create an org via the admin API, invite its admin, accept; return (session, org_id)."""
    org = client.post("/api/v1/admin/orgs", json={"name": "Acme"}, headers=ADMIN).json()
    invitation = client.post(
        f"/api/v1/admin/orgs/{org['org_id']}/invitations", json={"email": email}, headers=ADMIN
    )
    assert invitation.status_code == 201
    token = invitation.json()["token"]
    accepted = client.post(
        "/api/v1/auth/invitations/accept", json={"token": token, "password": PASSWORD}
    )
    assert accepted.status_code == 201
    return accepted.json(), org["org_id"]


def _bearer(session: dict) -> dict[str, str]:  # type: ignore[type-arg]
    return {"Authorization": f"Bearer {session['token']}"}


def test_admin_invitation_requires_secret_and_existing_org(client: TestClient) -> None:
    path = f"/api/v1/admin/orgs/{uuid.uuid4()}/invitations"
    assert client.post(path, json={"email": "a@b.co"}).status_code == 401
    assert client.post(path, json={"email": "a@b.co"}, headers=ADMIN).status_code == 404


def test_admin_invitation_rejects_an_invalid_email(client: TestClient) -> None:
    org = client.post("/api/v1/admin/orgs", json={"name": "Acme"}, headers=ADMIN).json()
    response = client.post(
        f"/api/v1/admin/orgs/{org['org_id']}/invitations",
        json={"email": "not-an-email"},
        headers=ADMIN,
    )
    assert response.status_code == 422


def test_invitation_preview_accept_and_whoami(client: TestClient) -> None:
    org = client.post("/api/v1/admin/orgs", json={"name": "Acme"}, headers=ADMIN).json()
    invitation = client.post(
        f"/api/v1/admin/orgs/{org['org_id']}/invitations",
        json={"email": "Ada@Acme.com"},
        headers=ADMIN,
    ).json()
    assert invitation["accept_url"].endswith(f"/invite#token={invitation['token']}")

    preview = client.post("/api/v1/auth/invitations/preview", json={"token": invitation["token"]})
    assert preview.status_code == 200
    assert preview.json()["email"] == "ada@acme.com"
    assert preview.json()["org_name"] == "Acme"
    assert preview.json()["role"] == "admin"

    session = client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": invitation["token"], "password": PASSWORD},
    ).json()
    assert session["token_type"] == "bearer"
    whoami = client.get("/api/v1/auth/whoami", headers=_bearer(session)).json()
    assert whoami["principal"] == "user"
    assert whoami["role"] == "admin"
    assert whoami["email"] == "ada@acme.com"
    assert whoami["org_id"] == org["org_id"]


def test_invalid_invitation_and_weak_password(client: TestClient) -> None:
    bad = client.post(
        "/api/v1/auth/invitations/accept", json={"token": "ddl_inv_nope", "password": PASSWORD}
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "invitation is invalid, expired or already used"
    assert client.post("/api/v1/auth/invitations/preview", json={"token": "x"}).status_code == 400

    org = client.post("/api/v1/admin/orgs", json={"name": "Acme"}, headers=ADMIN).json()
    token = client.post(
        f"/api/v1/admin/orgs/{org['org_id']}/invitations", json={"email": "a@b.co"}, headers=ADMIN
    ).json()["token"]
    weak = client.post(
        "/api/v1/auth/invitations/accept", json={"token": token, "password": "short"}
    )
    assert weak.status_code == 422
    assert "at least 12" in weak.json()["detail"]


def test_login_logout(client: TestClient) -> None:
    _bootstrap(client)
    response = client.post(
        "/api/v1/auth/login", json={"email": "ADA@acme.com", "password": PASSWORD}
    )
    assert response.status_code == 200
    session = response.json()
    assert client.get("/api/v1/datasets", headers=_bearer(session)).status_code == 200

    assert client.post("/api/v1/auth/logout", headers=_bearer(session)).status_code == 204
    after = client.get("/api/v1/datasets", headers=_bearer(session))
    assert after.status_code == 401
    assert after.headers["WWW-Authenticate"] == "Bearer"


def test_failed_logins_are_generic_then_rate_limited_alike_for_unknown_emails(
    client: TestClient,
) -> None:
    _bootstrap(client)
    responses: dict[str, list[tuple[int, object, bool]]] = {}
    retry_after: list[int] = []
    for email in ("ada@acme.com", "nobody@acme.com"):
        responses[email] = []
        for password in ["wrong password"] * 5 + [PASSWORD]:
            r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
            responses[email].append((r.status_code, r.json(), "Retry-After" in r.headers))
            if r.status_code == 429:
                retry_after.append(int(r.headers["Retry-After"]))
    # Same status codes, bodies and headers whether or not the account exists.
    assert responses["ada@acme.com"] == responses["nobody@acme.com"]
    known = responses["ada@acme.com"]
    assert known[:5] == [(401, {"detail": "invalid email or password"}, False)] * 5
    # Even the right password is refused.
    assert known[5] == (429, {"detail": "too many attempts; try again later"}, True)
    assert len(retry_after) == 2 and all(0 < seconds <= 900 for seconds in retry_after)


def test_sign_in_limits_are_per_client_ip(services: ApiServices) -> None:
    # One app, two client addresses; no run worker (one app lifespan per client).
    app = create_app(replace(services, worker=None))
    with (
        TestClient(app, client=("203.0.113.5", 1)) as attacker,
        TestClient(app, client=("198.51.100.9", 1)) as owner,
    ):
        _bootstrap(owner)
        for _ in range(6):
            refused = attacker.post(
                "/api/v1/auth/login", json={"email": "ada@acme.com", "password": "guess"}
            )
        assert refused.status_code == 429
        # The owner, on another IP, is not locked out by the attacker.
        ok = owner.post("/api/v1/auth/login", json={"email": "ada@acme.com", "password": PASSWORD})
        assert ok.status_code == 200


def test_failed_key_and_session_auth_get_429_with_retry_after(services: ApiServices) -> None:
    repos = services.repositories
    limited = replace(
        services, auth=AuthService(repos, AuthPolicy(auth_failure_limit_per_ip=2)), worker=None
    )
    app = create_app(limited)
    org = repos.organizations.create(Organization(name="Acme"))
    key = limited.auth.issue_key(org)
    wrong = {"X-API-Key": key.raw_key[:-4] + "xxxx"}
    with (
        TestClient(app, client=("203.0.113.5", 1)) as attacker,
        TestClient(app, client=("198.51.100.9", 1)) as other,
    ):
        assert attacker.get("/api/v1/datasets", headers=wrong).status_code == 401
        bad_session = {"Authorization": "Bearer ddl_sess_nope"}
        assert attacker.get("/api/v1/datasets", headers=bad_session).status_code == 401
        with patch("dndlabs.auth.service.verify_key") as verify:
            refused = attacker.get("/api/v1/datasets", headers=wrong)
        verify.assert_not_called()  # refused before the Argon2 verification
        assert refused.status_code == 429
        assert refused.json() == {"detail": "too many attempts; try again later"}
        assert 0 < int(refused.headers["Retry-After"]) <= 900
        valid = {"X-API-Key": key.raw_key}
        assert other.get("/api/v1/datasets", headers=valid).status_code == 200


def test_change_password(client: TestClient) -> None:
    session, _ = _bootstrap(client)
    new = "a different long passphrase"
    wrong = client.post(
        "/api/v1/auth/password",
        json={"current_password": "nope", "new_password": new},
        headers=_bearer(session),
    )
    assert wrong.status_code == 403
    ok = client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": new},
        headers=_bearer(session),
    )
    assert ok.status_code == 204
    login = client.post("/api/v1/auth/login", json={"email": "ada@acme.com", "password": new})
    assert login.status_code == 200


def test_admin_user_invites_member_who_cannot_invite(client: TestClient) -> None:
    session, _ = _bootstrap(client)
    invite = client.post(
        "/api/v1/auth/invitations", json={"email": "bob@acme.com"}, headers=_bearer(session)
    )
    assert invite.status_code == 201
    assert invite.json()["role"] == "member"
    member = client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": invite.json()["token"], "password": PASSWORD},
    ).json()
    forbidden = client.post(
        "/api/v1/auth/invitations", json={"email": "eve@acme.com"}, headers=_bearer(member)
    )
    assert forbidden.status_code == 403
    duplicate = client.post(
        "/api/v1/auth/invitations", json={"email": "bob@acme.com"}, headers=_bearer(session)
    )
    assert duplicate.status_code == 409


def test_only_admins_can_delete_org_data(client: TestClient) -> None:
    session, _ = _bootstrap(client)
    invite = client.post(
        "/api/v1/auth/invitations", json={"email": "bob@acme.com"}, headers=_bearer(session)
    ).json()
    member = client.post(
        "/api/v1/auth/invitations/accept", json={"token": invite["token"], "password": PASSWORD}
    ).json()
    denied = client.delete("/api/v1/orgs/me/data", headers=_bearer(member))
    assert denied.status_code == 403
    assert client.delete("/api/v1/orgs/me/data", headers=_bearer(session)).status_code == 204


def test_session_cannot_revoke_keys_and_key_cannot_log_out(
    client: TestClient, org_key: ApiKeyCreated
) -> None:
    session, _ = _bootstrap(client)
    assert client.post("/api/v1/auth/keys/revoke", headers=_bearer(session)).status_code == 403
    key_headers = {"X-API-Key": org_key.raw_key}
    assert client.post("/api/v1/auth/logout", headers=key_headers).status_code == 403


def test_session_principal_is_tenant_isolated(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    run = client.post(
        "/api/v1/pipelines/run", json={"source": "csv", "csv_path": "x.csv"}, headers=auth_headers
    ).json()
    session, _ = _bootstrap(client)  # a different org
    other = client.get(f"/api/v1/pipelines/runs/{run['id']}", headers=_bearer(session))
    assert other.status_code == 404


def test_malformed_bearer_is_rejected(client: TestClient) -> None:
    for header in ("Bearer ddl_sess_unknown", "Bearer ddl_live_x", "Basic abc", "Bearer"):
        response = client.get("/api/v1/datasets", headers={"Authorization": header})
        assert response.status_code == 401, header


def test_openapi_declares_both_auth_schemes(client: TestClient) -> None:
    schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert schemes["APIKeyHeader"]["name"] == "X-API-Key"
    assert schemes["HTTPBearer"]["scheme"] == "bearer"


def _invite_member(client: TestClient, admin: dict, email: str) -> dict:  # type: ignore[type-arg]
    token = client.post(
        "/api/v1/auth/invitations", json={"email": email}, headers=_bearer(admin)
    ).json()["token"]
    return client.post(
        "/api/v1/auth/invitations/accept", json={"token": token, "password": PASSWORD}
    ).json()


def test_member_management_routes(client: TestClient) -> None:
    admin, _ = _bootstrap(client)
    bob = _invite_member(client, admin, "bob@acme.com")
    bob_id = bob["user"]["id"]

    members = client.get("/api/v1/auth/members", headers=_bearer(admin)).json()
    assert [m["email"] for m in members] == ["ada@acme.com", "bob@acme.com"]
    assert client.get("/api/v1/auth/members", headers=_bearer(bob)).status_code == 403

    promoted = client.patch(
        f"/api/v1/auth/members/{bob_id}", json={"role": "admin"}, headers=_bearer(admin)
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    assert (
        client.delete(f"/api/v1/auth/members/{bob_id}", headers=_bearer(admin)).status_code == 204
    )
    assert client.get("/api/v1/auth/whoami", headers=_bearer(bob)).status_code == 401
    assert (
        client.delete(f"/api/v1/auth/members/{bob_id}", headers=_bearer(admin)).status_code == 404
    )


def test_last_admin_and_self_removal_are_refused(client: TestClient) -> None:
    admin, _ = _bootstrap(client)
    admin_id = admin["user"]["id"]
    demote = client.patch(
        f"/api/v1/auth/members/{admin_id}", json={"role": "member"}, headers=_bearer(admin)
    )
    assert demote.status_code == 409
    assert demote.json()["detail"] == "an organization must keep at least one admin"
    remove = client.delete(f"/api/v1/auth/members/{admin_id}", headers=_bearer(admin))
    assert remove.status_code == 403


def test_pending_invitations_routes(client: TestClient) -> None:
    admin, _ = _bootstrap(client)
    created = client.post(
        "/api/v1/auth/invitations", json={"email": "cleo@acme.com"}, headers=_bearer(admin)
    ).json()
    listed = client.get("/api/v1/auth/invitations", headers=_bearer(admin)).json()
    assert [(i["id"], i["email"], i["purpose"]) for i in listed] == [
        (created["id"], "cleo@acme.com", "join")
    ]
    assert "token" not in listed[0]

    path = f"/api/v1/auth/invitations/{created['id']}"
    assert client.delete(path, headers=_bearer(admin)).status_code == 204
    assert client.get("/api/v1/auth/invitations", headers=_bearer(admin)).json() == []
    accept = client.post(
        "/api/v1/auth/invitations/accept", json={"token": created["token"], "password": PASSWORD}
    )
    assert accept.status_code == 400


def test_password_reset_routes(client: TestClient) -> None:
    admin, _ = _bootstrap(client)
    bob = _invite_member(client, admin, "bob@acme.com")
    reset = client.post(
        f"/api/v1/auth/members/{bob['user']['id']}/password-reset", headers=_bearer(admin)
    )
    assert reset.status_code == 201
    body = reset.json()
    assert body["reset_url"].endswith(f"/reset#token={body['token']}")

    preview = client.post("/api/v1/auth/password-reset/preview", json={"token": body["token"]})
    assert preview.json()["email"] == "bob@acme.com"
    assert preview.json()["org_name"] == "Acme"

    new_password = "a brand new passphrase"
    done = client.post(
        "/api/v1/auth/password-reset/accept",
        json={"token": body["token"], "password": new_password},
    )
    assert done.status_code == 200
    assert client.get("/api/v1/auth/whoami", headers=_bearer(bob)).status_code == 401
    login = client.post(
        "/api/v1/auth/login", json={"email": "bob@acme.com", "password": new_password}
    )
    assert login.status_code == 200
    reused = client.post(
        "/api/v1/auth/password-reset/accept",
        json={"token": body["token"], "password": new_password},
    )
    assert reused.status_code == 400


def test_operator_password_reset(client: TestClient) -> None:
    _, org_id = _bootstrap(client)
    reset = client.post(
        f"/api/v1/admin/orgs/{org_id}/password-resets",
        json={"email": "ada@acme.com"},
        headers=ADMIN,
    )
    assert reset.status_code == 201
    unknown = client.post(
        f"/api/v1/admin/orgs/{org_id}/password-resets", json={"email": "x@acme.com"}, headers=ADMIN
    )
    assert unknown.status_code == 404
    no_secret = client.post(
        f"/api/v1/admin/orgs/{org_id}/password-resets", json={"email": "ada@acme.com"}
    )
    assert no_secret.status_code == 401
