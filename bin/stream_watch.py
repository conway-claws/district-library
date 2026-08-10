#!/usr/bin/env python3
"""Discover new district YouTube streams via RSS and mint pointer records.

Runner-side half of the stream pipeline: YouTube's RSS feed is reachable
credential-less from GitHub infrastructure, but caption fetching is not
(datacenter IPs are blocked), so this mints pointer records tagged
transcript-pending and the host-side bin/seed_youtube.py fills the
transcripts on its own cadence. The feed carries the channel's ~15 most
recent videos, which is ample for a weekly check.
"""

import html as html_mod
import re
import urllib.request
from datetime import datetime, timezone

from catalog import ROOT, records

CHANNEL_ID = "UCZhJym4G3x-JcQMQsGrjgBQ"  # Conway Public Schools Social Media
FEED = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
UA = "conway-claws-district-library/0.1 (stream-watch; +https://github.com/conway-claws/district-library)"
STREAM_TITLE = re.compile(r"board of education .*(?:stream|meeting)", re.I)


def slug_for(title):
    t = re.sub(r"conway schools board of education", "board", title, flags=re.I)
    t = re.sub(r"live stream", "stream", t, flags=re.I)
    return "cpsd-" + re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", t.lower())).strip("-")


def main():
    req = urllib.request.Request(FEED, headers={"User-Agent": UA})
    xml = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", errors="replace")
    entries = re.findall(
        r"<entry>.*?<yt:videoId>([-\w]+)</yt:videoId>.*?<title>([^<]+)</title>", xml, re.S)

    recs = records()
    existing_urls = {r.get("url") for r in recs if r.get("url")}
    existing_slugs = {r.slug for r in recs}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for video_id, title in entries:
        title = html_mod.unescape(title).strip()  # RSS titles carry raw XML entities
        watch = f"https://www.youtube.com/watch?v={video_id}"
        if watch in existing_urls:
            continue
        if not STREAM_TITLE.search(title):
            print(f"SKIP {title} (not a board stream)")
            continue
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
            f"url: {watch}", "drive_id:", "drive_kind:", "rights: public-web",
            "text:", "retrieved:", f"verified: {today}", "status: current",
            "tags: [school-board, meeting-stream, transcript-pending]",
            "---",
            "Live stream on the district's YouTube channel, discovered by stream-watch.",
            "Transcript pending: bin/seed_youtube.py (host-side) fills it.",
        ]) + "\n", encoding="utf-8")
        existing_slugs.add(slug)
        print(f"MINTED {slug}")


if __name__ == "__main__":
    main()
