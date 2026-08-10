#!/usr/bin/env python3
"""Anonymously re-resolve every record's source and stamp the outcome.

Usage: python3 bin/verify.py [--only <slug> [<slug> ...]]

Runs with no credentials on purpose: a source this script cannot reach is not
public enough for this catalog. Every probe stamps `last_check:`; success stamps
`verified:` and clears any failure fields; failure stamps `fail_since:` (first
failing date, kept until a success) and a one-line `fail_reason:` — so a clone
of the catalog answers "how long has this source been dark" without GitHub.
A 200 is not enough: binary formats must open with their magic bytes, so a
soft-404 or parked page no longer counts as alive. Never flips status itself —
a human moves a repeatedly-failing record to `vanished`.
"""

import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone

from catalog import records, target_for

UA = "conway-claws-district-library/0.1 (verify; +https://github.com/conway-claws/district-library)"
TIMEOUT = 20
MAGIC = {"pdf": (b"%PDF",), "docx": (b"PK",), "xlsx": (b"PK",), "pptx": (b"PK",),
         "gdoc": (b"PK",), "gsheet": (b"PK",)}


def fetch_head(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
        return resp.status, resp.geturl(), resp.read(2048)


def fetch_ok(rec, url):
    status, final, head = fetch_head(url)
    # A private Drive object redirects to the Google sign-in page and still
    # returns 200 — landing on accounts.google.com means "not public".
    if "accounts.google.com" in final:
        return False, "redirected to Google sign-in (not public)"
    if status != 200:
        return False, f"HTTP {status}"
    magic = MAGIC.get(rec.get("format"))
    if magic and not head.startswith(magic):
        if rec.get("drive_id") and rec.get("drive_kind") != "folder":
            # large public files answer uc?export=download with an HTTP-200 HTML
            # scan interstitial; the usercontent host skips it (same fallback as
            # seed_drive_folder.download) — retry there before calling it dead
            status, final, head = fetch_head(
                "https://drive.usercontent.google.com/download"
                f"?id={rec.get('drive_id')}&export=download&confirm=t")
            if status == 200 and head.startswith(magic):
                return True, ""
        got = "HTML" if head.lstrip()[:1] in (b"<",) else repr(head[:12])
        return False, f"got {got} for format={rec.get('format')} (soft 404?)"
    return True, ""


def probe(rec, url):
    """(ok, reason) with one retry — a transient blip must not stamp fail_since."""
    try:
        return fetch_ok(rec, url)
    except Exception:  # noqa: BLE001 - retry once
        time.sleep(10)
        try:
            return fetch_ok(rec, url)
        except Exception as exc:  # noqa: BLE001 - any fetch failure is a FAIL
            return False, " ".join(str(exc).split())[:120]


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1:])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    failures = 0
    for rec in records():
        if only is not None and rec.slug not in only:
            continue
        if rec.get("status") in ("pending", "vanished"):
            print(f"SKIP {rec.slug} (status: {rec.get('status')})")
            continue
        url = target_for(rec)
        if not url:
            print(f"SKIP {rec.slug} (no url or drive_id)")
            continue
        ok, reason = probe(rec, url)
        rec.set("last_check", today)
        if ok:
            rec.set("verified", today)
            rec.set("fail_since", "")
            rec.set("fail_reason", "")
            rec.save()
            print(f"OK {rec.slug}")
        else:
            failures += 1
            if not rec.get("fail_since"):
                rec.set("fail_since", today)
            rec.set("fail_reason", " ".join(reason.split())[:120])
            rec.save()
            print(f"FAIL {rec.slug} {url} -- {reason}")
        time.sleep(1)  # pace ~600 weekly anonymous hits against Drive
    print(f"DONE {failures} failure(s)")


if __name__ == "__main__":
    main()
