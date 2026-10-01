# Record schema

One markdown file per document under `catalog/<type>/`: flat YAML frontmatter, then
a one- or two-line body saying what the document is. The slug is the filename stem
and the record's stable ID. Everything references the slug, never the path.

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
extractor: anydoc@0.2.4
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
| `type` | yes | `policy` `minutes` `finance` `statute` `news` `site` `drive` `form` `dataset` `media` `plan` `handbook` `calendar` `notice` `feed`; must match the record's folder |
| `format` | yes | What the original is: `pdf` `docx` `xlsx` `pptx` `html` `gdoc` `gsheet` `folder` `video` `csv` … |
| `location` | yes | Where it lives: `district-site` `boarddocs` `drive` `state-site` `news` … |
| `url` | one of url/drive_id, unless `status: pending` | Direct link to the resource |
| `drive_id` | (same) | Google Drive file or folder ID; IDs outlive share URLs |
| `drive_kind` | if drive_id set | `file` (default) or `folder` |
| `rights` | yes | `public-record` (gov record; extraction default) · `public-web` (public but transient, revocable, or rights-encumbered: live-feed captures and caption transcripts; extraction allowed, and feed content follows the removal policy in the README) · `restricted` (pointer only, never an extraction) |
| `text` | no | Exactly `text/<slug>.md`; presence = tier 1 |
| `retrieved` | if `text` set | Date the extraction was captured |
| `verified` | no | Stamped by `bin/verify.py`; blank until first successful anonymous fetch |
| `date` | no | The document's own date (meeting held, policy last revised, reporting month ended), `YYYY-MM-DD`; distinct from the capture dates above |
| `sha256` | no | Hex digest of the fetched source bytes, stamped at seed/re-extraction. Only byte-stable sources carry it; gdoc/gsheet exports are re-zipped per request and are never hashed |
| `extractor` | no | Tool that produced the extraction, `name@version`: `anydoc@0.2.4`, `tesseract@5.5.3+pdftoppm`, `anydoc@0.2.4+tesseract@5.5.3` (scanned pages OCR'd, the rest anydoc), `pdftotext@26.08.0+finance-table`, `yt-dlp@2026.07.04`. Blank on extractions older than the stamp; change-watch treats a blank or older anydoc stamp as due for re-extraction |
| `last_check` | no | Stamped by `bin/verify.py` on every probe, success or failure |
| `fail_since` | no | First date the source failed anonymous fetch; kept until a success clears it. With `fail_reason`, the failure lives in the record ("404 on anonymous fetch since 2026-08-09"), not only in a CI log that expires |
| `fail_reason` | no | One line, ≤120 chars, set/cleared with `fail_since` |
| `supersedes` | no | Slug of the older revision this record replaces |
| `superseded_by` | no | Slug of the successor; requires `status: superseded`. See Supersession below |
| `status` | yes | `pending` (source not yet pinned) · `current` · `superseded` (set `superseded_by`, or for an instrument that expired with no successor, a body note) · `vanished` (verify failing; flipped by a human, not the runner) |
| `tags` | yes | `[a, b, c]`: topics, statutes, initiatives |

## Supersession

The district's folders hold more than one revision of some policies, and its CMS
posts some documents at more than one URL. Every posting keeps a record, since each is
watched separately, but only one may be `status: current`:

- An older revision gets `status: superseded` and `superseded_by:`; the survivor gets
  `supersedes:`. Lint enforces that two current policy records never share a policy
  number (the leading `8-42`-style component of the slug).
- A byte-identical duplicate posting becomes a pointer record: `superseded`,
  `superseded_by:` the survivor, extraction deleted, body note saying it is a duplicate
  posting rather than a revision.
- The body carries a one-line note naming the sibling and the relationship
  (`Superseded revision; the current text is [slug].`). The `-2` and `-dup` slug
  suffixes only resolve name collisions at seeding and mean nothing; the frontmatter
  says which text is current.

## Slug conventions

Lowercase, hyphenated, authority/date first where natural:
`ark-code-6-24-105-nepotism`, `2026-07-24-nea-conway-board-foia-ruling`,
`cps-board-policy-1-14-vacancies`. Minutes are date-first
(`cpsd-2026-05-12-board-minutes`): the seeders take the meeting date from the
district's filename, so IDs sort by date and never collide.

## Folder rules

- `catalog/<type>/` only. A year subfolder (`catalog/minutes/2026/`) is allowed once a
  type's listing gets unwieldy (~50 records). Nothing deeper; year-less records live in
  the type root.
- A record can move between allowed folders freely. Nothing links by path except its
  own `text:` field, which is keyed by slug and does not move.

## Citing the library

Cite a document as slug · official source URL · pinned raw URL. The official URL is
the record's `url`, or derived from `drive_id`; `catalog.jsonl` carries it resolved as
`source_url`. The pinned raw URL is

```
https://raw.githubusercontent.com/conway-claws/district-library/<commit>/text/<slug>.md
```

which does not change when the document is later re-extracted. `catalog.jsonl`
carries each record's `raw_url` on `main` and, on line 1, `_meta.generated_at_commit`;
put that commit in place of `main` to pin. The MCP server's results are already
pinned. (A workflow generates the jsonl after its content commit, so the commit it
names holds that content; a hand push is regenerated minutes later by
lint-and-index.)

## Machine consumers

`catalog.jsonl`: line 1 is a `_meta` object, then one JSON object per record with
all non-empty frontmatter, `tags[]`, resolved `source_url`, `text_bytes`,
`text_sha256` and `raw_url` for records with text, and `body`. `bin/lint_index.py`
regenerates it with the indexes. `bin/mcp_server.py` serves the same data as MCP
tools, from a checkout or over HTTPS; see [AGENTS.md](AGENTS.md).

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
