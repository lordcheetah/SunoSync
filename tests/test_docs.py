"""Documentation invariants.

Two things regressed in the past and are cheap to pin down here: the README
advertised features that did not exist in the codebase, and it pointed at a
clone URL for a repository that is not this one. The fork attribution is checked
for the same reason — it is easy to lose in a large edit.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
LICENSE = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
SECURITY = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
CHANGELOG = (REPO_ROOT / "CHANGELOG.txt").read_text(encoding="utf-8")

UPSTREAM = "sunsetsacoustic/SunoSync"
FORK = "lordcheetah/SunoSync"

# Prose is hard-wrapped, so a phrase can straddle a newline (and a "> " quote
# marker). Flatten before matching.
def flat(text: str) -> str:
    return re.sub(r"[\s>]+", " ", text).lower()


def section(text: str, heading: str) -> str:
    """Return the body of a markdown section, up to the next same-level heading."""
    match = re.search(
        rf"^{re.escape(heading)}\s*$(.*?)(?=^#{{1,2}} |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1) if match else ""


DOCS = [("README.md", README), ("SECURITY.md", SECURITY)]
DOC_IDS = [name for name, _ in DOCS]


class TestForkAttribution:
    @pytest.mark.parametrize(
        "text",
        [README, SECURITY, CHANGELOG],
        ids=["README.md", "SECURITY.md", "CHANGELOG.txt"],
    )
    def test_credits_the_original_project(self, text):
        assert UPSTREAM in text, "must link back to the original project"

    @pytest.mark.parametrize("name,text", DOCS, ids=DOC_IDS)
    def test_states_it_is_a_fork(self, name, text):
        assert "fork" in text.lower(), f"{name} must say this is a fork"

    @pytest.mark.parametrize("name,text", DOCS, ids=DOC_IDS)
    def test_disclaims_endorsement(self, name, text):
        assert "affiliated with or endorsed by" in flat(text), (
            f"{name} must disclaim affiliation with the original author"
        )

    def test_readme_credits_the_original_author(self):
        assert "InternetThot" in README

    def test_readme_points_support_at_the_original_author(self):
        credits = section(README, "## Credits")
        assert credits, "README must have a Credits section"
        assert "ko-fi.com" in credits, "credits should link the author's support page"

    def test_license_retains_original_copyright(self):
        # Required by the MIT license this project is distributed under.
        assert "Copyright (c) 2024 SunoSync" in LICENSE
        assert UPSTREAM in LICENSE


class TestCloneInstructions:
    def test_clone_url_points_at_this_repository(self):
        assert f"git clone https://github.com/{FORK}.git" in README

    def test_does_not_reference_the_nonexistent_v2_repo(self):
        # The original README told users to clone "SunoSyncV2", which is not
        # this repository and does not exist.
        assert "SunoSyncV2" not in README


class TestNoPhantomFeatures:
    """The README advertised subsystems that are not in the codebase.

    Scoped to the Features section: prose elsewhere may legitimately name these
    while explaining that they were removed.
    """

    @pytest.mark.parametrize(
        "claim", ["Live Radio", "On-Air", "Mobile Bridge", "QR code", "broadcast"]
    )
    def test_removed_claims_are_not_advertised_as_features(self, claim):
        features = section(README, "## Features")
        assert features, "README must have a Features section"
        assert claim.lower() not in features.lower(), (
            f"README advertises {claim!r}, which is not implemented"
        )

    def test_crash_reporting_is_described_as_opt_in(self):
        # Sentry shipped with a placeholder DSN, so "Crash Shield" was inert.
        assert "crash reporting is **off**" in README.lower()
