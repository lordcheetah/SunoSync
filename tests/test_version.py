"""Version parsing and comparison.

These exist because the app previously carried four disagreeing hard-coded
version strings, which made shipped builds show a permanent update banner.
"""

import pytest

from core.version import APP_VERSION, parse_version


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3.0.1", (3, 0, 1)),
        ("v3.0.1", (3, 0, 1)),
        ("  v3.0.1  ", (3, 0, 1)),
        ("3.0", (3, 0, 0)),
        ("3", (3, 0, 0)),
        ("v2.1.3-beta", (2, 1, 3)),
        ("v1.2.3.4", (1, 2, 3, 4)),
    ],
)
def test_parses_common_tag_shapes(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", ["", None, "not-a-version", "vX.Y.Z", 42])
def test_unparseable_returns_empty(text):
    assert parse_version(text) == ()


def test_short_and_long_forms_compare_equal():
    # The regression that produced a permanent "update available" banner.
    assert parse_version("3.0") == parse_version("3.0.0")


def test_ordering():
    assert parse_version("3.0.1") > parse_version("3.0.0")
    assert parse_version("2.9.9") < parse_version("3.0.0")
    assert parse_version("3.1.0") > parse_version("3.0.99")


def test_app_version_is_parseable():
    assert parse_version(APP_VERSION), "APP_VERSION must be a parseable version"
