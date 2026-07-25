# SunoSync

**Your World, Your Music. Seamlessly Synced.**

SunoSync is a desktop app for your Suno AI music: a bulk downloader, a local
library browser with tagging and stats, a built-in player, and a prompt vault.

![SunoSync Splash](resources/splash.png)

> **About this fork.** This is [lordcheetah/SunoSync](https://github.com/lordcheetah/SunoSync),
> forked from [sunsetsacoustic/SunoSync](https://github.com/sunsetsacoustic/SunoSync).
> It fixes a broken build, a token-bridge vulnerability, and an updater that
> pointed at the upstream author's release feed. See [CHANGELOG.txt](CHANGELOG.txt)
> and [SECURITY.md](SECURITY.md). Releases from this fork are published here, on
> this repository's [Releases page](https://github.com/lordcheetah/SunoSync/releases).

## Features

### Downloader
* **Bulk download** your Suno library in one pass, with **smart sync** that skips
  files you already have.
* **Filtering** by status (Liked, Public, Trash) and type (Generations, Uploads).
* **MP3 or WAV** output.
* **Metadata embedding**: title, artist, lyrics and cover art written into tags.
* **Organisation** into per-month, per-track or per-playlist subfolders.

### Library
* Grid browser over your downloaded collection.
* **Clean titles** — raw Suno titles are normalised into something readable.
* **Tagging**: Like, Star, Trash.
* **Stats dashboard**: top genres, monthly activity and similar breakdowns.

### Player
* Built-in playback (requires VLC), lyrics panel, media-key support, and a
  compact mini-player mode.
* Optional Discord Rich Presence.

### Prompt Vault
* Save, organise and one-click-copy your best prompts.

### Browser extension
* Syncs your Suno session token to the desktop app automatically, so you do not
  have to paste it by hand. Builds for **Chrome** and **Firefox/Zen**.

## Getting started

### Prerequisites
* **Windows** (the packaged build is Windows-only; running from source is not
  Windows-locked, but the clipboard integration is)
* **[VLC Media Player](https://www.videolan.org/)** — required by the audio engine

### Install
1. Download `SunoSync.exe` from the
   [latest release](https://github.com/lordcheetah/SunoSync/releases/latest).
2. Verify it against `SHA256SUMS.txt` on the same release page if you like.
   Builds are not code-signed, so SmartScreen will warn on first run.
3. Run it.

### Connect to Suno

**Option A — browser extension (recommended).** See below.

**Option B — manual.** Click **Get Token** in the app and follow the on-screen
steps to paste a session token.

## Browser extension

The extension watches your logged-in Suno tab and pushes a fresh session token
to the app before the old one expires.

### Build the extension

```bash
python scripts/build_extension.py
```

This writes `dist/extension-chrome/` and `dist/extension-firefox/`. Two builds
are needed because Chrome MV3 requires `background.service_worker` while Firefox
MV3 does not implement it and requires `background.scripts` plus a gecko add-on
id. Pre-built zips are attached to each release.

### Load it — Chrome / Edge / Brave
1. Go to `chrome://extensions`.
2. Enable **Developer mode**.
3. **Load unpacked** → select `dist/extension-chrome`.

### Load it — Firefox / Zen / LibreWolf
1. Go to `about:debugging#/runtime/this-firefox`.
2. **Load Temporary Add-on** → select `dist/extension-firefox/manifest.json`.
3. Firefox treats MV3 host permissions as optional. Open the extension's
   permissions and grant access to `127.0.0.1` if prompted, otherwise it cannot
   reach the app.

> Temporary add-ons are removed when the browser restarts. For a permanent
> install, sign the zip through [addons.mozilla.org](https://addons.mozilla.org/developers/)
> or use a build that permits unsigned add-ons.

### Pair it (required)

The app will not accept a token from an unpaired extension.

1. In SunoSync: **Settings → Browser Bridge → Copy**.
2. Click the extension icon in your browser.
3. Paste the code into the pairing box and hit **Save & Connect**.

The status dot turns green once the app accepts it. This exists because the
bridge previously accepted a token from *any* website you happened to be
visiting — see [SECURITY.md](SECURITY.md).

## Building from source

### Prerequisites
* **Python 3.10+**
* **Git**
* **VLC Media Player**

```bash
git clone https://github.com/lordcheetah/SunoSync.git
cd SunoSync
pip install -r requirements.txt
python main.py
```

### Compile the executable

```bash
pip install pyinstaller
pyinstaller SunoSync.spec
```

The result lands in `dist/`. The spec validates that every bundled resource
exists and aborts rather than shipping an executable with missing assets.

### Tests and linting

```bash
pip install pytest ruff
pytest          # unit tests
ruff check .    # lint
```

CI runs both on every push, plus a full PyInstaller build so that spec drift is
caught before release rather than at release.

## Updating

### From source
```bash
git pull
pip install -r requirements.txt
python main.py
```

### Standalone executable
Download the new build from the
[releases page](https://github.com/lordcheetah/SunoSync/releases/latest) and
replace the old `SunoSync.exe`.

Your settings, library cache and tags live in
`%LOCALAPPDATA%\InternetThot\SunoSync`, not next to the executable, so they are
untouched by replacing it. The library cache is schema-versioned and migrates
forward automatically; anything unreadable is backed up rather than discarded.

## Privacy and data

SunoSync stores your Suno session token **in plain text** in `config.json` in
your app data directory. **Settings → Browser Bridge → Sign out** clears it.
[SECURITY.md](SECURITY.md) explains the reasoning and the trade-off.

Crash reporting is **off** unless a build was compiled with a Sentry DSN, and can
be disabled in **Settings → Privacy**. When active, tokens, cookies and
authorization headers are stripped before anything is transmitted.

Antivirus software may flag the app because it is not digitally signed. That is
expected for unsigned PyInstaller binaries.

## Credits

Originally created by **@InternetThot**
([Ko-fi](https://ko-fi.com/s/374c24251c) ·
[Gumroad](https://justinmurray99.gumroad.com/l/rrxty) ·
[Discord](https://discord.gg/kZSc8sKUZR)).

This fork is maintained by [@lordcheetah](https://github.com/lordcheetah).

Licensed under the terms in [LICENSE](LICENSE).

---
*SunoSync is an unofficial tool and is not affiliated with Suno AI.*
