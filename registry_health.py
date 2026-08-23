#!/usr/bin/env python3
"""One command that answers "is the registry still whole, and can it still crack anything?"

Read-only. It never writes `companies.csv`; the only file it may write is its own census.
It exists because three questions had no answer anywhere in this repo:

1. **Did a company DISAPPEAR from `companies.csv`, and why?**
   No tool deletes rows — every writer is re-read-modify-write or append-only. But a HUMAN
   commit does, and the git layer makes that non-durable: `Time To Know` was deleted on
   purpose (`9c4372ef`, "time.com is Time To Know"), **resurrected** by a concurrent cloud
   run's conflict merge (`8644d8fd`, `row-merged state`, 1190 -> 1191 rows), and then
   re-deleted as a silent side effect of a commit about Oracle HCM (`0180e755`). Fifteen
   name-deletions exist in the whole history of the file and nothing anywhere reports one.
   `check_invariants.py` checks the SHAPE of the registry, never its SIZE.

2. **Is every parked row still owned by a recurring job?** ARCHITECTURE.md section 2 has an
   ownership matrix that was typed by hand. `pools()` below computes it from the same
   predicates the tools use, so the doc can be re-derived instead of trusted.

3. **Can the resolution ladder still do anything?** Every rung fails by returning an empty
   list: no SerpApi quota, no Bright Data key, no `claude` binary, no Playwright. That is
   the documented #1 bug class (silent exclusion) sitting under the most expensive job in
   the system - the 200-minute nightly hunt.

`alarms()` turns all three into short lines meant for the digest's run-audit block, and
`--census` persists them to `cloud_state/registry_alarms.json` for the digest to pick up.
See docs/BACKLOG.md ("Registry alarms in the daily mail") for the four-line hook that is
NOT in this lane to make.

Usage:
  python registry_health.py               # full report, no writes, no network
  python registry_health.py --resources   # also probe every rung live (spends <=1 BD credit)
  python registry_health.py --ats         # the unsupported-ATS inventory (what to build next)
  python registry_health.py --census      # update cloud_state/registry_census.json + alarms
  python registry_health.py --json        # machine-readable everything
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys

from pipeline.aggregators import is_aggregator
from pipeline.atomic import write_json
from pipeline.recruiters import is_recruiter
from pipeline.verdicts import in_pool

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). Company names here
# are Hebrew as often as not, and an UnicodeEncodeError in the REPORT would kill the process
# that is reporting. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CSV_PATH = "companies.csv"
CENSUS = os.path.join("cloud_state", "registry_census.json")
ALARMS = os.path.join("cloud_state", "registry_alarms.json")
TODAY = dt.date.today().isoformat()

# A row may leave the registry only for one of these reasons, and the reason must be IN the
# row's own note at the moment it goes. Anything else is an accident until proven otherwise.
GOOD_REMOVAL = re.compile(r"defunct|domain-dead|alias-of|duplicate of|redundant|recruiter|"
                          r"aggregator|sidebar-poisoned|removed \d{4}-\d{2}-\d{2}", re.I)
# States no re-check pool may ever re-open. `alias-of` belongs here and is missing from
# pipeline/verdicts.TERMINAL - see docs/BACKLOG.md; until that lands, every registry tool
# spells it out itself.
TERMINAL = re.compile(r"defunct|domain-dead|alias-of", re.I)


def read_rows(path=CSV_PATH):
    """Body rows only (header dropped), each a 6-field list."""
    rows = [r for r in csv.reader(open(path, encoding="utf-8")) if r and len(r) >= 6]
    return rows[1:] if rows and rows[0][0] == "company_name" else rows


# ---------------------------------------------------------------- census / deletion guard

def census(rows):
    """{company_name: "true"/"false"} — the smallest thing that detects a vanished row."""
    return {r[0]: r[4] for r in rows}


def load_census(path=CENSUS):
    try:
        d = json.load(open(path, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def census_diff(rows, prev=None):
    """What changed since the last census: gone / added / deactivated / reactivated.

    `gone` carries the LAST KNOWN NOTE for each vanished row, because "why was this deleted"
    is otherwise only answerable by `git log -S`. A vanished row whose last note gives no
    GOOD_REMOVAL reason is the thing this whole module exists to shout about.
    """
    prev = load_census() if prev is None else prev
    now = census(rows)
    notes = {r[0]: (r[5] or "") for r in rows}
    prev_notes = (prev.get("__notes__") or {}) if isinstance(prev.get("__notes__"), dict) else {}
    prev_active = {k: v for k, v in prev.items() if k != "__notes__"}
    gone, unexplained = [], []
    for name in prev_active:
        if name in now:
            continue
        why = prev_notes.get(name, "")
        gone.append({"company": name, "last_note": why[:160],
                     "explained": bool(GOOD_REMOVAL.search(why))})
        if not GOOD_REMOVAL.search(why):
            unexplained.append(name)
    added = [n for n in now if n not in prev_active]
    flipped_off = [n for n in now if prev_active.get(n) == "true" and now[n] == "false"]
    flipped_on = [n for n in now if prev_active.get(n) == "false" and now[n] == "true"]
    return {"rows": len(now), "active": sum(1 for v in now.values() if v == "true"),
            "prev_rows": len(prev_active), "gone": gone, "unexplained": unexplained,
            "added": added, "deactivated": flipped_off, "reactivated": flipped_on,
            "first_census": not prev_active, "_now": now, "_notes": notes}


def save_census(rows, path=CENSUS):
    d = census(rows)
    d["__notes__"] = {r[0]: (r[5] or "")[:200] for r in rows}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    write_json(path, d, indent=0, sort_keys=True)
    return len(d) - 1


# ---------------------------------------------------------------- the ownership matrix

def pools(rows):
    """Recompute ARCHITECTURE.md section 2's ownership matrix from the tools' own predicates.

    Each entry mirrors ONE scheduled tool's row filter. When a filter changes, change it
    here in the same commit — this is the only place the matrix is checkable, and a matrix
    that drifts is how 17 rows came to be owned by nothing.
    """
    parked = [r for r in rows if r[4] == "false"]

    def sel(pred):
        return [r for r in parked if pred(r[5] or "", r)]

    def _hunt(note, r):
        # listing_hunt.py main(): the wide parked-shape regex, minus page-empty/terminal
        return (bool(re.search(
            r"no ATS detected|unsupported ATS|scrape rotted|monitored candidate|"
            r"host documented|probe-woken|scanned; no open|unreachable|aggregator URL|"
            r"no listing found|redirects to|scanned via brightdata|empty-but-suspect|"
            r"needs re-resolution|needs manual resolution|url-cleared|url-flagged", note))
            and not TERMINAL.search(note) and not is_recruiter(r[0])
            and not re.search(r"dark-triage [^|]*:\s*page-empty", note))

    return {
        "triage_dark (18:00 daily)":
            sel(lambda n, r: bool(re.search(
                r"no listing found|no IL listing|no ATS detected|dark-triage", n))),
        "listing_hunt (19:00 daily)": sel(_hunt),
        "repair_extract_gap (19:00 daily)":
            sel(lambda n, r: bool(re.search(r"dark-triage[^|]*extract-gap", n))
                and (r[3] or "").startswith("http")),
        "crack_walled (19:00 daily + Sun)":
            sel(lambda n, r: "unsupported ATS" in n and not TERMINAL.search(n)
                and not is_recruiter(r[0])),
        "probe_candidates (05:00 daily)":
            sel(lambda n, r: bool(re.search(r"monitored candidate|host documented|no IL listing", n))
                and not TERMINAL.search(n) and (r[3] or "").startswith("http")),
        "audit_empty_rows (Sun 04:00)":
            sel(lambda n, r: in_pool(n) and not TERMINAL.search(n) and not is_recruiter(r[0])),
        "deep_validate (Sat 04:00)":
            sel(lambda n, r: in_pool(n) and not TERMINAL.search(n) and not is_recruiter(r[0])),
    }


def orphans(rows):
    """Parked rows owned by NO recurring job — permanently dark coverage."""
    owned = set()
    for members in pools(rows).values():
        owned.update(r[0] for r in members)
    return [r[0] for r in rows
            if r[4] == "false" and not TERMINAL.search(r[5] or "")
            and not is_recruiter(r[0]) and r[0] not in owned]


# ---------------------------------------------------------------- what can still crack

def unsupported_ats(rows):
    """Every ATS the resolvers recognised but cannot READ, with the rows waiting on it.

    This is the hand-off to the `ats-fetch` lane: ARCHITECTURE.md section 1's support policy
    is "a platform seen 3+ times gets a native fetcher", and until now nothing counted.
    """
    rx = re.compile(r"unsupported ATS ([A-Za-z0-9_.\- ]+)")
    out = {}
    for r in rows:
        m = rx.search(r[5] or "")
        if not m:
            continue
        plat = m.group(1).strip().lower().split(";")[0].strip()
        if not plat:
            continue
        e = out.setdefault(plat, {"rows": 0, "active": 0, "companies": []})
        e["rows"] += 1
        e["active"] += (r[4] == "true")
        if len(e["companies"]) < 12:
            e["companies"].append(r[0])
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["rows"]))


def resources(live=False):
    """Every rung of the resolution ladder, and whether it can do anything right now.

    Each of these fails by returning an empty list, never by raising, so an expired token
    looks exactly like "no company matched today". `live=True` costs at most one Bright Data
    credit and one SerpApi *account* call (which does not consume a search).
    """
    import shutil
    # Local runs keep their keys in the gitignored secrets.env; in Actions the same names
    # arrive as repo secrets. Without this the probe reports every paid rung DOWN on the dev
    # machine — a health check that cries wolf is a health check nobody reads.
    try:
        from bd_rescue import _load_secrets
        _load_secrets()
    except Exception:  # noqa: BLE001
        pass
    out = {}

    def add(key, ok, detail):
        out[key] = {"ok": bool(ok), "detail": detail}

    add("claude CLI (role judgments, listing pick, LLM resolve)",
        shutil.which("claude"), shutil.which("claude") or "not on PATH")
    add("CLAUDE_CODE_OAUTH_TOKEN",
        os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
        "set" if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") else
        "unset (fine locally: the CLI has its own login; REQUIRED in Actions)")
    bd = bool(os.environ.get("BRIGHTDATA_API_KEY") and os.environ.get("BRIGHTDATA_ZONE"))
    add("Bright Data unlocker (google_via_unlocker, blocked-page fetch)", bd,
        "key+zone set" if bd else "missing key or zone — the ONLY working search rung is off")
    try:
        import playwright  # noqa: F401
        add("Playwright/Chromium (render, XHR sniff, crack_walled)", True, "importable")
    except Exception as e:  # noqa: BLE001
        add("Playwright/Chromium (render, XHR sniff, crack_walled)", False, str(e)[:60])

    if not live:
        add("SerpApi", bool(os.environ.get("SERPAPI_KEY")),
            "key present; quota NOT checked (use --resources)")
        return out

    key = os.environ.get("SERPAPI_KEY", "")
    left = None
    if key:
        try:
            import urllib.request
            with urllib.request.urlopen(
                    f"https://serpapi.com/account?api_key={key}", timeout=20) as r:
                left = int(json.load(r).get("total_searches_left") or 0)
        except Exception as e:  # noqa: BLE001
            left = None
            add("SerpApi", False, f"account check failed: {str(e)[:50]}")
    if left is not None:
        add("SerpApi", left > 0, f"{left} searches left this month")
    elif not key:
        add("SerpApi", False, "no SERPAPI_KEY")
    try:
        from deep_validate import ddg
        n = len(ddg("Wix") or [])
        add("DuckDuckGo HTML (free search rung)", n > 0,
            f"{n} results" if n else "0 results — blocked from this machine (works on runners)")
    except Exception as e:  # noqa: BLE001
        add("DuckDuckGo HTML (free search rung)", False, str(e)[:60])
    if bd:
        try:
            from deep_validate import google_via_unlocker
            n = len(google_via_unlocker("Wix") or [])
            add("Bright Data Google (paid search rung)", n > 0, f"{n} results (1 credit spent)")
        except Exception as e:  # noqa: BLE001
            add("Bright Data Google (paid search rung)", False, str(e)[:60])
    return out


# ---------------------------------------------------------------- the mail lines

def alarms(rows=None, live=False, res=None, prev=None):
    """Short lines for the digest run-audit. Empty list = the registry is healthy.

    Deliberately terse and deliberately few: a daily audit block nobody reads is a daily
    audit block nobody reads. Only conditions that mean COVERAGE IS BEING LOST appear here.

    `res` takes an already-probed `resources()` result. Pass it: a live probe spends a Bright
    Data credit and a second DuckDuckGo request, and calling this after `_report` used to
    run the whole ladder twice — the second unlocker call came back empty and the report
    contradicted itself in adjacent lines. `prev` overrides the on-disk census, for tests
    and for asking "what would this say against last week's baseline".
    """
    rows = read_rows() if rows is None else rows
    out = []
    d = census_diff(rows, prev=prev)
    if not d["first_census"]:
        if d["unexplained"]:
            out.append(f"{len(d['unexplained'])} companies REMOVED from the registry with no "
                       f"reason in their note: {', '.join(d['unexplained'][:5])}")
        explained = [g["company"] for g in d["gone"] if g["explained"]]
        if explained:
            out.append(f"{len(explained)} companies removed (explained): "
                       f"{', '.join(explained[:5])}")
        # A registry that shrinks by more than a rounding error was not edited, it was lost.
        if d["prev_rows"] and d["rows"] < d["prev_rows"] * 0.98:
            out.append(f"registry shrank {d['prev_rows']} -> {d['rows']} rows "
                       f"(>2%) — suspect a truncated write or a bad merge")
    orph = orphans(rows)
    if len(orph) > 10:
        out.append(f"{len(orph)} parked rows are owned by NO recurring job "
                   f"(retired coverage): {', '.join(orph[:5])}")
    for label, members in pools(rows).items():
        if not members and label.startswith(("triage_dark", "listing_hunt", "probe_candidates")):
            out.append(f"re-check pool EMPTY: {label} — a predicate inverted, or the notes "
                       f"column was clobbered")
    for key, st in (res if res is not None else resources(live=live)).items():
        if not st["ok"] and not key.startswith(("SerpApi", "CLAUDE_CODE_OAUTH_TOKEN",
                                                "DuckDuckGo")):
            out.append(f"resolution rung DOWN: {key} — {st['detail']}")
    return out


# ---------------------------------------------------------------- report

def _report(rows, live=False, want_ats=False):
    from collections import Counter
    act = [r for r in rows if r[4] == "true"]
    print(f"registry: {len(rows)} rows · {len(act)} active · {len(rows) - len(act)} parked")
    plat = Counter(r[1] for r in act)
    print("  active by platform: " + ", ".join(f"{k}={v}" for k, v in plat.most_common()))
    api = sum(v for k, v in plat.items() if k not in ("scrape", "discovery"))
    print(f"  native-ATS rows {api} · scrape rows {plat.get('scrape', 0)} · "
          f"discovery rows {plat.get('discovery', 0)}")

    d = census_diff(rows)
    print(f"\ncensus (vs {CENSUS}):")
    if d["first_census"]:
        print("  no previous census — run --census to establish the baseline")
    else:
        print(f"  {d['prev_rows']} -> {d['rows']} rows · +{len(d['added'])} added · "
              f"-{len(d['gone'])} gone · {len(d['deactivated'])} parked · "
              f"{len(d['reactivated'])} re-activated")
        for g in d["gone"]:
            print(f"  {'[ok]' if g['explained'] else '[??]'} GONE {g['company']}: "
                  f"{g['last_note'][:90] or '(no note)'}")

    print("\nre-check ownership (recomputed from each tool's own filter):")
    for label, members in pools(rows).items():
        print(f"  {len(members):4}  {label}")
    orph = orphans(rows)
    print(f"  {len(orph):4}  OWNED BY NOTHING" + (f": {orph[:6]}" if orph else ""))

    print("\nresolution ladder:")
    for key, st in resources(live=live).items():
        print(f"  [{'OK' if st['ok'] else '--'}] {key}: {st['detail']}")

    if want_ats:
        print("\nunsupported ATS platforms — rows waiting on a native fetcher")
        print("  (ARCHITECTURE.md section 1: 3+ rows earns one; recipe in section 6)")
        for plat_name, e in unsupported_ats(rows).items():
            flag = "BUILD" if e["rows"] >= 3 else "     "
            print(f"  {flag} {plat_name:18} {e['rows']:3} rows ({e['active']} active): "
                  f"{', '.join(e['companies'][:6])}")

    a = alarms(rows, live=live)
    print(f"\nalarms for the daily mail: {len(a)}")
    for line in a:
        print(f"  ! {line}")
    return a


def main():
    argv = sys.argv[1:]
    live = "--resources" in argv
    rows = read_rows()
    if "--json" in argv:
        _res = resources(live=live)
        print(json.dumps({"census": {k: v for k, v in census_diff(rows).items()
                                     if not k.startswith("_")},
                          "pools": {k: len(v) for k, v in pools(rows).items()},
                          "orphans": orphans(rows),
                          "unsupported_ats": unsupported_ats(rows),
                          "resources": _res,
                          "alarms": alarms(rows, live=live, res=_res)}, indent=1,
                         ensure_ascii=False))
        return 0
    if "--ats" in argv and len(argv) == 1:
        for plat_name, e in unsupported_ats(rows).items():
            print(f"{plat_name:18} {e['rows']:3} rows ({e['active']} active): "
                  f"{', '.join(e['companies'])}")
        return 0
    a = _report(rows, live=live, want_ats=("--ats" in argv or "--census" in argv))
    if "--census" in argv:
        n = save_census(rows)
        os.makedirs(os.path.dirname(ALARMS) or ".", exist_ok=True)
        write_json(ALARMS, {"date": TODAY, "alarms": a})
        print(f"\ncensus written: {n} companies -> {CENSUS}; {len(a)} alarms -> {ALARMS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
