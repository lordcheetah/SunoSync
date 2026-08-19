"""Secure storage for the Suno client cookie.

The archiver needs a credential that outlives a single run. The session token
cannot: it is a one-hour JWT, and keeping it fresh meant keeping a browser and
extension alive, which does not survive an overnight run in Firefox or Zen --
temporary add-ons get unloaded.

The Clerk ``__client`` cookie is the durable credential behind that token, so
storing it lets the archiver mint its own JWTs (see :mod:`core.clerk`). It is
correspondingly more powerful: it can mint tokens until it expires or the
session is signed out. It therefore goes to the OS keystore -- Windows
Credential Manager via ``keyring`` -- rather than into config.json alongside
the short-lived token.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

__all__ = [
    "COOKIE_ENV_VAR",
    "clear_client_cookie",
    "get_client_cookie",
    "keyring_available",
    "set_client_cookie",
]

SERVICE_NAME = "SunoSync"
COOKIE_ENTRY = "suno_client_cookie"

# Lets a run supply the cookie without persisting it anywhere.
COOKIE_ENV_VAR = "SUNOSYNC_CLIENT_COOKIE"


def _keyring():
    try:
        import keyring

        return keyring
    except ImportError:
        return None


def keyring_available() -> bool:
    """Whether an OS keystore backend is usable."""
    kr = _keyring()
    if kr is None:
        return False
    try:
        backend = kr.get_keyring().__class__.__name__
        # The 'fail' backend raises on use; treat it as unavailable.
        return "Fail" not in backend
    except Exception:
        return False


def get_client_cookie() -> str | None:
    """The stored cookie, or None. The environment wins over the keystore."""
    from_env = (os.environ.get(COOKIE_ENV_VAR) or "").strip()
    if from_env:
        return from_env

    kr = _keyring()
    if kr is None:
        return None
    try:
        value = kr.get_password(SERVICE_NAME, COOKIE_ENTRY)
    except Exception:
        logger.debug("Could not read the cookie from the keystore", exc_info=True)
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def set_client_cookie(value: str) -> bool:
    """Persist the cookie to the OS keystore. Returns whether it was stored."""
    value = (value or "").strip()
    if not value:
        raise ValueError("refusing to store an empty cookie")

    kr = _keyring()
    if kr is None:
        logger.error("keyring is not installed; cannot store the cookie securely")
        return False
    try:
        kr.set_password(SERVICE_NAME, COOKIE_ENTRY, value)
        return True
    except Exception:
        logger.exception("Could not write the cookie to the keystore")
        return False


def clear_client_cookie() -> bool:
    """Remove the stored cookie. True if something was removed."""
    kr = _keyring()
    if kr is None:
        return False
    try:
        if kr.get_password(SERVICE_NAME, COOKIE_ENTRY) is None:
            return False
        kr.delete_password(SERVICE_NAME, COOKIE_ENTRY)
        return True
    except Exception:
        logger.debug("Could not clear the cookie", exc_info=True)
        return False
