"""Update-check safety.

The original updater fetched a manifest from a gist owned by the *upstream*
project and passed whatever ``download_url`` it found to ``webbrowser.open()``.
These tests pin down the two properties that replaced it: the feed belongs to
this repository, and URLs are validated before use.
"""

import pytest

from core.version import GITHUB_REPO
from services.updater import (
    RELEASES_API_URL,
    RELEASES_PAGE_URL,
    Updater,
    is_safe_download_url,
)


def _release(tag="v9.9.9", assets=None, **extra):
    payload = {
        "tag_name": tag,
        "html_url": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}",
        "assets": assets or [],
    }
    payload.update(extra)
    return payload


class TestUrlValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/lordcheetah/SunoSync/releases/latest",
            "https://objects.githubusercontent.com/some/asset.exe",
            "https://www.github.com/x/y",
        ],
    )
    def test_accepts_github_https(self, url):
        assert is_safe_download_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://github.com/x/y",                     # not HTTPS
            "https://evil.test/payload.exe",             # wrong host
            "https://github.com.evil.test/payload.exe",  # suffix confusion
            "https://evil.test/?x=github.com",           # host is not github
            "file:///C:/Windows/System32/calc.exe",      # local scheme
            "javascript:alert(1)",
            "",
            None,
            12345,
        ],
    )
    def test_rejects_everything_else(self, url):
        assert not is_safe_download_url(url)

    def test_rejects_userinfo_smuggling(self):
        # "github.com" here is credentials, not the host.
        assert not is_safe_download_url("https://github.com@evil.test/payload.exe")


class TestFeedOwnership:
    def test_api_url_targets_this_repository(self):
        assert RELEASES_API_URL == f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

    def test_no_third_party_host_in_urls(self):
        for url in (RELEASES_API_URL, RELEASES_PAGE_URL):
            assert "gist.githubusercontent.com" not in url
            assert "sunsetsacoustic" not in url


class TestFindUpdate:
    def test_newer_release_is_offered(self):
        result = Updater.find_update(_release("v99.0.0"))
        assert result is not None
        assert result[0] == "99.0.0"

    def test_same_version_is_not_offered(self):
        from core.version import APP_VERSION

        assert Updater.find_update(_release(f"v{APP_VERSION}")) is None

    def test_older_version_is_not_offered(self):
        assert Updater.find_update(_release("v0.0.1")) is None

    def test_drafts_and_prereleases_are_skipped(self):
        assert Updater.find_update(_release("v99.0.0", draft=True)) is None
        assert Updater.find_update(_release("v99.0.0", prerelease=True)) is None

    def test_none_release_is_handled(self):
        assert Updater.find_update(None) is None

    def test_unparseable_tag_is_ignored(self):
        assert Updater.find_update(_release("nightly")) is None

    def test_prefers_exe_asset(self):
        release = _release(
            "v99.0.0",
            assets=[
                {"name": "notes.txt", "browser_download_url": "https://github.com/a/b/notes.txt"},
                {"name": "SunoSync.exe", "browser_download_url": "https://github.com/a/b/SunoSync.exe"},
            ],
        )
        assert Updater.find_update(release)[1].endswith("SunoSync.exe")

    def test_hostile_asset_url_falls_back_to_releases_page(self):
        release = _release(
            "v99.0.0",
            assets=[{"name": "SunoSync.exe", "browser_download_url": "https://evil.test/x.exe"}],
        )
        version, url = Updater.find_update(release)
        assert url != "https://evil.test/x.exe"
        assert is_safe_download_url(url)

    def test_hostile_html_url_falls_back(self):
        release = _release("v99.0.0")
        release["html_url"] = "https://evil.test/release"
        _, url = Updater.find_update(release)
        assert url == RELEASES_PAGE_URL
