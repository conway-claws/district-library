#!/usr/bin/env python3
"""One-time supersession surgery, 2026-08: encode which coexisting texts are current.

The district's Drive containers genuinely hold multiple revisions of the same
policy, and its CMS pages post the same contract more than once; seeding
faithfully minted them all as `status: current`, which made the catalog vouch
for repealed policy text. This pass flips each older revision to `superseded`
with a `superseded_by:` link (decisions below were made by diffing the pair and
reading Last Revised lines — recorded here, not inferred at runtime), retires
byte-identical duplicate postings to pointer-only records, and chains the
superintendent contract lineage. Idempotent; kept in bin/ as the record of what
was decided and why.
"""

from catalog import ROOT, records

# (older slug, newer slug, kind); kind 'revision' links both directions,
# 'duplicate' retires the older to pointer-only (text deleted — byte-identical
# to the survivor's) with only superseded_by set: a duplicate posting is not a
# revision, so the survivor claims no `supersedes` lineage over it.
DECISIONS = [
    # -- policy revisions: older text vs newer, picked by Last Revised / content
    ("cpsd-3-46-licensed-personnel-responsibilities-in-dealing-with-sex-offenders-on-campus-2",
     "cpsd-3-46-licensed-personnel-responsibilities-in-dealing-with-sex-offenders-on-campus",
     "revision"),  # 2009 vs 2020
    ("cpsd-3-56-obtain-and-release-std-meal-info",
     "cpsd-3-56-obtaining-and-releasing-std-meal-eligibility-information",
     "revision"),  # 2014 vs 2020
    ("cpsd-3-60-written-code-of-conduct-procurement-cnp",
     "cpsd-3-60-written-code-of-conduct-procurement-cnp-05-23-2019",
     "revision"),  # pre-DESE naming vs post-2019 DESE naming
    ("cpsd-8-04-classified-employees-drug-testing-04-14-2015",
     "cpsd-8-04-classified-employees-drug-testing-04-12-2022",
     "revision"),  # 2015 vs 2022
    ("cpsd-8-05-classified-employees-sick-leave-excluding-food-service-and-bus-drivers-cps-2",
     "cpsd-8-05-classified-employees-sick-leave-excluding-food-service-and-bus-drivers-cps",
     "revision"),  # 2016 vs 2020
    ("cpsd-8-05a-classified-employees-sick-leave-food-service-2",
     "cpsd-8-05a-classified-employees-sick-leave-food-service",
     "revision"),  # 2016 vs 2020
    ("cpsd-8-05b-classified-employees-sick-leave-bus-drivers-2",
     "cpsd-8-05b-classified-employees-sick-leave-bus-drivers",
     "revision"),  # 2016 vs 2020
    ("cpsd-8-17-classified-personnel-political-activity",
     "cpsd-8-17-classified-personnel-political-activity-02-11-2020",
     "revision"),  # base lacks the legal references the 2020 posting adds
    ("cpsd-8-20-classified-personnel-sexual-harassment",
     "cpsd-8-20-classified-personnel-sexual-harassment-03-14-2023",
     "revision"),  # 2012 vs 2023
    ("cpsd-8-26-classified-personnel-responsibilities-governing-bullying",
     "cpsd-8-26-classified-personnel-responsibilities-governing-bullying-06-12-2020",
     "revision"),  # 2014 vs 2020
    ("cpsd-8-36-classified-personnel-responsibilities-in-dealing-with-sex-offenders-on-campus-2",
     "cpsd-8-36-classified-personnel-responsibilities-in-dealing-with-sex-offenders-on-campus",
     "revision"),  # 2009 vs 2020
    ("cpsd-8-41-obtaining-and-releasing-students-free-and-reduced-price-meal-eligibility-information-2",
     "cpsd-8-41-obtaining-and-releasing-students-free-and-reduced-price-meal-eligibility-information",
     "revision"),  # 2014 vs 2020
    ("cpsd-8-42-classified-personnel-weapons-on-campus-2",
     "cpsd-8-42-classified-personnel-weapons-on-campus",
     "revision"),  # 2016 vs 2020 (LEO exception added)
    ("cpsd-8-43-written-code-of-conduct-for-employees-child-nutrition",
     "cpsd-8-43-written-code-of-conduct-for-employees-child-nutrition-05-23-2019",
     "revision"),  # pre-DESE naming vs post-2019 DESE naming
    # -- byte-identical duplicate postings (same document at a second asset URL)
    ("cpsd-8-16-dress-of-classified-employees-excluding-maintenance-and-custodial-see-8-16a-2",
     "cpsd-8-16-dress-of-classified-employees-excluding-maintenance-and-custodial-see-8-16a",
     "duplicate"),
    ("cpsd-8-29-classified-personnel-video-surveillance-and-other-monitoring-2",
     "cpsd-8-29-classified-personnel-video-surveillance-and-other-monitoring",
     "duplicate"),
    ("cpsd-superintendent-contract-collum-2023-2026-dup",
     "cpsd-superintendent-contract-collum-2023-2026",
     "duplicate"),
    ("cpsd-superintendent-contract-collum-fragment-b",
     "cpsd-superintendent-contract-collum-fragment-a",
     "duplicate"),
    # -- superintendent contract lineage (each instrument replaced by the next)
    ("cpsd-superintendent-contract-collum-2023-2026",
     "cpsd-superintendent-contract-collum-2024",
     "revision"),
    ("cpsd-superintendent-contract-collum-2024",
     "cpsd-interim-superintendent-contract-2025-2026",
     "revision"),
    ("cpsd-interim-superintendent-contract-2025-2026",
     "cpsd-superintendent-employment-agreement-2026-2028",
     "revision"),
    ("cpsd-superintendent-employment-agreement-2026-2028",
     "cpsd-superintendent-employment-agreement-2026-2029",
     "revision"),
]

# expired without a successor instrument: superseded, no superseded_by
EXPIRED = ["cpsd-superintendent-contract-addendum-2024-2025"]


def main():
    by_slug = {r.slug: r for r in records()}
    for older_slug, newer_slug, kind in DECISIONS:
        older, newer = by_slug.get(older_slug), by_slug.get(newer_slug)
        if older is None or newer is None:
            print(f"FAIL missing record: {older_slug if older is None else newer_slug}")
            continue
        changed = older.get("status") != "superseded"
        older.set("status", "superseded")
        older.set("superseded_by", newer_slug)
        if kind == "duplicate" and older.get("text"):
            (ROOT / older.get("text")).unlink(missing_ok=True)
            older.set("text", "")
            older.set("retrieved", "")
            if "duplicate" not in older.body.lower():
                older.body += (f"\nByte-identical duplicate posting of [{newer_slug}]; "
                               "retired to a pointer record, the asset URL stays watched.")
        elif kind == "revision" and f"[{newer_slug}]" not in older.body:
            older.body += f"\nSuperseded revision; the current text is [{newer_slug}]."
        older.save()
        if kind == "revision":
            newer.set("supersedes", older_slug)
            newer.save()
        print(f"{'FLIPPED' if changed else 'ALREADY'} {older_slug} -> {newer_slug} ({kind})")
    for slug in EXPIRED:
        rec = by_slug.get(slug)
        if rec is None:
            print(f"FAIL missing record: {slug}")
            continue
        rec.set("status", "superseded")
        if "expired" not in rec.body.lower():
            rec.body += ("\nExpired with the 2024-2025 school year; the Collum contract "
                         "it amended was replaced by [cpsd-interim-superintendent-contract-2025-2026].")
        rec.save()
        print(f"FLIPPED {slug} (expired, no successor instrument)")


if __name__ == "__main__":
    main()
