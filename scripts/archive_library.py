#!/usr/bin/env python3
"""Archive every public Suno track, organised by playlist.

Collects MP3, WAV, cover art, lyrics and video for each track, filing them into
one folder per playlist. Tracks in several playlists are downloaded once and
copied into each folder; public tracks in no playlist go to ``_Unsorted``.

Safe to interrupt: re-running skips anything already on disk.

    # See what would happen, and how much disk it needs, without downloading:
    python scripts/archive_library.py --out G:/SunoArchive --dry-run

    # Real run
    python scripts/archive_library.py --out G:/SunoArchive

    # Skip WAV (much faster; WAV needs a server-side render per track)
    python scripts/archive_library.py --out G:/SunoArchive --no-wav

The token is read from SunoSync's config, so make sure the app has a fresh
session (open it and let the browser extension sync) before a long run.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.archiver import (  # noqa: E402
    UNSORTED_FOLDER,
    assign_track_stems,
    WAV_RENDER_SECONDS,
    Archiver,
    ArchiveError,
    estimate_bytes,
    human_bytes,
    plan_destinations,
)
from core.config_manager import ConfigManager  # noqa: E402


def load_token(explicit=None):
    if explicit:
        return explicit.strip()
    token = (ConfigManager("config.json").get("token") or "").strip()
    # Copy-pasted tokens sometimes carry a stray ellipsis or NBSP.
    return re.sub(r"[^\x00-\x7F]+", "", token)


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", required=True, help="Destination directory for the archive.")
    parser.add_argument("--token", help="Session token (defaults to SunoSync's config).")
    parser.add_argument("--no-wav", action="store_true",
                        help="Skip WAV. Much faster: each WAV needs a server-side render.")
    parser.add_argument("--no-video", action="store_true", help="Skip the .mp4 video.")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Minimum seconds between API calls (default: 1.0).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Enumerate and report only. Downloads nothing.")
    parser.add_argument("--limit", type=int,
                        help="Stop after N tracks. Useful for a trial run.")
    parser.add_argument("--wav-timeout", type=int, default=120,
                        help="Seconds to wait for each WAV render (default: 120).")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("archive")

    token = load_token(args.token)
    if not token:
        log.error("No token found. Open SunoSync and connect your account first.")
        return 2

    archiver = Archiver(
        token=token,
        out_dir=args.out,
        want_wav=not args.no_wav,
        want_video=not args.no_video,
        delay=args.delay,
        dry_run=args.dry_run,
        wav_timeout=args.wav_timeout,
    )

    try:
        log.info("Enumerating playlists...")
        playlists = archiver.fetch_playlists()
        membership, playlist_clips = archiver.build_membership(playlists)

        log.info("Enumerating public tracks...")
        public_clips = archiver.fetch_public_clips()

        # Union: everything public, plus anything reachable through a playlist
        # so that a playlist track which is not flagged public is still kept.
        all_clips = {c["id"]: c for c in playlist_clips.values()}
        for clip in public_clips:
            all_clips[clip["id"]] = clip

        in_playlists = sum(1 for cid in all_clips if membership.get(cid))
        unsorted = len(all_clips) - in_playlists
        copies = sum(len(plan_destinations(cid, membership)) for cid in all_clips)

        print()
        print("=" * 64)
        print(f"  Playlists              {len(playlists)}")
        print(f"  Tracks to archive      {len(all_clips)}")
        print(f"    in playlists         {in_playlists}")
        print(f"    {UNSORTED_FOLDER:<20} {unsorted}")
        print(f"  Folder copies total    {copies}  (duplicates across playlists)")
        print(f"  Formats                MP3"
              f"{', WAV' if not args.no_wav else ''}"
              f"{', MP4' if not args.no_video else ''}, cover, lyrics")
        estimate = estimate_bytes(copies, not args.no_wav, not args.no_video)
        print(f"  Rough disk estimate    {human_bytes(estimate)}")
        if not args.no_wav:
            minutes = len(all_clips) * WAV_RENDER_SECONDS / 60
            print(f"  WAV renders            {len(all_clips)}  "
                  f"(~{minutes / 60:.1f} h of render waiting alone)")
        print("=" * 64)
        print()

        if args.dry_run:
            log.info("Dry run: nothing was downloaded.")
            return 0

        # Same-titled tracks in one folder would otherwise share a path, and
        # the second would be skipped as 'already downloaded'.
        stems = assign_track_stems(all_clips, membership)

        completed = archiver.load_manifest()
        if completed:
            log.info("Resuming: %d tracks already recorded as complete.", len(completed))

        pending = [cid for cid in all_clips if cid not in completed]
        if args.limit:
            pending = pending[: args.limit]

        total = len(pending)
        for index, clip_id in enumerate(pending, 1):
            clip = all_clips[clip_id]
            folders = plan_destinations(clip_id, membership)
            log.info("[%d/%d] %s  ->  %s", index, total,
                     (clip.get("title") or clip_id)[:45], ", ".join(folders))
            try:
                archiver.archive_clip(clip, folders, stem=stems.get(clip_id))
                completed.add(clip_id)
            except ArchiveError:
                raise
            except Exception as exc:
                log.warning("  track failed: %s", exc)
                archiver.failures.append(f"{clip_id}: {exc}")

            if index % 10 == 0:
                archiver.save_manifest(completed)

        archiver.save_manifest(completed)

    except ArchiveError as exc:
        log.error("%s", exc)
        archiver.save_manifest(archiver.load_manifest())
        return 1
    except KeyboardInterrupt:
        log.warning("Interrupted. Re-run the same command to resume.")
        return 130

    stats = archiver.stats
    print()
    print("=" * 64)
    print(f"  Tracks processed   {stats['tracks']}")
    print(f"  Files downloaded   {stats['downloaded']}  ({human_bytes(stats['bytes'])})")
    print(f"  Files copied       {stats['copied']}")
    print(f"  Already present    {stats['skipped']}")
    print(f"  Failures           {stats['failed']}")
    print("=" * 64)

    if archiver.failures:
        report = os.path.join(archiver.out_dir, "archive_failures.txt")
        try:
            with open(report, "w", encoding="utf-8") as handle:
                handle.write("\n".join(archiver.failures))
            print(f"\n  {len(archiver.failures)} problems written to {report}")
        except OSError:
            for failure in archiver.failures[:20]:
                print("   ", failure)

    return 0


if __name__ == "__main__":
    sys.exit(main())
