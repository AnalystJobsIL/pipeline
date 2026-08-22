#!/usr/bin/env python3
"""Cross-validate 'validated-empty' companies — are they REALLY empty?

For each company marked "scanned; no open Israel roles now", fetch its careers page over plain
HTTP and look for CONTRADICTING signals the scraper may have missed:
  - an embedded ATS/Comeet/Workday signature  -> resolve via the ATS API and count Israel jobs
  - Israel city names near role-like words in the raw HTML -> flag as suspect (parse miss)

Promotes any company whose ATS turns out to have live Israel jobs; reports suspects. Updates
companies.csv in place. This is a deterministic audit — no LLM, no browser.
"""
from __future__ import annotations

import csv
import re
import time
import urllib.request

from wayback_rescue import extract_ats
from resolve_deep import _verify
from scrape_universal import ROLE, ISRAEL_LOC

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"


def _get(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(1_200_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def check(name, url):
    """Return ('promote', row) | ('suspect', reason) | ('confirmed', None)."""
    html = _get(url)
    if len(html) < 500:
        return ("confirmed", None)                 # can't re-check; leave as-is
    det = extract_ats(html, name)
    if det:
        plat, tok, api = det
        v = _verify(name, plat, tok, api)
        if v:
            n_all, il = v
            if il > 0:                              # scraper missed a live board with Israel jobs!
                return ("promote", [name, plat, tok, api, "true",
                                    f"cross-validated; {n_all}/{il} IL (was empty)"])
            return ("confirmed", None)              # board exists, genuinely 0 Israel now
    # textual contradiction: Israel city near a role word
    hits = 0
    for m in ISRAEL_LOC.finditer(html):
        ctx = html[max(0, m.start() - 300):m.end() + 300]
        if ROLE.search(ctx):
            hits += 1
        if hits >= 2:
            return ("suspect", f"{hits}+ role-near-Israel mentions in HTML")
    return ("confirmed", None)


_MODIFIED = set()   # names this run rewrote (single-writer merge)


def main():
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    idx = {r[0].strip(): (i, r[3]) for i, r in enumerate(rows)
           if len(r) >= 6 and "no open israel roles" in (r[5] or "").lower()}
    print(f"cross-validating {len(idx)} validated-empty companies ...")
    promoted, suspects, confirmed = 0, [], 0
    for name, (rowi, url) in idx.items():
        try:
            kind, payload = check(name, url)
        except Exception:  # noqa: BLE001
            kind, payload = "confirmed", None
        if kind == "promote":
            rows[rowi] = payload
            _MODIFIED.add(name)
            promoted += 1
            print(f"  [PROMOTE] {name}: {payload[5]}", flush=True)
        elif kind == "suspect":
            suspects.append((name, payload))
            # append, don't replace: the base note carries the row's re-check pool token
            _base = re.sub(r"\s\|\s?empty-but-suspect;[^|]*", "", rows[rowi][5] or "").strip(" |")
            rows[rowi][5] = ((_base + " | ") if _base else "") + "empty-but-suspect; " + payload
            _MODIFIED.add(name)
        else:
            confirmed += 1
        time.sleep(0.1)
    # single-writer discipline: merge back only rows this run modified
    changed = {r[0]: r for r in rows if r and len(r) > 5 and r[0] in _MODIFIED}
    fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
    for _i, fr in enumerate(fresh):
        if fr and len(fr) > 5 and fr[0] in changed:
            fresh[_i] = changed[fr[0]]
    with open("companies.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(fresh)
    print(f"\n=== promoted {promoted} · suspects {len(suspects)} · confirmed-empty {confirmed} ===")
    for n, why in suspects[:25]:
        print(f"   suspect: {n} ({why})")


if __name__ == "__main__":
    main()
