"""Shared record parsing for the district-library catalog.

Records are markdown files with flat YAML-ish frontmatter (key: value lines between
--- fences; tags as [a, b]). Deliberately dependency-free so runners install nothing.
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"

TYPES = {"policy", "minutes", "finance", "statute", "news", "site", "drive",
         "form", "dataset", "media", "plan", "handbook", "calendar", "notice", "feed"}
RIGHTS = {"public-record", "public-web", "restricted"}
STATUSES = {"pending", "current", "superseded", "vanished"}
REQUIRED = ["title", "org", "type", "format", "location", "rights", "status", "tags"]
# Optional provenance/lineage fields (schema.md); validated by lint only when non-empty
OPTIONAL = ["date", "sha256", "extractor", "last_check", "fail_since", "fail_reason",
            "supersedes", "superseded_by"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def target_for(rec):
    """The public URL a record's source resolves at, derived from its fields."""
    if rec.get("url"):
        return rec.get("url")
    fid = rec.get("drive_id")
    if fid:
        if rec.get("drive_kind") == "folder":
            return f"https://drive.google.com/drive/folders/{fid}"
        # native Google files 500 on uc?export=download; probe their export URL
        fmt = rec.get("format")
        if fmt == "gdoc":
            return f"https://docs.google.com/document/d/{fid}/export?format=docx"
        if fmt == "gsheet":
            return f"https://docs.google.com/spreadsheets/d/{fid}/export?format=xlsx"
        return f"https://drive.google.com/uc?export=download&id={fid}"
    return None


_POLICY_NUM = re.compile(r"^cpsd-((?:\d+[a-z]?)(?:-\d+[a-z]?)*)(?:-|$)")


def policy_number(slug: str) -> str:
    """Normalized policy number from a policy slug ('' when the slug has none).

    cpsd-8-05b-... -> 8-5b; cpsd-02-administration -> 2. Leading zeros are
    stripped per component so 8-05 and 8-5 read as the same policy.
    """
    m = _POLICY_NUM.match(slug)
    if not m:
        return ""
    parts = m.group(1).split("-")
    if len(parts[0]) == 4 and parts[0].isdigit():
        return ""  # a leading year, not a policy number
    out = []
    for p in parts:
        num = p.rstrip("abcdefghijklmnopqrstuvwxyz")
        suffix = p[len(num):]
        out.append(str(int(num)) + suffix)
    return "-".join(out)


class Record:
    def __init__(self, path: Path) -> None:
        self.path: Path = path
        self.slug: str = self.path.stem
        self.front: dict[str, str] = {}  # tags kept as raw "[a, b]" string
        self.order: list[str] = []       # frontmatter key order, for faithful rewrite
        self.body: str = ""
        self._parse()

    def _parse(self) -> None:
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError(f"{self.path}: no frontmatter fence")
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            line = lines[i]
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                self.front[key] = val.strip()
                self.order.append(key)
            i += 1
        if i >= len(lines):
            raise ValueError(f"{self.path}: unterminated frontmatter")
        self.body = "\n".join(lines[i + 1:]).strip()

    def get(self, key: str) -> str:
        return self.front.get(key, "")

    def tags(self) -> list[str]:
        raw = self.get("tags").strip("[]")
        return [t.strip() for t in raw.split(",") if t.strip()]

    def set(self, key: str, value: str) -> None:
        if key not in self.front:
            self.order.append(key)
        self.front[key] = value

    def save(self) -> None:
        out = ["---"]
        for key in self.order:
            val = self.front[key]
            out.append(f"{key}: {val}" if val else f"{key}:")
        out.append("---")
        out.append(self.body)
        self.path.write_text("\n".join(out) + "\n", encoding="utf-8")


def records() -> list[Record]:
    return [Record(p) for p in sorted(CATALOG.rglob("*.md"))]
