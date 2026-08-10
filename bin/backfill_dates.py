#!/usr/bin/env python3
"""One-time date backfill, 2026-08: give records their document's own date.

`date:` is the date of the document itself (meeting held, policy last revised,
reporting month ended) as distinct from retrieved/verified, which are capture
dates. Sources tried in order: an ISO or M-D-Y date in the slug, a month-name
plus year in the slug (monthly reports date to month end), a date in the title,
then the extraction's Date Adopted / Last Revised footer (Last Revised wins —
it is the revision the text embodies). Ambiguous records stay blank: a wrong
date is worse than none. Feed records span a school year and get no date.
Idempotent: records with a date already set are left alone.
"""

import calendar
import re
from datetime import datetime

from catalog import ROOT, records

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
ISO = re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b")
MDYYYY = re.compile(r"\b(\d{1,2})-(\d{1,2})-(20\d\d)\b")
MDY = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{2})\b")
MONTH_YEAR = re.compile(
    r"\b(" + "|".join(MONTHS) + r")[ -](20\d\d)\b", re.I)
LONG_DATE = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),?\s+((?:19|20)\d\d)\b", re.I)
FOOTER = re.compile(
    r"(Date Adopted|Last Revised)\s*[:|]*\s*(" + "|".join(MONTHS)
    + r")\s+(\d{1,2}),?\s+((?:19|20)\d\d)", re.I)


def iso(y, m, d):
    try:
        return datetime(int(y), int(m), int(d)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def month_end(name, year):
    m = MONTHS[name.lower()]
    return iso(year, m, calendar.monthrange(int(year), m)[1])


def from_string(s):
    m = ISO.search(s)
    if m:
        return iso(m.group(1), m.group(2), m.group(3))
    m = MDYYYY.search(s)
    if m:
        return iso(m.group(3), m.group(1), m.group(2))
    m = MDY.search(s)
    if m:
        return iso(f"20{m.group(3)}", m.group(1), m.group(2))
    m = MONTH_YEAR.search(s)
    if m:
        return month_end(m.group(1), m.group(2))
    return ""


def from_text(path):
    text = path.read_text(encoding="utf-8")
    revised = adopted = ""
    for kind, name, day, year in FOOTER.findall(text):
        stamp = iso(year, MONTHS[name.lower()], day)
        if kind.lower().startswith("last"):
            revised = stamp or revised
        else:
            adopted = stamp or adopted
    return revised or adopted


def main():
    stamped = blank = 0
    for rec in records():
        if rec.get("date") or rec.get("type") == "feed":
            continue
        date = from_string(rec.slug) or from_string(rec.get("title"))
        if not date:
            m = LONG_DATE.search(rec.get("title"))
            if m:
                date = iso(m.group(3), MONTHS[m.group(1).lower()], m.group(2))
        if not date and rec.get("text") and (ROOT / rec.get("text")).is_file():
            date = from_text(ROOT / rec.get("text"))
        if date:
            rec.set("date", date)
            rec.save()
            stamped += 1
            print(f"DATED {rec.slug} {date}")
        else:
            blank += 1
    print(f"DONE {stamped} dated, {blank} left blank")


if __name__ == "__main__":
    main()
