#!/usr/bin/env python3
"""Mint tier-1 records from explicit Drive file IDs (documents linked from a hub).

Usage: python3 bin/seed_drive_files.py <hub-slug> <extra-tag> <file-id> [<file-id> ...]

For documents referenced by hyperlink from a cataloged record (e.g. the per-policy
files linked from a policy-section index) rather than sitting in one folder.
Names come from each file's public /view page; org/type/rights are inherited from
the hub record, with <extra-tag> appended. Idempotent by drive_id, like the
folder seeder.
"""

import html
import re
import sys

from catalog import records
from seed_drive_folder import current_policy_numbers, fetch, mint

EXT_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def view_title(file_id):
    page = fetch(f"https://drive.google.com/file/d/{file_id}/view").decode(
        "utf-8", errors="replace")
    m = re.search(r"<title>(.*?)</title>", page, re.S)
    if not m or "Google Drive" not in m.group(1):
        raise ValueError("no public /view title — file may not be public")
    return html.unescape(m.group(1)).replace(" - Google Drive", "").strip()


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    hub_slug, extra_tag = sys.argv[1], sys.argv[2]
    all_records = records()
    hub = next((r for r in all_records if r.slug == hub_slug), None)
    if hub is None:
        sys.exit(f"FAIL no record with slug {hub_slug}")
    # extend tags in memory only; the hub record on disk is untouched
    hub.front["tags"] = f"[{', '.join(hub.tags() + [extra_tag])}]"
    existing = {r.slug for r in all_records}
    existing_ids = {r.get("drive_id") for r in all_records if r.get("drive_id")}
    policy_nums = current_policy_numbers(all_records)
    for file_id in sys.argv[3:]:
        try:
            name = view_title(file_id)
            m = re.search(r"\.(\w+)$", name)
            mime = EXT_MIME.get(m.group(1).lower() if m else "pdf", "application/pdf")
            print(mint(hub, file_id, name, mime, existing, existing_ids, policy_nums))
        except Exception as exc:  # noqa: BLE001 - keep the batch going
            print(f"FAIL {file_id} -- {exc}")


if __name__ == "__main__":
    main()
