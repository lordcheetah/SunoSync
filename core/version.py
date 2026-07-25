"""Single source of truth for the application version.

Before this module existed the version was written down in four places
(version.json, services/updater.py, main.py's changelog prompt and the README)
and all four disagreed, which meant shipped builds showed a permanent
"update available" banner. Import from here instead of hard-coding.
"""

from __future__ import annotations

import re

__all__ = ["APP_VERSION", "APP_NAME", "APP_AUTHOR", "GITHUB_REPO", "parse_version"]

APP_VERSION = "3.0.1"

APP_NAME = "SunoSync"
APP_AUTHOR = "InternetThot"

# Owner/name of the repository this build is published from. The updater only
# ever talks to this repository, so a fork does not inherit upstream's release
# feed. Change this if you re-fork.
GITHUB_REPO = "lordcheetah/SunoSync"

_VERSION_RE = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


def parse_version(value: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple of ints.

    Tolerates a leading ``v`` and trailing pre-release/build suffixes, both of
    which appear in real GitHub tag names::

        >>> parse_version("v3.0.1")
        (3, 0, 1)
        >>> parse_version("3.1") < parse_version("3.1.1")
        True

    The result is padded to three components so that "3.0" and "3.0.0" compare
    equal rather than the former sorting lower.

    Returns an empty tuple when nothing numeric can be extracted, which callers
    should treat as "unknown, do not offer an update".
    """
    if not value or not isinstance(value, str):
        return ()
    match = _VERSION_RE.match(value)
    if not match:
        return ()
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)
