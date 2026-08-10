# Record schema

One markdown file per resource under `catalog/<type>/`, flat YAML frontmatter, then a
one-or-two-line body: what this is and why it is in the library. The **slug** is the
filename stem and is the record's stable ID — everything references the slug, never
the path.

```markdown
---
title: CPS Board Policy 1.14 - Filling Board Vacancies
org: conway-public-schools
unit:
type: policy
format: pdf
location: boarddocs
url: https://...
drive_id:
drive_kind:
rights: public-record
text: text/cps-board-policy-1-14-vacancies.md
retrieved: 2026-08-08
verified: 2026-08-08
date: 2020-04-14
sha256: 9f2c…64 hex…
extractor: anydoc@0.1.7
status: current
tags: [governance, vacancies]
---
What this is and why it's here.
```

## Scope

District-level resources and the schools inside the district. The hierarchy
(district → school → program) is frontmatter, not folders: `unit:` names the school or
department a resource belongs to, blank means district-wide. Records for other
organizations' own material (including CLAWS's governance set, which lives on the CLAWS
records drive) do not belong in this catalog.

## Fields

| Field | Required | Values / notes |
|---|---|---|
| `title` | yes | Human title, authority first where one exists |
| `org` | yes | Owner/publisher: `conway-public-schools`, `state-of-arkansas`, `media`, … |
| `unit` | no | School or department within the district (`conway-high-school`, `athletics`, …); blank = district-wide |
| `type` | yes | `policy` `minutes` `finance` `statute` `news` `site` `drive` `form` `dataset` `media` `plan` `handbook` `calendar` `notice` `feed` — must match the record's folder |
| `format` | yes | What the original is: `pdf` `docx` `xlsx` `pptx` `html` `gdoc` `gsheet` `folder` `video` `csv` … |
| `location` | yes | Where it lives: `district-site` `boarddocs` `drive` `state-site` `news` … |
| `url` | one of url/drive_id, unless `status: pending` | Direct link to the resource |
| `drive_id` | (same) | Google Drive file/folder ID — IDs outlive share URLs |
| `drive_kind` | if drive_id set | `file` (default) or `folder` |
| `rights` | yes | `public-record` (gov record; extraction default) · `public-web` (public but transient, revocable, or rights-encumbered — live-feed captures and caption transcripts live here; extraction allowed, and feed content honors the removal policy in the README) · `restricted` (pointer only, **never** an extraction) |
| `text` | no | Exactly `text/<slug>.md`; presence = tier 1 |
| `retrieved` | if `text` set | Date the extraction was captured |
| `verified` | no | Stamped by `bin/verify.py`; blank until first successful anonymous fetch |
| `date` | no | The document's own date (meeting held, policy last revised, reporting month ended), `YYYY-MM-DD` — distinct from the capture dates above |
| `sha256` | no | Hex digest of the fetched source bytes, stamped at seed/re-extraction. Only byte-stable sources carry it; gdoc/gsheet exports are re-zipped per request and are never hashed |
| `extractor` | no | Tool that produced the extraction, `name@version` (e.g. `anydoc@0.1.7`, `tesseract@5.5.1+pdftoppm`, `pdftotext@25.07.0+finance-table`, `yt-dlp@2026.07.04`). Blank on extractions made before provenance stamping began (2026-08) |
| `last_check` | no | Stamped by `bin/verify.py` on **every** probe, success or failure — "when did automation last look" |
| `fail_since` | no | First date the source failed anonymous fetch; kept until a success clears it. With `fail_reason`, the record itself carries the negative observation ("404 on anonymous fetch since 2026-08-09") instead of an expiring CI log |
| `fail_reason` | no | One line, ≤120 chars, set/cleared with `fail_since` |
| `supersedes` | no | Slug of the older revision this record replaces |
| `superseded_by` | no | Slug of the successor; requires `status: superseded`. This is the machine answer to "which text is current" — see Supersession below |
| `status` | yes | `pending` (source not yet pinned) · `current` · `superseded` (set `superseded_by`, or for an instrument that expired with no successor, a body note) · `vanished` (verify failing; flipped by a human, not the runner) |
| `tags` | yes | `[a, b, c]` — topics, statutes, initiatives; this is where the taxonomy lives |

## Supersession

The district's containers genuinely hold multiple revisions of the same policy, and its
CMS pages post the same document at more than one asset URL. Both revisions stay in the
catalog (each published asset URL is watched independently), but only one may be
`status: current`:

- An older **revision** gets `status: superseded` + `superseded_by:`; the survivor gets
  `supersedes:`. Lint enforces that two current policy records never share a policy
  number (the leading `8-42`-style component of the slug).
- A byte-identical **duplicate posting** is retired to a pointer record: `superseded`,
  `superseded_by:` the survivor, extraction deleted, body note saying it is a duplicate
  posting rather than a revision.
- The convention for humans stays in the body: a one-line note naming the sibling and
  the relationship (`Superseded revision; the current text is [slug].`). The `-2`/`-dup`
  slug suffixes are mint-time collision artifacts and carry no meaning on their own —
  the frontmatter, not the suffix, says which text is current.

## Slug conventions

Lowercase, hyphenated, authority/date first where natural:
`ark-code-6-24-105-nepotism`, `2026-07-24-nea-conway-board-foia-ruling`,
`cps-board-policy-1-14-vacancies`. Minutes are date-first
(`cpsd-2026-05-12-board-minutes`) — the seeders compose this from the meeting date in
the district's filename, so IDs sort chronologically and never collide.

## Folder rules

- `catalog/<type>/` only. A year subfolder (`catalog/minutes/2026/`) is allowed once a
  type's listing gets unwieldy (~50 records). Nothing deeper; year-less records live in
  the type root.
- Moving a record between allowed folders is free — nothing links by path except its own
  `text:` field, which is keyed by slug and does not move.

## Citing the library

Cite a document as: **slug · official source URL · pinned raw URL**. The official URL
comes from the record (`url`, or derived from `drive_id` — `catalog.jsonl` carries it
resolved as `source_url`). The pinned raw URL is

```
https://raw.githubusercontent.com/conway-claws/district-library/<commit>/text/<slug>.md
```

which is immutable even after later re-extractions. `catalog.jsonl` carries each
record's `raw_url` on the `main` ref plus a first-line `_meta.generated_at_commit`;
substitute that commit for `main` to pin. (The jsonl committed by a scheduled workflow
is generated after its content commit, so its `generated_at_commit` is a true pin; a
hand push regenerates moments later via the lint-and-index workflow.)

## Machine consumers

`catalog.jsonl` at the repo root is the machine entry point: line 1 is a `_meta`
object, then one JSON object per record — all non-empty frontmatter plus `tags[]`,
`source_url` (resolved), `text_bytes`/`text_sha256`/`raw_url` for tier-1 records, and
`body`. Regenerated with the index by `bin/lint_index.py`. `AGENTS.md` documents the
conventions; `bin/mcp_server.py` serves the same data as MCP tools.

## Lint (enforced by `bin/lint_index.py`; the scheduled workflows run it before every commit)

- All required fields present; enum fields within their enums.
- `url` or `drive_id` present unless `status: pending`.
- `text:` if set must be `text/<slug>.md` and the file must exist.
- `rights: restricted` records must have no `text:`.
- Record's folder matches its `type`.
- Slugs unique across the catalog.
- `supersedes`/`superseded_by` must reference existing slugs; `superseded_by` requires
  `status: superseded`.
- Two `status: current` policy records may not share a normalized policy number.
- `date`/`last_check`/`fail_since` are `YYYY-MM-DD` when set; `sha256` is 64 hex chars.
- Every file in `text/` (except its README) is referenced by exactly one record.
