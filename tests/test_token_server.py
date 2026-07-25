"""Token-bridge access control.

The bridge used to answer every request with ``Access-Control-Allow-Origin: *``,
so any website the user visited could overwrite the stored Suno session token.
These tests are the regression net for the origin allowlist, the pairing secret,
and JWT shape validation.
"""

import json
import urllib.error
import urllib.request

import pytest

from services.token_server import (
    AUTH_HEADER,
    TokenServer,
    is_extension_origin,
    looks_like_jwt,
)

# A structurally valid but meaningless JWT.
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl"

SECRET = "test-pairing-secret-abcdefghijklmnop"
PORT = 38976  # Not the production port, so a running app does not interfere.


class TestOriginPredicate:
    @pytest.mark.parametrize(
        "origin",
        [
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
            "moz-extension://1b2c3d4e-5f60-7182-93a4-b5c6d7e8f900",
            "safari-web-extension://something",
            None,   # non-browser client, e.g. curl
            "",
            "null",
        ],
    )
    def test_allows_extension_and_headless_origins(self, origin):
        assert is_extension_origin(origin)

    @pytest.mark.parametrize(
        "origin",
        [
            "https://evil.test",
            "http://localhost:3000",
            "https://suno.com",
            "https://chrome-extension.evil.test",
            "chrome-extension://abc evil",
        ],
    )
    def test_rejects_web_page_origins(self, origin):
        assert not is_extension_origin(origin)


class TestJwtShape:
    @pytest.mark.parametrize("token", [FAKE_JWT, "a.b.c", "a.b."])
    def test_accepts_jwt_shaped_strings(self, token):
        assert looks_like_jwt(token)

    @pytest.mark.parametrize(
        "token",
        ["", "not-a-jwt", "only.two", "a.b.c.d", "has spaces.b.c", "x" * 9000],
    )
    def test_rejects_other_strings(self, token):
        assert not looks_like_jwt(token)


@pytest.fixture
def server():
    received = []
    srv = TokenServer(port=PORT, pairing_secret=SECRET)
    srv.on_token(received.append)
    srv.start()
    if not srv.is_running:
        pytest.skip(f"could not bind test port {PORT}")
    srv.received = received
    try:
        yield srv
    finally:
        srv.stop()


def _request(path, method="GET", body=None, headers=None):
    url = f"http://127.0.0.1:{PORT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


class TestAccessControl:
    def test_web_origin_is_forbidden(self, server):
        """The core vulnerability: a website pushing a token."""
        status, _ = _request(
            "/token",
            method="POST",
            body={"token": FAKE_JWT},
            headers={"Origin": "https://evil.test", AUTH_HEADER: SECRET},
        )
        assert status == 403
        assert server.received == []
        assert server.current_token is None

    def test_missing_secret_is_unauthorized(self, server):
        status, _ = _request("/token", method="POST", body={"token": FAKE_JWT})
        assert status == 401
        assert server.received == []

    def test_wrong_secret_is_unauthorized(self, server):
        status, _ = _request(
            "/token",
            method="POST",
            body={"token": FAKE_JWT},
            headers={AUTH_HEADER: "wrong-secret"},
        )
        assert status == 401
        assert server.received == []

    def test_status_also_requires_pairing(self, server):
        assert _request("/status")[0] == 401
        assert _request("/status", headers={AUTH_HEADER: SECRET})[0] == 200

    def test_valid_extension_request_is_accepted(self, server):
        status, payload = _request(
            "/token",
            method="POST",
            body={"token": FAKE_JWT},
            headers={
                "Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
                AUTH_HEADER: SECRET,
            },
        )
        assert status == 200
        assert payload == {"success": True}
        assert server.received == [FAKE_JWT]
        assert server.current_token == FAKE_JWT

    def test_malformed_token_is_rejected(self, server):
        status, _ = _request(
            "/token",
            method="POST",
            body={"token": "definitely-not-a-jwt"},
            headers={AUTH_HEADER: SECRET},
        )
        assert status == 400
        assert server.received == []

    def test_unchanged_token_does_not_refire_callbacks(self, server):
        headers = {AUTH_HEADER: SECRET}
        _request("/token", method="POST", body={"token": FAKE_JWT}, headers=headers)
        _request("/token", method="POST", body={"token": FAKE_JWT}, headers=headers)
        assert server.received == [FAKE_JWT]

    def test_unknown_route_is_404(self, server):
        assert _request("/admin", headers={AUTH_HEADER: SECRET})[0] == 404


class TestBinding:
    def test_refuses_non_loopback_bind(self):
        with pytest.raises(ValueError, match="loopback"):
            TokenServer(host="0.0.0.0", pairing_secret=SECRET).start()
