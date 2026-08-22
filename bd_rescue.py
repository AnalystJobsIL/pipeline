#!/usr/bin/env python3
"""Rescue 'unreachable' companies through Bright Data Web Unlocker (residential unblocking).

Fetches each anti-bot-blocked careers page via the Unlocker (free tier: 5,000 req/month — a full
pass over ~107 pages costs ~107-300), extracts ATS/Comeet/Workday signatures or JSON-LD from the
returned HTML, verifies against the LIVE ATS API, and promotes recoveries in companies.csv.

Needs BRIGHTDATA_API_KEY + BRIGHTDATA_ZONE in the environment or secrets.env
(run setup_brightdata.py once). Never prints the key.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.request

from resolve_deep import _verify
from retry_unreachable import alt_urls
from wayback_rescue import extract_ats
from scrape_universal import ISRAEL_LOC, ROLE

ROOT = os.path.dirname(os.path.abspath(__file__))
_MOD = set()   # names this run rewrote (single-writer merge)


def _load_secrets():
    p = os.path.join(ROOT, "secrets.env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)


def unlock(url, timeout=90):
    """Fetch url through Web Unlocker; returns HTML ('' on failure)."""
    body = json.dumps({"zone": os.environ["BRIGHTDATA_ZONE"], "url": url,
                       "format": "raw"}).encode()
    req = urllib.request.Request("https://api.brightdata.com/request", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(2_000_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def main():
    _load_secrets()
    if not (os.environ.get("BRIGHTDATA_API_KEY") and os.environ.get("BRIGHTDATA_ZONE")):
        print("BRIGHTDATA_API_KEY / BRIGHTDATA_ZONE not set — run setup_brightdata.py first")
        return
    limit = int(os.environ.get("BD_LIMIT", "0"))
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    idx = {r[0].strip(): (i, r[3]) for i, r in enumerate(rows)
           if len(r) >= 6 and "unreachable" in (r[5] or "").lower()}
    import datetime as _dtm
    recent = (_dtm.date.today() - _dtm.timedelta(days=7)).isoformat()
    def _skip(name):
        note = rows[idx[name][0]][5] if len(rows[idx[name][0]]) > 5 else ""
        m2 = re.search(r"bd-tried (\d{4}-\d{2}-\d{2}) x(\d+)", note)
        return bool(m2 and (m2.group(1) >= recent or int(m2.group(2)) >= 3))
    names = [n for n in idx if not _skip(n)]
    names = names[:limit] if limit else names
    print(f"bright-data rescuing {len(names)} unreachable ...")
    fixed = empt = still = 0
    for name in names:
        rowi, url = idx[name]
        best_html, best_url, resolved = "", url, False
        for alt in alt_urls(url)[:5]:              # try up to 5 candidate URLs via the unlocker
            html = unlock(alt)
            if len(html) < 600 or "NoSuchKey" in html[:400]:
                continue
            if len(html) > len(best_html):
                best_html, best_url = html, alt
            det = extract_ats(html, name)
            if det:
                plat, tok, api = det
                v = _verify(name, plat, tok, api)
                if v and v[0]:
                    n_all, il = v
                    _MOD.add(name)
                    rows[rowi] = [name, plat, tok, api, "true",
                                  f"brightdata-rescued; {n_all}/{il} IL"]
                    fixed += 1
                    resolved = True
                    print(f"  [OK] {name}: {plat} jobs={n_all} il={il}", flush=True)
                    break
        if resolved:
            time.sleep(1)
            continue
        if not best_html:
            still += 1
            import datetime as _dtm
            note = rows[rowi][5] if len(rows[rowi]) > 5 else ""
            mm = re.search(r"x(\d+)$", note)
            n_try = (int(mm.group(1)) if mm else 0) + 1
            rows[rowi][5] = f"unreachable; bd-tried {_dtm.date.today().isoformat()} x{n_try}"
            _MOD.add(name)
            print(f"  unre {name}", flush=True)
            time.sleep(1)
            continue
        # reached a real page but no resolvable board -> validated scan
        has_signal = any(ROLE.search(best_html[max(0, m.start() - 250):m.end() + 250])
                         for m in ISRAEL_LOC.finditer(best_html))
        note = ("scanned via brightdata; roles-text present but no resolvable board"
                if has_signal else "scanned via brightdata; no open Israel roles now")
        # keep the row hunt-eligible: append our verdict to the existing note instead of
        # replacing it (replacing destroyed monitored-candidate/host-documented tokens and
        # landed on a string no re-check matched — 31 rows were stranded this way)
        prev = re.sub(r"(^|\s\|\s)scanned via brightdata;[^|]*", "", rows[rowi][5] or "").strip(" |")
        note = ((prev + " | ") if prev else "") + note + " - monitored candidate"
        rows[rowi] = [name, "scrape", best_url, best_url, "false", note[:220]]
        _MOD.add(name)
        empt += 1
        print(f"  empt {name}", flush=True)
        time.sleep(1)
    # single-writer discipline: merge back only rows this run modified
    changed = {r[0]: r for r in rows if r and len(r) > 5 and r[0] in _MOD}
    fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
    for _i, fr in enumerate(fresh):
        if fr and len(fr) > 5 and fr[0] in changed:
            fresh[_i] = changed[fr[0]]
    with open("companies.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(fresh)
    print(f"=== rescued {fixed} · validated {empt} · still unreachable {still} ===")


if __name__ == "__main__":
    main()
