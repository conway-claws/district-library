#!/usr/bin/env python3
"""Validate every catalog record against schema.md; regenerate the index surfaces.

Usage:
  python3 bin/lint_index.py --check   # validate only (CI gate on PRs)
  python3 bin/lint_index.py           # validate + rewrite INDEX.md, index/, catalog.jsonl

Generated surfaces: INDEX.md (the root summary), index/<type>.md (per-type
tables), index/by-unit.md / index/by-tag.md (grouped listings, one line per
record so no line outgrows a pager), and catalog.jsonl — one JSON object per
record, first line a _meta object carrying the generating commit. The jsonl is
the machine entry point; the index files are for people.
"""

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

from catalog import (ROOT, TYPES, RIGHTS, STATUSES, REQUIRED, policy_number,
                     records, target_for)

RAW_BASE = "https://raw.githubusercontent.com/conway-claws/district-library/main"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SHA_RE = re.compile(r"[0-9a-f]{64}")


def lint(recs):
    errors = []
    seen = {}
    slugs = {r.slug for r in recs}

    def err(rec, msg):
        errors.append(f"{rec.path.relative_to(ROOT)}: {msg}")

    for rec in recs:
        if rec.slug in seen:
            err(rec, f"slug collides with {seen[rec.slug]}")
        seen[rec.slug] = rec.path.relative_to(ROOT)

        for field in REQUIRED:
            if not rec.get(field):
                err(rec, f"missing required field '{field}'")

        rtype, rights, status = rec.get("type"), rec.get("rights"), rec.get("status")
        if rtype and rtype not in TYPES:
            err(rec, f"type '{rtype}' not in {sorted(TYPES)}")
        if rights and rights not in RIGHTS:
            err(rec, f"rights '{rights}' not in {sorted(RIGHTS)}")
        if status and status not in STATUSES:
            err(rec, f"status '{status}' not in {sorted(STATUSES)}")

        # folder = catalog/<type>[/<year>]/
        parts = rec.path.relative_to(ROOT / "catalog").parts
        folder = parts[0] if parts else ""
        if rtype and folder != rtype:
            err(rec, f"lives in catalog/{folder}/ but type is '{rtype}'")
        if len(parts) == 3 and not (len(parts[1]) == 4 and parts[1].isdigit()):
            err(rec, f"subfolder '{parts[1]}' is not a year")
        if len(parts) > 3:
            err(rec, "folders deeper than catalog/<type>/<year>/ are not allowed")

        if not rec.get("url") and not rec.get("drive_id") and status != "pending":
            err(rec, "needs url or drive_id (or status: pending)")
        if rec.get("drive_id") and rec.get("drive_kind") not in ("", "file", "folder"):
            err(rec, "drive_kind must be file or folder")

        text = rec.get("text")
        if text:
            if text != f"text/{rec.slug}.md":
                err(rec, f"text must be text/{rec.slug}.md, got '{text}'")
            elif not (ROOT / text).is_file():
                err(rec, f"text file {text} does not exist")
            if rights == "restricted":
                err(rec, "restricted records must not carry an extraction")
            if not rec.get("retrieved"):
                err(rec, "extraction present but no retrieved date")

        # lineage and provenance fields: shape-checked only when non-empty
        for field in ("supersedes", "superseded_by"):
            val = rec.get(field)
            if val and val not in slugs:
                err(rec, f"{field} references unknown slug '{val}'")
        if rec.get("superseded_by") and status != "superseded":
            err(rec, "superseded_by set but status is not superseded")
        for field in ("date", "last_check", "fail_since"):
            val = rec.get(field)
            if val and not DATE_RE.fullmatch(val):
                err(rec, f"{field} '{val}' is not YYYY-MM-DD")
        sha = rec.get("sha256")
        if sha and not SHA_RE.fullmatch(sha):
            err(rec, "sha256 is not 64 lowercase hex chars")

    # one current text per policy number: two would make the catalog vouch for
    # a repealed revision — the seeder refuses this too, lint is the backstop
    by_num = {}
    for rec in recs:
        if (rec.get("type") == "policy" and rec.get("status") == "current"
                and rec.get("drive_kind") != "folder"):
            num = policy_number(rec.slug)
            if num:
                by_num.setdefault(num, []).append(rec)
    for num, rs in sorted(by_num.items()):
        if len(rs) > 1:
            names = ", ".join(r.slug for r in rs)
            for rec in rs[1:]:
                err(rec, f"policy {num} has multiple current records ({names}) "
                         "— supersede all but one")

    # every extraction must belong to a record, or it drifts unverified forever
    referenced = {r.get("text") for r in recs if r.get("text")}
    for p in sorted((ROOT / "text").glob("*.md")):
        if p.name != "README.md" and f"text/{p.name}" not in referenced:
            errors.append(f"text/{p.name}: extraction not referenced by any record")

    return errors


def esc(s):
    return s.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


def type_table(recs_of_type):
    # links carry a ../ prefix: these tables live one level down, in index/
    lines = ["| Record | Status | Rights | Date | Text | Verified | Tags |",
             "|---|---|---|---|---|---|---|"]
    for rec in sorted(recs_of_type, key=lambda r: r.slug):
        rel = rec.path.relative_to(ROOT)
        text = f"[✓](../{rec.get('text')})" if rec.get("text") else ""
        lines.append(
            f"| [{esc(rec.get('title'))}](../{rel}) | {rec.get('status')} "
            f"| {rec.get('rights')} | {rec.get('date')} | {text} "
            f"| {rec.get('verified')} | {esc(', '.join(rec.tags()))} |")
    return lines


def build_indexes(recs):
    """{relative filename: content} for INDEX.md and the index/ listings."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stamp = f"Generated by `bin/lint_index.py` on {now} — do not hand-edit."
    out = {}

    by_type = {}
    by_status = {}
    for rec in recs:
        by_type.setdefault(rec.get("type"), []).append(rec)
        by_status.setdefault(rec.get("status"), []).append(rec)

    summary = " · ".join(f"{len(v)} {k}" for k, v in sorted(by_status.items()))
    lines = ["# Index", "", stamp, "",
             f"**{len(recs)} records** — {summary}", "",
             "Machine consumers: read [catalog.jsonl](catalog.jsonl) "
             "(and [AGENTS.md](AGENTS.md) for the conventions).", "",
             "| Type | Records | Current |",
             "|---|---|---|"]
    for rtype in sorted(by_type):
        rs = by_type[rtype]
        current = sum(1 for r in rs if r.get("status") == "current")
        lines.append(f"| [{rtype}](index/{rtype}.md) | {len(rs)} | {current} |")
    lines += ["", "Grouped listings: [by unit](index/by-unit.md) · "
                  "[by tag](index/by-tag.md)", ""]
    out["INDEX.md"] = "\n".join(lines)

    for rtype, rs in by_type.items():
        out[f"index/{rtype}.md"] = "\n".join(
            [f"# Index — {rtype}", "", stamp, ""] + type_table(rs) + [""])

    for name, heading, key_of in (
            ("index/by-unit.md", "# Index — by unit",
             lambda r: [r.get("unit")] if r.get("unit") else []),
            ("index/by-tag.md", "# Index — by tag", lambda r: r.tags())):
        groups = {}
        for rec in recs:
            for key in key_of(rec):
                groups.setdefault(key, []).append(rec)
        lines = [heading, "", stamp, ""]
        for key in sorted(groups):
            lines += [f"## {key} ({len(groups[key])})", ""]
            for rec in sorted(groups[key], key=lambda r: r.slug):
                lines.append(f"- [{rec.slug}](../{rec.path.relative_to(ROOT)})")
            lines.append("")
        out[name] = "\n".join(lines)

    return {k: v if v.endswith("\n") else v + "\n" for k, v in out.items()}


def head_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, timeout=30,
                              ).stdout.decode().strip() or "unknown"
    except Exception:  # noqa: BLE001 - jsonl still generates without git
        return "unknown"


def build_jsonl(recs):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [json.dumps({
        "_meta": "conway-claws/district-library catalog export",
        "generated": now,
        "generated_at_commit": head_commit(),
        "records": len(recs),
        "cite_as": "see schema.md 'Citing the library'",
    }, ensure_ascii=False)]
    for rec in recs:
        obj = {"slug": rec.slug, "path": str(rec.path.relative_to(ROOT))}
        for key in rec.order:
            if key == "tags":
                continue
            val = rec.front.get(key, "")
            if val:
                obj[key] = val
        obj["tags"] = rec.tags()
        src = target_for(rec)
        if src:
            obj["source_url"] = src
        text = rec.get("text")
        if text and (ROOT / text).is_file():
            data = (ROOT / text).read_bytes()
            obj["text_bytes"] = len(data)
            obj["text_sha256"] = hashlib.sha256(data).hexdigest()
            obj["raw_url"] = f"{RAW_BASE}/{text}"
        if rec.body:
            obj["body"] = rec.body
        lines.append(json.dumps(obj, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def main():
    check_only = "--check" in sys.argv
    recs = records()
    errors = lint(recs)
    for e in errors:
        print(f"LINT {e}")
    if errors:
        sys.exit(1)
    print(f"OK {len(recs)} records")
    if not check_only:
        (ROOT / "index").mkdir(exist_ok=True)
        for name, content in build_indexes(recs).items():
            (ROOT / name).write_text(content, encoding="utf-8")
        (ROOT / "catalog.jsonl").write_text(build_jsonl(recs), encoding="utf-8")
        print("INDEX.md, index/, and catalog.jsonl regenerated")


if __name__ == "__main__":
    main()
