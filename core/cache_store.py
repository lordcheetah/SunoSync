"""Versioned, migrating storage for the library cache.

``library_cache.json`` originally had no version marker at all: it was a bare
``{filepath: metadata}`` dict written with ``json.dump`` and read back with a
blanket ``except Exception: self.cache = {}``. Any change to its shape would
have been read as "corrupt" and the user's entire scan cache would vanish
silently — which is at odds with the README's promise that the library database
survives updates.

The on-disk format is now::

    {
      "schema_version": 2,
      "entries": { "<filepath>": { ... }, ... }
    }

Loading walks the file forward through ``_MIGRATIONS`` one version at a time.
Anything genuinely unreadable is moved aside with a ``.corrupt`` suffix rather
than deleted, so a user can recover it.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = ["CURRENT_SCHEMA_VERSION", "load_cache", "save_cache", "migrate"]

CURRENT_SCHEMA_VERSION = 2


def _migrate_v1_to_v2(data: dict) -> dict:
    """v1 was an unversioned flat mapping of filepath -> metadata."""
    entries = data.get("entries")
    if not isinstance(entries, dict):
        # A genuine v1 file: the whole document is the entry map.
        entries = {k: v for k, v in data.items() if k != "schema_version"}
    return {"schema_version": 2, "entries": entries}


# Keyed by the version being migrated *from*.
_MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    1: _migrate_v1_to_v2,
}


def _detect_version(data: dict) -> int:
    version = data.get("schema_version")
    if isinstance(version, int) and version > 0:
        return version
    # No marker means the original unversioned format.
    return 1


def migrate(data: dict) -> dict:
    """Bring a decoded cache document up to CURRENT_SCHEMA_VERSION."""
    if not isinstance(data, dict):
        raise ValueError(f"cache root must be an object, got {type(data).__name__}")

    version = _detect_version(data)

    if version > CURRENT_SCHEMA_VERSION:
        # Written by a newer build. Refuse rather than mangle it.
        raise ValueError(
            f"cache schema v{version} is newer than supported v{CURRENT_SCHEMA_VERSION}"
        )

    while version < CURRENT_SCHEMA_VERSION:
        migration = _MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(f"no migration registered from schema v{version}")
        data = migration(data)
        new_version = _detect_version(data)
        if new_version <= version:
            raise ValueError(f"migration from v{version} did not advance the version")
        logger.info("Migrated library cache v%d -> v%d", version, new_version)
        version = new_version

    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("migrated cache has no 'entries' object")

    return data


def _quarantine(path: str) -> None:
    """Move an unreadable cache aside instead of destroying it."""
    backup = f"{path}.corrupt.{int(time.time())}"
    try:
        os.replace(path, backup)
        logger.warning("Unreadable library cache moved to %s", backup)
    except OSError:
        logger.exception("Could not quarantine unreadable cache at %s", path)


def load_cache(path: str | None) -> dict[str, Any]:
    """Return the entry mapping from `path`, or {} when unavailable.

    Never raises: a missing, unreadable or future-schema cache degrades to an
    empty cache (the library simply re-scans), and the offending file is kept.
    """
    if not path or not os.path.exists(path):
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        logger.error("Could not read library cache: %s", e)
        _quarantine(path)
        return {}

    try:
        return migrate(raw)["entries"]
    except ValueError as e:
        logger.error("Could not migrate library cache: %s", e)
        _quarantine(path)
        return {}


def save_cache(path: str | None, entries: dict[str, Any]) -> bool:
    """Write `entries` to `path` atomically. Returns whether it succeeded."""
    if not path:
        return False

    document = {"schema_version": CURRENT_SCHEMA_VERSION, "entries": entries}
    directory = os.path.dirname(path) or "."

    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(document, f)
            # Atomic replace: a crash mid-write cannot leave a truncated cache.
            os.replace(tmp_path, path)
            return True
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except (OSError, TypeError, ValueError) as e:
        logger.error("Could not save library cache: %s", e)
        return False
