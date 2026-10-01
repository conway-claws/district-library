#!/usr/bin/env python3
"""Graduate a Drive-folder container record's documents into tier-1 records.

Usage: python3 bin/seed_drive_folder.py <container-slug> [<container-slug> ...]

Anonymously lists the container's public Drive folder, downloads each document,
extracts it with anydoc, writes text/<slug>.md plus a catalog record. Idempotent:
existing records are skipped, so re-running after the district posts new minutes
mints only the new ones. Anonymous download doubles as the publicness proof, so
minted records are stamped verified.

Reads the folder's embedded first-page listing (~50 items); a folder bigger than
that needs pagination this script doesn't do. It warns if the page looks full.
"""

import functools
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

import finance_table
from catalog import ROOT, policy_number, records, sha256_bytes

UA = "conway-claws-district-library/0.1 (seed; +https://github.com/conway-claws/district-library)"
TIMEOUT = 60
ANYDOC_FLOOR = "0.2.4"  # oldest acceptable; used only if the registry is unreachable
# 0.1.7 (pdf-inspector 0.1.7) silently dropped most lines of some Word-made
# PDFs (4.5 School Choice: 354 of ~2,690 words); fixed from 0.1.8.


def _latest_anydoc():
    """The current published anydoc, resolved once per run.

    The library tracks upstream: every run uses the newest release, pinned to
    that exact version for the whole run so each extraction's `extractor:`
    stamp names what produced it. change-watch re-extracts records stamped
    with any other version, so a new release rolls through once, as a normal
    reviewed diff, with the shrink guard still refusing a regression."""
    try:
        out = subprocess.run(["npm", "view", "@firecrawl/anydoc", "version"],
                             capture_output=True, timeout=60)
        ver = out.stdout.decode().strip()
        if out.returncode == 0 and re.fullmatch(r"\d+\.\d+\.\d+", ver):
            return ver
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    print(f"WARN npm registry unreachable; anydoc falls back to {ANYDOC_FLOOR}",
          file=sys.stderr)
    return ANYDOC_FLOOR


ANYDOC_VERSION = _latest_anydoc()  # the extractor: stamp names this
ANYDOC = f"@firecrawl/anydoc@{ANYDOC_VERSION}"
THIN_WORDS_PER_PAGE = 40  # below this, a text-layer PDF is suspect: OCR and compare


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _decode_js_escapes(blob):
    # Decode only the escape sequences. A bare unicode_escape pass latin-1-mangles
    # real UTF-8 in filenames and crashes on surrogate pairs (emoji).
    def sub(m):
        s = m.group(0)
        if s[1] in "xu":
            return chr(int(s[2:], 16))
        return {"\\n": "\n", "\\t": "\t", "\\r": "\r",
                "\\'": "'", '\\"': '"', "\\\\": "\\"}.get(s, s)
    text = re.sub(r"\\x[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|\\.", sub, blob)
    return text.encode("utf-16", "surrogatepass").decode("utf-16")


def list_folder(folder_id):
    html = fetch(f"https://drive.google.com/drive/folders/{folder_id}").decode(
        "utf-8", errors="replace")
    m = re.search(r"window\['_DRIVE_ivd'\]\s*=\s*'(.*?)';", html, re.S)
    if not m:
        raise ValueError("no embedded listing; folder empty or not public")
    blob = m.group(1).replace("\\/", "/")
    items = json.loads(_decode_js_escapes(blob))[0] or []
    if len(items) >= 50:
        print(f"WARN folder {folder_id} listing has {len(items)} items; "
              "first page only, pagination not implemented")
    return [(it[0], it[2].strip(), it[3]) for it in items]


# mime -> (format field, download strategy); native Google files export to an
# office format anydoc can read, binary files download directly
HANDLED = {
    "application/pdf": ("pdf", "binary"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("docx", "binary"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("xlsx", "binary"),
    "application/vnd.google-apps.document": ("gdoc", "export-docx"),
    "application/vnd.google-apps.spreadsheet": ("gsheet", "export-xlsx"),
}
ANYDOC_FMT = {"pdf": "pdf", "docx": "docx", "xlsx": "xlsx", "gdoc": "docx", "gsheet": "xlsx"}
MAGIC = {"pdf": b"%PDF", "docx": b"PK", "xlsx": b"PK", "gdoc": b"PK", "gsheet": b"PK"}


@functools.lru_cache(maxsize=None)
def _tool_version(tool):
    try:
        proc = subprocess.run([tool, "--version" if tool != "pdftotext" else "-v"],
                              capture_output=True, timeout=30)
        first = (proc.stdout or proc.stderr).decode(errors="replace").splitlines()[0]
        m = re.search(r"(\d+[.\d]*\d)", first)
        return m.group(1) if m else "unknown"
    except Exception:  # noqa: BLE001 - version is provenance garnish, never fatal
        return "unknown"


def _page_count(data):
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        tf.write(data)
        tf.flush()
        try:
            out = subprocess.run(["pdfinfo", tf.name], capture_output=True, timeout=60)
        except FileNotFoundError:
            return 0  # no poppler: the thin guard just doesn't fire
    m = re.search(rb"^Pages:\s+(\d+)", out.stdout, re.M)
    return int(m.group(1)) if m else 0


def _ocr_pdf(data, first=None, last=None, marker=True):
    """tesseract over pages first..last (1-based, inclusive; default all)."""
    import tempfile
    from pathlib import Path as _P
    rng = []
    if first:
        rng = ["-f", str(first), "-l", str(last or first)]
    with tempfile.TemporaryDirectory() as td:
        pdf = _P(td) / "doc.pdf"
        pdf.write_bytes(data)
        subprocess.run(["pdftoppm", "-r", "200", "-png", *rng, str(pdf), str(_P(td) / "pg")],
                       check=True, timeout=600)
        pages = []
        for png in sorted(_P(td).glob("pg-*.png")):
            ocr = subprocess.run(["tesseract", str(png), "-", "--dpi", "200"],
                                 capture_output=True, timeout=300, check=True)
            pages.append(ocr.stdout.decode("utf-8", errors="replace").strip())
    text = "\n\n".join(p for p in pages if p)
    if not marker:
        return text
    if not text:
        raise ValueError("OCR produced no text")
    return "<!-- OCR (tesseract): scanned source, no text layer -->\n\n" + text


def _ocr_tag():
    return f"tesseract@{_tool_version('tesseract')}+pdftoppm"


_NEEDS_OCR = re.compile(r"pages? ([\d,\s-]+) of (\d+) needs? OCR")


def _ocr_pages(err):
    """({1-based pages}, page_count) from anydoc's needs-OCR error, else None.
    anydoc >= 0.2.4 rejects the whole document (exit 3) naming the pages."""
    m = _NEEDS_OCR.search(err)
    if not m:
        return None
    pages = set()
    for part in m.group(1).split(","):
        lo, _, hi = part.strip().partition("-")
        if lo:
            pages.update(range(int(lo), int(hi or lo) + 1))
    return pages, int(m.group(2))


def _pdf_pages(data, first, last):
    """The pages first..last of a PDF as new PDF bytes (poppler)."""
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as td:
        src = _P(td) / "src.pdf"
        src.write_bytes(data)
        subprocess.run(["pdfseparate", "-f", str(first), "-l", str(last), str(src),
                        str(_P(td) / "p-%d.pdf")], check=True, timeout=120)
        parts = [str(_P(td) / f"p-{n}.pdf") for n in range(first, last + 1)]
        out = _P(td) / "out.pdf"
        if len(parts) == 1:
            return _P(parts[0]).read_bytes()
        subprocess.run(["pdfunite", *parts, str(out)], check=True, timeout=120)
        return out.read_bytes()


def _mixed_pdf(data, ocr_pages, page_count):
    """Text pages through anydoc, scanned pages through tesseract, each page
    extracted once, joined in page order. Runs of consecutive pages of the same
    kind go through their extractor together."""
    runs, start = [], 1
    for n in range(2, page_count + 2):
        if n > page_count or ((n in ocr_pages) != (start in ocr_pages)):
            runs.append((start, n - 1, start in ocr_pages))
            start = n
    out = []
    for first, last, scanned in runs:
        if scanned:
            text = _ocr_pdf(data, first, last, marker=False)
            if text:
                out.append(f"<!-- OCR (tesseract): page{'s' if last > first else ''} "
                           f"{first}{'-' + str(last) if last > first else ''}, "
                           f"scanned, no text layer -->\n\n{text}")
            continue
        proc = subprocess.run(["npx", "-y", ANYDOC, "-", "--format", "pdf"],
                              input=_pdf_pages(data, first, last),
                              capture_output=True, timeout=300)
        if proc.returncode != 0:
            raise ValueError(proc.stderr.decode(errors="replace").strip()[:200])
        out.append(proc.stdout.decode("utf-8", errors="replace").strip())
    return "\n\n".join(t for t in out if t) + "\n"


def extract_document(data, fmt, rtype=None):
    """anydoc, with a tesseract OCR fallback for scanned PDFs.

    Returns (markdown, extractor_tag) so the record carries provenance. Finance
    PDFs go through the layout-preserving table path first; a thin anydoc result
    on any PDF (words/page below the floor) is OCR'd too and the longer text wins,
    because anydoc can exit 0 with a fraction of the document.
    A PDF anydoc rejects for some scanned pages is split: those pages are OCR'd,
    the rest still go through anydoc, so one scanned cover never costs a
    document its text layer.
    """
    if rtype == "finance" and fmt == "pdf":
        table = finance_table.extract(data)
        if table is not None:
            return table, f"pdftotext@{_tool_version('pdftotext')}+finance-table"
        print("SUSPECT finance table extraction failed validation; anydoc fallback")
    proc = subprocess.run(
        ["npx", "-y", ANYDOC, "-", "--format", ANYDOC_FMT[fmt]],
        input=data, capture_output=True, timeout=300)
    if proc.returncode == 0:
        text = proc.stdout.decode("utf-8", errors="replace")
        if fmt == "pdf":
            pages = _page_count(data)
            if pages and len(text.split()) < THIN_WORDS_PER_PAGE * pages:
                try:
                    ocr = _ocr_pdf(data)
                    if len(ocr.split()) > len(text.split()):
                        return ocr, _ocr_tag()
                except Exception:  # noqa: BLE001 - thin but OCR unavailable: keep anydoc's
                    pass
        return text, f"anydoc@{ANYDOC_VERSION}"
    err = proc.stderr.decode(errors="replace")
    if fmt != "pdf" or "OCR" not in err:
        raise ValueError(err.strip()[:200])
    flagged = _ocr_pages(err)
    if flagged and flagged[0] and len(flagged[0]) < flagged[1]:
        return (_mixed_pdf(data, *flagged),
                f"anydoc@{ANYDOC_VERSION}+tesseract@{_tool_version('tesseract')}")
    return _ocr_pdf(data), _ocr_tag()


def download(file_id, fmt, strategy):
    if strategy == "export-docx":
        data = fetch(f"https://docs.google.com/document/d/{file_id}/export?format=docx")
    elif strategy == "export-xlsx":
        data = fetch(f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx")
    else:
        data = fetch(f"https://drive.google.com/uc?export=download&id={file_id}")
        if not data.startswith(MAGIC[fmt]):
            # large files get a scan-warning interstitial; the usercontent host skips it
            data = fetch("https://drive.usercontent.google.com/download"
                         f"?id={file_id}&export=download&confirm=t")
    if not data.startswith(MAGIC[fmt]):
        raise ValueError(f"did not receive a {fmt}")
    return data


def slugify(name):
    name = re.sub(r"\.(pdf|docx?|xlsx?)$", "", name, flags=re.I)
    return "cpsd-" + re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


DATE_ISO = re.compile(r"(20\d\d)[-_./ ](\d{1,2})[-_./ ](\d{1,2})")
DATE_MDY = re.compile(r"(\d{1,2})[-_./ ](\d{1,2})[-_./ ](\d{2}|20\d\d)\b")


def doc_date(name):
    """ISO date parsed out of a district filename, or ''."""
    m = DATE_ISO.search(name)
    if m:
        y, mo, d = m.groups()
    else:
        m = DATE_MDY.search(name)
        if not m:
            return ""
        mo, d, y = m.groups()
        y = y if len(y) == 4 else f"20{y}"
    try:
        return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def minutes_slug(name):
    """Date-first minutes slug (cpsd-YYYY-MM-DD-…) so IDs sort and never collide."""
    iso = doc_date(name)
    if not iso:
        return slugify(name)
    rest = DATE_ISO.sub(" ", name, count=1)
    rest = DATE_MDY.sub(" ", rest, count=1)
    rest = re.sub(r"\.(pdf|docx?|xlsx?)$", "", rest, flags=re.I)
    rest = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", rest.lower())).strip("-")
    return f"cpsd-{iso}-{rest}" if rest else f"cpsd-{iso}"


def clean_name(name):
    # the district prefixes files staged for its website with "WEBSITE:" cruft
    return re.sub(r"^\s*website\s*:?\s*", "", name, flags=re.I).strip()


def record_dir(container):
    # minutes are voluminous: shard per-document records by meeting year
    if container.get("type") == "minutes":
        return None  # decided per document from its dated filename
    return container.path.parent


def current_policy_numbers(recs):
    """policy number -> slug for every current policy record."""
    out = {}
    for r in recs:
        if r.get("type") == "policy" and r.get("status") == "current":
            num = policy_number(r.slug)
            if num:
                out[num] = r.slug
    return out


def mint(container, file_id, name, mime, existing_slugs, existing_ids, policy_nums):
    fmt, strategy = HANDLED[mime]
    rtype = container.get("type")
    name = clean_name(name)
    # records may be renamed to descriptive slugs after minting; the drive_id
    # is the identity that survives that
    if file_id in existing_ids:
        return f"SKIP {name} (drive_id already cataloged)"
    slug = base = minutes_slug(name) if rtype == "minutes" else slugify(name)
    n = 1
    while slug in existing_slugs:  # distinct files can share a cleaned name
        n += 1
        slug = f"{base}-{n}"
    if rtype == "policy":
        num = policy_number(slug)
        if num and num in policy_nums:
            # a second current text for one policy number needs a human: mint it
            # by hand and mark the loser superseded, or the catalog contradicts itself
            return (f"SKIP {name} (policy {num} already current as "
                    f"{policy_nums[num]}; supersede one by hand)")

    parent = record_dir(container)
    if parent is None:
        ymatch = re.search(r"20\d\d", name) or re.search(r"20\d\d", container.get("tags"))
        # year-less records live in the type root, the one layout lint allows
        parent = container.path.parent / ymatch.group(0) if ymatch else container.path.parent
    parent.mkdir(parents=True, exist_ok=True)

    data = download(file_id, fmt, strategy)
    markdown, extractor = extract_document(data, fmt, rtype)
    # gdoc/gsheet export bytes are non-deterministic (fresh zip per request), so
    # a hash of them would churn; only byte-stable downloads get sha256
    digest = sha256_bytes(data) if strategy == "binary" else ""

    (ROOT / "text" / f"{slug}.md").write_text(markdown, encoding="utf-8")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = re.sub(r"\.(pdf|docx?|xlsx?)$", "", name, flags=re.I).strip()
    path = parent / f"{slug}.md"
    path.write_text("\n".join([
        "---",
        f"title: {title}",
        f"org: {container.get('org')}",
        "unit:",
        f"type: {rtype}",
        f"format: {fmt}",
        "location: drive",
        "url:",
        f"drive_id: {file_id}",
        "drive_kind: file",
        f"rights: {container.get('rights')}",
        f"text: text/{slug}.md",
        f"retrieved: {today}",
        f"verified: {today}",
        f"date: {doc_date(name)}",
        f"sha256: {digest}",
        f"extractor: {extractor}",
        "status: current",
        f"tags: [{', '.join(container.tags())}]",
        "---",
        f"Source file '{name}' from the [{container.slug}] container; "
        f"extracted with {extractor.split('@')[0]}.",
    ]) + "\n", encoding="utf-8")
    existing_slugs.add(slug)
    existing_ids.add(file_id)
    if rtype == "policy":
        num = policy_number(slug)
        if num:
            policy_nums[num] = slug
    return f"MINTED {slug}"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    all_records = records()
    by_slug = {r.slug: r for r in all_records}
    existing = set(by_slug)
    existing_ids = {r.get("drive_id") for r in all_records if r.get("drive_id")}
    policy_nums = current_policy_numbers(all_records)
    for container_slug in sys.argv[1:]:
        container = by_slug.get(container_slug)
        if container is None or container.get("drive_kind") != "folder":
            print(f"FAIL {container_slug} is not a drive-folder container record")
            continue
        queue = [(container.get("drive_id"), 0)]
        while queue:
            folder_id, depth = queue.pop(0)
            for file_id, name, mime in list_folder(folder_id):
                if mime == "application/vnd.google-apps.folder":
                    if depth < 2:
                        queue.append((file_id, depth + 1))
                    else:
                        print(f"SKIP {name} (folder deeper than recursion limit)")
                    continue
                if mime not in HANDLED:
                    print(f"SKIP {name} (mime {mime} not handled)")
                    continue
                try:
                    print(mint(container, file_id, name, mime, existing,
                               existing_ids, policy_nums))
                except Exception as exc:  # noqa: BLE001 - keep the batch going
                    print(f"FAIL {name} -- {exc}")


if __name__ == "__main__":
    main()
