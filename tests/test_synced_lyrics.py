"""Word-timing alignment -> LRC / SRT."""

import pytest

from core.synced_lyrics import (
    MAX_CUE_SECONDS,
    group_into_lines,
    parse_aligned_lyrics,
    render_lrc,
    render_srt,
)

# Shape confirmed against the live endpoint: [words, confidences, score].
RESPONSE = {
    "data": [
        [
            {"word": "Twenty ", "success": True, "start_s": 10.0, "end_s": 10.4, "p_align": 0.99},
            {"word": "thousand ", "success": True, "start_s": 10.4, "end_s": 10.9},
            {"word": "years\n", "success": True, "start_s": 10.9, "end_s": 11.6},
            {"word": "we ", "success": True, "start_s": 12.0, "end_s": 12.2},
            {"word": "crossed\n", "success": True, "start_s": 12.2, "end_s": 13.4},
        ],
        [0.001, 0.002],
        0.229,
    ]
}


class TestParsing:
    def test_extracts_words_from_the_triple(self):
        words = parse_aligned_lyrics(RESPONSE)
        assert len(words) == 5
        assert words[0]["word"] == "Twenty "
        assert words[0]["start"] == 10.0

    def test_accepts_a_bare_word_list(self):
        assert len(parse_aligned_lyrics([{"word": "a", "start_s": 0, "end_s": 1}])) == 1

    def test_accepts_the_data_value_directly(self):
        assert len(parse_aligned_lyrics(RESPONSE["data"])) == 5

    @pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": []}, None, "nope"])
    def test_bad_payloads_yield_nothing(self, payload):
        assert parse_aligned_lyrics(payload) == []

    def test_skips_entries_missing_timings(self):
        payload = {"data": [[{"word": "x"}, {"word": "y", "start_s": 1, "end_s": 2}], [], 0]}
        assert len(parse_aligned_lyrics(payload)) == 1

    def test_repairs_reversed_timings(self):
        payload = {"data": [[{"word": "x", "start_s": 5, "end_s": 2}], [], 0]}
        assert parse_aligned_lyrics(payload)[0]["end"] == 5


class TestLineGrouping:
    def test_splits_on_embedded_newlines(self):
        lines = group_into_lines(parse_aligned_lyrics(RESPONSE))
        assert [line["text"] for line in lines] == ["Twenty thousand years", "we crossed"]

    def test_line_starts_at_its_first_word(self):
        lines = group_into_lines(parse_aligned_lyrics(RESPONSE))
        assert lines[0]["start"] == 10.0
        assert lines[1]["start"] == 12.0

    def test_blank_lines_are_dropped(self):
        words = [{"word": "a\n\n\nb", "start": 1.0, "end": 2.0}]
        assert [line["text"] for line in group_into_lines(words)] == ["a", "b"]

    def test_cues_do_not_overlap(self):
        lines = group_into_lines(parse_aligned_lyrics(RESPONSE))
        for previous, following in zip(lines, lines[1:], strict=False):
            assert previous["end"] <= following["start"]

    def test_long_lines_are_capped(self):
        words = [{"word": "x\n", "start": 0.0, "end": 300.0}]
        assert group_into_lines(words)[0]["end"] <= MAX_CUE_SECONDS

    def test_very_short_lines_are_held_readable(self):
        words = [{"word": "x\n", "start": 0.0, "end": 0.01}]
        assert group_into_lines(words)[0]["end"] > 0.01

    def test_empty_input(self):
        assert group_into_lines([]) == []

    def test_trailing_line_without_newline_is_kept(self):
        words = [{"word": "final words", "start": 1.0, "end": 2.0}]
        assert [line["text"] for line in group_into_lines(words)] == ["final words"]


class TestLrc:
    def test_timestamps_and_text(self):
        lines = group_into_lines(parse_aligned_lyrics(RESPONSE))
        text = render_lrc(lines)
        assert "[00:10.00]Twenty thousand years" in text
        assert "[00:12.00]we crossed" in text

    def test_metadata_header(self):
        text = render_lrc([], title="Beringia", artist="Galaxy Rise", album="wAyfInders")
        assert "[ti:Beringia]" in text and "[ar:Galaxy Rise]" in text and "[al:wAyfInders]" in text

    def test_minutes_roll_over(self):
        text = render_lrc([{"text": "late", "start": 125.5, "end": 127.0}])
        assert "[02:05.50]late" in text

    def test_empty_is_still_valid(self):
        assert render_lrc([]).strip() == ""


class TestSrt:
    def test_numbering_and_arrow_format(self):
        lines = group_into_lines(parse_aligned_lyrics(RESPONSE))
        text = render_srt(lines)
        assert text.startswith("1\n")
        assert "00:00:10,000 --> " in text
        assert "Twenty thousand years" in text

    def test_blocks_separated_by_blank_line(self):
        lines = group_into_lines(parse_aligned_lyrics(RESPONSE))
        assert "\n\n2\n" in render_srt(lines)

    def test_hours_are_rendered(self):
        text = render_srt([{"text": "x", "start": 3661.25, "end": 3662.0}])
        assert "01:01:01,250" in text

    def test_millisecond_rounding_does_not_produce_1000(self):
        text = render_srt([{"text": "x", "start": 1.9999, "end": 3.0}])
        assert ",1000" not in text

    def test_empty_input(self):
        assert render_srt([]) == ""


class TestAnnotationFiltering:
    """Bracketed stage directions are not sung and must not become captions."""

    WORDS = [
        {"word": "[Intro — Instrumental]\n", "start": 31.83, "end": 31.85},
        {"word": "[Verse 1]\n", "start": 31.85, "end": 31.86},
        {"word": "The ice had swallowed half the sky\n", "start": 44.28, "end": 47.4},
        {"word": "The sea had pulled its waters dry\n", "start": 47.53, "end": 50.5},
    ]

    def test_annotations_are_dropped(self):
        lines = group_into_lines(self.WORDS)
        assert [line["text"] for line in lines] == [
            "The ice had swallowed half the sky",
            "The sea had pulled its waters dry",
        ]

    def test_can_be_kept_when_asked(self):
        assert len(group_into_lines(self.WORDS, drop_annotations=False)) == 4

    def test_sung_lines_keep_a_readable_duration(self):
        """Regression: annotations used to clamp the next line to milliseconds."""
        lines = group_into_lines(self.WORDS)
        assert lines[0]["end"] - lines[0]["start"] > 1.0

    @pytest.mark.parametrize("text,expected", [
        ("[Verse 1]", True),
        ("[Wind. Silence. Then the drum]", True),
        ("The ice had swallowed half the sky", False),
        ("", False),
        ("[not closed", False),
    ])
    def test_annotation_detection(self, text, expected):
        from core.synced_lyrics import is_annotation
        assert is_annotation(text) is expected

    def test_all_annotations_yields_nothing(self):
        words = [{"word": "[Intro]\n", "start": 1.0, "end": 1.01}]
        assert group_into_lines(words) == []
