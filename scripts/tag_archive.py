#!/usr/bin/env python3
"""Tag an existing SunoSync archive so music libraries can read it.

Plex and similar have no MusicBrainz entry for your music, so they rely entirely
on embedded tags plus a cover image in the album folder. The archiver writes
audio, art and lyrics but no tags, which leaves albums showing as loose files in
arbitrary order.

This pass adds, per playlist folder:

  * album, album artist, title, artist
  * track numbers taken from the playlist's own ordering
  * genre, year, lyrics, embedded cover art
  * a SUNO_ID tag holding the clip's UUID, standing in for a MusicBrainz id
  * cover.jpg and folder.jpg -- the filenames Plex looks for
  * an .m3u in playlist order

It downloads no audio and re-runs safely over a partially tagged archive, so it
can be pointed at an archive that is still being filled.

    python scripts/tag_archive.py --archive G:/SunoArchive
    python scripts/tag_archive.py --archive G:/SunoArchive --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from core.archiver import (  # noqa: E402
    PLAYLIST_URL,
    Archiver,
    ArchiveError,
    assign_folder_names,
    clip_lyrics,
)
from core.config_manager import ConfigManager  # noqa: E402
from core.tagging import (  # noqa: E402
    TAGGABLE_EXTENSIONS,
    build_album_plans,
    render_m3u,
    tag_audio_file,
)
from core.utils import sanitize_filename  # noqa: E402

log = logging.getLogger("tag")


def load_token(explicit=None):
    if explicit:
        return explicit.strip()
    token = (ConfigManager("config.json").get("token") or "").strip()
    return re.sub(r"[^\x00-\x7F]+", "", token)


def find_track_files(folder, title):
    """Audio files in `folder` belonging to `title`.

    Matches on the sanitised stem the archiver used, and tolerates the " v2"
    suffix get_unique_filename adds on collisions.
    """
    if not os.path.isdir(folder):
        return []
    stem = sanitize_filename(title)
    matches = []
    for entry in os.listdir(folder):
        name, extension = os.path.splitext(entry)
        if extension.lower() not in TAGGABLE_EXTENSIONS:
            continue
        if name == stem or re.fullmatch(re.escape(stem) + r"(_[0-9a-f]{8})?( v\d+)?", name):
            matches.append(os.path.join(folder, entry))
    return matches


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--archive", required=True, help="Archive directory to tag.")
    parser.add_argument("--token", help="Session token (defaults to SunoSync's config).")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between API calls.")
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    parser.add_argument("--no-cover", action="store_true", help="Skip cover.jpg / embedded art.")
    parser.add_argument("--published-only", action="store_true",
                        help="Number albums over published tracks only. Playlists often "
                             "hold several takes of a song; publishing marks the chosen one.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )

    archive = os.path.abspath(args.archive)
    if not os.path.isdir(archive):
        log.error("No such archive directory: %s", archive)
        return 2

    token = load_token(args.token)
    if not token:
        log.error("No token found. Open SunoSync and connect your account first.")
        return 2

    api = Archiver(token=token, out_dir=archive, delay=args.delay)
    session = requests.Session()

    try:
        log.info("Fetching playlists...")
        playlists = api.fetch_playlists()

        pairs = []
        for playlist in playlists:
            entries, page, seen = [], 1, set()
            while page <= 100:
                payload = api._get_json(
                    PLAYLIST_URL.format(playlist_id=playlist["id"], page=page)
                )
                batch = payload.get("playlist_clips") or []
                fresh = [
                    e for e in batch
                    if isinstance(e, dict) and (e.get("clip") or {}).get("id") not in seen
                ]
                if not fresh:
                    break
                for entry in fresh:
                    seen.add((entry.get("clip") or {}).get("id"))
                entries.extend(fresh)
                page += 1
            pairs.append((playlist, entries))
            log.info("  %-40s %d tracks", playlist.get("name", "?")[:40], len(entries))
    except ArchiveError as exc:
        log.error("%s", exc)
        return 1

    # Same disambiguation the archiver used, so albums sharing a title are
    # tagged against the folders they were actually written to.
    plans = build_album_plans(pairs, assign_folder_names(playlists),
                              published_only=args.published_only)

    tagged = covers = playlists_written = missing = 0

    for plan in plans:
        folder = os.path.join(archive, plan.folder)
        if not os.path.isdir(folder):
            log.debug("skip %s (not archived yet)", plan.folder)
            continue

        log.info("Album: %-38s %d tracks", plan.name[:38], len(plan))

        cover_bytes = None
        if plan.cover_url and not args.no_cover:
            try:
                response = session.get(plan.cover_url, timeout=30)
                response.raise_for_status()
                cover_bytes = response.content
            except requests.RequestException as exc:
                log.warning("  cover fetch failed: %s", exc)

        # Plex looks for these names beside the audio.
        if cover_bytes and not args.dry_run:
            for name in ("cover.jpg", "folder.jpg"):
                try:
                    with open(os.path.join(folder, name), "wb") as handle:
                        handle.write(cover_bytes)
                except OSError as exc:
                    log.warning("  could not write %s: %s", name, exc)
            covers += 1

        filenames = {}
        for track in plan.tracks:
            track.cover_bytes = cover_bytes
            files = find_track_files(folder, track.title)
            if not files:
                missing += 1
                log.debug("  missing on disk: %s", track.title)
                continue

            for path in files:
                if path.lower().endswith(".mp3"):
                    filenames.setdefault(track.clip_id, os.path.basename(path))
                if args.dry_run:
                    continue
                if tag_audio_file(path, track, lyrics=clip_lyrics(track.clip)):
                    tagged += 1

        if filenames and not args.dry_run:
            m3u = os.path.join(folder, f"{plan.folder}.m3u")
            try:
                with open(m3u, "w", encoding="utf-8") as handle:
                    handle.write(render_m3u(plan, filenames))
                playlists_written += 1
            except OSError as exc:
                log.warning("  could not write m3u: %s", exc)

    print()
    print("=" * 60)
    print(f"  Files tagged        {tagged}")
    print(f"  Album covers        {covers}")
    print(f"  M3U playlists       {playlists_written}")
    print(f"  Tracks not on disk  {missing}")
    if args.dry_run:
        print("  (dry run - nothing written)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
