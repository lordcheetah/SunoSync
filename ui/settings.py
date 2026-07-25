import os
import shutil
import datetime
import customtkinter as ctk
from ui.widgets import CollapsibleCard
from ui.layouts import create_settings_card

class SettingsTab(ctk.CTkFrame):
    """
    Global Application Settings View.
    """
    def __init__(self, parent, config_manager, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.config_manager = config_manager
        self.card_bg = "#27272a"
        
        # UI Setup
        self._setup_layout()
        self.load_settings()

    def _setup_layout(self):
        # Title
        title = ctk.CTkLabel(self, text="Settings", font=("Inter", 24, "bold"))
        title.pack(anchor="w", padx=20, pady=(20, 10))
        
        # Scrollable container
        self.container = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Use Layout Helper for common settings
        # We need to simulate 'app' object interface expected by create_settings_card
        # So we initialize the variables it expects
        self.init_variables()
        
        base_path = os.getcwd()
        self.settings_card = create_settings_card(self.container, self, base_path)
        
        # Add a Save Button/Indicator?
        # create_settings_card binds vars to nothing (it just uses them). 
        # We need to bind them to save_config.
        

        
        self.app_card = CollapsibleCard(self.container, title="Application", collapsed=False)
        self.app_card.pack(fill="x", pady=10)
        
        self.disable_sounds_var = ctk.BooleanVar(value=False)
        s = ctk.CTkSwitch(self.app_card.body, text="Disable Notification Sounds", variable=self.disable_sounds_var)
        s.pack(anchor="w", padx=10, pady=10)

        # --- Scan Settings ---
        self.scan_card = CollapsibleCard(self.container, title="Scan Configuration", collapsed=False)
        self.scan_card.pack(fill="x", pady=10)
        
        # Grid layout for scan settings
        scan_inner = ctk.CTkFrame(self.scan_card.body, fg_color="transparent")
        scan_inner.pack(fill="x", padx=10, pady=5)
        
        def add_scan_row(row, label, var, hint):
            ctk.CTkLabel(scan_inner, text=label, width=120, anchor="w").grid(row=row, column=0, pady=5, sticky="w")
            ctk.CTkEntry(scan_inner, textvariable=var, width=80).grid(row=row, column=1, pady=5, sticky="w", padx=10)
            ctk.CTkLabel(scan_inner, text=hint, text_color="gray", font=("Inter", 11)).grid(row=row, column=2, pady=5, sticky="w")
            
        add_scan_row(0, "Speed (Delay):", self.scan_speed_var, "Seconds between API requests (0.5s default)")
        add_scan_row(1, "Start Page:", self.scan_start_var, "Library page to start scanning from")
        add_scan_row(2, "Max Pages:", self.scan_max_var, "Limit number of pages to scan (0 = Unlimited)")
        
        # --- Maintenance & Debugging ---
        self.maint_card = CollapsibleCard(self.container, title="Maintenance & Debugging", collapsed=False)
        self.maint_card.pack(fill="x", pady=10)
        
        # 1. Force Rescan
        self.force_rescan_var = ctk.BooleanVar(value=False)
        rescan_frame = ctk.CTkFrame(self.maint_card.body, fg_color="transparent")
        rescan_frame.pack(fill="x", padx=5, pady=5)
        
        ctk.CTkCheckBox(rescan_frame, text="Force Rescan", variable=self.force_rescan_var).pack(anchor="w")
        ctk.CTkLabel(rescan_frame, text="Forces the downloader to re-check the server for every file, even if it exists locally.\nUseful if downloads were interrupted or files are corrupted.", 
                     text_color="gray", font=("Inter", 11), justify="left").pack(anchor="w", padx=28)

        # 2. Clear Cache
        cache_frame = ctk.CTkFrame(self.maint_card.body, fg_color="transparent")
        cache_frame.pack(fill="x", padx=5, pady=10)
        
        ctk.CTkButton(cache_frame, text="🧹 Sweep Cache", width=120, fg_color="#333", hover_color="#444", 
                      command=self.clear_cache).pack(anchor="w", padx=5)
        ctk.CTkLabel(cache_frame, text="Clears the internal list of 'seen' songs for the current session.\nDoes not delete files. Resets the queue so you can add songs again.", 
                     text_color="gray", font=("Inter", 11), justify="left").pack(anchor="w", padx=5, pady=(2,0))

        # 3. Debug Log
        debug_frame = ctk.CTkFrame(self.maint_card.body, fg_color="transparent")
        debug_frame.pack(fill="x", padx=5, pady=5)
        
        ctk.CTkButton(debug_frame, text="🐞 Open Debug Log", width=120, fg_color="#333", hover_color="#444", 
                      command=self.open_debug).pack(anchor="w", padx=5)
        ctk.CTkLabel(debug_frame, text="View raw internal logs and API responses.\nUseful for troubleshooting errors or reporting bugs.", 
                     text_color="gray", font=("Inter", 11), justify="left").pack(anchor="w", padx=5, pady=(2,0))
                     
        ctk.CTkButton(debug_frame, text="📤 Export Log File", width=120, fg_color="#333", hover_color="#444", 
                      command=self.export_log).pack(anchor="w", padx=5, pady=(10, 0))
        ctk.CTkLabel(debug_frame, text="Save the 'debug.log' file to share with developer.", 
                     text_color="gray", font=("Inter", 11), justify="left").pack(anchor="w", padx=5, pady=(2,0))
        
        self._build_bridge_card()
        self._build_privacy_card()
        self._build_about_card()

        self.save_btn = ctk.CTkButton(self, text="Save Settings", command=self.save_settings, width=200)
        self.save_btn.pack(pady=20)

    def _build_about_card(self):
        """Version and fork attribution.

        People who download the .exe never see the README, so the fork
        relationship and credit to the original author are surfaced in-app too.
        """
        import webbrowser

        from core.version import APP_VERSION, GITHUB_REPO

        self.about_card = CollapsibleCard(self.container, title="About", collapsed=False)
        self.about_card.pack(fill="x", pady=10)

        body = self.about_card.body

        ctk.CTkLabel(
            body, text=f"SunoSync v{APP_VERSION}", font=("Inter", 14, "bold"),
        ).pack(anchor="w", padx=10, pady=(10, 2))

        ctk.CTkLabel(
            body,
            text=(
                "SunoSync was created by @InternetThot.\n"
                f"This is the {GITHUB_REPO} fork, maintained by @lordcheetah,\n"
                "and is not affiliated with or endorsed by the original author."
            ),
            text_color="gray", font=("Inter", 11), justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 8))

        links = ctk.CTkFrame(body, fg_color="transparent")
        links.pack(anchor="w", padx=10, pady=(0, 10))

        def link(text, url, color="#333"):
            ctk.CTkButton(
                links, text=text, width=150, height=28, fg_color=color,
                hover_color="#444", font=("Inter", 11),
                command=lambda: webbrowser.open(url),
            ).pack(side="left", padx=(0, 8))

        link("💜 Support the creator", "https://ko-fi.com/s/374c24251c", "#7c3aed")
        link("Original project", "https://github.com/sunsetsacoustic/SunoSync")
        link("This fork", f"https://github.com/{GITHUB_REPO}")

    def _build_bridge_card(self):
        """Pairing code for the browser extension, plus session controls."""
        self.bridge_card = CollapsibleCard(self.container, title="Browser Bridge", collapsed=False)
        self.bridge_card.pack(fill="x", pady=10)

        body = self.bridge_card.body

        ctk.CTkLabel(
            body,
            text=(
                "The browser extension must present this pairing code before SunoSync\n"
                "will accept a token from it. Paste it into the extension popup once."
            ),
            text_color="gray", font=("Inter", 11), justify="left",
        ).pack(anchor="w", padx=10, pady=(10, 6))

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 6))

        self.pairing_var = ctk.StringVar(value="•" * 32)
        self._pairing_revealed = False

        self.pairing_entry = ctk.CTkEntry(
            row, textvariable=self.pairing_var, font=("Consolas", 12), state="readonly"
        )
        self.pairing_entry.pack(side="left", fill="x", expand=True)

        self.reveal_btn = ctk.CTkButton(
            row, text="Show", width=60, fg_color="#333", hover_color="#444",
            command=self.toggle_pairing_visibility,
        )
        self.reveal_btn.pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            row, text="Copy", width=60, fg_color="#7c3aed", hover_color="#6d28d9",
            command=self.copy_pairing_code,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            body, text="🔄 Regenerate pairing code", width=200,
            fg_color="#333", hover_color="#444", command=self.regenerate_pairing_code,
        ).pack(anchor="w", padx=10, pady=(4, 2))
        ctk.CTkLabel(
            body,
            text="Invalidates the old code. You will need to re-pair the extension.",
            text_color="gray", font=("Inter", 11), justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 8))

        ctk.CTkButton(
            body, text="🚪 Sign out (clear stored token)", width=240,
            fg_color="#7f1d1d", hover_color="#991b1b", command=self.clear_session,
        ).pack(anchor="w", padx=10, pady=(4, 2))
        ctk.CTkLabel(
            body,
            text="Forgets the Suno session token saved on this machine.",
            text_color="gray", font=("Inter", 11), justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 10))

    def _build_privacy_card(self):
        self.privacy_card = CollapsibleCard(self.container, title="Privacy", collapsed=False)
        self.privacy_card.pack(fill="x", pady=10)

        self.crash_reporting_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            self.privacy_card.body, text="Send anonymous crash reports",
            variable=self.crash_reporting_var,
        ).pack(anchor="w", padx=10, pady=(10, 4))

        ctk.CTkLabel(
            self.privacy_card.body,
            text=(
                "Sends the stack trace when SunoSync crashes. Tokens, cookies and\n"
                "authorization headers are stripped before anything is transmitted.\n"
                "Reporting is inactive unless this build was compiled with a Sentry DSN."
            ),
            text_color="gray", font=("Inter", 11), justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 10))

    # --- Browser bridge actions ---

    def _pairing_secret(self):
        from services.token_server import load_or_create_secret
        return load_or_create_secret()

    def toggle_pairing_visibility(self):
        self._pairing_revealed = not self._pairing_revealed
        if self._pairing_revealed:
            self.pairing_var.set(self._pairing_secret())
            self.reveal_btn.configure(text="Hide")
        else:
            self.pairing_var.set("•" * 32)
            self.reveal_btn.configure(text="Show")

    def copy_pairing_code(self):
        from tkinter import messagebox
        try:
            import pyperclip
            pyperclip.copy(self._pairing_secret())
            messagebox.showinfo(
                "Copied",
                "Pairing code copied.\n\nOpen the SunoSync extension in your browser "
                "and paste it into the pairing box.",
            )
        except Exception as e:
            messagebox.showerror("Error", f"Could not copy pairing code: {e}")

    def regenerate_pairing_code(self):
        from tkinter import messagebox
        from core.paths import get_bridge_file

        if not messagebox.askyesno(
            "Regenerate pairing code",
            "The current code will stop working and the extension will need to be "
            "re-paired.\n\nContinue?",
        ):
            return

        try:
            os.remove(get_bridge_file())
        except FileNotFoundError:
            pass
        except OSError as e:
            messagebox.showerror("Error", f"Could not reset pairing code: {e}")
            return

        new_secret = self._pairing_secret()
        if self._pairing_revealed:
            self.pairing_var.set(new_secret)

        messagebox.showinfo(
            "Pairing code regenerated",
            "Restart SunoSync for the new code to take effect, then re-pair the extension.",
        )

    def clear_session(self):
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Sign out",
            "Forget the Suno session token stored on this machine?",
        ):
            return

        self.config_manager.clear_token()
        messagebox.showinfo("Signed out", "The stored session token has been cleared.")

    def init_variables(self):
        # Variables expected by create_settings_card
        self.path_var = ctk.StringVar()
        self.path_display_var = ctk.StringVar()
        
        self.embed_thumb_var = ctk.BooleanVar(value=True)
        self.download_wav_var = ctk.BooleanVar(value=False)
        self.organize_var = ctk.BooleanVar(value=False)
        self.save_lyrics_var = ctk.BooleanVar(value=True)
        self.track_folder_var = ctk.BooleanVar(value=False)
        self.playlist_folder_var = ctk.BooleanVar(value=False)
        self.smart_resume_var = ctk.BooleanVar(value=False)
        
        # Scan vars
        self.scan_speed_var = ctk.DoubleVar(value=0.5)
        self.scan_start_var = ctk.IntVar(value=1)
        self.scan_max_var = ctk.IntVar(value=0)
        
        # Dummy variables for "app" interface if needed by other components, 
        # but create_settings_card only uses the above.
        
    def browse_folder(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(initialdir=self.path_var.get())
        if path:
            self.path_var.set(path)
            self.path_display_var.set(path) # Simple set, no truncate for full path in settings? Or truncate?
            # settings_card uses path_display_var for Entry.
            
    def clear_cache(self):
        # Access DownloaderTab logic
        if hasattr(self.master.master, 'views') and "downloader" in self.master.master.views:
             # self.master.master is likely the Content Area, so we need to go up to SunoSyncApp?
             # Actually parent passed to __init__ is self.content_area. 
             # self.master is content_area. self.master.master is SunoSyncApp.
             # Ideally we shouldn't rely on strict hierarchy, but let's try safely.
             try:
                 app = self.winfo_toplevel()
                 if hasattr(app, 'views') and "downloader" in app.views:
                     app.views["downloader"].clear_uuid_cache()
             except Exception as e:
                 print(f"Error accessing downloader: {e}")
    
    def open_debug(self):
         try:
             app = self.winfo_toplevel()
             if hasattr(app, 'views') and "downloader" in app.views:
                 app.views["downloader"].open_debug_window()
         except Exception as e:
             print(f"Error accessing debug: {e}")

    def export_log(self):
        from tkinter import filedialog, messagebox
        from core.paths import get_log_file

        # Resolve through core.paths: the log lives in the user data directory,
        # not the working directory this was previously reading from.
        log_file = get_log_file()
        if not os.path.exists(log_file):
            messagebox.showerror("Error", f"No debug log found at:\n{log_file}")
            return
            
        # timestamp for filename
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default_name = f"SunoSync_Log_{ts}.txt"
        
        target = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            initialfile=default_name,
            title="Export Debug Log"
        )
        
        if target:
            try:
                shutil.copy(log_file, target)
                messagebox.showinfo("Success", f"Log exported to:\n{target}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export log: {e}")

    def load_settings(self):
        c = self.config_manager
        self.path_var.set(c.get("path", ""))
        self.path_display_var.set(c.get("path", ""))
        
        self.embed_thumb_var.set(c.get("embed_metadata", True))
        self.download_wav_var.set(c.get("prefer_wav", False))
        self.organize_var.set(c.get("organize", False))
        self.save_lyrics_var.set(c.get("save_lyrics", True))
        self.track_folder_var.set(c.get("track_folder", False))
        self.playlist_folder_var.set(c.get("playlist_folder", False))
        self.smart_resume_var.set(c.get("smart_resume", False))
        self.disable_sounds_var.set(c.get("disable_sounds", False))
        self.force_rescan_var.set(c.get("force_rescan", False))
        
        self.scan_speed_var.set(c.get("download_delay", 0.5))
        self.scan_start_var.set(c.get("start_page", 1))
        self.scan_max_var.set(c.get("max_pages", 0))

        if hasattr(self, "crash_reporting_var"):
            self.crash_reporting_var.set(c.get("crash_reporting", True))

    def save_settings(self):
        c = self.config_manager
        c.set("path", self.path_var.get())
        c.set("embed_metadata", self.embed_thumb_var.get())
        c.set("prefer_wav", self.download_wav_var.get())
        c.set("organize", self.organize_var.get())
        c.set("save_lyrics", self.save_lyrics_var.get())
        c.set("track_folder", self.track_folder_var.get())
        c.set("playlist_folder", self.playlist_folder_var.get())
        c.set("smart_resume", self.smart_resume_var.get())
        c.set("disable_sounds", self.disable_sounds_var.get())
        c.set("force_rescan", self.force_rescan_var.get())
        
        c.set("download_delay", self.scan_speed_var.get())
        c.set("start_page", self.scan_start_var.get())
        c.set("max_pages", self.scan_max_var.get())
        c.set("crash_reporting", self.crash_reporting_var.get())
        c.save_config()
        
        # Show toast
        from tkinter import messagebox
        messagebox.showinfo("Saved", "Settings saved successfully.")
