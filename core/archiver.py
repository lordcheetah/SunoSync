"""Bulk archive of a Suno library, organised by playlist.

Built for a one-off, unattended run against a deadline, so the priorities are
different from the interactive downloader:

* **Resumable.** Every asset is skipped if it already exists on disk, and the
  manifest records *which* asset kinds each clip has, so a later run asking for
  more (a WAV pass after a --no-wav pass) correctly picks up the difference.
  Interrupt and re-run as often as you like.
* **Download once, copy many.** A track in five playlists is fetched from the
  network once and copied into the other four folders. Re-downloading would
  multiply bandwidth and the risk of being rate-limited for no benefit.
* **Never lose the run to one bad track.** A failure on any single asset is
  recorded and the sweep continues.

Per track it collects: MP3, WAV (optional; see the cost note below), cover art,
lyrics, and the generated video.

A note on WAV
-------------
The feed exposes no WAV URL. Each one requires a server-side conversion --
``POST /api/gen/{id}/convert_wav/`` followed by polling for up to two minutes.
That is slow and is the part of this process most likely to be metered or
throttled by Suno. ``--no-wav`` skips it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from typing import Any

import requests

from core.utils import build_safe_path, sanitize_filename

logger = logging.getLogger(__name__)

API_BASE = "https://studio-api.prod.suno.com"

PLAYLISTS_URL = API_BASE + "/api/playlist/me?page={page}&show_trashed=false&show_sharelist=false"
PLAYLIST_URL = API_BASE + "/api/playlist/{playlist_id}/?page={page}"
FEED_URL = API_BASE + "/api/feed/v2?is_public=true&page={page}"
CONVERT_WAV_URL = API_BASE + "/api/gen/{clip_id}/convert_wav/"
WAV_FILE_URL = API_BASE + "/api/gen/{clip_id}/wav_file/"

UNSORTED_FOLDER = "_Unsorted"
PLAYLISTS_FOLDER = "Playlists"
MANIFEST_NAME = "archive_manifest.json"
# v1 recorded only that a clip was processed; v2 records which asset kinds.
MANIFEST_SCHEMA = 2

# Per-track sizes for the --dry-run estimate. Measured from real tracks rather
# than guessed: WAV in particular came out at ~68 MB for a 7-minute piece, half
# again as large as a first estimate, which materially changes whether an
# archive fits on a given drive.
ESTIMATED_BYTES = {
    "mp3": 8 * 1024 * 1024,
    "wav": 68 * 1024 * 1024,
    "mp4": 14 * 1024 * 1024,
    "jpg": 170 * 1024,
    "txt": 4 * 1024,
}

# Observed wall-clock for one WAV render request plus polling.
WAV_RENDER_SECONDS = 17


class ArchiveError(Exception):
    """Unrecoverable problem, such as a rejected token."""


# --------------------------------------------------------------------------
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------

def clip_title(clip: dict) -> str:
    """A usable title for a clip, even when Suno left it blank."""
    title = (clip.get("title") or "").strip()
    if not title:
        title = (clip.get("metadata") or {}).get("prompt", "").strip().split("\n")[0][:60]
    if not title:
        title = f"untitled-{str(clip.get('id', ''))[:8]}"
    return title


def clip_lyrics(clip: dict) -> str:
    """Lyrics text for a clip, or '' when there is none."""
    md = clip.get("metadata") or {}
    for key in ("lyrics", "text", "prompt"):
        value = md.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def cover_url(clip: dict) -> str | None:
    """Prefer the large artwork; the small one is a thumbnail."""
    for key in ("image_large_url", "image_url"):
        value = clip.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


def find_wav_url(data: Any, _depth: int = 0) -> str | None:
    """Recursively hunt for a .wav URL in a conversion response."""
    if _depth > 6:
        return None
    if isinstance(data, str):
        value = data.strip()
        if value.lower().startswith("http") and ".wav" in value.lower():
            return value
        return None
    if isinstance(data, dict):
        for key in ("audio_url_wav", "wav_url", "wav_audio_url", "master_wav_url"):
            found = find_wav_url(data.get(key), _depth + 1)
            if found:
                return found
        for value in data.values():
            found = find_wav_url(value, _depth + 1)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = find_wav_url(item, _depth + 1)
            if found:
                return found
    return None


def extract_playlist_clips(payload: dict) -> list[dict]:
    """Pull the clip objects out of a playlist response.

    The API nests them as ``playlist_clips: [{clip: {...}}]`` but has used
    other shapes, so several are accepted.
    """
    if not isinstance(payload, dict):
        return []

    raw = None
    for key in ("playlist_clips", "clips", "items"):
        if isinstance(payload.get(key), list):
            raw = payload[key]
            break
    if raw is None and isinstance(payload.get("playlist"), dict):
        return extract_playlist_clips(payload["playlist"])
    if raw is None:
        return []

    clips = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        clip = entry.get("clip") if isinstance(entry.get("clip"), dict) else entry
        if clip.get("id"):
            clips.append(clip)
    return clips


def assign_folder_names(playlists: list[dict]) -> dict[str, str]:
    """Map playlist id -> a unique folder name.

    Playlist names are not unique: this account has two called
    'skepticAl humanIsm' and two called 'cArcosa carnIval'. Left alone they
    share a directory, so two different albums merge and their track numbering
    collides.

    The lowest-id playlist of a colliding group keeps the plain name and the
    rest get a short id suffix. Sorting by id (rather than by API order) keeps
    the assignment stable across runs, so a resumed archive does not suddenly
    rename folders.
    """
    # Grouped case-insensitively, because Windows and SMB shares are. Two
    # playlists named 'AxIom' and 'Axiom' are distinct to Suno but resolve to
    # one directory on disk, which would silently merge them.
    grouped: dict[str, list[dict]] = {}
    for playlist in playlists:
        name = sanitize_filename((playlist.get("name") or "").strip()) or "Untitled Playlist"
        grouped.setdefault(name.casefold(), []).append(playlist)

    names: dict[str, str] = {}
    for group in grouped.values():
        ordered = sorted(group, key=lambda p: str(p.get("id", "")))
        for position, playlist in enumerate(ordered):
            pid = str(playlist.get("id", ""))
            # Each keeps its own spelling; only the duplicates gain a suffix.
            own = sanitize_filename((playlist.get("name") or "").strip()) or "Untitled Playlist"
            names[pid] = own if position == 0 else f"{own} [{pid[:8]}]"
    return names


def plan_destinations(clip_id: str, membership: dict[str, list[str]]) -> list[str]:
    """Folder names a clip should be archived into.

    Returns playlist folder names, or ``[_Unsorted]`` when the track belongs to
    no playlist, so that nothing public is silently dropped.
    """
    names = membership.get(clip_id) or []
    if not names:
        return [UNSORTED_FOLDER]
    # Deduplicate while keeping playlist order stable.
    seen, ordered = set(), []
    for name in names:
        safe = sanitize_filename(name) or "Untitled Playlist"
        if safe not in seen:
            seen.add(safe)
            ordered.append(safe)
    return ordered


def assign_track_stems(all_clips: dict[str, dict],
                       membership: dict[str, list[str]]) -> dict[str, str]:
    """Map clip id -> filename stem, disambiguating same-titled tracks.

    Two clips with the same title landing in the same folder resolve to the
    same path. Because a download is skipped when its file already exists, the
    second track was silently never archived -- it simply went missing, with no
    error. Several playlists here have two published takes sharing a title.

    Any clip whose title collides inside a folder gets a short id suffix, in
    every folder it appears in, so a track's filename is the same everywhere.
    """
    colliding: set[str] = set()
    per_folder: dict[str, dict[str, set[str]]] = {}

    for clip_id, clip in all_clips.items():
        stem = sanitize_filename(clip_title(clip)).casefold()
        for folder in plan_destinations(clip_id, membership):
            per_folder.setdefault(folder, {}).setdefault(stem, set()).add(clip_id)

    for titles in per_folder.values():
        for clip_ids in titles.values():
            if len(clip_ids) > 1:
                colliding.update(clip_ids)

    stems = {}
    for clip_id, clip in all_clips.items():
        title = clip_title(clip)
        stems[clip_id] = f"{title} [{clip_id[:8]}]" if clip_id in colliding else title
    return stems


def estimate_bytes(track_count: int, want_wav: bool, want_video: bool) -> int:
    per_track = ESTIMATED_BYTES["mp3"] + ESTIMATED_BYTES["jpg"] + ESTIMATED_BYTES["txt"]
    if want_wav:
        per_track += ESTIMATED_BYTES["wav"]
    if want_video:
        per_track += ESTIMATED_BYTES["mp4"]
    return per_track * track_count


def human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if count < 1024 or unit == "TB":
            return f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} TB"


# --------------------------------------------------------------------------
# Archiver
# --------------------------------------------------------------------------

class Archiver:
    def __init__(self, token, out_dir, *, want_wav=True, want_video=True,
                 delay=1.0, session=None, dry_run=False, wav_timeout=120,
                 token_provider=None):
        self.token = token
        # Suno session tokens live about a minute and are refreshed into
        # SunoSync's config by the browser extension. A multi-hour run must
        # therefore be able to re-read the token, or it dies partway through.
        self._token_provider = token_provider
        self.out_dir = os.path.abspath(out_dir)
        self.want_wav = want_wav
        self.want_video = want_video
        self.delay = max(0.0, float(delay))
        self.dry_run = dry_run
        self.wav_timeout = wav_timeout
        self.session = session or requests.Session()
        self.stats = {
            "tracks": 0, "downloaded": 0, "copied": 0,
            "skipped": 0, "failed": 0, "bytes": 0,
        }
        self.failures: list[str] = []
        self._last_request = 0.0

    # --- plumbing ------------------------------------------------------

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "SunoSync-Archiver/1.0",
        }

    def refresh_token(self):
        """Re-read the session token. Returns True when a new one was found."""
        if self._token_provider is None:
            return False
        try:
            fresh = (self._token_provider() or "").strip()
        except Exception:
            logger.debug("Token provider failed", exc_info=True)
            return False
        if fresh and fresh != self.token:
            self.token = fresh
            logger.info("Picked up a refreshed session token; continuing.")
            return True
        return False

    def _throttle(self):
        """Keep a floor between API calls so the sweep stays polite."""
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def _get_json(self, url, timeout=30, _retried=False):
        self._throttle()
        response = self.session.get(url, headers=self.headers, timeout=timeout)
        if response.status_code == 401:
            if not _retried and self.refresh_token():
                return self._get_json(url, timeout, _retried=True)
            raise ArchiveError(
                "Suno rejected the token (401). Open SunoSync, let the extension "
                "refresh your session, then re-run."
            )
        if response.status_code == 429:
            raise ArchiveError(
                "Suno is rate-limiting this account (429). Wait a while and "
                "re-run — the archive resumes where it stopped."
            )
        response.raise_for_status()
        return response.json()

    # --- enumeration ---------------------------------------------------

    def fetch_playlists(self, max_pages=100):
        """Every playlist the user owns."""
        playlists, page = [], 1
        while page <= max_pages:
            payload = self._get_json(PLAYLISTS_URL.format(page=page))
            batch = payload.get("playlists") or []
            if not batch:
                break
            for entry in batch:
                # Skip Suno's curated/discover lists; archive only the user's own.
                if entry.get("is_discover_playlist"):
                    continue
                if entry.get("is_owned") is False:
                    continue
                playlists.append(entry)
            page += 1
        logger.info("Found %d playlists", len(playlists))
        return playlists

    def fetch_playlist_clips(self, playlist, max_pages=100):
        """Every clip in one playlist, following pagination."""
        clips, seen, page = [], set(), 1
        playlist_id = playlist.get("id")
        while page <= max_pages:
            try:
                payload = self._get_json(PLAYLIST_URL.format(playlist_id=playlist_id, page=page))
            except requests.HTTPError as exc:
                logger.warning("Playlist %s page %d failed: %s", playlist_id, page, exc)
                break
            batch = extract_playlist_clips(payload)
            fresh = [c for c in batch if c.get("id") not in seen]
            if not fresh:
                break
            for clip in fresh:
                seen.add(clip["id"])
                clips.append(clip)
            page += 1
        return clips

    def fetch_public_clips(self, max_pages=500):
        """Every public clip in the account."""
        clips, seen, page = [], set(), 0
        while page < max_pages:
            payload = self._get_json(FEED_URL.format(page=page))
            batch = payload.get("clips") or payload.get("items") or []
            if not batch:
                break
            fresh = 0
            for clip in batch:
                cid = clip.get("id")
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                # The endpoint is filtered server-side, but double-check: this
                # decides what gets archived before the download limit lands.
                if clip.get("is_public"):
                    clips.append(clip)
                fresh += 1
            if fresh == 0:
                break
            page += 1
            logger.info("Scanned %d public tracks so far...", len(clips))
        return clips

    def build_membership(self, playlists):
        """Map clip id -> [folder names], and collect the clips themselves.

        Folder names are pre-disambiguated by assign_folder_names, so two
        playlists sharing a name do not end up merged in one directory.
        """
        folder_names = assign_folder_names(playlists)
        membership: dict[str, list[str]] = {}
        clips_by_id: dict[str, dict] = {}

        for playlist in playlists:
            folder = folder_names.get(str(playlist.get("id", ""))) or "Untitled Playlist"
            clips = self.fetch_playlist_clips(playlist)
            logger.info("Playlist %-44s %d tracks", folder[:44], len(clips))
            for clip in clips:
                cid = clip["id"]
                membership.setdefault(cid, []).append(folder)
                clips_by_id.setdefault(cid, clip)
        return membership, clips_by_id

    # --- downloading ---------------------------------------------------

    def _download_to(self, url, path, timeout=180):
        """Stream a URL to disk. Returns bytes written, or 0 when skipped."""
        if os.path.exists(path) and os.path.getsize(path) > 0:
            self.stats["skipped"] += 1
            return 0
        if self.dry_run:
            return 0

        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = path + ".part"
        self._throttle()
        try:
            with self.session.get(url, headers=self.headers, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                written = 0
                with open(temp, "wb") as handle:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            handle.write(chunk)
                            written += len(chunk)
            if written == 0:
                os.unlink(temp)
                raise OSError("empty response")
            # Rename only once complete, so an interrupted run never leaves a
            # truncated file that the resume logic would mistake for finished.
            os.replace(temp, path)
            self.stats["downloaded"] += 1
            self.stats["bytes"] += written
            return written
        except Exception:
            if os.path.exists(temp):
                try:
                    os.unlink(temp)
                except OSError:
                    pass
            raise

    def request_wav_url(self, clip_id):
        """Ask Suno to render a WAV, then wait for it. None if unavailable.

        Renders are ephemeral -- a WAV fetched last week is gone today -- so the
        conversion must be requested fresh every time.

        Auth failures abort the whole run rather than being absorbed. Previously
        a 401 fell through to the poll loop, which spent the full timeout seeing
        401s and then reported "conversion unavailable or timed out". With an
        expired token that is 2 minutes wasted per track, and 607 tracks spent
        about 20 hours producing nothing but a misleading error.
        """
        self._throttle()
        try:
            response = self.session.post(
                CONVERT_WAV_URL.format(clip_id=clip_id), headers=self.headers, timeout=20
            )
        except requests.RequestException as exc:
            logger.debug("convert_wav failed for %s: %s", clip_id, exc)
            return None

        if response.status_code in (401, 403):
            if not self.refresh_token():
                raise ArchiveError(
                    "Suno rejected the token while converting WAV (HTTP "
                    f"{response.status_code}). Session tokens expire in about a "
                    "minute, so a long run needs SunoSync open with the browser "
                    "extension syncing. Re-run once it is; finished tracks are kept."
                )
            self._throttle()
            response = self.session.post(
                CONVERT_WAV_URL.format(clip_id=clip_id), headers=self.headers, timeout=20
            )
        if response.status_code == 429:
            raise ArchiveError(
                "Suno is rate-limiting WAV conversion (429). Wait a while and "
                "re-run -- the archive resumes where it stopped."
            )
        if response.status_code not in (200, 201, 202, 204, 409):
            logger.debug("convert_wav returned %s for %s", response.status_code, clip_id)

        # Observed: the render lands within about 1-7 seconds and the response
        # is {} until it does, then {"wav_file_url": "..."}.
        deadline = time.monotonic() + self.wav_timeout
        last_status = None
        while time.monotonic() < deadline:
            try:
                self._throttle()
                poll = self.session.get(
                    WAV_FILE_URL.format(clip_id=clip_id), headers=self.headers, timeout=20
                )
                last_status = poll.status_code
                if poll.status_code == 200:
                    url = find_wav_url(poll.json())
                    if url:
                        return url
                elif poll.status_code in (401, 403):
                    if not self.refresh_token():
                        raise ArchiveError(
                            "Suno rejected the token while polling for WAV (HTTP "
                            f"{poll.status_code}). Re-run with SunoSync open so the "
                            "extension can keep the session fresh."
                        )
                elif poll.status_code == 429:
                    raise ArchiveError(
                        "Suno is rate-limiting WAV conversion (429). Wait and re-run."
                    )
            except (requests.RequestException, ValueError) as exc:
                logger.debug("wav poll failed for %s: %s", clip_id, exc)
            time.sleep(3)

        self._last_wav_status = last_status
        logger.debug("wav render never appeared for %s (last status %s)", clip_id, last_status)
        return None

    @property
    def wanted_kinds(self) -> set[str]:
        """Asset kinds this run is trying to collect."""
        kinds = {"mp3", "jpg", "txt"}
        if self.want_wav:
            kinds.add("wav")
        if self.want_video:
            kinds.add("mp4")
        return kinds

    def archive_clip(self, clip, folders, stem=None):
        """Fetch every asset for one clip into the first folder, copy to the rest.

        ``stem`` overrides the filename base; pass the value from
        assign_track_stems so same-titled tracks do not overwrite each other.

        Returns the set of asset kinds now secured for this clip, which the
        manifest records. A kind counts as secured when its file is on disk, or
        when the clip simply has no such asset (no video, no lyrics). WAV counts
        only when the file exists, so a failed or throttled render is retried on
        the next run rather than being marked done.
        """
        title = stem or clip_title(clip)
        secured: set[str] = set()
        clip_id = clip.get("id", "")
        primary = os.path.join(self.out_dir, folders[0])

        assets = []
        if clip.get("audio_url"):
            assets.append((".mp3", clip["audio_url"]))
        else:
            secured.add("mp3")  # nothing to fetch
        if self.want_video:
            if clip.get("video_url"):
                assets.append((".mp4", clip["video_url"]))
            else:
                secured.add("mp4")
        cover = cover_url(clip)
        if cover:
            assets.append((".jpg", cover))
        else:
            secured.add("jpg")

        written_paths = []

        for extension, url in assets:
            path = build_safe_path(primary, title, extension)
            try:
                self._download_to(url, path)
                written_paths.append(path)
                if os.path.exists(path):
                    secured.add(extension.lstrip("."))
            except Exception as exc:
                self.stats["failed"] += 1
                self.failures.append(f"{title} [{extension}]: {exc}")
                logger.warning("Failed %s%s: %s", title, extension, exc)

        # Lyrics come from the clip payload, so no network call is needed.
        lyrics = clip_lyrics(clip)
        if lyrics:
            path = build_safe_path(primary, title, ".txt")
            if not os.path.exists(path) and not self.dry_run:
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(lyrics)
                except OSError as exc:
                    self.failures.append(f"{title} [lyrics]: {exc}")
            written_paths.append(path)
            if os.path.exists(path):
                secured.add("txt")
        else:
            secured.add("txt")  # this clip has no lyrics

        # WAV last: it is the slowest and most likely to be throttled, so the
        # cheap assets are safely on disk before we risk it.
        if self.want_wav:
            path = build_safe_path(primary, title, ".wav")
            if os.path.exists(path) and os.path.getsize(path) > 0:
                self.stats["skipped"] += 1
                written_paths.append(path)
                secured.add("wav")
            elif not self.dry_run:
                wav_url = self.request_wav_url(clip_id)
                if wav_url:
                    try:
                        self._download_to(wav_url, path)
                        written_paths.append(path)
                    except Exception as exc:
                        self.stats["failed"] += 1
                        self.failures.append(f"{title} [.wav]: {exc}")
                else:
                    status = getattr(self, "_last_wav_status", None)
                    self.failures.append(
                        f"{title} [.wav]: render did not appear within "
                        f"{self.wav_timeout}s (last poll status {status})")
                # Only a file on disk counts: a throttled or failed render must
                # be retried next run, not recorded as done.
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    secured.add("wav")

        # Mirror into any remaining playlist folders without re-downloading.
        for folder in folders[1:]:
            destination_dir = os.path.join(self.out_dir, folder)
            for source in written_paths:
                if not os.path.exists(source):
                    continue
                destination = os.path.join(destination_dir, os.path.basename(source))
                if os.path.exists(destination):
                    self.stats["skipped"] += 1
                    continue
                if self.dry_run:
                    continue
                try:
                    os.makedirs(destination_dir, exist_ok=True)
                    shutil.copy2(source, destination)
                    self.stats["copied"] += 1
                except OSError as exc:
                    self.stats["failed"] += 1
                    self.failures.append(f"{title} -> {folder}: {exc}")

        self.stats["tracks"] += 1
        return secured

    # --- manifest ------------------------------------------------------

    def manifest_path(self):
        return os.path.join(self.out_dir, MANIFEST_NAME)

    def load_manifest(self) -> dict[str, set[str]]:
        """Return clip id -> the asset kinds already secured for it.

        The original format was a flat list of "this clip was processed", which
        said nothing about *which* assets. After a --no-wav run every clip was
        listed, so a later WAV run found nothing pending and did nothing at all.
        A v1 manifest is therefore treated as empty: the per-file existence
        checks make re-walking cheap, and it self-heals on the first re-run.
        """
        try:
            with open(self.manifest_path(), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}

        completed = data.get("completed")
        if isinstance(completed, dict):
            return {
                cid: set(kinds) for cid, kinds in completed.items()
                if isinstance(kinds, list)
            }
        if isinstance(completed, list):
            logger.info(
                "Found an old manifest that does not record asset kinds; "
                "re-checking every track against the files on disk."
            )
        return {}

    def save_manifest(self, completed: dict[str, set[str]]):
        if self.dry_run:
            return
        try:
            os.makedirs(self.out_dir, exist_ok=True)
            payload = {
                "schema_version": MANIFEST_SCHEMA,
                "completed": {cid: sorted(kinds) for cid, kinds in sorted(completed.items())},
            }
            with open(self.manifest_path(), "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=1)
        except OSError as exc:
            logger.warning("Could not write manifest: %s", exc)
