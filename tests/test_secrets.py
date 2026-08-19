"""Client-cookie storage.

The cookie is a stronger credential than the one-hour session token -- it can
mint replacements until it expires -- so it belongs in the OS keystore rather
than in config.json.
"""

import pytest

from core import secrets


class _FakeKeyring:
    """Stands in for the keyring module."""

    class _Backend:
        pass

    def __init__(self, backend_name="WinVaultKeyring", raise_on=None):
        self.store = {}
        self._backend_name = backend_name
        self._raise_on = raise_on or set()

    def get_keyring(self):
        backend = type(self._backend_name, (self._Backend,), {})
        return backend()

    def get_password(self, service, entry):
        if "get" in self._raise_on:
            raise RuntimeError("keystore locked")
        return self.store.get((service, entry))

    def set_password(self, service, entry, value):
        if "set" in self._raise_on:
            raise RuntimeError("keystore locked")
        self.store[(service, entry)] = value

    def delete_password(self, service, entry):
        del self.store[(service, entry)]


@pytest.fixture
def fake(monkeypatch):
    kr = _FakeKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
    monkeypatch.delenv(secrets.COOKIE_ENV_VAR, raising=False)
    return kr


class TestRoundTrip:
    def test_store_and_read(self, fake):
        assert secrets.set_client_cookie("cookie-value") is True
        assert secrets.get_client_cookie() == "cookie-value"

    def test_absent_is_none(self, fake):
        assert secrets.get_client_cookie() is None

    def test_whitespace_is_trimmed(self, fake):
        secrets.set_client_cookie("  padded  ")
        assert secrets.get_client_cookie() == "padded"

    def test_empty_is_refused(self, fake):
        with pytest.raises(ValueError):
            secrets.set_client_cookie("   ")

    def test_clear(self, fake):
        secrets.set_client_cookie("x")
        assert secrets.clear_client_cookie() is True
        assert secrets.get_client_cookie() is None

    def test_clear_when_absent(self, fake):
        assert secrets.clear_client_cookie() is False


class TestEnvironmentOverride:
    def test_environment_wins(self, fake, monkeypatch):
        secrets.set_client_cookie("from-keystore")
        monkeypatch.setenv(secrets.COOKIE_ENV_VAR, "from-env")
        assert secrets.get_client_cookie() == "from-env"

    def test_environment_alone_is_enough(self, fake, monkeypatch):
        monkeypatch.setenv(secrets.COOKIE_ENV_VAR, "only-env")
        assert secrets.get_client_cookie() == "only-env"

    def test_blank_environment_is_ignored(self, fake, monkeypatch):
        secrets.set_client_cookie("stored")
        monkeypatch.setenv(secrets.COOKIE_ENV_VAR, "  ")
        assert secrets.get_client_cookie() == "stored"


class TestDegradedBackends:
    def test_no_keyring_installed(self, monkeypatch):
        monkeypatch.setattr(secrets, "_keyring", lambda: None)
        monkeypatch.delenv(secrets.COOKIE_ENV_VAR, raising=False)
        assert secrets.keyring_available() is False
        assert secrets.get_client_cookie() is None
        assert secrets.set_client_cookie("x") is False

    def test_fail_backend_reported_unavailable(self, monkeypatch):
        monkeypatch.setattr(secrets, "_keyring", lambda: _FakeKeyring("FailKeyring"))
        assert secrets.keyring_available() is False

    def test_read_error_is_not_fatal(self, monkeypatch):
        monkeypatch.setattr(secrets, "_keyring", lambda: _FakeKeyring(raise_on={"get"}))
        monkeypatch.delenv(secrets.COOKIE_ENV_VAR, raising=False)
        assert secrets.get_client_cookie() is None

    def test_write_error_reports_failure(self, monkeypatch):
        monkeypatch.setattr(secrets, "_keyring", lambda: _FakeKeyring(raise_on={"set"}))
        assert secrets.set_client_cookie("x") is False

    def test_env_still_works_without_a_keystore(self, monkeypatch):
        monkeypatch.setattr(secrets, "_keyring", lambda: None)
        monkeypatch.setenv(secrets.COOKIE_ENV_VAR, "env-only")
        assert secrets.get_client_cookie() == "env-only"
