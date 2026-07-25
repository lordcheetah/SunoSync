"""Sentry initialisation with credential scrubbing and a user opt-out.

The README advertises a "Crash Shield", but the DSN was the literal placeholder
``YOUR_DSN_HERE``, so nothing was ever reported. Turning it on naively would
have been worse than leaving it off: SunoSync handles Suno session JWTs, and
those show up in request headers, local variables and URLs that Sentry captures
by default.

This module therefore:

  * reads the DSN from the environment rather than hard-coding it, so forks and
    source builds are opt-in rather than reporting to someone else's project,
  * disables PII collection outright,
  * redacts anything that looks like a credential from events before they leave
    the machine, and
  * honours a ``crash_reporting`` flag in the user's config.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["init_sentry", "scrub_event", "REDACTED"]

REDACTED = "[redacted]"

# Key names whose values must never be transmitted. Matched case-insensitively
# as a substring, so "X-Suno-Authorization" and "client_token" both hit.
_SENSITIVE_KEY_PARTS = (
    "token",
    "authorization",
    "auth",
    "cookie",
    "session",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "credential",
    "__client",
    "pairing",
)

# JWTs, which is what Suno/Clerk session tokens are. Caught even when they are
# embedded in a free-text message or a URL rather than sitting under a key.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")

# Query-string credentials, e.g. "?token=abc123" or "&api_key=xyz".
_QUERY_CRED_RE = re.compile(
    r"([?&](?:" + "|".join(_SENSITIVE_KEY_PARTS) + r")[^=]*=)[^&\s]+",
    re.IGNORECASE,
)

_MAX_DEPTH = 12


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _scrub_text(value: str) -> str:
    value = _JWT_RE.sub(REDACTED, value)
    value = _QUERY_CRED_RE.sub(r"\1" + REDACTED, value)
    return value


def scrub_event(event: Any, _depth: int = 0) -> Any:
    """Recursively redact credentials from a Sentry event.

    Exposed separately from :func:`init_sentry` so it can be unit tested without
    a live Sentry client.
    """
    if _depth > _MAX_DEPTH:
        return event

    if isinstance(event, dict):
        cleaned = {}
        for key, value in event.items():
            if _is_sensitive_key(key):
                cleaned[key] = REDACTED
            else:
                cleaned[key] = scrub_event(value, _depth + 1)
        return cleaned

    if isinstance(event, (list, tuple)):
        scrubbed = [scrub_event(item, _depth + 1) for item in event]
        return type(event)(scrubbed) if isinstance(event, tuple) else scrubbed

    if isinstance(event, str):
        return _scrub_text(event)

    return event


def _before_send(event, hint):  # noqa: ARG001 - hint is part of the Sentry API
    try:
        return scrub_event(event)
    except Exception:
        # If scrubbing fails we drop the event rather than risk sending
        # unredacted credentials.
        logger.exception("Sentry scrubbing failed; dropping event")
        return None


def is_enabled(config_manager=None) -> bool:
    """Whether crash reporting should run for this launch."""
    if os.environ.get("SUNOSYNC_DISABLE_SENTRY", "").strip().lower() in ("1", "true", "yes"):
        return False
    if config_manager is not None:
        # Default True so the setting is opt-out, but only ever reaches Sentry
        # when a DSN was actually configured at build time.
        if not config_manager.get("crash_reporting", True):
            return False
    return bool(os.environ.get("SUNOSYNC_SENTRY_DSN", "").strip())


def init_sentry(config_manager=None) -> bool:
    """Initialise Sentry if configured and permitted. Returns whether it is on."""
    dsn = os.environ.get("SUNOSYNC_SENTRY_DSN", "").strip()

    if not dsn:
        logger.info("Crash reporting disabled (no SUNOSYNC_SENTRY_DSN configured).")
        return False

    if not is_enabled(config_manager):
        logger.info("Crash reporting disabled by user preference.")
        return False

    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            # Never attach usernames, IPs, request bodies or cookies.
            send_default_pii=False,
            # Local variables in stack frames routinely hold the session token.
            include_local_variables=False,
            traces_sample_rate=0.0,
            profiles_sample_rate=0.0,
            before_send=_before_send,
            release=_release_string(),
        )
        logger.info("Crash reporting enabled (PII off, credentials scrubbed).")
        return True
    except Exception:
        logger.exception("Sentry init failed")
        return False


def _release_string() -> str:
    try:
        from core.version import APP_NAME, APP_VERSION

        return f"{APP_NAME}@{APP_VERSION}"
    except Exception:
        return "unknown"
