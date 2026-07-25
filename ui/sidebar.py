import customtkinter as ctk


class Sidebar(ctk.CTkFrame):
    """Left sidebar navigation — Spotify-style."""
    def __init__(self, parent, on_navigate, **kwargs):
        super().__init__(parent, width=220, corner_radius=0,
                         fg_color="#0a0a0a", **kwargs)

        self.on_navigate = on_navigate
        self.buttons = {}
        self.indicators = {}

        self._create_widgets()

    def _create_widgets(self):
        # --- Header Area (Logo + Mini Settings) ---
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", pady=(20, 10), padx=15)
        
        # Logo
        logo_label = ctk.CTkLabel(header_frame, text="SunoSync",
                                  font=("Inter", 20, "bold"),
                                  text_color="#FFFFFF")
        logo_label.pack(side="left")
        
        # Mini Settings Icon (Redundant access)
        settings_btn = ctk.CTkButton(header_frame, text="⚙", width=24, height=24,
                                     fg_color="transparent", hover_color="#333333",
                                     font=("Inter", 14), text_color="#94a3b8",
                                     command=lambda: self.handle_click("settings"))
        settings_btn.pack(side="right")

        # Thin separator under logo
        ctk.CTkFrame(self, height=1, fg_color="#333333").pack(fill="x", padx=15, pady=(0, 10))

        # --- Bottom Container (Settings, Fixed) ---
        # Packed before the nav container so the Settings entry always keeps its
        # strip at the bottom and can never be pushed off a short window.
        self.bottom_container = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_container.pack(side="bottom", fill="x", pady=(0, 10))

        # --- Navigation Container (Top, Expands) ---
        # Scrollable: on a short window (or with more nav items than fit) the
        # entries used to run off the bottom edge with no way to reach them.
        self.nav_container = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
        )
        self.nav_container.pack(side="top", fill="both", expand=True, anchor="n")
        self._hide_scrollbar_until_needed(self.nav_container)

        # Navigation Items (Top)
        self._add_nav_item("Dashboard", "🏠", "dashboard", parent=self.nav_container)
        self._add_nav_item("Downloader", "⬇", "downloader", parent=self.nav_container)
        self._add_nav_item("Library", "🎵", "library", parent=self.nav_container)
        self._add_nav_item("Prompt Vault", "📓", "vault", parent=self.nav_container)
        
        # Settings (Bottom)
        self._add_nav_item("Settings", "⚙", "settings", parent=self.bottom_container)

    @staticmethod
    def _hide_scrollbar_until_needed(scrollable):
        """Keep the nav scrollbar out of sight unless the items overflow.

        CTkScrollableFrame always reserves room for its scrollbar, which eats
        into an already narrow sidebar. Re-checking on <Configure> lets the
        scrollbar appear only when there is genuinely something to scroll to.
        """
        try:
            bar = scrollable._scrollbar
            canvas = scrollable._parent_canvas
        except AttributeError:
            return  # CustomTkinter internals moved; degrade to always-on.

        def sync(_event=None):
            try:
                first, last = canvas.yview()
                if first <= 0.0 and last >= 1.0:
                    bar.grid_remove()
                else:
                    bar.grid()
            except Exception:
                pass

        scrollable.bind("<Configure>", sync, add="+")
        scrollable.after(200, sync)

    def set_active(self, view_name):
        """Update active state of buttons — white text + purple left border + background."""
        for name, btn in self.buttons.items():
            if name == view_name:
                # Active: bg-violet-500/10 (matched approx color #2e243f from FilterBar)
                btn.configure(fg_color="#2e243f",
                              text_color="#FFFFFF")
                # Show purple indicator
                if name in self.indicators:
                    self.indicators[name].configure(fg_color="#8B5CF6")
            else:
                btn.configure(fg_color="transparent",
                              text_color="#B3B3B3")
                # Hide indicator
                if name in self.indicators:
                    self.indicators[name].configure(fg_color="transparent")

    # --- Wrapper for Navigation with Limits ---
    def handle_click(self, view_name):
        # UNLOCKED: All features available in paid EXE
        self.on_navigate(view_name)

    # Row height in logical pixels. CustomTkinter scales this for the display.
    ITEM_HEIGHT = 34
    BUTTON_HEIGHT = 28

    def _add_nav_item(self, text, icon, view_name, parent=None, bottom=False):
        target = parent if parent else self

        # Container frame for indicator + button.
        #
        # pack_propagate(False) is load-bearing. The indicator below is a
        # CTkFrame with no height, and CustomTkinter's default frame height is
        # 200px. With propagation on, that made every row 200px tall (312px once
        # display scaling and padding were applied) for a 28px button, so the
        # nav items were spread hundreds of pixels apart and ran off the bottom
        # of the sidebar with no way to reach them.
        item_frame = ctk.CTkFrame(target, fg_color="transparent", height=self.ITEM_HEIGHT)
        item_frame.pack_propagate(False)

        # Purple left border indicator. The explicit height is what stops the
        # 200px default from coming back.
        indicator = ctk.CTkFrame(item_frame, width=4, height=self.BUTTON_HEIGHT,
                                 fg_color="transparent", corner_radius=2)
        indicator.pack(side="left", fill="y", padx=(0, 0), pady=3)
        self.indicators[view_name] = indicator

        # Navigation button
        btn = ctk.CTkButton(item_frame,
                            text=f"  {icon}  {text}",
                            anchor="w",
                            command=lambda: self.handle_click(view_name),
                            fg_color="transparent",
                            text_color="#B3B3B3",
                            hover_color="#2A2A2A",
                            height=self.BUTTON_HEIGHT,
                            font=("Inter", 13))

        btn.pack(side="left", fill="both", expand=True, padx=(3, 10), pady=3)

        item_frame.pack(fill="x", pady=1, padx=5)

        self.buttons[view_name] = btn
