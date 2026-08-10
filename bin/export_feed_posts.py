#!/usr/bin/env python3
"""Regenerate exports/feed-posts.jsonl from the live-feed capture anchors.

The 85 per-school-year feed files are the corpus's chunking-hostile tail (up to
480KB each); this export makes the same 19k+ posts individually addressable —
one JSON line per post — for embedding pipelines and anything else that wants
units instead of files. Derived entirely from the `### date · author (id N)`
anchors, so the append-only text/ contract is untouched; feed-watch re-runs it
after each capture. Posts redacted by the reconcile pass export with
removed: true and no text.
"""

import json
import re

from catalog import ROOT
from feed_watch import HEADER_RE

FILE_RE = re.compile(r"cpsd-(.+)-live-feed-(\d{4}-\d{4})\.md")


def main():
    out = ROOT / "exports" / "feed-posts.jsonl"
    out.parent.mkdir(exist_ok=True)
    posts = []
    for path in sorted((ROOT / "text").glob("cpsd-*-live-feed-*.md")):
        m = FILE_RE.fullmatch(path.name)
        if not m:
            continue
        school, school_year = m.groups()
        pieces = HEADER_RE.split(path.read_text(encoding="utf-8"))
        for i in range(1, len(pieces), 4):
            day, author, pid, body = pieces[i:i + 4]
            body = body.strip()
            removed = "removed upstream" in body
            posts.append({"school": school, "school_year": school_year,
                          "post_id": int(pid), "date": day, "author": author,
                          **({"removed": True} if removed else {"text": body})})
    posts.sort(key=lambda p: (p["school"], p["date"], p["post_id"]))
    with out.open("w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"EXPORTED {len(posts)} posts -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
