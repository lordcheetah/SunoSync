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


def test_find_track_files_tolerates_suffixes(tmp_path):
    from scripts.tag_archive import find_track_files

    for name in ["Song.mp3", "Song.wav", "Song v2.mp3", "Other.mp3", "Song.jpg"]:
        (tmp_path / name).write_bytes(b"x")
    found = {os.path.basename(p) for p in find_track_files(str(tmp_path), "Song")}
    assert found == {"Song.mp3", "Song.wav", "Song v2.mp3"}
