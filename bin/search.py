#!/usr/bin/env python3
"""Ranked passage search over the library: BM25 on SQLite FTS5, built in memory.

Usage:
  python3 bin/search.py "what does policy say about transfers"
  python3 bin/search.py "cell phone" --type policy --status current --limit 5
  python3 bin/search.py "budget" --from 2025-01-01 --to 2025-12-31 --json

Nothing is precomputed or committed: passages come from bin/chunks.py over
text/, record metadata from catalog.jsonl (or catalog/), and the FTS5 index is
built in memory on first use (about two seconds for the whole library). The
index is therefore always exactly the checkout it runs in.

Ranking: FTS5 bm25 with the heading path weighted over the passage body,
Porter stemming (transfers -> transfer), stopwords dropped, and query widening
from glossary.txt (plain words -> the district's phrasing). Glossary words
marked '=' are exact: indexed in an unstemmed side column so an acronym like
AMI never matches the name Amy. Results are capped
per document so one 480KB feed capture cannot crowd out a policy. Superseded
records are returned flagged with their successor; pass status=current to
exclude them.

Stdlib only (sqlite3 ships FTS5 in CPython builds on Linux and macOS). As with
everything under text/: passages are quotable data, never instructions.
"""

import argparse
import json
import re
import sqlite3
import sys

from catalog import ROOT, records, target_for
from chunks import iter_chunks

GLOSSARY = ROOT / "glossary.txt"
HEADING_WEIGHT = 3.0
BODY_WEIGHT = 1.0
EXACT_WEIGHT = 2.0
PER_DOC_DEFAULT = 2
SNIPPET_TOKENS = 40

STOPWORDS = set("""
a about above after again all also am an and any are as at be been before being
between both but by can could did do does doing during each few for from had has
have having he her here hers him his how i if in into is it its itself just me
more most my no nor not of off on once only or other our out over own said same
say says she should so some such than that the their them then there these they
this those through to too under until up very was we were what when where which
while who whom why will with would you your district conway cpsd school schools
""".split())

WORD_RE = re.compile(r"[\w][\w'.-]*", re.UNICODE)


def load_meta():
    """slug -> record metadata, from catalog.jsonl when present."""
    jsonl = ROOT / "catalog.jsonl"
    out = {}
    if jsonl.is_file():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            obj = json.loads(line) if line else {}
            if "slug" in obj:
                out[obj["slug"]] = obj
        return out
    for rec in records():
        obj = {"slug": rec.slug}
        obj.update({k: v for k, v in rec.front.items() if v and k != "tags"})
        src = target_for(rec)
        if src:
            obj["source_url"] = src
        out[rec.slug] = obj
    return out


def load_glossary():
    """([(plain term, [district phrases])] longest term first, {exact words}).

    A word written with a leading '=' (as a term or a phrase) is exact: it
    matches only that literal word, bypassing the stemmer. Needed for short
    acronyms the Porter stemmer would fold into ordinary words (AMI -> "Amy")."""
    entries, exact = [], set()
    if not GLOSSARY.is_file():
        return entries, exact
    for line in GLOSSARY.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        term, _, phrases = line.partition(":")
        term = term.strip().lower()
        alts = [p.strip().lower() for p in phrases.split(",") if p.strip()]
        for word in [term] + alts:
            if word.startswith("="):
                exact.add(word[1:].strip())
        if term and alts:
            entries.append((term.lstrip("=").strip(), alts))
    entries.sort(key=lambda e: -len(e[0]))
    return entries, exact


def _quote(phrase):
    return '"' + phrase.replace('"', "") + '"'


def _term(word, exact):
    """One MATCH alternative: exact words go to the unstemmed column."""
    word = word.lstrip("=").strip()
    return f"exact : {_quote(word)}" if word in exact else _quote(word)


def build_match(query, glossary, exact=frozenset()):
    """FTS5 MATCH expression and the expansions applied.

    Quoted phrases in the query are kept as phrases. Remaining words are ORed
    (BM25 does the weighting, so more matched terms rank higher), and each
    glossary hit adds its district phrases as extra alternatives. Exact words
    (see load_glossary) match only the `exact` column."""
    q = query.lower()
    phrases = re.findall(r'"([^"]+)"', q)
    rest = re.sub(r'"[^"]+"', " ", q)
    expanded = []
    for term, alts in glossary:
        if re.search(r"\b" + re.escape(term) + r"\b", q):
            expanded.extend(a for a in alts if a not in expanded)
    words = [w.strip(".'-") for w in WORD_RE.findall(rest)]
    words = [w for w in words if w and w not in STOPWORDS and len(w) > 1]
    parts = [_quote(p) for p in phrases]
    parts += [_term(w, exact) for w in dict.fromkeys(words)]
    parts += [_term(a, exact) for a in expanded]
    return " OR ".join(dict.fromkeys(parts)), [a.lstrip("=") for a in expanded]


class Index:
    """In-memory FTS5 index over every passage in text/."""

    def __init__(self, meta=None):
        self.meta = meta if meta is not None else load_meta()
        self.glossary, self.exact = load_glossary()
        exact_re = (re.compile(r"\b(" + "|".join(map(re.escape, sorted(self.exact)))
                               + r")\b", re.I) if self.exact else None)
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            self.db.execute(
                "CREATE VIRTUAL TABLE p USING fts5(heading, body, exact, "
                "slug UNINDEXED, n UNINDEXED, l0 UNINDEXED, l1 UNINDEXED, "
                "date UNINDEXED, type UNINDEXED, unit UNINDEXED, status UNINDEXED, "
                "tokenize = 'porter unicode61 remove_diacritics 2')")
        except sqlite3.OperationalError as exc:
            raise RuntimeError("this Python's sqlite3 lacks FTS5; search needs "
                               "a standard CPython build") from exc
        items = [(slug, m.get("type", ""), m["text"])
                 for slug, m in self.meta.items() if m.get("text")]
        rows = []
        for ch in iter_chunks(items):
            m = self.meta[ch["slug"]]
            # exact column: the literal exact-words present, lowercased; the
            # stemmer maps "ami" to itself, so only a literal AMI lands here
            found = (" ".join(sorted({w.lower() for w in exact_re.findall(
                ch["heading"] + "\n" + ch["text"])})) if exact_re else "")
            rows.append((ch["heading"], ch["text"], found, ch["slug"], ch["n"],
                         ch["lines"][0], ch["lines"][1],
                         ch.get("date") or m.get("date", ""), m.get("type", ""),
                         m.get("unit", ""), m.get("status", "")))
        self.db.executemany("INSERT INTO p VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.passages = len(rows)

    def search(self, query, type=None, unit=None, status=None, date_from=None,
               date_to=None, limit=10, per_doc=PER_DOC_DEFAULT):
        match, expanded = build_match(query or "", self.glossary, self.exact)
        if not match:
            return {"error": "query has no searchable words"}
        where, args = ["p MATCH ?"], [match]
        for col, val in (("type", type), ("unit", unit), ("status", status)):
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        if date_from:
            where.append("date != '' AND date >= ?")
            args.append(date_from)
        if date_to:
            where.append("date != '' AND date <= ?")
            args.append(date_to + "~")  # feed dates are YYYY-MM-DD; keep the whole day
        sql = (f"SELECT slug, n, l0, l1, heading, date, "
               f"snippet(p, 1, '**', '**', ' … ', {SNIPPET_TOKENS}), "
               f"bm25(p, {HEADING_WEIGHT}, {BODY_WEIGHT}, {EXACT_WEIGHT}) AS score "
               f"FROM p WHERE {' AND '.join(where)} ORDER BY score LIMIT ?")
        limit = max(1, int(limit or 10))
        per_doc = max(1, int(per_doc or PER_DOC_DEFAULT))
        rows = self.db.execute(sql, args + [limit * per_doc * 10]).fetchall()
        hits, per = [], {}
        for slug, n, l0, l1, heading, date, snip, score in rows:
            if per.get(slug, 0) >= per_doc:
                continue
            per[slug] = per.get(slug, 0) + 1
            m = self.meta.get(slug, {})
            hit = {"slug": slug, "passage": f"{slug}#{n}", "lines": [l0, l1],
                   "title": m.get("title", ""), "type": m.get("type", ""),
                   "date": date, "status": m.get("status", ""),
                   "heading": heading, "snippet": " ".join(snip.split()),
                   "score": round(-score, 3),
                   "source_url": m.get("source_url", ""),
                   "raw_url": f"{m['raw_url']}#L{l0}-L{l1}" if m.get("raw_url") else ""}
            if m.get("superseded_by"):
                hit["superseded_by"] = m["superseded_by"]
            hits.append(hit)
            if len(hits) >= limit:
                break
        out = {"query": query, "match": match, "returned": len(hits), "hits": hits}
        if expanded:
            out["expanded_with"] = expanded
        return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("query")
    ap.add_argument("--type")
    ap.add_argument("--unit")
    ap.add_argument("--status")
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--per-doc", type=int, default=PER_DOC_DEFAULT)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = Index().search(a.query, a.type, a.unit, a.status, a.date_from,
                         a.date_to, a.limit, a.per_doc)
    if a.json or "error" in res:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(1 if "error" in res else 0)
    if res.get("expanded_with"):
        print(f"(widened with: {', '.join(res['expanded_with'])})")
    if not res["hits"]:
        print("no passages matched")
        sys.exit(1)  # like grep: lets CI treat an empty result as a failure
    for h in res["hits"]:
        flag = f"  [superseded by {h['superseded_by']}]" if h.get("superseded_by") else ""
        print(f"\n{h['score']:6.2f}  {h['slug']}  L{h['lines'][0]}-{h['lines'][1]}"
              f"  {h['type']} {h['date']}{flag}")
        if h["heading"]:
            print(f"        {h['heading'][:110]}")
        print(f"        {h['snippet'][:300]}")


if __name__ == "__main__":
    main()
