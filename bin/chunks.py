#!/usr/bin/env python3
"""Split every extraction in text/ into retrieval-sized passages.

Usage:
  python3 bin/chunks.py            # print counts and sizes
  python3 bin/chunks.py --jsonl    # emit every passage as JSONL on stdout

Nothing is written to the repo: chunking the whole library takes under a
second, so bin/search.py derives passages from text/ at load time and the only
committed source of truth stays text/ itself.

With --jsonl, one JSON line per passage after a _meta first line:

  {"id": "<slug>#<n>", "slug", "n", "lines": [first, last], "heading", "text"}

plus "date" on feed posts (taken from the `### YYYY-MM-DD · Author` anchor).
`lines` are 1-based and inclusive against text/<slug>.md, so a passage cites as
a GitHub line anchor and reads back through get_text(offset=first-1). Record
metadata (title, type, unit, status, source_url) is not repeated here: join on
slug to catalog.jsonl.

Deterministic: the same text/ produces the same bytes, so a re-extraction diffs
as exactly the passages that changed. Stdlib only.
"""

import json
import re
import sys

from catalog import ROOT, records

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
FEED_ANCHOR_RE = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\b")
MARKER_RE = re.compile(r"^\s*<!--.*-->\s*$")
FENCE_RE = re.compile(r"^\s*```")

# Target passage size in characters (~4 chars/token): big enough to carry a
# policy clause or a minutes item with its motion, small enough to rank well.
MAX_CHARS = {"finance": 3000}
DEFAULT_MAX = 1600
MIN_CHARS = 400        # below this, a section merges into the next one
LINE_OVERLAP = 2       # lines repeated across a forced split (transcripts, long lists)


def _blocks(lines):
    """Yield (kind, start, end) over line indexes: 'heading' single lines and
    'para' runs separated by blank lines. Marker comments and fences drop out."""
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or MARKER_RE.match(line) or FENCE_RE.match(line):
            i += 1
            continue
        if HEADING_RE.match(line):
            yield "heading", i, i
            i += 1
            continue
        start = i
        while (i < n and lines[i].strip() and not HEADING_RE.match(lines[i])
               and not FENCE_RE.match(lines[i])):
            i += 1
        yield "para", start, i - 1


def _split_long(lines, start, end, limit):
    """Break one oversized paragraph into line windows, overlapping slightly.
    A single line longer than the limit is cut at whitespace."""
    pieces, cur, cur_len, cur_start = [], [], 0, start
    idx = start
    while idx <= end:
        line = lines[idx]
        if len(line) > limit:
            if cur:
                pieces.append((cur_start, idx - 1, "\n".join(cur)))
                cur, cur_len = [], 0
            rest = line
            while rest:
                cut = rest.rfind(" ", 0, limit) if len(rest) > limit else len(rest)
                cut = cut if cut > limit // 2 else min(limit, len(rest))
                pieces.append((idx, idx, rest[:cut].strip()))
                rest = rest[cut:].strip()
            idx += 1
            cur_start = idx
            continue
        if cur and cur_len + len(line) + 1 > limit:
            pieces.append((cur_start, idx - 1, "\n".join(cur)))
            back = max(cur_start, idx - LINE_OVERLAP)
            cur = lines[back:idx]
            cur_len = sum(len(x) + 1 for x in cur)
            cur_start = back
        cur.append(line)
        cur_len += len(line) + 1
        idx += 1
    if cur:
        pieces.append((cur_start, end, "\n".join(cur)))
    return pieces


def chunk_text(text, rec_type=""):
    """Passages for one extraction: list of dicts with lines/heading/text."""
    lines = text.splitlines()
    limit = MAX_CHARS.get(rec_type, DEFAULT_MAX)
    is_feed = rec_type == "feed"
    out = []
    stack = []            # [(level, title)] heading path
    cur = []              # [(start, end, text)]
    cur_len = 0
    cur_heading = ""
    cur_date = ""

    def flush():
        nonlocal cur, cur_len
        if cur:
            body = "\n".join(t for _, _, t in cur).strip()
            if body:
                item = {"lines": [cur[0][0] + 1, cur[-1][1] + 1],
                        "heading": cur_heading, "text": body}
                if cur_date:
                    item["date"] = cur_date
                out.append(item)
        cur, cur_len = [], 0

    for kind, start, end in _blocks(lines):
        if kind == "heading":
            level, title = HEADING_RE.match(lines[start]).groups()
            level = len(level)
            if is_feed or cur_len >= MIN_CHARS:
                flush()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title.strip()))
            if not cur:
                cur_heading = " > ".join(t for _, t in stack)
                m = FEED_ANCHOR_RE.match(lines[start]) if is_feed else None
                cur_date = m.group(1) if m else ""
            cur.append((start, end, lines[start]))
            cur_len += len(lines[start]) + 1
            continue
        para = "\n".join(lines[start:end + 1])
        if len(para) > limit:
            for p_start, p_end, piece in _split_long(lines, start, end, limit):
                if cur and cur_len + len(piece) > limit:
                    flush()
                if not cur:
                    cur_heading = " > ".join(t for _, t in stack)
                cur.append((p_start, p_end, piece))
                cur_len += len(piece) + 1
            continue
        if cur and cur_len + len(para) > limit:
            flush()
        if not cur:
            cur_heading = " > ".join(t for _, t in stack)
        cur.append((start, end, para))
        cur_len += len(para) + 1
    flush()
    return out


def iter_chunks(items):
    """Passages for (slug, type, text_rel) triples, in slug order."""
    for slug, rec_type, rel in sorted(items):
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for n, ch in enumerate(chunk_text(text, rec_type), 1):
            row = {"id": f"{slug}#{n}", "slug": slug, "n": n}
            row.update(ch)
            yield row


def main():
    items = [(r.slug, r.get("type"), r.get("text")) for r in records() if r.get("text")]
    rows = list(iter_chunks(items))
    if "--jsonl" in sys.argv:
        print(json.dumps({"_meta": "conway-claws/district-library passages",
                          "chunks": len(rows),
                          "join": "slug -> catalog.jsonl; lines are 1-based "
                                  "inclusive in text/<slug>.md"}))
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
        return
    sizes = sorted(len(r["text"]) for r in rows)
    print(f"{len(rows)} passages over {len({r['slug'] for r in rows})} documents; "
          f"chars median {sizes[len(sizes) // 2]}, max {sizes[-1]}")


if __name__ == "__main__":
    main()
