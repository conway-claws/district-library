#!/usr/bin/env python3
"""One-time provenance backfill, 2026-08: stamp sha256, re-extract the bad set.

Fetches every byte-stable source (static Drive/CMS binaries; gdoc/gsheet exports
are non-deterministic and never hashed) and stamps `sha256:` so change-watch's
hash fast path and the provenance contract start from a known baseline. Two sets
also get re-extracted with the Stage-1 extractors, because their committed text
is wrong, not just unprovenanced: the monthly board reports (collapsed tables →
finance layout path) and four policies anydoc silently truncated (→ thin-output
guard picks the OCR result). OCR-marked extractions keep their text: tesseract
already produced it deliberately. Idempotent; kept in bin/ as the record of the
baseline's origin.
"""

import time
from datetime import datetime, timezone

from catalog import ROOT, records, sha256_bytes
from seed_drive_folder import download, extract_document, fetch

# committed text provably truncated by anydoc (ends mid-sentence / interior cut)
TRUNCATED = {
    "cpsd-3-19-licensed-personnel-employment",
    "cpsd-8-46-classified-personnel-contract-return",
    "cpsd-8-51-classified-personnel-debts",
    "cpsd-02-administration",
}
OCR_MARKER = "<!-- OCR (tesseract)"
STABLE = {"pdf", "docx", "xlsx", "pptx"}


def needs_reextract(rec):
    if rec.slug in TRUNCATED:
        return True
    return rec.get("type") == "finance" and "board-report" in rec.slug


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    done = failed = rewritten = 0
    for rec in records():
        if not rec.get("text") or rec.get("format") not in STABLE:
            continue
        if rec.get("type") == "feed" or rec.get("drive_kind") == "folder":
            continue
        if rec.get("sha256"):
            continue  # already stamped; rerun-safe
        try:
            if rec.get("url"):
                data = fetch(rec.get("url"))
            elif rec.get("drive_id"):
                data = download(rec.get("drive_id"), rec.get("format"), "binary")
            else:
                continue
        except Exception as exc:  # noqa: BLE001 - unstamped is honest for unreachable
            failed += 1
            print(f"FAIL {rec.slug} -- {str(exc)[:100]}")
            time.sleep(1)
            continue
        if rec.get("format") == "pdf" and not data.startswith(b"%PDF"):
            failed += 1
            print(f"FAIL {rec.slug} -- fetched bytes are not a PDF")
            time.sleep(1)
            continue
        rec.set("sha256", sha256_bytes(data))
        old = (ROOT / rec.get("text")).read_text(encoding="utf-8")
        if needs_reextract(rec) and not old.startswith(OCR_MARKER):
            markdown, extractor = extract_document(data, rec.get("format"), rec.get("type"))
            (ROOT / rec.get("text")).write_text(markdown, encoding="utf-8")
            rec.set("retrieved", today)
            rec.set("extractor", extractor)
            rewritten += 1
            print(f"REEXTRACTED {rec.slug} ({extractor})")
        else:
            print(f"STAMPED {rec.slug}")
        rec.save()
        done += 1
        time.sleep(0.5)
    print(f"DONE {done} stamped, {rewritten} re-extracted, {failed} failed")


if __name__ == "__main__":
    main()
