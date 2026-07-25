"""Canonical locations for everything SunoSync writes to disk.

The app used to scatter its state across three different roots:

  * ``config.json`` went to the appdirs user-data directory (correct),
  * ``library_cache.json`` and ``tags.json`` went next to the executable, and
  * ``window_state.json`` and ``debug.log`` went to the current working
    directory, which is wherever the user happened to launch from.

For an installed build under ``C:\\Program Files`` the second and third groups
land in a read-only location, so the cache silently failed to save — despite the
README promising the library database survives updates. Everything now resolves
through this module.

There is a one-time migration from the legacy locations so existing users keep
their library cache and tags.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys

import appdirs

from core.version import APP_AUTHOR, APP_NAME

logger = logging.getLogger(__name__)

__all__ = [
    "get_data_dir",
    "get_cache_file",
    "get_tags_file",
    "get_config_file",
    "get_window_state_file",
    "get_log_file",
    "get_bridge_file",
    "get_bundle_dir",
    "resource_path",
    "migrate_legacy_files",
]


def get_data_dir() -> str:
    """Per-user writable directory for application state. Created on demand."""
    path = appdirs.user_data_dir(APP_NAME, APP_AUTHOR)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        logger.exception("Could not create data directory: %s", path)
    return path


def _in_data_dir(filename: str) -> str:
    return os.path.join(get_data_dir(), filename)


def get_config_file() -> str:
    return _in_data_dir("config.json")


def get_cache_file() -> str:
    return _in_data_dir("library_cache.json")


def get_tags_file() -> str:
    return _in_data_dir("tags.json")


def get_window_state_file() -> str:
    return _in_data_dir("window_state.json")


def get_log_file() -> str:
    return _in_data_dir("debug.log")


def get_bridge_file() -> str:
    """Where the browser-extension pairing secret is stored."""
    return _in_data_dir("token_bridge.json")


def get_bundle_dir() -> str:
    """Directory holding read-only bundled resources.

    Under PyInstaller this is the extraction directory (``sys._MEIPASS``); in a
    source checkout it is the repository root.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative_path: str) -> str:
    """Absolute path to a bundled read-only resource."""
    return os.path.join(get_bundle_dir(), relative_path)


def _legacy_roots() -> list[str]:
    """Directories the app previously wrote state into."""
    roots = [os.getcwd()]
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(sys.executable))
    else:
        roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # De-duplicate while preserving order.
    seen, unique = set(), []
    for root in roots:
        norm = os.path.normcase(os.path.normpath(root))
        if norm not in seen:
            seen.add(norm)
            unique.append(root)
    return unique


_MIGRATABLE = ("library_cache.json", "tags.json", "window_state.json")


def migrate_legacy_files() -> list[str]:
    """Copy state files from their old locations into the data directory.

    Only runs for files that do not already exist at the new location, so it is
    safe to call on every launch and will never clobber newer data. Returns the
    list of filenames that were migrated.
    """
    data_dir = get_data_dir()
    migrated: list[str] = []

    for filename in _MIGRATABLE:
        destination = os.path.join(data_dir, filename)
        if os.path.exists(destination):
            continue
        for root in _legacy_roots():
            source = os.path.join(root, filename)
            if os.path.normcase(os.path.normpath(source)) == os.path.normcase(
                os.path.normpath(destination)
            ):
                continue
            if not os.path.isfile(source):
                continue
            try:
                shutil.copy2(source, destination)
                migrated.append(filename)
                logger.info("Migrated %s from %s", filename, root)
            except OSError:
                logger.exception("Could not migrate %s from %s", filename, root)
            break

    return migrated
