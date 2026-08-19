"""Read the Suno client cookie straight out of a Firefox-family profile.

Zen hides the developer tools behind keyboard shortcuts, and copying a 615
character credential out of a cookie inspector by hand is both awkward and easy
to get wrong. The browser already has the cookie in a SQLite file, so read it
from there.

Supports Zen, Firefox, LibreWolf and Waterfox, which all use the same profile
layout and ``moz_cookies`` schema.

Note the cookie is scoped to ``auth.suno.com``, Suno's Clerk instance -- not to
``suno.com``, where one would first think to look.
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
import sqlite3
import tempfile

logger = logging.getLogger(__name__)

__all__ = [
    "COOKIE_NAME",
    "BrowserCookieError",
    "find_profiles",
    "read_client_cookie",
]

COOKIE_NAME = "__client"

# Hosts the Clerk client cookie may be scoped to, best first.
COOKIE_HOSTS = ("auth.suno.com", ".suno.com", "suno.com")

# Profile roots, relative to APPDATA on Windows.
_BROWSER_DIRS = {
    "Zen": ("zen", "Profiles"),
    "Firefox": (os.path.join("Mozilla", "Firefox"), "Profiles"),
    "LibreWolf": ("librewolf", "Profiles"),
    "Waterfox": ("Waterfox", "Profiles"),
}


class BrowserCookieError(Exception):
    """The profile could not be read, or held no usable cookie."""


def find_profiles():
    """Return [(browser, profile_name, cookies.sqlite path)], newest first."""
    roots = [os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"),
             os.path.expanduser("~/.mozilla"), os.path.expanduser("~/Library/Application Support")]

    found = []
    for root in filter(None, roots):
        for browser, (subdir, profiles_dir) in _BROWSER_DIRS.items():
            pattern = os.path.join(root, subdir, profiles_dir, "*", "cookies.sqlite")
            for path in glob.glob(pattern):
                entry = (browser, os.path.basename(os.path.dirname(path)), path)
                if entry not in found:
                    found.append(entry)

    # A profile used recently is the one the user is signed in on.
    found.sort(key=lambda e: os.path.getmtime(e[2]), reverse=True)
    return found


def _snapshot(path):
    """Copy the database aside so a running browser's lock does not block us."""
    directory = tempfile.mkdtemp(prefix="sunosync-cookies-")
    target = os.path.join(directory, "cookies.sqlite")
    for suffix in ("", "-wal", "-shm"):
        source = path + suffix
        if os.path.exists(source):
            shutil.copy2(source, target + suffix)
    return directory, target


def read_client_cookie(path):
    """Return the __client cookie value from one profile, or None.

    Never logs the value; it is a credential.
    """
    directory, snapshot = _snapshot(path)
    try:
        connection = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT host, value FROM moz_cookies WHERE name = ?", (COOKIE_NAME,)
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise BrowserCookieError(f"could not read the cookie database: {exc}") from exc
    finally:
        shutil.rmtree(directory, ignore_errors=True)

    if not rows:
        return None

    # Prefer the Clerk host; fall back to whatever scope is present.
    by_host = {host: value for host, value in rows if value}
    for host in COOKIE_HOSTS:
        if by_host.get(host):
            logger.debug("Found %s scoped to %s", COOKIE_NAME, host)
            return by_host[host].strip()
    return next(iter(by_host.values()), "").strip() or None
