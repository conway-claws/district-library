#!/usr/bin/env python3
"""Refetch every extracted source, re-extract, and rewrite text/ on a real change.

Usage:
  python3 bin/change_watch.py [--dry-run] [--only <slug> [<slug> ...]]

Extraction: `npx @firecrawl/anydoc` (latest release, resolved once per run) for
file formats, a local tag-strip
pass for static HTML, the layout path for finance PDFs. Byte-stable sources are
hashed first: an unchanged sha256 skips re-extraction entirely, unless the
record's text came from an older anydoc than this run's (stale_extractor), so
each upstream release re-extracts every affected record exactly once. Diffs are
compared after whitespace normalization so re-renders don't read as content
changes, and a fresh extraction that comes back empty or sharply shrunken is
refused (SUSPECT) rather than committed: a soft-404 or extractor failure must
not overwrite good text. Prints CHANGED/SAME/SUSPECT/FAIL/RETRY-EXHAUSTED per
record; the workflow turns CHANGED lines into commits and an issue.
"""

import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import StringIO

from catalog import ROOT, records, sha256_bytes
from seed_drive_folder import ANYDOC_VERSION, download, extract_document

UA = "conway-claws-district-library/0.1 (change-watch; +https://github.com/conway-claws/district-library)"
TIMEOUT = 60
STRATEGY = {"gdoc": "export-docx", "gsheet": "export-xlsx"}
SHRINK_FLOOR = 0.3  # a fresh extraction below 30% of the old one is refused
ERROR_TITLE = ("page not found", "not found", "error", "sign in", "access denied",
               "maintenance")


ANYDOC_STAMP = f"anydoc@{ANYDOC_VERSION}"
# extractions made deliberately by another path open with one of these markers
OTHER_PATH_MARKERS = ("<!-- OCR (tesseract)", "<!-- finance report", "<!-- YouTube")


def _ver(stamp):
    return tuple(int(x) for x in re.findall(r"\d+", stamp.split("@", 1)[-1])[:3])


def stale_extractor(rec, old_text):
    """True when this record's text came from an anydoc older than this run's.

    Records stamped with an older anydoc@x.y.z are stale; a newer stamp (a run
    that fell back to ANYDOC_FLOOR) is not, so an offline run never downgrades.
    Unstamped records predate the stamp and are anydoc output unless their text
    carries another path's marker. Any other stamp (tesseract, pdftotext,
    html-tagstrip) is current."""
    ext = rec.get("extractor")
    if ext:
        return ext.startswith("anydoc@") and _ver(ext) < _ver(ANYDOC_STAMP)
    return bool(old_text) and not old_text.startswith(OTHER_PATH_MARKERS)


class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer"}

    def __init__(self):
        super().__init__()
        self.out = StringIO()
        self.title = ""
        self.depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.depth:
            self.out.write(data)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read(), resp.geturl()


def with_retry(fn, *args):
    """One retry with backoff; transient network blips must not read as FAILs."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001 - retried once, then reported
        time.sleep(10)
        return fn(*args)


def extract_html(data, final_url):
    """(text, rejection reason) for an html source; rejects error pages."""
    parser = TextExtractor()
    parser.feed(data.decode("utf-8", errors="replace"))
    title = " ".join(parser.title.split()).lower()
    if any(marker in title for marker in ERROR_TITLE):
        return "", f"page title reads as an error page: '{title[:60]}'"
    if "accounts.google.com" in final_url:
        return "", "redirected to Google sign-in"
    return parser.out.getvalue(), ""


def normalize(text):
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def main():
    dry_run = "--dry-run" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1:])
        only.discard("--dry-run")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for rec in records():
        if only is not None and rec.slug not in only:
            continue
        if not rec.get("text") or rec.get("status") != "current":
            continue
        fmt = rec.get("format")
        if fmt == "video":
            continue  # transcripts are host-fetched; YouTube blocks runner IPs
        if rec.get("type") == "feed":
            continue  # append-only captures owned by feed-watch, never re-extracted
        if not rec.get("url") and not (
                rec.get("drive_id") and rec.get("drive_kind") != "folder"):
            print(f"SKIP {rec.slug} (no fetchable source)")
            continue
        text_path = ROOT / rec.get("text")
        old = text_path.read_text(encoding="utf-8") if text_path.is_file() else ""
        extractor = ""
        digest = ""
        try:
            if rec.get("url"):
                data, final_url = with_retry(fetch, rec.get("url"))
                if fmt == "html":
                    fresh, reason = extract_html(data, final_url)
                    if reason:
                        print(f"SUSPECT {rec.slug} -- {reason}")
                        continue
                    extractor = "html-tagstrip"
                else:
                    digest = sha256_bytes(data)
                    if (digest and digest == rec.get("sha256")
                            and not stale_extractor(rec, old)):
                        print(f"SAME {rec.slug} (source hash unchanged)")
                        continue
                    fresh, extractor = extract_document(data, fmt, rec.get("type"))
            else:
                strategy = STRATEGY.get(fmt, "binary")
                data = with_retry(download, rec.get("drive_id"), fmt, strategy)
                if strategy == "binary":
                    # gdoc/gsheet export bytes differ per request; only stable
                    # bytes get the hash fast path and a stamped sha256
                    digest = sha256_bytes(data)
                    if (digest and digest == rec.get("sha256")
                            and not stale_extractor(rec, old)):
                        print(f"SAME {rec.slug} (source hash unchanged)")
                        continue
                fresh, extractor = extract_document(data, fmt, rec.get("type"))
        except Exception as exc:  # noqa: BLE001 - retried once already
            print(f"RETRY-EXHAUSTED {rec.slug} -- {exc}")
            continue
        finally:
            time.sleep(1)  # pace ~600 weekly anonymous hits against Drive
        norm_fresh, norm_old = normalize(fresh), normalize(old)
        if norm_fresh == norm_old:
            if not dry_run and ((digest and digest != rec.get("sha256"))
                                or (extractor and extractor != rec.get("extractor"))):
                # same text, new or changed byte hash (re-saved PDF, or a record
                # the backfill missed) or a newer extractor: stamp both so the
                # fast path fires next week instead of re-extracting again
                if digest:
                    rec.set("sha256", digest)
                if extractor:
                    rec.set("extractor", extractor)
                rec.save()
            print(f"SAME {rec.slug}")
            continue
        if old and (not norm_fresh
                    or len(norm_fresh) < SHRINK_FLOOR * len(norm_old)):
            print(f"SUSPECT {rec.slug} -- fresh extraction is "
                  f"{len(norm_fresh)} chars vs {len(norm_old)} old; not overwriting")
            continue
        if dry_run:
            print(f"CHANGED {rec.slug} (dry run, not written)")
            continue
        text_path.write_text(fresh, encoding="utf-8")
        rec.set("retrieved", today)
        if digest:
            rec.set("sha256", digest)
        if extractor:
            rec.set("extractor", extractor)
        rec.save()
        print(f"CHANGED {rec.slug}")


if __name__ == "__main__":
    main()
