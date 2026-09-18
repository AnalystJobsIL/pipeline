#!/usr/bin/env python3
"""One-off (2026-09-18, `scraper`): blank the description of every url-less cache card that
holds a SIBLING's text, keeping the card that held it FIRST.

`refresh_scrape_cache._carry_jd` keyed `prev` by a card's url, and a url-less card's url is
the LISTING every url-less card on that board shares -- so `prev[listing]` was whichever old
card came last and its text went to any new title with an empty description. Git shows the
spread: Medison's compensation body sat on `Senior Total Rewards Analyst` alone from
2026-08-31 and reached five titles by 09-16, one a night.

The capture fix (`_addresses(j, listing)`) stops the next carry; it cannot undo the ones on
disk, because a url-less card has no page any layer can re-read (`not_job_url`) and the text
would simply be carried again from the same twin. So the wrong copies are voided ONCE, by
name, and the OWNER keeps its text.

Cal's two `נציג/ת שירות ומכירה` cards (Ashdod / Bnei Brak) are deliberately NOT here: both
titles arrived holding that 312-character body in the same commit (`1398106d`, 09-14). They
are one posting at two branches, read by `_card_own_text` from the listing, not a carry --
which is why the `carried_twins` counter on the `collect:` stamp settles at 2 and not 0.

Dry-run by default; `--apply` writes. Re-read the file immediately before applying: the 00:00
refresh commits it too.

lane: `scraper`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.atomic import write_json        # noqa: E402

CACHE = "scraped_cache.json"

# company -> (owner title, [titles to void]). Owner = the first title git shows holding the
# text; every other title acquired it on a later night with no fetch of its own.
VOID = {
    "Discount Bank": ("מנהל.ת בכיר.ה מקצועי.ת- ניהול אגף נכסים ובינוי",
                      ["יועץ.ת משכנתאות - סניף לוד - החטיבה הבנקאית"]),
    "Magic Software": ("Magic XPI – Developer position", ["R&D Architect"]),
    "Medison Pharma": ("Senior Total Rewards Analyst",
                       ["HR Business Partner (HRBP)", "Senior AI Enablement",
                        "Senior ERP Specialist, Business Technology",
                        "Senior Product Designer, Business Technology"]),
    "Mikud Security": ("מאבטח/ת לקריית הממשלה בירושלים – שכר 59-62 ₪ (משרה – 6876)",
                       ["מאבטח/ת לקריית הממשלה בתל אביב – שכר 59-62 ₪ (משרה – 6875)"]),
    "Omnisys": ("Senior Systems Engineer", ["Testing & Integration Engineer"]),
    "TELUS Digital": ("Online Data Analyst - Israel",
                      ["Media Search Analyst - Hebrew (Israel)"]),
    "בנק לאומי": ("בנקאי/ת PEPPER למרכז הבנקאות בראשל\"צ 2787",
                  ["מהנדס/ת Generative AI 2920"]),
}


def plan(cache):
    """(hits, misses): the cards to void, and every named card the cache no longer has."""
    hits, misses = [], []
    for company, (owner, victims) in VOID.items():
        jobs = cache.get(company)
        if not isinstance(jobs, list):
            misses.append(f"{company}: no cache entry")
            continue
        own = [j for j in jobs if isinstance(j, dict) and j.get("title") == owner]
        if len(own) != 1 or not (own[0].get("description") or "").strip():
            misses.append(f"{company}: owner {owner!r} is not a single described card")
            continue
        text = own[0]["description"]
        for title in victims:
            same = [j for j in jobs if isinstance(j, dict) and j.get("title") == title
                    and (j.get("description") or "") == text]
            if not same:
                misses.append(f"{company}: {title!r} no longer holds the owner's text")
                continue
            hits.extend((company, title, j) for j in same)
    return hits, misses


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the cache (default: dry run)")
    o = ap.parse_args(argv)
    with open(CACHE, encoding="utf-8") as fh:
        cache = json.load(fh)
    hits, misses = plan(cache)
    for company, title, _j in hits:
        print(f"void  {company} | {title}")
    for m in misses:
        print(f"skip  {m}")
    if not o.apply:
        print(f"dry run: {len(hits)} card(s) would lose a sibling's text "
              f"({len(misses)} already gone). --apply to write.")
        return 0
    for _company, _title, j in hits:
        j["description"] = ""
        j.pop("_jd_attempted", None)
    write_json(CACHE, cache, sort_keys=True)
    with open(CACHE, encoding="utf-8") as fh:               # it must still parse whole
        json.load(fh)
    print(f"voided {len(hits)} card(s) in {CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
