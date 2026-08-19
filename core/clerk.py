"""Mint Suno session tokens directly from the Clerk client cookie.

Suno authenticates with Clerk. The token the app uses is a one-hour JWT that the
browser mints on demand from a longer-lived ``__client`` cookie. Doing the same
thing ourselves removes the browser from the loop entirely, which is what an
unattended multi-hour archive needs: Firefox and Zen unload temporary add-ons,
so the extension cannot be relied on to keep pushing tokens overnight.

    POST https://auth.suno.com/v1/client/sessions/{session_id}/tokens
    Cookie: __client=...
    -> {"jwt": "<one-hour token>"}
"""

from __future__ import annotations

import base64
import json
import logging

import requests

logger = logging.getLogger(__name__)

__all__ = [
    "CLERK_BASE",
    "ClerkAuthError",
    "discover_session_id",
    "mint_session_token",
    "session_id_from_token",
]

CLERK_BASE = "https://auth.suno.com"
REQUEST_TIMEOUT = 20


class ClerkAuthError(Exception):
    """The cookie was rejected, or no session could be resolved."""


def session_id_from_token(token):
    """Read the `sid` claim from a JWT, expired or not.

    An expired token is still a perfectly good record of which session it came
    from, which saves a round trip when minting a replacement.
    """
    if not isinstance(token, str) or token.count(".") != 2:
        return None
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload)).get("sid")
    except Exception:
        return None


def _headers(cookie):
    return {
        "Cookie": f"__client={cookie}",
        "Origin": "https://suno.com",
        "Referer": "https://suno.com/",
        "Accept": "application/json",
        "User-Agent": "SunoSync-Archiver/1.0",
    }


def discover_session_id(cookie, session=None):
    """Ask Clerk which session this cookie currently belongs to."""
    getter = (session or requests).get
    try:
        response = getter(
            f"{CLERK_BASE}/v1/client",
            headers=_headers(cookie),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.debug("Could not reach Clerk to discover the session: %s", exc)
        return None

    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None

    client = payload.get("response") if isinstance(payload, dict) else None
    client = client if isinstance(client, dict) else payload
    if not isinstance(client, dict):
        return None

    active = client.get("last_active_session_id")
    if isinstance(active, str) and active:
        return active
    for entry in client.get("sessions") or []:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            return entry["id"]
    return None


def mint_session_token(cookie, session_id=None, known_token=None, session=None):
    """Exchange the client cookie for a fresh one-hour session token.

    `session_id` is used if given; otherwise it is read from `known_token`, and
    only failing that is Clerk asked. Raises ClerkAuthError when the cookie is
    no longer valid, which means signing in again.
    """
    cookie = (cookie or "").strip()
    if not cookie:
        raise ClerkAuthError("no client cookie configured")

    sid = session_id or session_id_from_token(known_token) or discover_session_id(cookie, session)
    if not sid:
        raise ClerkAuthError(
            "Could not determine the Clerk session. The cookie may have expired; "
            "sign in to suno.com again and re-copy it."
        )

    poster = (session or requests).post
    try:
        response = poster(
            f"{CLERK_BASE}/v1/client/sessions/{sid}/tokens",
            headers=_headers(cookie),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ClerkAuthError(f"Could not reach Clerk: {exc}") from exc

    if response.status_code in (401, 403, 404):
        raise ClerkAuthError(
            f"Clerk rejected the client cookie (HTTP {response.status_code}). "
            "It has expired or the session was signed out -- sign in to suno.com "
            "and store the new cookie."
        )
    if response.status_code >= 400:
        raise ClerkAuthError(f"Clerk returned HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ClerkAuthError("Clerk returned a non-JSON response") from exc

    token = _extract_jwt(payload)
    if not token:
        raise ClerkAuthError("Clerk response contained no token")
    return token


def _extract_jwt(payload, _depth=0):
    """Pull a JWT out of a Clerk response without assuming its exact shape."""
    if _depth > 5:
        return None
    if isinstance(payload, str):
        value = payload.strip()
        return value if value.count(".") == 2 and len(value) > 40 else None
    if isinstance(payload, dict):
        for key in ("jwt", "token", "last_active_token"):
            found = _extract_jwt(payload.get(key), _depth + 1)
            if found:
                return found
        for value in payload.values():
            found = _extract_jwt(value, _depth + 1)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _extract_jwt(item, _depth + 1)
            if found:
                return found
    return None
