"""Sentry event scrubbing.

SunoSync handles Suno session JWTs, so anything sent to a third-party error
tracker has to be redacted first.
"""

import pytest

from services.crash_reporting import REDACTED, scrub_event

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlaGVyZQ"


class TestKeyRedaction:
    @pytest.mark.parametrize(
        "key",
        [
            "token", "Token", "access_token", "__client", "Authorization",
            "authorization", "Cookie", "session", "api_key", "apiKey",
            "password", "secret", "pairing_secret", "X-SunoSync-Auth",
        ],
    )
    def test_sensitive_keys_are_redacted(self, key):
        assert scrub_event({key: "sensitive-value"})[key] == REDACTED

    def test_ordinary_keys_survive(self):
        event = {"title": "Midnight Drive", "duration": 210, "count": 3}
        assert scrub_event(event) == event


class TestValueRedaction:
    def test_bare_jwt_is_redacted(self):
        assert scrub_event({"message": f"Request failed with {JWT}"})["message"] == (
            f"Request failed with {REDACTED}"
        )

    def test_jwt_in_url_is_redacted(self):
        result = scrub_event({"url": f"https://studio-api.suno.ai/x?t={JWT}"})
        assert JWT not in result["url"]

    def test_query_string_credentials_are_redacted(self):
        result = scrub_event({"url": "https://api.test/x?token=abc123&page=2"})
        assert "abc123" not in result["url"]
        assert "page=2" in result["url"], "non-sensitive params should survive"


class TestStructures:
    def test_nested_dicts_are_scrubbed(self):
        event = {"request": {"headers": {"Authorization": f"Bearer {JWT}"}}}
        assert scrub_event(event)["request"]["headers"]["Authorization"] == REDACTED

    def test_lists_are_scrubbed(self):
        event = {"frames": [{"vars": {"token": JWT}}, {"vars": {"n": 1}}]}
        result = scrub_event(event)
        assert result["frames"][0]["vars"]["token"] == REDACTED
        assert result["frames"][1]["vars"]["n"] == 1

    def test_deeply_nested_token_is_caught(self):
        event = {"a": {"b": {"c": {"d": {"e": {"token": JWT}}}}}}
        assert scrub_event(event)["a"]["b"]["c"]["d"]["e"]["token"] == REDACTED

    def test_tuple_type_is_preserved(self):
        assert isinstance(scrub_event({"x": (1, 2)})["x"], tuple)

    def test_no_jwt_survives_anywhere(self):
        event = {
            "message": f"boom {JWT}",
            "extra": {"cookie": JWT, "nested": [JWT, {"authorization": JWT}]},
        }
        assert JWT not in repr(scrub_event(event))

    def test_recursion_is_bounded(self):
        event = current = {}
        for _ in range(200):
            current["next"] = {}
            current = current["next"]
        scrub_event(event)  # must not raise RecursionError


class TestPassthrough:
    @pytest.mark.parametrize("value", [None, 42, 3.14, True])
    def test_scalars_pass_through(self, value):
        assert scrub_event({"v": value})["v"] == value
