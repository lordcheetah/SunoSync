"""Browser-extension manifest validity.

Chrome MV3 requires ``background.service_worker``; Firefox MV3 does not
implement it and requires ``background.scripts`` plus a gecko id. Getting this
wrong means the extension silently fails to load, so it is checked here rather
than discovered by hand.
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = REPO_ROOT / "browser_extension"

CHROME_MANIFEST = EXT_DIR / "manifest.json"
FIREFOX_MANIFEST = EXT_DIR / "manifest.firefox.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def chrome():
    return _load(CHROME_MANIFEST)


@pytest.fixture(scope="module")
def firefox():
    return _load(FIREFOX_MANIFEST)


class TestChromeManifest:
    def test_uses_service_worker(self, chrome):
        assert "service_worker" in chrome["background"]

    def test_is_manifest_v3(self, chrome):
        assert chrome["manifest_version"] == 3


class TestFirefoxManifest:
    def test_uses_background_scripts_not_service_worker(self, firefox):
        # The reason the extension could not load in Zen.
        assert "scripts" in firefox["background"]
        assert "service_worker" not in firefox["background"]

    def test_declares_gecko_id(self, firefox):
        gecko = firefox["browser_specific_settings"]["gecko"]
        assert gecko["id"]

    def test_is_manifest_v3(self, firefox):
        assert firefox["manifest_version"] == 3


class TestManifestsAgree:
    @pytest.mark.parametrize(
        "key", ["name", "version", "permissions", "host_permissions", "content_scripts"]
    )
    def test_shared_fields_match(self, chrome, firefox, key):
        assert chrome[key] == firefox[key]

    def test_bridge_host_permission_present(self, chrome, firefox):
        for manifest in (chrome, firefox):
            assert any("127.0.0.1:38945" in h for h in manifest["host_permissions"])


class TestReferencedFilesExist:
    @pytest.mark.parametrize("manifest_path", [CHROME_MANIFEST, FIREFOX_MANIFEST])
    def test_every_referenced_script_exists(self, manifest_path):
        manifest = _load(manifest_path)
        background = manifest["background"]

        referenced = list(background.get("scripts", []))
        if "service_worker" in background:
            referenced.append(background["service_worker"])
        for entry in manifest.get("content_scripts", []):
            referenced += entry.get("js", [])
        for entry in manifest.get("web_accessible_resources", []):
            referenced += entry.get("resources", [])
        referenced.append(manifest["action"]["default_popup"])

        missing = [name for name in referenced if not (EXT_DIR / name).exists()]
        assert not missing, f"{manifest_path.name} references missing files: {missing}"


class TestSourceSafety:
    """Guards against reintroducing the token-leak patterns."""

    def test_injected_script_does_not_broadcast_to_wildcard_origin(self):
        source = (EXT_DIR / "injected.js").read_text(encoding="utf-8")
        assert "postMessage" in source
        assert ", '*')" not in source, "postMessage must target a specific origin"
        assert ', "*")' not in source

    def test_content_script_validates_message_origin(self):
        source = (EXT_DIR / "content.js").read_text(encoding="utf-8")
        assert "event.origin" in source

    def test_background_sends_the_auth_header(self):
        source = (EXT_DIR / "background.js").read_text(encoding="utf-8")
        assert "X-SunoSync-Auth" in source
