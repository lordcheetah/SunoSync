"""Update checking against this repository's GitHub Releases.

Previously this module fetched a manifest from a gist owned by the upstream
project and handed the ``download_url`` it found straight to
``webbrowser.open()``. That gave whoever controlled that gist the ability to
send every user to an arbitrary URL. Two things changed:

  * the release feed is this repository's GitHub Releases API, derived from
    ``core.version.GITHUB_REPO`` rather than a hard-coded third-party URL, and
  * any URL that comes back over the wire is validated before it is opened.
"""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlparse

import requests

from core.version import APP_VERSION, GITHUB_REPO, parse_version

logger = logging.getLogger(__name__)

RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"

REQUEST_TIMEOUT = 10

# A release URL must live on one of these hosts. Anything else is discarded and
# the user is sent to the repository's own releases page instead.
_ALLOWED_HOSTS = frozenset({
    "github.com",
    "www.github.com",
    "objects.githubusercontent.com",
})


def is_safe_download_url(url: str) -> bool:
    """Return True only for HTTPS URLs on a GitHub host we expect releases on.

    This is the guard that stops a compromised or hostile release feed from
    steering users to an arbitrary download.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    # Compare the host only; userinfo such as "github.com@evil.test" must not pass.
    host = (parsed.hostname or "").lower()
    return host in _ALLOWED_HOSTS


def _pick_download_url(release: dict) -> str:
    """Choose the best URL to send the user to for a given release payload."""
    for asset in release.get("assets") or []:
        name = (asset.get("name") or "").lower()
        if name.endswith(".exe"):
            url = asset.get("browser_download_url")
            if is_safe_download_url(url):
                return url

    url = release.get("html_url")
    if is_safe_download_url(url):
        return url

    return RELEASES_PAGE_URL


class Updater:
    """Checks GitHub Releases for a newer build, off the UI thread."""

    @staticmethod
    def fetch_latest_release(session: requests.Session | None = None) -> dict | None:
        """Fetch the latest release payload, or None if unavailable.

        Split out from :meth:`check_for_updates` so it can be tested without
        spawning a thread.
        """
        getter = session.get if session is not None else requests.get
        try:
            response = getter(
                RELEASES_API_URL,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except requests.RequestException as exc:
            logger.info("Update check failed: %s", exc)
            return None

        if response.status_code == 404:
            # No releases published yet. Not an error worth surfacing.
            logger.info("Update check: no releases published for %s", GITHUB_REPO)
            return None
        if response.status_code != 200:
            logger.info("Update check: HTTP %s", response.status_code)
            return None

        try:
            payload = response.json()
        except ValueError:
            logger.warning("Update check: response was not valid JSON")
            return None

        return payload if isinstance(payload, dict) else None

    @staticmethod
    def find_update(release: dict | None) -> tuple[str, str] | None:
        """Return (version, url) when `release` is newer than this build."""
        if not release or release.get("draft") or release.get("prerelease"):
            return None

        tag = release.get("tag_name") or release.get("name") or ""
        latest = parse_version(tag)
        current = parse_version(APP_VERSION)

        if not latest or not current:
            logger.info("Update check: could not parse version from %r", tag)
            return None
        if latest <= current:
            return None

        return ".".join(str(p) for p in latest), _pick_download_url(release)

    @staticmethod
    def check_for_updates(callback) -> threading.Thread:
        """Run the update check on a background thread.

        callback: function(latest_version: str, download_url: str) -> None,
        invoked only when a strictly newer release is found. The URL passed to
        the callback has already been validated by :func:`is_safe_download_url`.
        """

        def _check():
            try:
                update = Updater.find_update(Updater.fetch_latest_release())
                if update:
                    logger.info("Update available: v%s", update[0])
                    callback(*update)
            except Exception:
                # A failed update check must never take the app down.
                logger.exception("Unexpected error during update check")

        thread = threading.Thread(target=_check, daemon=True, name="SunoSync-Updater")
        thread.start()
        return thread
