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
import urllib.error
import urllib.request

from pipeline import identity_gate as _gate
from pipeline.notes import replace_own as _note_replace
from pipeline.verdicts import is_terminal

from resolve_deep import _verify
from retry_unreachable import alt_urls
from wayback_rescue import extract_ats
from scrape_universal import ISRAEL_LOC, ROLE
from pipeline.atomic import write_csv_rows

ROOT = os.path.dirname(os.path.abspath(__file__))
_MOD = set()   # names this run rewrote (single-writer merge)


def _reached_note(base):
    """The unlocker REACHED the page, so `unreachable` is disproved: remove that token (it
    is this tool's own, per `pipeline.verdicts.TOKENS`) and the `bd-tried` counter, keep
    every other tool's segment. Leaving `unreachable` in place re-selected the row for
    `retry_unreachable` 90 seconds later in the same job, which rewrote the cell and erased
    the verdict this call had just paid a credit for (2026-08-25, 9 rows nightly)."""
    return _note_replace(_note_replace(base, "unreachable", ""), "bd-tried", "")


def _load_secrets():
    p = os.path.join(ROOT, "secrets.env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)


# what the LAST unlock reported: "" on success, else `policy_20140` (the host is closed to
# residential access -- every myworkdayjobs.com page), `reject_block` (walled),
# `http-401` (a dead token: the ACCOUNT is unusable), `timeout`. Six spenders share this
# function and used to see every one of those as "no HTML" (BACKLOG 110).
LAST = {"error": "", "status": None}


def unlock_status(url, timeout=90):
    """(html, error). `error` is "" on success; see LAST."""
    body = json.dumps({"zone": os.environ["BRIGHTDATA_ZONE"], "url": url,
                       "format": "raw"}).encode()
    req = urllib.request.Request("https://api.brightdata.com/request", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read(2_000_000).decode("utf-8", "replace")
            err = r.headers.get("x-brd-error-code") or ""       # 200 with a failure inside
            LAST.update(error=err, status=r.status)
            return ("" if err else text), err
    except urllib.error.HTTPError as e:
        LAST.update(error=f"http-{e.code}", status=e.code)
        return "", f"http-{e.code}"
    except Exception:  # noqa: BLE001
        LAST.update(error="timeout", status=None)
        return "", "timeout"


def unlock(url, timeout=90):
    """Fetch url through Web Unlocker; returns HTML ('' on failure). `LAST["error"]` says why."""
    return unlock_status(url, timeout)[0]


def _policy_closed(err):
    """A `policy_*` code is Bright Data refusing the HOST, not a transient: retrying it
    nightly spends a credit for the same answer."""
    return str(err or "").startswith("policy_")


def main():
    _load_secrets()
    if not (os.environ.get("BRIGHTDATA_API_KEY") and os.environ.get("BRIGHTDATA_ZONE")):
        print("BRIGHTDATA_API_KEY / BRIGHTDATA_ZONE not set — run setup_brightdata.py first")
        return
    limit = int(os.environ.get("BD_LIMIT", "0"))
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    # terminal rows are never re-attempted (an `alias-of` twin parked while unreachable
    # would otherwise be unlocked -- and paid for -- 90 s before retry_unreachable skips it)
    idx = {r[0].strip(): (i, r[3]) for i, r in enumerate(rows)
           if len(r) >= 6 and "unreachable" in (r[5] or "").lower()
           and not is_terminal(r[5] or "")}
    import datetime as _dtm
    recent = (_dtm.date.today() - _dtm.timedelta(days=7)).isoformat()
    def _skip(name):
        note = rows[idx[name][0]][5] if len(rows[idx[name][0]]) > 5 else ""
        m2 = re.search(r"bd-tried (\d{4}-\d{2}-\d{2}) x(\d+)", note)
        # a host Bright Data's policy refuses is never retried (BACKLOG 110)
        return bool("bd-policy" in note
                    or (m2 and (m2.group(1) >= recent or int(m2.group(2)) >= 3)))
    names = [n for n in idx if not _skip(n)]
    names = names[:limit] if limit else names
    print(f"bright-data rescuing {len(names)} unreachable ...")
    fixed = empt = still = 0
    for name in names:
        rowi, url = idx[name]
        best_html, best_url, resolved = "", url, False
        policy = ""
        for alt in alt_urls(url)[:5]:              # try up to 5 candidate URLs via the unlocker
            html, err = unlock_status(alt)
            if err.startswith("http-4"):
                # 401/402/403 from the API itself: the ACCOUNT is unusable -- stop spending
                print(f"::warning::bd_rescue: Bright Data answered {err}; stopping the pass",
                      flush=True)
                raise SystemExit(0)
            if _policy_closed(err):
                policy = err
                break                            # the host is refused, not the page
            if len(html) < 600 or "NoSuchKey" in html[:400]:
                continue
            if len(html) > len(best_html):
                best_html, best_url = html, alt
            det = extract_ats(html, name)
            if det:
                plat, tok, api = det
                v = _verify(name, plat, tok, api)
                # The unlocker HTML is IN HAND, so gate on the page this candidate was
                # extracted FROM - strictly stronger evidence than a re-fetch, and free.
                # The page can only REFUSE: `extract_ats` returns whatever board the page
                # embeds, and a page naming THIS company cannot vouch for someone else's
                # board (wave-4 R1) -- so activation also needs `embedded_board_ok`, the
                # board's own tenant token near-matching the name.
                # Until 2026-08-24 this branch had no identity check at all: `extract_ats`
                # finds whatever board a page embeds, and a company page that embeds another
                # company's board (or a bot-wall interstitial that embeds the vendor's own)
                # activated that board under this company's name.
                if v and v[0] and not (_gate.activation_ok(name, api, v[0], html=html)
                                       and _gate.embedded_board_ok(name, tok, api)):
                    print(f"  [XX] {name}: {plat} verified {v[0]} but {api[:44]} is not "
                          f"this company's board", flush=True)
                    v = None
                if v and v[0]:
                    n_all, il = v
                    _MOD.add(name)
                    rows[rowi] = [name, plat, tok, api, "true",
                                  _note_replace(_reached_note(rows[rowi][5]),
                                                "brightdata-rescued",
                                                f"brightdata-rescued; {n_all}/{il} IL")]
                    fixed += 1
                    resolved = True
                    print(f"  [OK] {name}: {plat} jobs={n_all} il={il}", flush=True)
                    break
        if resolved:
            time.sleep(1)
            continue
        if policy and not best_html:
            still += 1
            import datetime as _dtm
            rows[rowi][5] = _note_replace(rows[rowi][5] or "unreachable; could not scan",
                                          "bd-policy", f"bd-policy {_dtm.date.today().isoformat()}: {policy}")
            _MOD.add(name)
            print(f"  pol  {name} ({policy}: host closed to the unlocker; not retried)", flush=True)
            time.sleep(1)
            continue
        if not best_html:
            still += 1
            import datetime as _dtm
            note = rows[rowi][5] if len(rows[rowi]) > 5 else ""
            # unanchored: retry_unreachable appends its own segment AFTER this one 90 s
            # later, so a `$` anchor read `x1` forever and the give-up at x3 never came
            mm = re.search(r"bd-tried \d{4}-\d{2}-\d{2} x(\d+)", note)
            n_try = (int(mm.group(1)) if mm else 0) + 1
            _base = rows[rowi][5] or "unreachable; could not scan"
            rows[rowi][5] = _note_replace(
                _base, "bd-tried",
                f"bd-tried {_dtm.date.today().isoformat()} x{n_try}")
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
        note = _note_replace(_reached_note(rows[rowi][5]), "scanned via brightdata",
                             note + " - monitored candidate")
        rows[rowi] = [name, "scrape", best_url, best_url, "false", note]
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
    write_csv_rows("companies.csv", fresh)
    print(f"=== rescued {fixed} · validated {empt} · still unreachable {still} ===")


if __name__ == "__main__":
    main()
