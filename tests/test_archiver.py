"""Archiver planning and asset-selection logic.

Network calls are not exercised here; the pure decision-making is, because a
mistake in it means a track is silently missing from the archive.
"""

import os

import pytest

from core.archiver import (
    UNSORTED_FOLDER,
    Archiver,
    assign_folder_names,
    assign_track_stems,
    clip_lyrics,
    clip_title,
    cover_url,
    estimate_bytes,
    extract_playlist_clips,
    find_wav_url,
    human_bytes,
    plan_destinations,
)

# Field names confirmed against the live API.
CLIP = {
    "id": "4fe9fcba-8457-4419-bdfe-b7577369c4a4",
    "title": "Artemis",
    "audio_url": "https://cdn1.suno.ai/abc.mp3",
    "video_url": "https://cdn1.suno.ai/abc.mp4",
    "image_url": "https://cdn2.suno.ai/small.jpeg",
    "image_large_url": "https://cdn2.suno.ai/large.jpeg",
    "is_public": True,
    "metadata": {"prompt": "[Verse]\nsome words", "duration": 446.16},
}


class TestTitle:
    def test_uses_title(self):
        assert clip_title(CLIP) == "Artemis"

    def test_falls_back_to_prompt_first_line(self):
        clip = {"id": "x", "title": "", "metadata": {"prompt": "First line\nSecond"}}
        assert clip_title(clip) == "First line"

    def test_falls_back_to_id_when_nothing_usable(self):
        assert clip_title({"id": "abcdef123456"}).startswith("untitled-")

    def test_never_returns_empty(self):
        assert clip_title({})


class TestLyrics:
    def test_prefers_explicit_lyrics(self):
        clip = {"metadata": {"lyrics": "real lyrics", "prompt": "the prompt"}}
        assert clip_lyrics(clip) == "real lyrics"

    def test_falls_back_to_prompt(self):
        assert clip_lyrics(CLIP) == "[Verse]\nsome words"

    def test_empty_when_absent(self):
        assert clip_lyrics({"metadata": {}}) == ""
        assert clip_lyrics({}) == ""


class TestCover:
    def test_prefers_large_artwork(self):
        # image_url is only a thumbnail; the archive should keep the big one.
        assert cover_url(CLIP).endswith("large.jpeg")

    def test_falls_back_to_small(self):
        assert cover_url({"image_url": "https://x/y.jpeg"}).endswith("y.jpeg")

    def test_none_when_absent(self):
        assert cover_url({}) is None

    def test_ignores_non_http_values(self):
        assert cover_url({"image_large_url": "not-a-url"}) is None


class TestWavDiscovery:
    def test_finds_top_level(self):
        assert find_wav_url({"wav_url": "https://x/y.wav"}) == "https://x/y.wav"

    def test_finds_nested(self):
        payload = {"data": {"audio": [{"master_wav_url": "https://x/z.wav"}]}}
        assert find_wav_url(payload) == "https://x/z.wav"

    def test_ignores_mp3(self):
        assert find_wav_url({"audio_url": "https://x/y.mp3"}) is None

    def test_handles_empty_and_cycles_safely(self):
        assert find_wav_url({}) is None
        assert find_wav_url(None) is None
        deep = {}
        current = deep
        for _ in range(50):
            current["next"] = {}
            current = current["next"]
        assert find_wav_url(deep) is None


class TestPlaylistParsing:
    def test_nested_clip_objects(self):
        payload = {"playlist_clips": [{"clip": {"id": "a"}}, {"clip": {"id": "b"}}]}
        assert [c["id"] for c in extract_playlist_clips(payload)] == ["a", "b"]

    def test_flat_clip_objects(self):
        assert [c["id"] for c in extract_playlist_clips({"clips": [{"id": "a"}]})] == ["a"]

    def test_nested_playlist_wrapper(self):
        payload = {"playlist": {"playlist_clips": [{"clip": {"id": "z"}}]}}
        assert [c["id"] for c in extract_playlist_clips(payload)] == ["z"]

    def test_skips_entries_without_ids(self):
        payload = {"playlist_clips": [{"clip": {}}, {"clip": {"id": "ok"}}]}
        assert [c["id"] for c in extract_playlist_clips(payload)] == ["ok"]

    def test_unknown_shape_is_empty(self):
        assert extract_playlist_clips({"nope": 1}) == []
        assert extract_playlist_clips(None) == []


class TestDestinationPlanning:
    def test_single_playlist(self):
        assert plan_destinations("a", {"a": ["Chill"]}) == ["Chill"]

    def test_copied_into_every_playlist(self):
        result = plan_destinations("a", {"a": ["Chill", "Best Of", "Epic"]})
        assert result == ["Chill", "Best Of", "Epic"]

    def test_unfoldered_track_goes_to_unsorted(self):
        """A public track in no playlist must not be silently dropped."""
        assert plan_destinations("orphan", {}) == [UNSORTED_FOLDER]

    def test_playlist_names_are_sanitised(self):
        result = plan_destinations("a", {"a": ['Bad:Name?/Here']})
        assert ":" not in result[0] and "?" not in result[0] and "/" not in result[0]

    def test_duplicate_playlist_names_collapse(self):
        assert plan_destinations("a", {"a": ["Same", "Same"]}) == ["Same"]

    def test_blank_playlist_name_still_yields_a_folder(self):
        assert plan_destinations("a", {"a": [""]})[0]


class TestEstimates:
    def test_wav_dominates(self):
        with_wav = estimate_bytes(100, True, False)
        without = estimate_bytes(100, False, False)
        assert with_wav > without * 5

    def test_scales_with_count(self):
        assert estimate_bytes(200, True, True) == 2 * estimate_bytes(100, True, True)

    @pytest.mark.parametrize(
        "value,expected", [(0, "0.0 B"), (1536, "1.5 KB"), (5 * 1024**3, "5.0 GB")]
    )
    def test_human_bytes(self, value, expected):
        assert human_bytes(value) == expected


class TestResumeManifest:
    def test_round_trip(self, tmp_path):
        archiver = Archiver("tok", str(tmp_path))
        archiver.save_manifest({"a", "b"})
        assert Archiver("tok", str(tmp_path)).load_manifest() == {"a", "b"}

    def test_missing_manifest_is_empty(self, tmp_path):
        assert Archiver("tok", str(tmp_path)).load_manifest() == set()

    def test_corrupt_manifest_is_empty_not_fatal(self, tmp_path):
        archiver = Archiver("tok", str(tmp_path))
        os.makedirs(archiver.out_dir, exist_ok=True)
        with open(archiver.manifest_path(), "w", encoding="utf-8") as f:
            f.write("{not json")
        assert archiver.load_manifest() == set()

    def test_dry_run_writes_nothing(self, tmp_path):
        archiver = Archiver("tok", str(tmp_path), dry_run=True)
        archiver.save_manifest({"a"})
        assert not os.path.exists(archiver.manifest_path())


class TestSkipExisting:
    def test_existing_file_is_not_redownloaded(self, tmp_path):
        """Resume safety: a finished file must never be fetched again."""
        archiver = Archiver("tok", str(tmp_path))
        target = tmp_path / "song.mp3"
        target.write_bytes(b"already here")

        # No session is configured, so any network attempt would raise.
        assert archiver._download_to("https://example.invalid/x.mp3", str(target)) == 0
        assert archiver.stats["skipped"] == 1
        assert target.read_bytes() == b"already here"

    def test_zero_byte_file_is_retried(self, tmp_path):
        archiver = Archiver("tok", str(tmp_path), dry_run=True)
        target = tmp_path / "empty.mp3"
        target.write_bytes(b"")
        # dry_run returns before any network call, but must not count as skipped.
        assert archiver._download_to("https://example.invalid/x", str(target)) == 0
        assert archiver.stats["skipped"] == 0


class TestFolderNameCollisions:
    """Playlist names are not unique; two albums must not share a folder."""

    @staticmethod
    def _playlists(*pairs):
        return [{"id": pid, "name": name} for pid, name in pairs]

    def test_unique_names_are_untouched(self):
        names = assign_folder_names(self._playlists(("a", "Rock"), ("b", "Jazz")))
        assert names == {"a": "Rock", "b": "Jazz"}

    def test_collision_is_disambiguated(self):
        names = assign_folder_names(
            self._playlists(("8fdfa25b", "skepticAl humanIsm"),
                            ("031d6ce2", "skepticAl humanIsm"))
        )
        assert len(set(names.values())) == 2, "both playlists mapped to one folder"

    def test_lowest_id_keeps_the_plain_name(self):
        names = assign_folder_names(
            self._playlists(("8fdfa25b", "Album"), ("031d6ce2", "Album"))
        )
        assert names["031d6ce2"] == "Album"
        assert names["8fdfa25b"] == "Album [8fdfa25b]"

    def test_assignment_is_stable_regardless_of_api_order(self):
        forward = assign_folder_names(self._playlists(("aaa", "X"), ("bbb", "X")))
        reversed_ = assign_folder_names(self._playlists(("bbb", "X"), ("aaa", "X")))
        assert forward == reversed_, "a resumed run would rename folders"

    def test_three_way_collision(self):
        names = assign_folder_names(
            self._playlists(("a", "Same"), ("b", "Same"), ("c", "Same"))
        )
        assert len(set(names.values())) == 3

    def test_names_differing_only_by_illegal_chars_still_separate(self):
        # 'A:B' and 'A?B' both sanitise to 'A_B'.
        names = assign_folder_names(self._playlists(("a", "A:B"), ("b", "A?B")))
        assert len(set(names.values())) == 2

    def test_blank_name_gets_a_folder(self):
        assert assign_folder_names(self._playlists(("a", "")))["a"]


class TestSameTitleCollisions:
    """Two clips sharing a title in one folder must not share a filename."""

    CLIPS = {
        "aaaa1111-x": {"id": "aaaa1111-x", "title": "Overture"},
        "bbbb2222-x": {"id": "bbbb2222-x", "title": "Overture"},
        "cccc3333-x": {"id": "cccc3333-x", "title": "Finale"},
    }

    def test_colliding_titles_get_distinct_stems(self):
        membership = {"aaaa1111-x": ["Album"], "bbbb2222-x": ["Album"]}
        stems = assign_track_stems(
            {k: v for k, v in self.CLIPS.items() if k in membership}, membership
        )
        assert stems["aaaa1111-x"] != stems["bbbb2222-x"], (
            "same path means the second track is skipped as already downloaded"
        )

    def test_unique_titles_keep_the_plain_name(self):
        membership = {"aaaa1111-x": ["Album"], "cccc3333-x": ["Album"]}
        stems = assign_track_stems(
            {k: v for k, v in self.CLIPS.items() if k in membership}, membership
        )
        assert stems["cccc3333-x"] == "Finale"

    def test_same_title_in_different_folders_is_fine(self):
        membership = {"aaaa1111-x": ["A"], "bbbb2222-x": ["B"]}
        stems = assign_track_stems(
            {k: v for k, v in self.CLIPS.items() if k in membership}, membership
        )
        assert stems["aaaa1111-x"] == "Overture"
        assert stems["bbbb2222-x"] == "Overture"

    def test_suffix_is_consistent_across_every_folder(self):
        # A track must have one filename everywhere, or copies diverge.
        membership = {"aaaa1111-x": ["A", "B"], "bbbb2222-x": ["A"]}
        stems = assign_track_stems(
            {k: v for k, v in self.CLIPS.items() if k in membership}, membership
        )
        assert "[aaaa1111]" in stems["aaaa1111-x"]

    def test_collision_detection_is_case_insensitive(self):
        clips = {
            "a1": {"id": "a1", "title": "Overture"},
            "b2": {"id": "b2", "title": "OVERTURE"},
        }
        stems = assign_track_stems(clips, {"a1": ["Album"], "b2": ["Album"]})
        assert stems["a1"] != stems["b2"]

    def test_unsorted_tracks_are_disambiguated_too(self):
        clips = {"a1": {"id": "a1", "title": "Same"}, "b2": {"id": "b2", "title": "Same"}}
        stems = assign_track_stems(clips, {})
        assert stems["a1"] != stems["b2"]
