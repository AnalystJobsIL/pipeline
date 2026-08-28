#!/usr/bin/env python3
"""Rescue 'unreachable' companies through Bright Data Web Unlocker (residential unblocking).

Fetches each anti-bot-blocked careers page via the Unlocker (free tier: 5,000 req/month — a full
pass over ~107 pages costs ~107-300), extracts ATS/Comeet/Workday signatures or JSON-LD from the
returned HTML, verifies against the LIVE ATS API, and promotes recoveries in companies.csv.

Needs BRIGHTDATA_API_KEY + BRIGHTDATA_ZONE in the environment or secrets.env
(run setup_brightdata.py once). Never prints the key.
"""
from __future__ import annotations

import atexit
import csv
import json
import os
import re
import sys
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

# THE CHOKEPOINT EVERY UNLOCKER SPENDER PASSES (lane: infra, 2026-08-28; shared plumbing, so
# it is named in the session record for every lane that spends here). Ten of the ~thirteen
# paths that buy a Bright Data credit reach the account through `unlock_status`:
# scrape_universal, crack_walled, triage_dark, repair_dead_urls, resolve_broken,
# identity_gate, deep_validate (and through it listing_hunt, resolve_llm, audit_empty_rows,
# registry_health), plus discovery_daily's Indeed and LinkedIn sweeps. Before this,
# scrape-refresh set SCRAPE_VIA_UNLOCKER=1 with no cap at all and spent 72 credits a night
# unattended (BACKLOG 335).
#
# `BD_RUN_CAP` IS PER PROCESS, AND THAT IS NOT WHAT A READER ASSUMES. `SPENT` is module state,
# so it resets in every interpreter -- and `refresh_scrape_cache` runs a spawn-context
# ProcessPoolExecutor, rebuilt per chunk, so a "150" there is 150 PER WORKER and the job's real
# ceiling is nearer 3,000. An adversarial pass measured that on 2026-08-28 before it shipped.
# It is still strictly better than the nothing it replaces -- it bounds a runaway loop inside
# one worker -- but it is a BLAST RADIUS, not a budget, and the honest per-job bound needs a
# counter outside the process (BACKLOG 359). Do not quote it as a job total.
#
# UNSET = no cap, so a lane that does not name it sees byte-for-byte the behaviour it saw
# before this existed; `0` means buy nothing. A capped call reports `bd-capped` -- but note
# that `unlock()` throws the reason away and returns "", so a CALLER cannot tell a refusal
# from a failure unless it reads `LAST["error"]`. `main()` below does; nothing else in the
# repo does, which is why a capped pass must never be allowed to write a verdict.
SPENT = {"n": 0, "capped": False}


def run_cap():
    """The cap in force, or None for no cap. UNSET means no cap; **`0` means buy nothing**.

    `0` used to mean unlimited, which is the wrong way round for the one number an operator
    reaches for when they want spend to stop -- `BD_RUN_CAP=0` read as "no limit" and the run
    spent freely. A value that will not parse (`1,000`, `1e3`) is a typo, not a licence: it
    warns and buys nothing rather than silently removing the cap it was meant to set."""
    raw = os.environ.get("BD_RUN_CAP")
    if raw is None or raw.strip() == "":
        return None
    try:
        return max(0, int(raw.strip()))
    except ValueError:
        print(f"::warning::bd_rescue: BD_RUN_CAP={raw!r} is not a number; buying nothing this "
              f"run rather than removing the cap it was meant to set", flush=True)
        return 0


def _report_spend():
    """What THIS process bought, on the way out. Per-workflow spend was unmeasurable before
    2026-08-28: `unlock_calls` is stamped only by refresh_scrape_cache, so the other six
    workflows that spend here reported nothing at all and their caps could only ever be
    guesses. One line per step makes the run page the evidence, and the next session can set
    a cap from a measurement instead of from a theoretical maximum."""
    if not SPENT["n"]:
        return
    cap = run_cap()
    print(f"[bd-spend] this step bought {SPENT['n']} Bright Data credit(s)"
          + (" (no cap set)" if cap is None else f" of a {cap} cap")
          + (" -- CAP REACHED" if SPENT["capped"] else ""), flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"- `{os.path.basename(sys.argv[0]) or 'python'}` bought "
                        f"**{SPENT['n']}** Bright Data credit(s)"
                        f"{' — CAP REACHED' if SPENT['capped'] else ''}\n")
        except OSError:
            pass                        # a report never costs the run it reports on
    # AND somewhere a LATER run can read it back. The log line and the step summary both die
    # with the run record -- and this repo deletes run records on purpose (CLAUDE.local.md
    # section 3), which is how the only evidence of a `pipeline: failure` was destroyed on
    # 2026-08-28. A committed line survives that. `persist_state` owns and merges this file
    # for every workflow, so no workflow has to name it in `--own`.
    try:
        import datetime as _dt
        rec = {"at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "tool": os.path.basename(sys.argv[0]) or "python", "pid": os.getpid(),
               "credits": SPENT["n"], "capped": SPENT["capped"], "cap": cap}
        d = os.path.join(ROOT, "cloud_state")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "bd_spend.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
    except OSError:
        pass


atexit.register(_report_spend)


def unlock_status(url, timeout=90):
    """(html, error). `error` is "" on success; see LAST."""
    cap = run_cap()
    if cap is not None and SPENT["n"] >= cap:
        if not SPENT["capped"]:
            SPENT["capped"] = True                  # say it once, not once per refused call
            print(f"::warning::bd_rescue: BD_RUN_CAP={cap} reached; this run buys no more "
                  f"Bright Data credits. Later rungs report `bd-capped`, not `empty`.",
                  flush=True)
        LAST.update(error="bd-capped", status=None)
        return "", "bd-capped"
    SPENT["n"] += 1
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
    from retry_unreachable import in_retry_pool          # the chain's ONE selector
    idx = {r[0].strip(): (i, r[3]) for i, r in enumerate(rows) if in_retry_pool(r)}
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
        capped = False
        for alt in alt_urls(url)[:5]:              # try up to 5 candidate URLs via the unlocker
            LAST["error"] = ""                  # `unlock` is the seam fixtures stub; read LAST after it
            html = unlock(alt)
            err = LAST["error"]
            if err.startswith("http-4"):
                # 401/402/403 from the API itself: the ACCOUNT is unusable -- stop spending
                print(f"::warning::bd_rescue: Bright Data answered {err}; stopping the pass",
                      flush=True)
                raise SystemExit(0)
            if err == "bd-capped":
                # The CAP refused this call; the page was never asked. Falling through would
                # reach the `not best_html` branch below and stamp `bd-tried <date> xN` on a
                # row nothing was fetched for -- a verdict that puts the row in a 7-day
                # cooldown and, at x3, drops it from the rescue pool for good. A budget must
                # never be able to write a fact about a company (CLAUDE.md rule 2: a
                # mass-zero result is a broken run, not a measurement). Found by an
                # adversarial pass on 2026-08-28, before the push.
                capped = True
                break
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
        if capped:
            print(f"  skip {name}: BD_RUN_CAP reached, nothing was fetched -- no verdict "
                  f"written, the row keeps its place in tomorrow's pool", flush=True)
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
