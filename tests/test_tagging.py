"""Album tagging: ordering, field derivation, and round-tripping through ID3."""

import os

import pytest
from mutagen.id3 import ID3

from core.tagging import (
    build_album_plans,
    primary_genre,
    release_year,
    render_m3u,
    tag_audio_file,
)

# A silent MP3 frame, enough for mutagen to attach ID3 to.
SILENT_MP3 = bytes.fromhex("fffb90c4") + b"\x00" * 800


def clip(cid="c1", title="Track One", tags="progressive rock, cinematic synth, world percussion",
         created="2026-07-25T20:29:45.787Z", duration=200):
    return {
        "id": cid,
        "title": title,
        "created_at": created,
        "major_model_version": "v5.5",
        "metadata": {"tags": tags, "duration": duration, "prompt": "[Verse]\nwords"},
    }


PLAYLIST = {
    "id": "p1",
    "name": "wAyfInders",
    "description": "concept album",
    "image_url": "https://cdn2.suno.ai/cover.jpeg",
    "user_display_name": "Galaxy Rise",
    "user_handle": "galaxyrise",
}


class TestGenre:
    def test_truncates_the_style_prompt(self):
        # metadata.tags is a several-hundred-character style prompt; a genre
        # field holding all of it makes library browsers unusable.
        assert primary_genre("a, b, c, d, e", limit=3) == "a, b, c"

    def test_handles_newlines(self):
        assert primary_genre("rock\nsynth, pop", limit=2) == "rock, synth"

    def test_caps_length(self):
        assert len(primary_genre(", ".join(["verylongtag" * 5] * 6))) <= 120

    @pytest.mark.parametrize("value", [None, "", "   ", 42])
    def test_empty_input(self, value):
        assert primary_genre(value) is None


class TestYear:
    def test_from_created_at(self):
        assert release_year(clip(created="2026-07-25T20:29:45Z")) == "2026"

    def test_falls_back_when_missing(self):
        assert release_year({}).isdigit()

    def test_falls_back_on_garbage(self):
        assert release_year({"created_at": "nope"}).isdigit()


class TestAlbumOrdering:
    def test_uses_relative_index(self):
        entries = [
            {"clip": clip("c3", "Third"), "relative_index": 3.0},
            {"clip": clip("c1", "First"), "relative_index": 1.0},
            {"clip": clip("c2", "Second"), "relative_index": 2.0},
        ]
        plan = build_album_plans([(PLAYLIST, entries)])[0]
        assert [t.title for t in plan.tracks] == ["First", "Second", "Third"]
        assert [t.track_number for t in plan.tracks] == [1, 2, 3]

    def test_total_tracks_set_on_every_track(self):
        entries = [{"clip": clip(f"c{i}"), "relative_index": float(i)} for i in range(1, 5)]
        plan = build_album_plans([(PLAYLIST, entries)])[0]
        assert {t.total_tracks for t in plan.tracks} == {4}

    def test_falls_back_to_api_order_without_index(self):
        entries = [{"clip": clip("a", "A")}, {"clip": clip("b", "B")}]
        plan = build_album_plans([(PLAYLIST, entries)])[0]
        assert [t.title for t in plan.tracks] == ["A", "B"]

    def test_album_fields_from_playlist(self):
        plan = build_album_plans([(PLAYLIST, [{"clip": clip(), "relative_index": 1.0}])])[0]
        assert plan.name == "wAyfInders"
        assert plan.album_artist == "Galaxy Rise"
        assert plan.cover_url.endswith("cover.jpeg")

    def test_folder_name_is_sanitised(self):
        playlist = dict(PLAYLIST, name='Bad:Name?/Here')
        plan = build_album_plans([(playlist, [])])[0]
        assert not set(plan.folder) & set(':?/')

    def test_entries_without_ids_are_dropped(self):
        entries = [{"clip": {}}, {"clip": clip("ok")}]
        assert len(build_album_plans([(PLAYLIST, entries)])[0]) == 1


class TestTagWriting:
    @pytest.fixture
    def mp3(self, tmp_path):
        path = tmp_path / "Track One.mp3"
        path.write_bytes(SILENT_MP3)
        return str(path)

    @pytest.fixture
    def track(self):
        entries = [
            {"clip": clip("c1", "Track One"), "relative_index": 1.0},
            {"clip": clip("c2", "Track Two"), "relative_index": 2.0},
        ]
        return build_album_plans([(PLAYLIST, entries)])[0].tracks[0]

    def test_writes_album_fields(self, mp3, track):
        assert tag_audio_file(mp3, track, lyrics="la la")
        tags = ID3(mp3)
        assert tags["TIT2"].text[0] == "Track One"
        assert tags["TALB"].text[0] == "wAyfInders"
        assert tags["TPE2"].text[0] == "Galaxy Rise"
        assert str(tags["TDRC"].text[0]) == "2026"

    def test_track_number_includes_total(self, mp3, track):
        tag_audio_file(mp3, track)
        # "1/2" is what players need to render a complete album.
        assert ID3(mp3)["TRCK"].text[0] == "1/2"

    def test_writes_lyrics(self, mp3, track):
        tag_audio_file(mp3, track, lyrics="the words")
        assert ID3(mp3).getall("USLT")[0].text == "the words"

    def test_writes_stable_suno_id(self, mp3, track):
        tag_audio_file(mp3, track)
        ids = [f for f in ID3(mp3).getall("TXXX") if f.desc == "SUNO_ID"]
        assert ids and ids[0].text[0] == "c1"

    def test_embeds_cover(self, mp3, track):
        track.cover_bytes = b"\xff\xd8\xff\xe0fakejpeg"
        tag_audio_file(mp3, track)
        assert ID3(mp3).getall("APIC")

    def test_is_idempotent(self, mp3, track):
        tag_audio_file(mp3, track, lyrics="x")
        tag_audio_file(mp3, track, lyrics="x")
        tags = ID3(mp3)
        # Re-running must not accumulate duplicate frames.
        assert len(tags.getall("TXXX")) == len({f.desc for f in tags.getall("TXXX")})
        assert len(tags.getall("APIC")) <= 1

    def test_missing_file_is_not_fatal(self, tmp_path, track):
        assert tag_audio_file(str(tmp_path / "nope.mp3"), track) is False

    def test_unsupported_extension_skipped(self, tmp_path, track):
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"x")
        assert tag_audio_file(str(path), track) is False


class TestM3U:
    def test_orders_by_track_number(self):
        entries = [
            {"clip": clip("c2", "Second"), "relative_index": 2.0},
            {"clip": clip("c1", "First"), "relative_index": 1.0},
        ]
        plan = build_album_plans([(PLAYLIST, entries)])[0]
        text = render_m3u(plan, {"c1": "First.mp3", "c2": "Second.mp3"})
        assert text.startswith("#EXTM3U")
        assert text.index("First.mp3") < text.index("Second.mp3")

    def test_skips_tracks_absent_from_disk(self):
        entries = [
            {"clip": clip("c1", "Here"), "relative_index": 1.0},
            {"clip": clip("c2", "Gone"), "relative_index": 2.0},
        ]
        plan = build_album_plans([(PLAYLIST, entries)])[0]
        text = render_m3u(plan, {"c1": "Here.mp3"})
        assert "Here.mp3" in text and "Gone" not in text

    def test_includes_duration(self):
        plan = build_album_plans([(PLAYLIST, [{"clip": clip("c1"), "relative_index": 1.0}])])[0]
        assert "#EXTINF:200," in render_m3u(plan, {"c1": "a.mp3"})


class TestAssetDiscovery:
    def test_finds_each_asset_type(self, tmp_path):
        from scripts.tag_archive import find_track_assets

        for name in ["Song.mp3", "Song.wav", "Song.mp4", "Song.txt", "Other.mp3"]:
            (tmp_path / name).write_bytes(b"x")
        assets = find_track_assets(str(tmp_path), "Song")
        assert set(assets) == {".mp3", ".wav", ".mp4", ".txt"}
        assert os.path.basename(assets[".wav"]) == "Song.wav"

    def test_does_not_claim_another_tracks_file(self, tmp_path):
        """'Song v2.mp3' is a different track, not this one."""
        from scripts.tag_archive import find_track_assets

        for name in ["Song.mp3", "Song v2.mp3"]:
            (tmp_path / name).write_bytes(b"x")
        assets = find_track_assets(str(tmp_path), "Song")
        assert os.path.basename(assets[".mp3"]) == "Song.mp3"

    def test_finds_the_collision_suffixed_form(self, tmp_path):
        from scripts.tag_archive import find_track_assets

        (tmp_path / "Song [abcd1234].mp3").write_bytes(b"x")
        assets = find_track_assets(str(tmp_path), "Song", "abcd1234-0000")
        assert os.path.basename(assets[".mp3"]) == "Song [abcd1234].mp3"

    def test_taggable_helper_returns_audio_only(self, tmp_path):
        from scripts.tag_archive import find_track_files

        for name in ["Song.mp3", "Song.wav", "Song.mp4", "Song.txt"]:
            (tmp_path / name).write_bytes(b"x")
        found = {os.path.basename(p) for p in find_track_files(str(tmp_path), "Song")}
        assert found == {"Song.mp3", "Song.wav"}


class TestPublishedOnly:
    """Playlists hold multiple takes; publishing marks the chosen one."""

    ENTRIES = [
        {"clip": dict(clip("c1", "Take A"), is_public=True), "relative_index": 1.0},
        {"clip": dict(clip("c2", "Take A"), is_public=False), "relative_index": 2.0},
        {"clip": dict(clip("c3", "Song B"), is_public=True), "relative_index": 3.0},
    ]

    def test_includes_everything_by_default(self):
        assert len(build_album_plans([(PLAYLIST, self.ENTRIES)])[0]) == 3

    def test_filters_to_published(self):
        plan = build_album_plans([(PLAYLIST, self.ENTRIES)], published_only=True)[0]
        assert [t.title for t in plan.tracks] == ["Take A", "Song B"]

    def test_renumbers_contiguously_after_filtering(self):
        plan = build_album_plans([(PLAYLIST, self.ENTRIES)], published_only=True)[0]
        # Numbering must be 1..N over the kept tracks, not the original indexes.
        assert [t.track_number for t in plan.tracks] == [1, 2]
        assert {t.total_tracks for t in plan.tracks} == {2}


class TestDuration:
    @pytest.mark.parametrize("seconds,expected", [
        (0, "0:00"), (59, "0:59"), (60, "1:00"), (446.16, "7:26"), (3600, "60:00"),
    ])
    def test_formats(self, seconds, expected):
        from core.tagging import format_duration
        assert format_duration(seconds) == expected

    @pytest.mark.parametrize("value", [None, "", "abc"])
    def test_bad_input(self, value):
        from core.tagging import format_duration
        assert format_duration(value) == "0:00"


class TestCsvExport:
    ENTRIES = [
        {"clip": dict(clip("c1", "First"), is_public=True), "relative_index": 1.0},
        {"clip": dict(clip("c2", "Second"), is_public=False), "relative_index": 2.0},
    ]
    FILES = {
        "c1": {".mp3": "First.mp3", ".wav": "First.wav",
               ".mp4": "First.mp4", ".txt": "First.txt"},
        "c2": {".mp3": "Second.mp3"},
    }

    def _rows(self):
        from core.tagging import build_csv_rows
        plan = build_album_plans([(PLAYLIST, self.ENTRIES)])[0]
        return plan, build_csv_rows(plan, self.FILES, {"c1": "the words"})

    def test_one_row_per_track_in_order(self):
        _plan, rows = self._rows()
        assert [r["track"] for r in rows] == [1, 2]
        assert [r["title"] for r in rows] == ["First", "Second"]

    def test_carries_the_upload_filenames(self):
        _plan, rows = self._rows()
        assert rows[0]["wav_file"] == "First.wav"
        assert rows[0]["mp4_file"] == "First.mp4"

    def test_missing_files_are_blank_not_guessed(self):
        _plan, rows = self._rows()
        assert rows[1]["wav_file"] == ""

    def test_marks_published_state(self):
        _plan, rows = self._rows()
        assert [r["published"] for r in rows] == ["yes", "no"]

    def test_includes_lyrics_and_duration(self):
        _plan, rows = self._rows()
        assert rows[0]["lyrics"] == "the words"
        assert rows[0]["duration"] == "3:20"

    def test_survives_a_csv_round_trip_with_multiline_lyrics(self):
        import csv
        import io

        from core.tagging import CSV_COLUMNS, build_csv_rows
        plan = build_album_plans([(PLAYLIST, self.ENTRIES)])[0]
        rows = build_csv_rows(plan, self.FILES, {"c1": "line one\nline two,with comma"})

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

        parsed = list(csv.DictReader(io.StringIO(buffer.getvalue())))
        assert parsed[0]["lyrics"] == "line one\nline two,with comma"
        assert len(parsed) == 2

    def test_album_index_flags_duplicate_published_titles(self):
        from core.tagging import album_summary_row, build_csv_rows
        entries = [
            {"clip": dict(clip("c1", "Same"), is_public=True), "relative_index": 1.0},
            {"clip": dict(clip("c2", "Same"), is_public=True), "relative_index": 2.0},
        ]
        plan = build_album_plans([(PLAYLIST, entries)])[0]
        summary = album_summary_row(plan, build_csv_rows(plan, {}))
        assert summary["published"] == 2
        assert summary["distinct_published_titles"] == 1
        assert summary["needs_review"] == "yes"

    def test_album_index_clean_album(self):
        from core.tagging import album_summary_row
        plan, rows = self._rows()
        summary = album_summary_row(plan, rows)
        assert summary["needs_review"] == "no"
        assert summary["album"] == "wAyfInders"


class TestStyleFields:
    """The four style-related fields are distinct and must not be conflated."""

    CLIP = {
        "id": "s1",
        "title": "T",
        "display_tags": "rock, synth, ambient",
        "caption": "Prose written about the finished song.",
        "metadata": {
            "tags": "x" * 950,
            "negative_tags": "slow, ballad",
            "gpt_description_prompt": "hard rock, intense, gothic metal",
            "persona_id": "b131d7e9-fc32-48ff-a1a7-ba8f33f7f0e1",
            "prompt": "[Verse]\nwords",
        },
    }

    def test_style_is_preserved_whole(self):
        from core.tagging import clip_style
        # Previously truncated to 900; the style prompt reaches ~1000 chars.
        assert len(clip_style(self.CLIP)) == 950

    def test_exclude_styles(self):
        from core.tagging import clip_negative_style
        assert clip_negative_style(self.CLIP) == "slow, ballad"

    def test_description_prompt_is_not_the_caption(self):
        from core.tagging import clip_caption, clip_description_prompt
        assert clip_description_prompt(self.CLIP) == "hard rock, intense, gothic metal"
        assert clip_caption(self.CLIP).startswith("Prose written")

    def test_genre_stays_short_despite_a_long_style(self):
        from core.tagging import clip_genre
        assert clip_genre(self.CLIP) == "rock, synth, ambient"

    @pytest.mark.parametrize("fn", ["clip_style", "clip_negative_style",
                                    "clip_description_prompt"])
    def test_absent_fields_yield_empty(self, fn):
        import core.tagging as t
        assert getattr(t, fn)({"metadata": {}}) == ""
        assert getattr(t, fn)({}) == ""

    def test_written_to_id3_without_truncation(self, tmp_path):
        from core.tagging import build_album_plans, tag_audio_file
        path = tmp_path / "T.mp3"
        path.write_bytes(SILENT_MP3)
        plan = build_album_plans([(PLAYLIST, [{"clip": self.CLIP, "relative_index": 1.0}])])[0]
        assert tag_audio_file(str(path), plan.tracks[0])

        frames = {f.desc: f.text[0] for f in ID3(str(path)).getall("TXXX")}
        assert len(frames["SUNO_STYLE"]) == 950
        assert frames["SUNO_STYLE_EXCLUDE"] == "slow, ballad"
        assert frames["SUNO_PERSONA_ID"].startswith("b131d7e9")

    def test_absent_style_frames_are_not_written(self, tmp_path):
        from core.tagging import build_album_plans, tag_audio_file
        path = tmp_path / "T.mp3"
        path.write_bytes(SILENT_MP3)
        bare = {"id": "b", "title": "T", "metadata": {}}
        plan = build_album_plans([(PLAYLIST, [{"clip": bare, "relative_index": 1.0}])])[0]
        tag_audio_file(str(path), plan.tracks[0])
        descs = {f.desc for f in ID3(str(path)).getall("TXXX")}
        assert "SUNO_STYLE_EXCLUDE" not in descs
        assert "SUNO_ID" in descs

    def test_csv_carries_all_style_columns(self):
        from core.tagging import CSV_COLUMNS, build_album_plans, build_csv_rows
        plan = build_album_plans([(PLAYLIST, [{"clip": self.CLIP, "relative_index": 1.0}])])[0]
        row = build_csv_rows(plan, {})[0]
        for column in ("style", "exclude_style", "description_prompt", "caption"):
            assert column in CSV_COLUMNS
            assert row[column]
