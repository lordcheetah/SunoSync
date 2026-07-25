"""Sidebar row geometry.

The nav items used to be spread hundreds of pixels apart and ran off the bottom
of the sidebar. The cause was subtle: the purple active-indicator is a CTkFrame
created without a height, and CustomTkinter's default frame height is 200px.
With pack propagation on, that stretched every row to 200px (312px once display
scaling and padding applied) around a 28px button.

These tests measure real widget geometry, so they need a display. They skip
rather than fail where Tk cannot open one.
"""

import pytest

ctk = pytest.importorskip("customtkinter")


# Module-scoped: Tk cannot reliably re-initialise after a root is destroyed in
# the same process, so a per-test root made most of these silently skip.
@pytest.fixture(scope="module")
def sidebar():
    """A realised Sidebar inside a 750px-tall window, or skip if no display."""
    import tkinter

    from ui.sidebar import Sidebar

    try:
        root = ctk.CTk()
    except tkinter.TclError as exc:
        pytest.skip(f"no display available: {exc}")

    try:
        root.geometry("760x750")
        bar = Sidebar(root, lambda _view: None)
        bar.pack(side="left", fill="y")
        # Two passes: geometry is only final once idle tasks have run.
        root.update_idletasks()
        root.update()
        root.update_idletasks()
        yield bar
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def _scaling(widget):
    try:
        return float(ctk.ScalingTracker.get_window_scaling(widget)) or 1.0
    except Exception:
        return 1.0


class TestRowHeight:
    def test_rows_are_not_the_200px_default(self, sidebar):
        """Each row should be about ITEM_HEIGHT, not CTkFrame's 200px default."""
        scale = _scaling(sidebar)
        budget = (sidebar.ITEM_HEIGHT + 12) * scale

        for name, button in sidebar.buttons.items():
            height = button.master.winfo_height()
            assert height <= budget, (
                f"nav row {name!r} is {height}px tall (budget {budget:.0f}px). "
                "A child frame is probably missing an explicit height."
            )

    def test_rows_are_tall_enough_to_click(self, sidebar):
        for name, button in sidebar.buttons.items():
            assert button.master.winfo_height() >= 20, f"nav row {name!r} collapsed"


class TestFitsOnScreen:
    def test_all_nav_items_fit_within_the_sidebar(self, sidebar):
        """The whole nav list must fit a 750px sidebar without scrolling."""
        rows = [b.master for name, b in sidebar.buttons.items() if name != "settings"]
        total = sum(r.winfo_height() for r in rows)
        assert total <= 700, (
            f"nav items need {total}px, which overflows the sidebar; "
            "they would run off the bottom edge"
        )

    def test_items_do_not_overlap(self, sidebar):
        rows = sorted(
            (b.master for n, b in sidebar.buttons.items() if n != "settings"),
            key=lambda w: w.winfo_y(),
        )
        for previous, current in zip(rows, rows[1:], strict=False):
            assert current.winfo_y() >= previous.winfo_y() + previous.winfo_height() - 1


class TestScrollability:
    def test_nav_container_can_scroll(self, sidebar):
        """Overflow must remain reachable if more items are ever added."""
        assert isinstance(sidebar.nav_container, ctk.CTkScrollableFrame)

    def test_settings_is_outside_the_scroll_area(self, sidebar):
        """Settings is pinned to the bottom, so it can never scroll away."""
        assert sidebar.buttons["settings"].master.master is sidebar.bottom_container
