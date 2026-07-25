"""Library-cache schema versioning and migration."""

import json
import os

import pytest

from core.cache_store import (
    CURRENT_SCHEMA_VERSION,
    load_cache,
    migrate,
    save_cache,
)

LEGACY = {
    "C:/Music/song.mp3": {"title": "Song", "uuid": "abc-123"},
    "C:/Music/other.mp3": {"title": "Other", "uuid": "def-456"},
}


class TestMigrate:
    def test_unversioned_document_is_treated_as_v1(self):
        result = migrate(dict(LEGACY))
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION
        assert result["entries"] == LEGACY

    def test_current_version_passes_through(self):
        doc = {"schema_version": CURRENT_SCHEMA_VERSION, "entries": LEGACY}
        assert migrate(doc)["entries"] == LEGACY

    def test_future_schema_is_refused(self):
        doc = {"schema_version": CURRENT_SCHEMA_VERSION + 5, "entries": {}}
        with pytest.raises(ValueError, match="newer than supported"):
            migrate(doc)

    def test_non_dict_root_is_refused(self):
        with pytest.raises(ValueError, match="must be an object"):
            migrate([1, 2, 3])

    def test_empty_document_migrates_to_empty_entries(self):
        assert migrate({})["entries"] == {}


class TestRoundTrip:
    def test_save_then_load(self, tmp_path):
        path = str(tmp_path / "library_cache.json")
        assert save_cache(path, LEGACY)
        assert load_cache(path) == LEGACY

    def test_saved_file_records_the_schema_version(self, tmp_path):
        path = str(tmp_path / "library_cache.json")
        save_cache(path, LEGACY)
        with open(path, encoding="utf-8") as f:
            assert json.load(f)["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_legacy_file_on_disk_is_read(self, tmp_path):
        """An existing v1 cache must survive the upgrade, not be discarded."""
        path = tmp_path / "library_cache.json"
        path.write_text(json.dumps(LEGACY), encoding="utf-8")
        assert load_cache(str(path)) == LEGACY

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_cache(str(tmp_path / "nope.json")) == {}

    def test_none_path_returns_empty(self):
        assert load_cache(None) == {}
        assert save_cache(None, LEGACY) is False


class TestCorruption:
    def test_corrupt_file_is_quarantined_not_deleted(self, tmp_path):
        path = tmp_path / "library_cache.json"
        path.write_text("{not valid json at all", encoding="utf-8")

        assert load_cache(str(path)) == {}
        assert not path.exists(), "the unreadable file should have been moved aside"

        quarantined = [p for p in os.listdir(tmp_path) if ".corrupt" in p]
        assert quarantined, "a .corrupt backup should exist"

    def test_future_schema_file_is_quarantined(self, tmp_path):
        path = tmp_path / "library_cache.json"
        path.write_text(
            json.dumps({"schema_version": 999, "entries": LEGACY}), encoding="utf-8"
        )
        assert load_cache(str(path)) == {}
        assert [p for p in os.listdir(tmp_path) if ".corrupt" in p]


class TestAtomicity:
    def test_failed_save_leaves_no_temp_files(self, tmp_path):
        path = str(tmp_path / "library_cache.json")
        # Sets are not JSON-serialisable, so the write fails mid-flight.
        assert save_cache(path, {"k": {1, 2, 3}}) is False
        assert [p for p in os.listdir(tmp_path) if p.endswith(".tmp")] == []

    def test_failed_save_does_not_destroy_existing_cache(self, tmp_path):
        path = str(tmp_path / "library_cache.json")
        save_cache(path, LEGACY)
        save_cache(path, {"k": {1, 2, 3}})  # fails
        assert load_cache(path) == LEGACY
