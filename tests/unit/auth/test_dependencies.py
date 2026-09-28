from starlette.requests import Request

from dndlabs.auth.dependencies import client_ip


def _request(client: tuple[str, int] | None, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({"type": "http", "client": client, "headers": headers})


def test_client_ip_is_the_connection_peer_not_a_forwarded_header() -> None:
    # X-Forwarded-For is client-controlled; only uvicorn's proxy-header
    # handling (for the trusted proxy) may rewrite the peer address.
    forged = [(b"x-forwarded-for", b"1.2.3.4")]
    assert client_ip(_request(("203.0.113.5", 4321), forged)) == "203.0.113.5"


def test_a_request_without_a_client_address_shares_one_bucket() -> None:
    assert client_ip(_request(None, [])) == "unknown"
