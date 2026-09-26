"""HTTP contract of the sign-in, session and invitation endpoints."""

import uuid

from fastapi.testclient import TestClient

from dndlabs.core.schemas import ApiKeyCreated

ADMIN = {"X-Admin-Secret": "test-admin-secret"}
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


def test_failed_logins_are_generic_then_locked(client: TestClient) -> None:
    _bootstrap(client)
    unknown = client.post("/api/v1/auth/login", json={"email": "x@y.co", "password": "whatever"})
    assert unknown.status_code == 401
    for _ in range(5):
        wrong = client.post(
            "/api/v1/auth/login", json={"email": "ada@acme.com", "password": "wrong password"}
        )
        assert wrong.status_code == 401
        assert wrong.json() == unknown.json() == {"detail": "invalid email or password"}
    locked = client.post("/api/v1/auth/login", json={"email": "ada@acme.com", "password": PASSWORD})
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0


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
