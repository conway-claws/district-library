#!/usr/bin/env python3
"""Capture the district's Apptegy live feeds into append-only yearly files.

Usage:
  python3 bin/feed_watch.py                        # incremental: append new posts
  python3 bin/feed_watch.py --backfill             # walk the full history
  python3 bin/feed_watch.py --reconcile [--dry-run]  # propagate upstream deletions

The live-feed pages (conwayschools.org/o/<school>/live-feed) are backed by an
open Thrillshare JSON API, reachable credential-less from anywhere - this is
the RSS the page doesn't offer. Posts are ephemeral school communications, so
they get the rolling-capture shape, not per-post records: one catalog record
per school per school-year (type: feed) backing an append-only file in text/,
entries deduped by post id. change-watch skips feed records; this tool owns
their files.

Reconcile honors the district's own takedown mechanism: a post deleted upstream
(including a parent revoking directory-information consent) gets its captured
body redacted in place — the `### date · author (id N)` header line stays, so
dedupe still counts it and a briefly-reappearing post is never re-appended. A
feed whose walk hit any SKIPped page is exempt that run: a transient 500 must
not manufacture a false "removed upstream". (Persistent bad pages move at a
different FEED_PER_PAGE; rerun reconcile with one that walks clean.)
"""

import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

from catalog import ROOT, Record

UA = "conway-claws-district-library/0.1 (feed-watch; +https://github.com/conway-claws/district-library)"
# (slug fragment, thrillshare org id, live-feed section id, unit, page url) -
# every school runs its own org id on the district's Apptegy instance
FEEDS = [
    ("cps",   17220, 288000, "",                                        "https://www.conwayschools.org/o/cps/live-feed"),
    ("chs",   17714, 294859, "conway-high-school",                      "https://www.conwayschools.org/o/chs/live-feed"),
    ("cjhs",  17712, 294840, "conway-junior-high-school",               "https://www.conwayschools.org/o/cjhs/live-feed"),
    ("bbcms", 17706, 294782, "bob-and-betty-courtway-middle-school",    "https://www.conwayschools.org/o/bbcms/live-feed"),
    ("csms",  17711, 294830, "carl-stuart-middle-school",               "https://www.conwayschools.org/o/csms/live-feed"),
    ("rdms",  17708, 294801, "ruth-doyle-middle-school",                "https://www.conwayschools.org/o/rdms/live-feed"),
    ("rpsms", 17709, 294811, "simon-middle-school",                     "https://www.conwayschools.org/o/rpsms/live-feed"),
    ("cles",  17695, 294682, "carolyn-lewis-elementary",                "https://www.conwayschools.org/o/cles/live-feed"),
    ("eses",  17701, 294737, "ellen-smith-elementary",                  "https://www.conwayschools.org/o/eses/live-feed"),
    ("ibes",  17692, 294655, "ida-burns-elementary",                    "https://www.conwayschools.org/o/ibes/live-feed"),
    ("jses",  17703, 294755, "jim-stone-elementary",                    "https://www.conwayschools.org/o/jses/live-feed"),
    ("jlmes", 17699, 294718, "julia-lee-moore-elementary",              "https://www.conwayschools.org/o/jlmes/live-feed"),
    ("mves",  17705, 294773, "marguerite-vann-elementary",              "https://www.conwayschools.org/o/mves/live-feed"),
    ("pfmes", 17697, 294700, "preston-and-florence-mattison-elementary","https://www.conwayschools.org/o/pfmes/live-feed"),
    ("tjes",  17694, 294673, "theodore-jones-elementary",               "https://www.conwayschools.org/o/tjes/live-feed"),
    ("wces",  17693, 294664, "woodrow-cummins-elementary",              "https://www.conwayschools.org/o/wces/live-feed"),
    ("scp",   17691, 294646, "sallie-cone-preschool",                   "https://www.conwayschools.org/o/scp/live-feed"),
]
# big pages 500 on some deep windows (a malformed post breaks serialization at
# per_page=100 but not 25); FEED_PER_PAGE lets a rerun walk past such a window
PER_PAGE = int(os.environ.get("FEED_PER_PAGE", "100"))


def fetch_page(org_id, section_id, page_no):
    url = (f"https://api.thrillshare.com/api/v4/o/{org_id}/cms/live_feeds"
           f"?section_ids={section_id}&page_no={page_no}&per_page={PER_PAGE}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in (1, 2, 3):  # the API throws transient 500s mid-pagination
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * attempt)


def clean(status_html):
    text = re.sub(r"<br\s*/?>", "\n", status_html or "")
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def school_year(iso_time):
    d = datetime.fromisoformat(iso_time)
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{start + 1}"


def capture_path(slug_frag, year):
    return ROOT / "text" / f"cpsd-{slug_frag}-live-feed-{year}.md"


def ensure_record(slug_frag, year, unit, page_url, today):
    slug = f"cpsd-{slug_frag}-live-feed-{year}"
    path = ROOT / "catalog" / "feed" / f"{slug}.md"
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([
        "---", f"title: {slug_frag.upper()} Live Feed, {year}",
        "org: conway-public-schools", f"unit: {unit}", "type: feed",
        "format: json", "location: district-site", f"url: {page_url}",
        "drive_id:", "drive_kind:", "rights: public-web",
        f"text: text/{slug}.md", f"retrieved: {today}", f"verified: {today}",
        "status: current", f"tags: [live-feed, {year}]",
        "---",
        "Append-only capture of the school's live feed (official day-to-day",
        "communications), maintained by bin/feed_watch.py from the open Thrillshare",
        "API. Entries are newest-last, deduped by post id. Posts removed upstream",
        "are redacted by the reconcile pass; see the README's removal policy.",
    ]) + "\n", encoding="utf-8")
    print(f"MINTED {slug}")


# the anchored form: a bare `\(id (\d+)\)` also matches digits inside post bodies
HEADER_RE = re.compile(r"(?m)^### (\d{4}-\d{2}-\d{2}) · (.+) \(id (\d+)\)$")


def existing_ids():
    ids = set()
    for p in (ROOT / "text").glob("cpsd-*-live-feed-*.md"):
        for _, _, pid in HEADER_RE.findall(p.read_text(encoding="utf-8")):
            ids.add(pid)
    return ids


def touch_record(slug_frag, year, today):
    path = ROOT / "catalog" / "feed" / f"cpsd-{slug_frag}-live-feed-{year}.md"
    if path.exists():
        rec = Record(path)
        rec.set("retrieved", today)
        rec.save()


def reconcile_file(path, live_ids, today, dry_run):
    """Redact captured posts absent upstream; returns the redacted ids."""
    text = path.read_text(encoding="utf-8")
    pieces = HEADER_RE.split(text)
    out = [pieces[0]]
    redacted = []
    for i in range(1, len(pieces), 4):
        day, author, pid, body = pieces[i:i + 4]
        header = f"### {day} · {author} (id {pid})"
        if pid not in live_ids and "removed upstream" not in body:
            body = f"\n\n*(removed upstream, observed {today})*\n\n"
            redacted.append(pid)
        out.append(header + body)
    if redacted and not dry_run:
        path.write_text("".join(out), encoding="utf-8")
    return redacted


def entry(post):
    day = post["time"][:10]
    author = " ".join((post.get("author_name") or "unknown").split())
    body = clean(post.get("status"))
    return f"### {day} · {author} (id {post['id']})\n\n{body}\n"


def walk_feed(org_id, section_id, slug_frag):
    """(posts, clean) — the feed's full history; clean means zero SKIPped pages."""
    posts, clean = [], True
    page_no, bad_streak = 1, 0
    while True:
        try:
            data = fetch_page(org_id, section_id, page_no)
        except Exception as exc:  # noqa: BLE001 - the API 500s specific page
            # numbers persistently (cps page 32 at any per_page); skip and
            # keep walking - a rerun at another FEED_PER_PAGE recovers the
            # window, since the same posts land on different page numbers
            bad_streak += 1
            clean = False
            print(f"SKIP {slug_frag} page {page_no} -- {str(exc)[:80]}")
            if bad_streak >= 3:
                print(f"FAIL {slug_frag} -- 3 consecutive bad pages, stopping this feed")
                break
            page_no += 1
            continue
        bad_streak = 0
        page = data.get("live_feeds", [])
        posts.extend(page)
        if not page:
            break
        nxt = (data.get("meta", {}).get("links") or {}).get("next")
        if not nxt:
            break
        page_no += 1
    return posts, clean


def capture(backfill, today, seen):
    for slug_frag, org_id, section_id, unit, page_url in FEEDS:
        new_posts = []
        page_no, bad_streak = 1, 0
        while True:
            try:
                data = fetch_page(org_id, section_id, page_no)
            except Exception as exc:  # noqa: BLE001 - see walk_feed
                bad_streak += 1
                print(f"SKIP {slug_frag} page {page_no} -- {str(exc)[:80]}")
                if bad_streak >= 3:
                    print(f"FAIL {slug_frag} -- 3 consecutive bad pages, stopping this feed")
                    break
                page_no += 1
                continue
            bad_streak = 0
            posts = data.get("live_feeds", [])
            fresh = [p for p in posts if str(p["id"]) not in seen]
            new_posts.extend(fresh)
            # incremental mode stops at the first page with nothing new
            if not posts or (not backfill and len(fresh) < len(posts)):
                break
            nxt = (data.get("meta", {}).get("links") or {}).get("next")
            if not nxt:
                break
            page_no += 1

        # append oldest-first so each yearly file reads chronologically
        by_year = {}
        for post in sorted(new_posts, key=lambda p: p["time"]):
            by_year.setdefault(school_year(post["time"]), []).append(post)
        for year, posts in sorted(by_year.items()):
            ensure_record(slug_frag, year, unit, page_url, today)
            path = capture_path(slug_frag, year)
            with path.open("a", encoding="utf-8") as f:
                for post in posts:
                    f.write(entry(post) + "\n")
            touch_record(slug_frag, year, today)
            print(f"APPENDED {len(posts)} post(s) -> {path.name}")


def reconcile(today, dry_run):
    for slug_frag, org_id, section_id, _unit, _page_url in FEEDS:
        posts, clean = walk_feed(org_id, section_id, slug_frag)
        if not clean:
            print(f"EXEMPT {slug_frag} -- walk hit a bad page; no redactions this run")
            continue
        live = {str(p["id"]) for p in posts}
        for path in sorted((ROOT / "text").glob(f"cpsd-{slug_frag}-live-feed-*.md")):
            for pid in reconcile_file(path, live, today, dry_run):
                mark = "would redact" if dry_run else "REDACTED"
                print(f"{mark} {path.name} id {pid}")


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if "--reconcile" in sys.argv:
        reconcile(today, dry_run="--dry-run" in sys.argv)
        return
    capture("--backfill" in sys.argv, today, existing_ids())


if __name__ == "__main__":
    main()
