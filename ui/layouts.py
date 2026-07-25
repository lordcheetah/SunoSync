"""Layout builders and dialog helpers for SunoSync GUI."""
import os
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox
import webbrowser
import pyperclip
from ui.widgets import CollapsibleCard, FilterPopup, WorkspaceBrowser

# Note: App instance passed here is expected to be a CTk class (from main.py)

def create_auth_card(parent, app):
    """Create the authorization card with token input."""
    # Parent is likely a scrollable frame or main frame
    bg = getattr(app, 'card_bg', '#27272a')
    card = CollapsibleCard(parent, title="Authorization", bg_color=bg,
                          corner_radius=12, padding=12, collapsed=False)
    card.pack(fill="x", pady=(0, 12))
    
    body = card.body
    
    ctk.CTkLabel(body, text="Bearer Token", font=("Inter", 12, "bold"), text_color="gray").pack(anchor="w", padx=5, pady=(5, 0))
    
    # Input Row
    row = ctk.CTkFrame(body, fg_color="transparent")
    row.pack(fill="x", padx=5, pady=5)
    
    app.token_var = ctk.StringVar()
    app.token_entry = ctk.CTkEntry(row, textvariable=app.token_var, show="●", width=300)
    app.token_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
    
    get_token_btn = ctk.CTkButton(row, text="Get Token", command=app.get_token_logic, width=100)
    get_token_btn.pack(side="right")
    
    return card


def create_settings_card(parent, app, base_path):
    """Create the settings card with path and toggles."""
    bg = getattr(app, 'card_bg', '#27272a')
    card = CollapsibleCard(parent, title="Download Settings", bg_color=bg,
                          corner_radius=12, padding=12, collapsed=False)
    card.pack(fill="x", pady=(0, 12))
    body = card.body
    
    # --- Path Selection ---
    ctk.CTkLabel(body, text="Download Folder", font=("Inter", 12, "bold"), text_color="gray").pack(anchor="w", padx=5, pady=(5, 0))
            
    path_row = ctk.CTkFrame(body, fg_color="transparent")
    path_row.pack(fill="x", padx=5, pady=5)
    
    app.path_var = ctk.StringVar(value=os.path.join(base_path, "Suno_Downloads"))
    app.path_display_var = ctk.StringVar() # Optional now if we bind directly, but keeping logic same
    
    # CTkEntry for path
    path_entry = ctk.CTkEntry(path_row, textvariable=app.path_display_var, state="readonly")
    path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
    
    browse_btn = ctk.CTkButton(path_row, text="Browse", command=app.browse_folder, width=80)
    browse_btn.pack(side="right")

    # --- Toggles Grid ---
    toggles_frame = ctk.CTkFrame(body, fg_color="transparent")
    toggles_frame.pack(fill="x", padx=5, pady=10)
    
    toggles_frame.columnconfigure(0, weight=1)
    toggles_frame.columnconfigure(1, weight=1)
    
    # Helpers
    def add_toggle(row, col, text, var, tooltip=""):
        # Wrapper frame not strictly needed for alignment in grid but good for consistency
        s = ctk.CTkSwitch(toggles_frame, text=text, variable=var)
        s.grid(row=row, column=col, sticky="w", padx=10, pady=8)
        # Tooltip logic removed for now or needs a CTkTooltip lib.

    app.embed_thumb_var = ctk.BooleanVar(value=True)
    add_toggle(0, 0, "Embed Metadata", app.embed_thumb_var)
    
    app.download_wav_var = ctk.BooleanVar(value=False)
    add_toggle(0, 1, "Prefer WAV", app.download_wav_var)
    
    app.organize_var = ctk.BooleanVar(value=False)
    add_toggle(1, 0, "Monthly Folders", app.organize_var)
    
    app.save_lyrics_var = ctk.BooleanVar(value=True)
    add_toggle(1, 1, "Save Lyrics (.txt)", app.save_lyrics_var)

    app.track_folder_var = ctk.BooleanVar(value=False)
    add_toggle(2, 0, "Stem Track Folder", app.track_folder_var)

    app.playlist_folder_var = ctk.BooleanVar(value=False)
    add_toggle(2, 1, "Playlist/Workspace Folders", app.playlist_folder_var)

    app.smart_resume_var = ctk.BooleanVar(value=False)
    add_toggle(3, 1, "Smart Resume", app.smart_resume_var)
    
    app.disable_sounds_var = ctk.BooleanVar(value=False)
    add_toggle(3, 0, "Disable Notification Sounds", app.disable_sounds_var)
    
    return card


def create_scraping_card(parent, app):
    """Create the scraping options card."""
    bg = getattr(app, 'card_bg', '#27272a')
    card = CollapsibleCard(parent, title="Scraping Options", bg_color=bg,
                          corner_radius=12, padding=12, collapsed=False)
    card.pack(fill="x", pady=(0, 12))
    body = card.body
    
    # Horizontal layout for inputs
    row = ctk.CTkFrame(body, fg_color="transparent")
    row.pack(fill="x", padx=5, pady=10)
    
    def add_input(frame, label, var, width=60):
        c = ctk.CTkFrame(frame, fg_color="transparent")
        c.pack(side="left", padx=(0, 20))
        ctk.CTkLabel(c, text=label, font=("Inter", 12, "bold"), text_color="gray").pack(anchor="w")
        # Spinbox doesn't exist natively in basic CTk, using Entry for now or external lib. 
        # Actually CTk doesn't have Spinbox. We'll use Entry with validation ideally, or just Entry.
        # User can type number.
        e = ctk.CTkEntry(c, textvariable=var, width=width)
        e.pack()
        return e

    app.rate_limit_var = ctk.DoubleVar(value=0.5) # Using DoubleVar for entry works if careful
    add_input(row, "Delay (s)", app.rate_limit_var)
    
    app.start_page_var = ctk.IntVar(value=1)
    add_input(row, "Start Page", app.start_page_var)
    
    app.max_pages_var = ctk.IntVar(value=0)
    add_input(row, "Max Pages", app.max_pages_var)

    # Filter/Workspace Buttons Frame
    filter_frame = ctk.CTkFrame(body, fg_color="transparent")
    filter_frame.pack(fill="x", padx=5, pady=(0, 10))
    
    app.filter_btn = ctk.CTkButton(filter_frame, text="Filters", command=app.open_filters, fg_color="transparent", border_width=1)
    app.filter_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
    
    app.workspace_btn = ctk.CTkButton(filter_frame, text="Workspaces", command=app.open_workspaces, fg_color="transparent", border_width=1)
    app.workspace_btn.pack(side="left", fill="x", expand=True, padx=5)

    app.playlist_btn = ctk.CTkButton(filter_frame, text="Playlists", command=app.open_playlists, fg_color="transparent", border_width=1)
    app.playlist_btn.pack(side="left", fill="x", expand=True, padx=(5, 0))

    # Preload Button
    app.preload_btn = ctk.CTkButton(body, text="Preload List", command=app.preload_songs, fg_color="#db2777", hover_color="#be185d")
    app.preload_btn.pack(fill="x", padx=5, pady=(5, 0))
    
    app.force_rescan_var = ctk.BooleanVar(value=False)
    rescan_chk = ctk.CTkCheckBox(body, text="Force Rescan (Ignore Cache)", variable=app.force_rescan_var, font=("Inter", 11), text_color="gray")
    rescan_chk.pack(anchor="e", padx=10, pady=(5, 5))

    return card


def create_action_area(parent, app):
    """Create the action buttons area."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="x", pady=10)
    
    # Start Button (Primary)
    app.start_btn = ctk.CTkButton(frame, text="Start Download", command=app.start_download_thread,
                                  height=45, font=("Inter", 16, "bold"), fg_color="#7c3aed", hover_color="#6d28d9")
    app.start_btn.pack(side="left", padx=(0, 10), fill="x", expand=True)
    
    # Stop Button (Destructive)
    app.stop_btn = ctk.CTkButton(frame, text="Stop", command=app.stop_download,
                                height=45, font=("Inter", 16, "bold"), fg_color="transparent", 
                                border_color="#ef4444", border_width=2, text_color="#ef4444", hover_color="#450a0a")
    app.stop_btn.pack(side="left", padx=(0, 0))
    app.stop_btn.configure(state="disabled")
    
    return frame


def _open_bridge_settings(app, dialog):
    """Jump from the token dialog to Settings, where the pairing code lives."""
    try:
        dialog.destroy()
    except Exception:
        pass
    try:
        root = app.winfo_toplevel()
        if hasattr(root, "show_view"):
            root.show_view("settings")
    except Exception:
        pass


def create_token_dialog(app):
    """Create and show the token acquisition dialog."""
    try:
        app.log("Opening Suno in your default browser...", "info")
        webbrowser.open("https://suno.com")
    except Exception:
        pass
    
    try:
        dialog = ctk.CTkToplevel(app)
        dialog.title("Get Token")
        dialog.geometry("640x620")
        dialog.minsize(460, 360)
        dialog.attributes("-topmost", True)
        dialog.lift()
        dialog.focus_force()
    except Exception:
        return

    ctk.CTkLabel(dialog, text="CONNECT TO SUNO", font=("Inter", 18, "bold")).pack(pady=(15, 8))

    # Scrollable body so the dialog stays usable on short screens. Packed at the
    # very end, after the Submit button claims the bottom strip, so that the
    # button can never be pushed off-screen by the content above it.
    body = ctk.CTkScrollableFrame(dialog, fg_color="transparent")

    # --- Option 1: Browser extension (Recommended) ---
    ext_frame = ctk.CTkFrame(body, fg_color="#1a2332", corner_radius=10)
    ext_frame.pack(fill="x", padx=14, pady=(0, 10))

    ctk.CTkLabel(ext_frame, text="⚡ Option 1 — Browser Extension (Recommended)",
                 font=("Inter", 13, "bold"), text_color="#10b981").pack(anchor="w", padx=12, pady=(10, 5))

    ctk.CTkLabel(
        ext_frame,
        text=(
            "Build the extension once, then load it in your browser:\n"
            "    python scripts/build_extension.py"
        ),
        justify="left", font=("Consolas", 10), text_color="#94a3b8",
    ).pack(anchor="w", padx=12, pady=(0, 8))

    ctk.CTkLabel(
        ext_frame,
        text=(
            "Chrome / Edge / Brave\n"
            "1. Open chrome://extensions and enable 'Developer mode'.\n"
            "2. 'Load unpacked' → select dist/extension-chrome\n"
            "\n"
            "Firefox / Zen / LibreWolf\n"
            "1. Open about:debugging#/runtime/this-firefox\n"
            "2. 'Load Temporary Add-on' → select\n"
            "    dist/extension-firefox/manifest.json\n"
            "3. Click the extension and press 'Grant access' when asked —\n"
            "    Firefox withholds site access from add-ons by default."
        ),
        justify="left", font=("Inter", 11), text_color="#B3B3B3",
    ).pack(anchor="w", padx=12, pady=(0, 8))

    pair_note = ctk.CTkFrame(ext_frame, fg_color="#0f172a", corner_radius=6)
    pair_note.pack(fill="x", padx=12, pady=(0, 10))
    ctk.CTkLabel(
        pair_note,
        text=(
            "🔑 Then pair it. Open Settings → Browser Bridge, copy the pairing\n"
            "code, and paste it into the extension popup. SunoSync ignores tokens\n"
            "from anything that cannot present that code."
        ),
        justify="left", font=("Inter", 11), text_color="#fbbf24",
    ).pack(anchor="w", padx=10, pady=8)

    ctk.CTkButton(
        ext_frame, text="Open Settings → Browser Bridge", height=30, width=240,
        fg_color="#334155", hover_color="#475569", font=("Inter", 11),
        command=lambda: _open_bridge_settings(app, dialog),
    ).pack(anchor="w", padx=12, pady=(0, 12))

    # --- Divider ---
    ctk.CTkLabel(body, text="— OR —", font=("Inter", 11), text_color="#666").pack(pady=5)

    # --- Option 2: Manual (Original) ---
    manual_frame = ctk.CTkFrame(body, fg_color="#1f1f2e", corner_radius=10)
    manual_frame.pack(fill="x", padx=14, pady=(0, 10))

    ctk.CTkLabel(manual_frame, text="📋 Option 2 — Manual (Console)",
                 font=("Inter", 13, "bold"), text_color="#8B5CF6").pack(anchor="w", padx=12, pady=(10, 5))

    steps = (
        "1. Log in to Suno in the opened browser tab.\n"
        "2. Press F12 to open Developer Tools.\n"
        "3. Go to the 'Console' tab.\n"
        "4. Copy the code below and paste it, then press Enter."
    )
    ctk.CTkLabel(manual_frame, text=steps, justify="left", font=("Inter", 11),
                 text_color="#B3B3B3").pack(anchor="w", padx=12, pady=(0, 5))
    
    code = "window.Clerk.session.getToken().then(t => prompt('Copy this token:', t))"
    
    code_frame = ctk.CTkFrame(manual_frame, fg_color="#272727")
    code_frame.pack(fill="x", padx=12, pady=5)
    
    code_entry = ctk.CTkEntry(code_frame, font=("Consolas", 11))
    code_entry.insert(0, code)
    code_entry.configure(state="readonly")
    code_entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)
    
    def copy_code():
        pyperclip.copy(code)
        
    ctk.CTkButton(code_frame, text="Copy", command=copy_code, width=50, height=24,
                  fg_color="#444", hover_color="#555").pack(side="left", padx=8)
    copy_code() # Auto copy
    
    ctk.CTkLabel(manual_frame, text="5. Copy the token from the popup → paste below:",
                 justify="left", font=("Inter", 11), text_color="#B3B3B3").pack(anchor="w", padx=12, pady=(5, 2))
    
    token_input = ctk.CTkEntry(manual_frame, fg_color="#272727", border_color="#333",
                               text_color="#fff", font=("Inter", 11))
    token_input.pack(fill="x", padx=12, pady=(0, 10))
    token_input.focus_set()
    
    def submit():
        t = token_input.get().strip()
        if t:
            app.token_var.set(t)
            app.log("Token set successfully!", "success")
            app.save_config()
            dialog.destroy()
        else:
            pass
    
    # Reserve the bottom strip before the scrollable body claims the cavity.
    ctk.CTkButton(dialog, text="Submit Token", command=submit, height=40,
                  fg_color="#7c3aed", hover_color="#6d28d9").pack(side="bottom", pady=15)
    body.pack(fill="both", expand=True, padx=6)
