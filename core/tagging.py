"""Turn an archived folder of tracks into a proper tagged album.

Plex, Navidrome, foobar2000 and friends have no MusicBrainz entry to look your
music up in, so everything they display has to come from the files themselves:
embedded tags first, then a cover image sitting next to them. The archiver
writes audio, art and lyrics but no tags at all, which leaves a Plex library
showing filenames in arbitrary order.

The useful discovery is that Suno playlists already carry album structure:

    playlist.name                -> album
    playlist.image_url           -> album cover (distinct from per-track art)
    playlist.user_display_name   -> album artist
    playlist_clips[].relative_index -> track number
    clip.metadata.tags           -> genre
    clip.created_at              -> year
    clip.id                      -> a stable unique id, standing in for a
                                    MusicBrainz recording id

Tagging is a separate, idempotent pass so it can be re-run over an archive that
already exists without downloading anything again.
"""

from __future__ import annotations

import datetime
import logging
import os

from mutagen.id3 import (
    APIC,
    COMM,
    ID3,
    TALB,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    TXXX,
    USLT,
    ID3NoHeaderError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AlbumPlan",
    "TrackPlan",
    "primary_genre",
    "release_year",
    "build_album_plans",
    "tag_audio_file",
    "render_m3u",
]

TAGGABLE_EXTENSIONS = (".mp3", ".wav")


# --------------------------------------------------------------------------
# Field derivation
# --------------------------------------------------------------------------

def primary_genre(tags, limit=3):
    """Condense Suno's style prompt into something a genre field can hold.

    ``metadata.tags`` is the full style prompt -- routinely several hundred
    characters of comma-separated descriptors. Dropping the whole thing into a
    genre tag makes library browsers unusable, so keep the leading few.
    """
    if not isinstance(tags, str) or not tags.strip():
        return None
    parts = [p.strip() for p in tags.replace("\n", ",").split(",") if p.strip()]
    if not parts:
        return None
    return ", ".join(parts[:limit])[:120]


def release_year(clip):
    """Four-digit year from the clip's creation timestamp."""
    stamp = clip.get("created_at") or ""
    if isinstance(stamp, str) and len(stamp) >= 4 and stamp[:4].isdigit():
        return stamp[:4]
    return str(datetime.date.today().year)


class TrackPlan:
    """One track's intended tags."""

    __slots__ = ("clip", "track_number", "total_tracks", "album", "album_artist",
                 "artist", "cover_bytes")

    def __init__(self, clip, track_number, total_tracks, album, album_artist,
                 artist, cover_bytes=None):
        self.clip = clip
        self.track_number = track_number
        self.total_tracks = total_tracks
        self.album = album
        self.album_artist = album_artist
        self.artist = artist
        self.cover_bytes = cover_bytes

    @property
    def title(self):
        return (self.clip.get("title") or "").strip() or "Untitled"

    @property
    def clip_id(self):
        return self.clip.get("id", "")


class AlbumPlan:
    """An album's worth of tracks, in order."""

    def __init__(self, name, folder, album_artist, description="", cover_url=None):
        self.name = name
        self.folder = folder
        self.album_artist = album_artist
        self.description = description
        self.cover_url = cover_url
        self.tracks: list[TrackPlan] = []

    def __len__(self):
        return len(self.tracks)


def build_album_plans(playlists_with_clips, folder_names=None):
    """Build ordered album plans from (playlist, playlist_clip_entries) pairs.

    ``entries`` are the raw ``playlist_clips`` items, which carry both the clip
    and its ``relative_index``. Ordering follows relative_index where present,
    falling back to the order the API returned.

    ``folder_names`` maps playlist id -> directory name and must come from
    ``core.archiver.assign_folder_names`` so that albums sharing a title are
    tagged against the same disambiguated folders the archiver wrote.
    """
    from core.utils import sanitize_filename

    folder_names = folder_names or {}
    plans = []
    for playlist, entries in playlists_with_clips:
        name = (playlist.get("name") or "Untitled Album").strip()
        album_artist = (playlist.get("user_display_name")
                        or playlist.get("user_handle") or "Suno").strip()

        ordered = []
        for position, entry in enumerate(entries):
            clip = entry.get("clip") if isinstance(entry.get("clip"), dict) else entry
            if not isinstance(clip, dict) or not clip.get("id"):
                continue
            index = entry.get("relative_index")
            try:
                index = float(index)
            except (TypeError, ValueError):
                index = float(position + 1)
            ordered.append((index, clip))

        ordered.sort(key=lambda pair: pair[0])

        plan = AlbumPlan(
            name=name,
            folder=(folder_names.get(str(playlist.get("id", "")))
                    or sanitize_filename(name) or "Untitled Album"),
            album_artist=album_artist,
            description=(playlist.get("description") or "").strip(),
            cover_url=playlist.get("image_url"),
        )
        total = len(ordered)
        for position, (_index, clip) in enumerate(ordered, start=1):
            plan.tracks.append(TrackPlan(
                clip=clip,
                track_number=position,
                total_tracks=total,
                album=name,
                album_artist=album_artist,
                # Suno exposes the uploader handle per clip; fall back to the
                # album artist so the field is never blank.
                artist=(clip.get("display_name") or clip.get("handle")
                        or album_artist),
            ))
        plans.append(plan)
    return plans


# --------------------------------------------------------------------------
# Writing tags
# --------------------------------------------------------------------------

def _load_id3(path):
    """Open (or create) an ID3 container for MP3 and WAV alike."""
    try:
        return ID3(path)
    except ID3NoHeaderError:
        return ID3()
    except Exception as exc:
        logger.debug("Could not read tags from %s: %s", path, exc)
        return ID3()


def tag_audio_file(path, track: TrackPlan, lyrics=None, overwrite=True):
    """Write album tags into one audio file. Returns True when saved.

    Idempotent: running it twice produces the same result, so a tagging pass can
    be repeated over a partially processed archive.
    """
    extension = os.path.splitext(path)[1].lower()
    if extension not in TAGGABLE_EXTENSIONS:
        return False
    if not os.path.exists(path):
        return False

    tags = _load_id3(path)

    if not overwrite and tags.getall("TALB"):
        return False

    clip = track.clip
    metadata = clip.get("metadata") or {}

    tags.setall("TIT2", [TIT2(encoding=3, text=track.title)])
    tags.setall("TPE1", [TPE1(encoding=3, text=track.artist)])
    tags.setall("TPE2", [TPE2(encoding=3, text=track.album_artist)])
    tags.setall("TALB", [TALB(encoding=3, text=track.album)])
    # "n/total" is what players use to show a complete album.
    tags.setall("TRCK", [TRCK(encoding=3, text=f"{track.track_number}/{track.total_tracks}")])
    tags.setall("TPOS", [TPOS(encoding=3, text="1/1")])
    tags.setall("TDRC", [TDRC(encoding=3, text=release_year(clip))])

    genre = primary_genre(metadata.get("tags"))
    if genre:
        tags.setall("TCON", [TCON(encoding=3, text=genre)])

    model = clip.get("major_model_version") or clip.get("model_name")
    if model:
        tags.setall("COMM", [COMM(encoding=3, lang="eng", desc="",
                                  text=f"Generated with Suno {model}")])

    if lyrics:
        tags.setall("USLT", [USLT(encoding=3, lang="eng", desc="", text=lyrics)])

    # A stable identifier so the archive can be re-matched to Suno later, and so
    # duplicate copies across playlist folders are recognisable as the same
    # recording. This is the role a MusicBrainz recording id would normally play.
    tags.delall("TXXX:SUNO_ID")
    tags.add(TXXX(encoding=3, desc="SUNO_ID", text=track.clip_id))
    if metadata.get("tags"):
        tags.delall("TXXX:SUNO_STYLE")
        tags.add(TXXX(encoding=3, desc="SUNO_STYLE", text=str(metadata["tags"])[:900]))

    if track.cover_bytes:
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3,
                      desc="Cover", data=track.cover_bytes))

    try:
        # v2.3 has the broadest player support, WAV included.
        tags.save(path, v2_version=3)
        return True
    except Exception as exc:
        logger.warning("Could not write tags to %s: %s", path, exc)
        return False


def render_m3u(plan: AlbumPlan, filenames):
    """Extended M3U for an album, preserving playlist order.

    `filenames` maps clip id -> filename on disk. Missing tracks are skipped so
    the playlist never points at files that were not archived.
    """
    lines = ["#EXTM3U"]
    for track in plan.tracks:
        name = filenames.get(track.clip_id)
        if not name:
            continue
        duration = int((track.clip.get("metadata") or {}).get("duration") or 0)
        lines.append(f"#EXTINF:{duration},{track.album_artist} - {track.title}")
        lines.append(name)
    return "\n".join(lines) + "\n"
