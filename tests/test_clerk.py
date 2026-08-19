"""Minting session tokens from the Clerk client cookie.

This is what lets an unattended run keep going: session tokens last one hour,
and the browser extension that would otherwise refresh them does not survive
overnight in Firefox or Zen, where temporary add-ons are unloaded.
"""

import base64
import json

import pytest
import requests

from core.clerk import (
    ClerkAuthError,
    discover_session_id,
    mint_session_token,
    session_id_from_token,
)

JWT = "header.{}.signature"
SID = "session_cb448fdd26c18624d3ef3c"


def jwt_with(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return JWT.format(payload)


class _Response:
    def __init__(self, status, payload=None, text="{}"):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _Session:
    def __init__(self, post=None, get=None):
        self._post = post
        self._get = get
        self.posted = []

    def post(self, url, **_kw):
        self.posted.append(url)
        if isinstance(self._post, Exception):
            raise self._post
        return self._post

    def get(self, url, **_kw):
        if isinstance(self._get, Exception):
            raise self._get
        return self._get


class TestSessionIdFromToken:
    def test_reads_the_sid_claim(self):
        assert session_id_from_token(jwt_with({"sid": SID})) == SID

    def test_works_on_an_expired_token(self):
        # An expired token is still a fine record of which session it came from.
        assert session_id_from_token(jwt_with({"sid": SID, "exp": 1})) == SID

    @pytest.mark.parametrize("value", [None, "", "not-a-jwt", "a.b", 42])
    def test_unusable_input(self, value):
        assert session_id_from_token(value) is None

    def test_missing_claim(self):
        assert session_id_from_token(jwt_with({"sub": "user"})) is None


class TestMintSessionToken:
    FRESH = jwt_with({"sid": SID, "exp": 9999999999})

    def test_returns_the_minted_token(self):
        session = _Session(post=_Response(200, {"jwt": self.FRESH}))
        assert mint_session_token("cookie", session_id=SID, session=session) == self.FRESH

    def test_uses_the_session_id_from_a_known_token(self):
        session = _Session(post=_Response(200, {"jwt": self.FRESH}))
        mint_session_token("cookie", known_token=jwt_with({"sid": SID}), session=session)
        assert SID in session.posted[0], "should not need to ask Clerk for the session"

    def test_falls_back_to_discovery(self):
        session = _Session(
            post=_Response(200, {"jwt": self.FRESH}),
            get=_Response(200, {"response": {"last_active_session_id": SID}}),
        )
        assert mint_session_token("cookie", session=session) == self.FRESH
        assert SID in session.posted[0]

    def test_finds_a_nested_token(self):
        session = _Session(post=_Response(200, {"response": {"jwt": self.FRESH}}))
        assert mint_session_token("c", session_id=SID, session=session) == self.FRESH

    def test_empty_cookie_is_rejected_without_a_call(self):
        session = _Session()
        with pytest.raises(ClerkAuthError, match="no client cookie"):
            mint_session_token("", session=session)
        assert session.posted == []

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_rejected_cookie_says_to_sign_in_again(self, status):
        session = _Session(post=_Response(status))
        with pytest.raises(ClerkAuthError, match="sign in"):
            mint_session_token("stale", session_id=SID, session=session)

    def test_other_errors_surface_the_status(self):
        session = _Session(post=_Response(500))
        with pytest.raises(ClerkAuthError, match="500"):
            mint_session_token("c", session_id=SID, session=session)

    def test_network_failure_is_wrapped(self):
        session = _Session(post=requests.ConnectionError("down"))
        with pytest.raises(ClerkAuthError, match="Could not reach Clerk"):
            mint_session_token("c", session_id=SID, session=session)

    def test_response_without_a_token(self):
        session = _Session(post=_Response(200, {"object": "token"}))
        with pytest.raises(ClerkAuthError, match="no token"):
            mint_session_token("c", session_id=SID, session=session)

    def test_non_json_response(self):
        session = _Session(post=_Response(200, None))
        with pytest.raises(ClerkAuthError, match="non-JSON"):
            mint_session_token("c", session_id=SID, session=session)

    def test_unresolvable_session(self):
        session = _Session(get=_Response(404))
        with pytest.raises(ClerkAuthError, match="Could not determine"):
            mint_session_token("cookie", session=session)


class TestDiscoverSessionId:
    def test_prefers_the_active_session(self):
        session = _Session(get=_Response(200, {"response": {"last_active_session_id": SID}}))
        assert discover_session_id("c", session) == SID

    def test_falls_back_to_the_first_session(self):
        session = _Session(get=_Response(200, {"sessions": [{"id": SID}]}))
        assert discover_session_id("c", session) == SID

    def test_returns_none_on_failure(self):
        assert discover_session_id("c", _Session(get=_Response(403))) is None
        assert discover_session_id("c", _Session(get=requests.Timeout())) is None
