#!/usr/bin/env python3
"""Seed and enrich records for the district's YouTube meeting streams.

Usage: python3 bin/seed_youtube.py [--channel-tab URL]

HOST-SIDE TOOL: YouTube blocks caption fetching from datacenter IPs, so this
runs on a maintainer machine with yt-dlp (and a JS runtime for it), not on a
GitHub runner. The stream-watch workflow handles credential-less discovery;
this tool does the full job when run locally, and is idempotent:

- enumerates the channel's streams tab (yt-dlp --flat-playlist)
- mints a `media` record for any stream not yet cataloged (by watch URL)
- for any media record whose transcript is missing (including stream-watch's
  `transcript-pending` pointers), fetches the English auto-captions and writes
  the cleaned transcript to text/<slug>.md

Transcripts are YouTube auto-captions: machine-generated and error-prone; the
video is authoritative. Each transcript opens with a marker saying so.
"""

import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from catalog import ROOT, records

STREAMS_URL = "https://www.youtube.com/@conwaypublicschoolssocialm3021/streams"
YTDLP = ["yt-dlp", "--js-runtimes", "node"]


def _run(args, timeout):
    """subprocess.run wrapper that reports failures as returncode + stderr tail,
    not str(exc) — the raw exception text embeds the full argv."""
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        tail = " ".join(stderr.split())[-200:]
        rc = getattr(exc, "returncode", "timeout")
        raise RuntimeError(f"yt-dlp exit {rc}: {tail}") from None


def list_streams(url):
    out = _run(YTDLP + ["--flat-playlist", "--print", "%(id)s\t%(title)s", url],
               timeout=600).stdout.decode()
    return [line.split("\t", 1) for line in out.splitlines() if "\t" in line]


def _ytdlp_version():
    try:
        return subprocess.run(["yt-dlp", "--version"], capture_output=True,
                              timeout=30).stdout.decode().strip() or "unknown"
    except Exception:  # noqa: BLE001 - version is provenance garnish, never fatal
        return "unknown"


def slug_for(title):
    t = title
    t = re.sub(r"conway schools board of education", "board", t, flags=re.I)
    t = re.sub(r"live stream", "stream", t, flags=re.I)
    s = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", t.lower())).strip("-")
    return "cpsd-" + s


def clean_vtt(vtt):
    lines, out = vtt.splitlines(), []
    for line in lines:
        line = re.sub(r"<[^>]+>", "", line).strip()
        # no isdigit() filter: YouTube VTT has no numeric cue indices, so it
        # only deleted real digit-only captions (dollar figures, vote counts)
        if (not line or "-->" in line
                or line.startswith(("WEBVTT", "Kind:", "Language:", "align:", "position:"))):
            continue
        if out and out[-1] == line:  # rolling-caption duplicates
            continue
        out.append(line)
    return "\n".join(out)


def fetch_transcript(video_id):
    with tempfile.TemporaryDirectory() as td:
        _run(YTDLP + ["--skip-download", "--write-auto-subs", "--sub-langs", "en",
                      "--sub-format", "vtt", "-o", f"{td}/cap",
                      f"https://www.youtube.com/watch?v={video_id}"],
             timeout=600)
        vtts = list(Path(td).glob("*.vtt"))
        if not vtts:
            raise ValueError("no English auto-captions available")
        return ("<!-- YouTube auto-captions: machine transcript, error-prone; "
                "the video is authoritative -->\n\n" + clean_vtt(vtts[0].read_text(encoding="utf-8")))


def mint(video_id, title, existing_slugs, today):
    slug = base = slug_for(title)
    n = 1
    while slug in existing_slugs:
        n += 1
        slug = f"{base}-{n}"
    ymatch = re.search(r"20\d\d", title)
    # year-less titles land in the type root — the one layout lint allows
    parent = ROOT / "catalog" / "media" / ymatch.group(0) if ymatch else ROOT / "catalog" / "media"
    parent.mkdir(parents=True, exist_ok=True)
    (parent / f"{slug}.md").write_text("\n".join([
        "---", f"title: {title}", "org: conway-public-schools", "unit:",
        "type: media", "format: video", "location: youtube",
        f"url: https://www.youtube.com/watch?v={video_id}",
        "drive_id:", "drive_kind:", "rights: public-web",
        "text:", "retrieved:", f"verified: {today}", "status: current",
        "tags: [school-board, meeting-stream]",
        "---",
        "Live stream on the district's YouTube channel. Transcript (when present) is",
        "YouTube auto-captions; the video is authoritative.",
    ]) + "\n", encoding="utf-8")
    existing_slugs.add(slug)
    return slug


def main():
    url = sys.argv[sys.argv.index("--channel-tab") + 1] if "--channel-tab" in sys.argv else STREAMS_URL
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    recs = records()
    existing_urls = {r.get("url") for r in recs if r.get("url")}
    existing_slugs = {r.slug for r in recs}

    if "--transcripts-only" not in sys.argv:
        for video_id, title in list_streams(url):
            watch = f"https://www.youtube.com/watch?v={video_id}"
            if watch in existing_urls:
                continue
            print(f"MINTED {mint(video_id, title.strip(), existing_slugs, today)}")

    # transcript pass: every media record without one (fresh mints included)
    for rec in records():
        if rec.get("type") != "media" or rec.get("text") or rec.get("status") != "current":
            continue
        vid = re.search(r"[?&]v=([-\w]+)", rec.get("url") or "")
        if not vid:
            continue
        try:
            transcript = fetch_transcript(vid.group(1))
        except Exception as exc:  # noqa: BLE001 - keep the batch going
            print(f"FAIL {rec.slug} -- {str(exc)[:120]}")
            continue
        (ROOT / "text" / f"{rec.slug}.md").write_text(transcript, encoding="utf-8")
        rec.set("text", f"text/{rec.slug}.md")
        rec.set("retrieved", today)
        rec.set("extractor", f"yt-dlp@{_ytdlp_version()}")
        rec.set("tags", rec.get("tags").replace(", transcript-pending", ""))
        rec.save()
        print(f"TRANSCRIBED {rec.slug}")


if __name__ == "__main__":
    main()
