#!/usr/bin/env python3
"""Mint one tier-1 record from a direct public document URL.

Usage: python3 bin/seed_url.py <url> <type> <rights> <slug> "<title>" "<tag,tag,...>"

The single-document sibling of seed_drive_folder.py, for resources that live at
a plain URL (district CMS assets and the like) rather than in a Drive folder.
Anonymous download is the publicness proof; only PDF handled so far. Rights is
explicit because a bare URL carries no container to inherit it from.
"""

import sys
import urllib.request
from datetime import datetime, timezone

from catalog import RIGHTS, ROOT, TYPES, records, sha256_bytes
from seed_drive_folder import doc_date, extract_document

UA = "conway-claws-district-library/0.1 (seed; +https://github.com/conway-claws/district-library)"


def main():
    if len(sys.argv) != 7:
        sys.exit(__doc__)
    url, rtype, rights, slug, title, tags = sys.argv[1:]
    if rtype not in TYPES:
        sys.exit(f"FAIL type '{rtype}' not in {sorted(TYPES)}")
    if rights not in RIGHTS:
        sys.exit(f"FAIL rights '{rights}' not in {sorted(RIGHTS)}")
    if slug in {r.slug for r in records()}:
        print(f"SKIP {slug} (record exists)")
        return

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    if not data.startswith(b"%PDF"):
        sys.exit(f"FAIL {slug} -- source is not a PDF")

    markdown, extractor = extract_document(data, "pdf", rtype)
    (ROOT / "text" / f"{slug}.md").write_text(markdown, encoding="utf-8")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parent = ROOT / "catalog" / rtype
    parent.mkdir(parents=True, exist_ok=True)
    (parent / f"{slug}.md").write_text("\n".join([
        "---",
        f"title: {title}",
        "org: conway-public-schools",
        "unit:",
        f"type: {rtype}",
        "format: pdf",
        "location: district-site",
        f"url: {url}",
        "drive_id:",
        "drive_kind:",
        f"rights: {rights}",
        f"text: text/{slug}.md",
        f"retrieved: {today}",
        f"verified: {today}",
        f"date: {doc_date(title)}",
        f"sha256: {sha256_bytes(data)}",
        f"extractor: {extractor}",
        "status: current",
        f"tags: [{', '.join(t.strip() for t in tags.split(','))}]",
        "---",
        f"Extracted with {extractor.split('@')[0]} from the district's published PDF.",
    ]) + "\n", encoding="utf-8")
    print(f"MINTED {slug}")


if __name__ == "__main__":
    main()
