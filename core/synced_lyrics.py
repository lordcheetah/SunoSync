"""Turn Suno's word-level lyric alignment into LRC and SRT files.

``GET /api/gen/{id}/aligned_lyrics/`` returns per-word timings::

    {"data": [[{"word": "Twenty ", "start_s": 31.8, "end_s": 32.1, ...}, ...],
              [...confidences...], 0.229]}

This is the data that used to drive per-word highlighting on Suno. Two useful
things fall out of it:

* **LRC** beside each MP3 gives synced lyrics in Plexamp and most players.
* **SRT** beside each MP4 gives real YouTube captions, rather than relying on
  auto-generated ones that mishear sung vocals.

Both are emitted at line granularity. Word-level LRC exists but player support
is patchy, and Suno's own display has moved to lines anyway.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = [
    "parse_aligned_lyrics",
    "group_into_lines",
    "render_lrc",
    "render_srt",
]

# Lines are held on screen at least this long, and never past the next line.
MIN_CUE_SECONDS = 0.8
MAX_CUE_SECONDS = 7.0


def parse_aligned_lyrics(payload):
    """Extract [{word, start, end}] from an aligned_lyrics response.

    Tolerates the outer envelope being either the full response, the ``data``
    triple, or the word list itself.
    """
    data = payload.get("data") if isinstance(payload, dict) else payload

    words = None
    if isinstance(data, list) and data:
        # The documented shape is [words, confidences, score].
        if isinstance(data[0], list):
            words = data[0]
        elif isinstance(data[0], dict):
            words = data
    if not isinstance(words, list):
        return []

    parsed = []
    for entry in words:
        if not isinstance(entry, dict):
            continue
        text = entry.get("word")
        if not isinstance(text, str) or not text:
            continue
        try:
            start = float(entry.get("start_s"))
            end = float(entry.get("end_s", start))
        except (TypeError, ValueError):
            continue
        if end < start:
            end = start
        parsed.append({"word": text, "start": start, "end": end})
    return parsed


def is_annotation(text):
    """Whether a lyric line is a stage direction rather than sung words.

    Suno lyrics carry structure markers and performance notes in brackets --
    '[Verse 1]', '[Intro - Instrumental]', '[Wind. Silence. Then the shaman
    drum...]'. Nobody sings them, so the aligner gives them near-zero durations
    and they bunch together at the start of a section. Left in, they produce
    captions that flash past in milliseconds and drown the actual lyric.
    """
    stripped = text.strip()
    return bool(stripped.startswith("[") and stripped.endswith("]"))


def group_into_lines(words, drop_annotations=True):
    """Collapse word timings into display lines.

    Suno embeds the line structure in the word text itself -- a word carries the
    trailing newlines that end its line -- so lines are recovered by splitting
    on those rather than by guessing at pauses.

    Bracketed stage directions are dropped by default; see :func:`is_annotation`.
    """
    lines = []
    buffer: list[str] = []
    start = None
    end = None

    def flush():
        nonlocal buffer, start, end
        text = "".join(buffer).strip()
        if text and start is not None:
            lines.append({"text": text, "start": start, "end": end if end is not None else start})
        buffer, start, end = [], None, None

    for word in words:
        segments = word["word"].split("\n")
        for index, segment in enumerate(segments):
            if index > 0:
                # Crossing a newline closes the line built so far.
                flush()
            if not segment:
                continue
            if start is None:
                start = word["start"]
            buffer.append(segment)
            end = word["end"]

    flush()

    if drop_annotations:
        lines = [line for line in lines if not is_annotation(line["text"])]

    # Trim each cue so it neither vanishes instantly nor lingers over the next.
    # Done after filtering: annotations sit at near-zero durations and would
    # otherwise clamp the following sung line down to nothing.
    for position, line in enumerate(lines):
        next_start = lines[position + 1]["start"] if position + 1 < len(lines) else None

        end = line["end"]
        if end - line["start"] < MIN_CUE_SECONDS:
            end = line["start"] + MIN_CUE_SECONDS
        end = min(end, line["start"] + MAX_CUE_SECONDS)
        if next_start is not None:
            end = min(end, next_start)
        line["end"] = max(end, line["start"])

    return lines


def _lrc_stamp(seconds):
    seconds = max(0.0, seconds)
    minutes, remainder = divmod(seconds, 60)
    return f"[{int(minutes):02d}:{remainder:05.2f}]"


def _srt_stamp(seconds):
    seconds = max(0.0, seconds)
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:  # rounding carried
        millis, secs = 0, secs + 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_lrc(lines, title=None, artist=None, album=None):
    """LRC text. Players read the bracketed metadata header if present."""
    out = []
    for tag, value in (("ti", title), ("ar", artist), ("al", album)):
        if value:
            out.append(f"[{tag}:{value}]")
    if out:
        out.append("")
    for line in lines:
        out.append(f"{_lrc_stamp(line['start'])}{line['text']}")
    return "\n".join(out) + "\n"


def render_srt(lines):
    """SubRip text, numbered from 1, as YouTube expects."""
    blocks = []
    for number, line in enumerate(lines, start=1):
        blocks.append(
            f"{number}\n"
            f"{_srt_stamp(line['start'])} --> {_srt_stamp(line['end'])}\n"
            f"{line['text']}\n"
        )
    return "\n".join(blocks)
