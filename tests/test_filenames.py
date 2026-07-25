"""Filename sanitisation and path budgeting."""

import os
import unicodedata

import pytest

from core.utils import (
    MAX_PATH_BUDGET,
    WINDOWS_RESERVED_NAMES,
    build_safe_path,
    sanitize_filename,
)

FORBIDDEN = '<>:"/\\|?*'


class TestSanitize:
    @pytest.mark.parametrize("char", list(FORBIDDEN))
    def test_strips_characters_windows_forbids(self, char):
        assert char not in sanitize_filename(f"song{char}title")

    def test_strips_control_characters(self):
        assert "\x00" not in sanitize_filename("song\x00title")
        assert "\x1f" not in sanitize_filename("song\x1ftitle")

    def test_strips_trailing_dots_and_spaces(self):
        # Win32 silently drops these, collapsing "foo." and "foo" into one file.
        assert sanitize_filename("song.") == "song"
        assert sanitize_filename("song   ") == "song"
        assert sanitize_filename("  song  ") == "song"

    def test_normalises_to_nfc(self):
        decomposed = unicodedata.normalize("NFD", "café")
        assert sanitize_filename(decomposed) == unicodedata.normalize("NFC", "café")

    def test_composed_and_decomposed_agree(self):
        nfc = unicodedata.normalize("NFC", "café")
        nfd = unicodedata.normalize("NFD", "café")
        assert sanitize_filename(nfc) == sanitize_filename(nfd)

    @pytest.mark.parametrize("name", sorted(WINDOWS_RESERVED_NAMES))
    def test_renames_reserved_device_names(self, name):
        assert sanitize_filename(name) != name
        assert sanitize_filename(f"{name}.mp3") != f"{name}.mp3"

    def test_reserved_check_is_case_insensitive(self):
        assert sanitize_filename("con") != "con"
        assert sanitize_filename("Com1") != "Com1"

    def test_reserved_substring_is_left_alone(self):
        assert sanitize_filename("CONCERT") == "CONCERT"
        assert sanitize_filename("Aux Cable Blues") == "Aux Cable Blues"

    def test_respects_maxlen(self):
        assert len(sanitize_filename("x" * 500, maxlen=50)) <= 50

    @pytest.mark.parametrize("name", ["", None, "...", "   ", '<>:"|?*'])
    def test_degenerate_input_yields_a_usable_name(self, name):
        result = sanitize_filename(name)
        assert result
        assert not result.endswith((" ", "."))

    def test_keeps_ordinary_titles_intact(self):
        assert sanitize_filename("Midnight Drive (Remix)") == "Midnight Drive (Remix)"


class TestBuildSafePath:
    def test_stays_within_the_path_budget(self, tmp_path):
        path = build_safe_path(str(tmp_path), "y" * 400, ".mp3")
        assert len(path) <= MAX_PATH_BUDGET

    def test_deep_directory_still_fits(self, tmp_path):
        # organize_by_month + organize_by_track nest two extra levels.
        deep = tmp_path / ("d" * 30) / ("e" * 30) / ("f" * 20)
        path = build_safe_path(str(deep), "z" * 300, ".mp3")
        assert len(path) <= MAX_PATH_BUDGET

    def test_over_budget_directory_degrades_gracefully(self, tmp_path):
        """When the directory alone exceeds the budget there is nothing to trim.

        The function cannot shorten a path the user chose, but it must still
        return a usable name rather than raising or emitting a huge one.
        """
        absurd = tmp_path / ("d" * 80) / ("e" * 80) / ("f" * 80)
        path = build_safe_path(str(absurd), "z" * 300, ".mp3")
        assert path.endswith(".mp3")
        assert len(os.path.basename(path)) < 20

    def test_extension_is_preserved_when_truncating(self, tmp_path):
        assert build_safe_path(str(tmp_path), "y" * 400, ".mp3").endswith(".mp3")
        assert build_safe_path(str(tmp_path), "y" * 400, ".wav").endswith(".wav")

    def test_distinct_long_titles_do_not_collide(self, tmp_path):
        a = build_safe_path(str(tmp_path), "y" * 300 + "AAA", ".mp3")
        b = build_safe_path(str(tmp_path), "y" * 300 + "BBB", ".mp3")
        assert a != b, "truncation must keep long titles distinguishable"

    def test_short_title_is_untouched(self, tmp_path):
        path = build_safe_path(str(tmp_path), "Short Song", ".mp3")
        assert os.path.basename(path) == "Short Song.mp3"

    def test_sanitisation_is_applied(self, tmp_path):
        base = os.path.basename(build_safe_path(str(tmp_path), 'bad:name?', ".mp3"))
        assert ":" not in base and "?" not in base
