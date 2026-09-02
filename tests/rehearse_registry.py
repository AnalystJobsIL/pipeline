#!/usr/bin/env python3
"""Rehearse N nights of the registry's scheduled tools over a COPY of the real registry, with
every network seam stubbed, and assert that no pool loses a row it should keep.

Why this exists (docs/BACKLOG.md 52, 53): the claim "no pool reaches zero over 14 nights"
was UNPROVEN -- the one attempt stalled because `listing_hunt` spawns Chromium out of
process, and the string-algebra measurement it replaced (probe 148 -> 4) stubbed the hunt
wholesale. This harness drives each tool's REAL `main()` and REAL note writers; only the
per-row verdict seam (the network) is stubbed, at the tool's own function, and any socket
use is a harness failure rather than a stub.

    python tests/rehearse_registry.py --nights 14 --policy worst
    python tests/rehearse_registry.py --nights 3 --policy mixed --rows 60

Policies: `worst` = every tool returns its most eroding verdict every night (the hunt finds
nothing, crack says `notours`, deep says unsupported, triage re-stamps, retry stays
unreachable, validate confirms empty); `mixed` = seeded pseudo-random over each tool's real
verdict shapes. Prints the night x pool table; exit 1 on the first broken invariant:
  - a pool never loses a non-terminal row it held on night 0, unless that row was
    activated, became terminal, or lost its http address (the legitimate exits);
  - `registry_health.pool_floor` against night 0's census prints nothing;
  - orphans on night n are a subset of orphans on night 0;
  - a row terminal on night 0 is terminal on night n;
  - `check_invariants` exits 0 at the end of every night.

lane: `registry`. Read-only with respect to the repo: everything happens in a temp dir.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as _dt
import io
import json
import os
import random
import shutil
import socket
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

POOL_KEYS = None   # filled from registry_health.pools()


class _NoNet(Exception):
    pass


def _forbid_sockets():
    """Every way out: connect, connect_ex, and DNS (`repair_dead_urls.resolves` decides
    "dead host" with `socket.gethostbyname`, which the first version let through)."""
    def boom(*a, **k):
        raise _NoNet("network reached from inside the rehearsal -- a seam is unstubbed")
    socket.socket.connect = boom          # type: ignore[assignment]
    socket.socket.connect_ex = boom       # type: ignore[assignment]
    socket.create_connection = boom       # type: ignore[assignment]
    socket.getaddrinfo = boom             # type: ignore[assignment]
    socket.gethostbyname = boom           # type: ignore[assignment]
    socket.gethostbyname_ex = boom        # type: ignore[assignment]


class _FakeDate(_dt.date):
    _today = _dt.date(2026, 8, 26)

    @classmethod
    def today(cls):
        return cls._today


def _set_day(d):
    _FakeDate._today = d
    _dt.date = _FakeDate               # tools call `dt.date.today()` at call time
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", "") and str(getattr(mod, "__file__", "")).startswith(ROOT) \
                and hasattr(mod, "TODAY") and isinstance(getattr(mod, "TODAY"), str):
            mod.TODAY = d.isoformat()


def _rows(path="companies.csv"):
    return [r for r in csv.reader(open(path, encoding="utf-8")) if r and len(r) >= 6][1:]


def _pools(rows):
    import registry_health as RH
    return {k: {r[0] for r in v} for k, v in RH.pools(rows).items()}


def _stub_all(policy, rng):
    """Stub each tool at its per-row verdict seam. Returns nothing; modules are patched."""
    import listing_hunt as LH
    import crack_walled as CW
    import probe_candidates as PC
    import retry_unreachable as RU
    import bd_rescue as BD
    import validate_empty as VE
    import triage_dark as TD
    import deep_validate as DV
    import audit_empty_rows as AE
    import scan_dead_domains as SD
    import repair_extract_gap as RG
    import shutil as _sh

    def pick(options):
        return options[0] if policy == "worst" else rng.choice(options)

    _sh.which = lambda x: None                                   # no claude anywhere
    import time as _time
    _time.sleep = lambda *a, **k: None                           # the tools pace real hosts; no hosts here
    LH.hunt_one = lambda name, seed, documented=False, mode="": pick([
        ("nolisting", None, 0, "no listing found"),
        ("dead", None, 0, "no pages reachable"),
        ("nolisting", "https://www.%s.example/careers" % name.lower().replace(" ", "")[:12], 0, "no IL listing"),
    ])
    CW.crack_one = lambda name, seed, platform: pick([
        ("notours", ("scrape", "https://careers-other.icims.com/jobs/search"), 3, "page belongs to another company"),
        ("nocapture", None, 0, "ATS host not seen in render"),
        ("skip", None, 0, "unsupported"),
    ])
    PC.probe = lambda url: pick([{"sig": 0, "il": 0}, {"sig": 2, "il": 1}, None])
    RU.attempt = lambda name, url: ("unreachable", None)
    BD.unlock = lambda url, timeout=90: ""
    BD._load_secrets = lambda *a, **k: None
    VE.check = lambda name, url: pick([("confirmed", None), ("suspect", "3 IL but the board is not this company's")])
    # triage's eroding verdict is "the same mode again" (a changed mode is a MOVE between
    # pools -- e.g. extract-gap -> wrong-page hands the row to the hunt); under `mixed` it
    # may flip. The current mode is read off the registry copy at stub time.
    #
    # Keyed by the row's OWN name, never by `api_url`. `worst` means "the same mode again",
    # and a url key could not deliver that for two populations at once:
    #
    #   * a row with NO api_url -- the old guard was `if m and r[3]`, so 139 parked rows
    #     were absent from the dictionary entirely and every night handed them the
    #     `wrong-page` default instead of their own recorded mode (`no-url` 92, `url-dead`
    #     24, `js-shell` 9, `page-empty` 6, `extract-gap` 5, `blocked` 3);
    #   * a row that SHARES an address with another -- 5 more, of which `Linnovate
    #     Technologies`/`Linnovate` and `GenCell Energy`/`GenCell` carry DIFFERENT modes
    #     over one url, and `Synopsys Israel` carries none while its twin carries
    #     `page-empty`. Those get their twin's verdict.
    #
    # Either way `worst` manufactured a mode CHANGE, which is a move between pools, and the
    # per-pool retention invariant then reported a row the harness had itself moved: seed 1
    # failed on `listing_hunt` losing `Synopsys Israel` (docs/BACKLOG.md 558) and, once the
    # data moved, on `repair_extract_gap` losing `Linnovate Technologies` at night 12. 144
    # rows change verdict under the new key and NONE changes pool: three nights of `worst`
    # seed 1 give byte-identical per-pool censuses either way. Company names are unique
    # across all 2,141 rows, so the new key cannot collide the way the old one did, and
    # `triage_dark.main()` is the only caller of `classify` and always passes `company=r[0]`.
    import re as _re
    _modes = {}
    for r in _rows():
        m = _re.search(r"dark-triage \d{4}-\d{2}-\d{2}: ([a-z-]+)", r[5] or "")
        if m:
            _modes[r[0]] = m.group(1)

    def _classify(url, render=False, company=""):
        same = (_modes.get(company) or "wrong-page", "re-classified the same")
        return same if policy == "worst" else pick([
            same, ("wrong-page", "no listing on the page"), ("js-shell", "shell"),
            ("url-dead", "404"), ("page-empty", "live, no openings"), ("extract-gap", "3 role phrases")])
    TD.classify = _classify
    DV.Renderer = _NoRenderer
    # `dark` is deep's eroding verdict; `unsupported` is a MOVE (the row joins the crack
    # pool by its protected token) and would make every dark row walled under `worst`
    DV.validate_one = lambda rend, name, seed: pick([
        ("dark", None, None, None, 0, 0, "no ATS detected (rendered)"),
        ("unreachable", None, None, None, 0, 0, "error"),
        ("unsupported", None, None, None, 0, 0, "icims.com"),
    ])
    AE.fetch = lambda u, timeout=20: ""
    AE.serp = lambda name, limit=5: []
    AE._playwright_available = lambda: True
    AE._load_secrets = lambda *a, **k: None
    SD.alive = lambda url: pick([(True, ""), (False, "dns")])
    RG.scrape = None
    import scrape_universal as SU
    SU.scrape = lambda name, url, **k: []

    import repair_dead_urls as RD
    import wayback_rescue as WB
    # repair_dead_urls: `resolves` decides membership (worst: every host is dead), the
    # candidates are fetched (worst: unreadable) -- nothing may be written from no page
    RD.resolves = lambda host, tries=3: False if policy == "worst" else rng.random() < 0.7
    RD.candidates = lambda name, dead_url: []      # the search ladder (ddg/unlocker) is a seam, not a fixture
    RD.fetch = lambda url: (None, "")
    RD._unlock = lambda url: ""
    RD.time.sleep = lambda s: None
    # wayback_rescue: the archive read (worst: nothing archived)
    WB.rescue = lambda name, url: None
    if os.environ.get("REHEARSE_SELF_TEST") == "overwrite":
        # the harness's own control: the classic cell overwrite must be CAUGHT (a
        # mutation that turns the retention check off would let this pass)
        LH._note_replace = lambda base, marker, seg, cap=220: seg

class _NoRenderer:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False



def _run(mod, argv):
    """Call `mod.main()` with `sys.argv` set; swallow SystemExit(0); capture stdout."""
    old = sys.argv
    sys.argv = argv
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            try:
                mod.main()
            except SystemExit as e:
                if e.code not in (0, None):
                    raise
    finally:
        sys.argv = old
    return buf.getvalue()


def _invariants_ok():
    """Run the real `check_invariants.py` and return (ok, its last 400 chars).

    `encoding=`/`errors=` are load-bearing, not tidiness. `check_invariants.py` reconfigures
    its own streams to utf-8 on purpose -- a Hebrew name in a violation message used to kill
    the run -- so the WRITER is utf-8 while `text=True` alone decodes with the platform
    default, which is cp1252 on Windows. The night a violation named a Hebrew company,
    `subprocess` raised UnicodeDecodeError internally, left `r.stdout` as None, and this
    function died on `None[-400:]` -- reported as `exit 1`, i.e. indistinguishable from the
    pool collapse this harness exists to catch. `--policy mixed --seed 4` did exactly that at
    night 12 on clean origin/master (2026-08-28), while the same commit was green in CI,
    because the runners are Linux/utf-8. A gate that only fails on one operating system is
    not a gate."""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(ROOT, "check_invariants.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0, (r.stdout or "")[-400:]


SCHEDULE = [   # (label, module name, argv, weekday filter: None = daily, 5 = Sat, 6 = Sun)
    ("02:30 bd_rescue", "bd_rescue", ["bd_rescue.py"], None),
    ("02:30 retry_unreachable", "retry_unreachable", ["retry_unreachable.py"], None),
    ("19:00 repair_dead_urls", "repair_dead_urls", ["repair_dead_urls.py", "--apply"], None),
    ("05:00 scan_dead_domains", "scan_dead_domains", ["scan_dead_domains.py", "--apply"], None),
    ("05:00 probe_candidates", "probe_candidates", ["probe_candidates.py", "--apply"], None),
    ("18:00 triage_dark", "triage_dark", ["triage_dark.py", "--apply"], None),
    ("19:00 repair_extract_gap", "repair_extract_gap", ["repair_extract_gap.py", "--apply"], None),
    ("19:00 listing_hunt", "listing_hunt", ["listing_hunt.py", "--apply"], None),
    ("19:00 crack_walled", "crack_walled", ["crack_walled.py", "--apply"], None),
    ("Sun 04:00 validate_empty", "validate_empty", ["validate_empty.py"], 6),
    ("Sun 04:00 audit_empty_rows", "audit_empty_rows", ["audit_empty_rows.py", "--apply"], 6),
    ("Sun 04:00 wayback_rescue", "wayback_rescue", ["wayback_rescue.py"], 6),
]
# Scheduled companies.csv writers deliberately NOT here: auto_expand (appends NEW rows from a
# discovery queue; it never rewrites a parked row) -- listed so the omission is a decision.


def rehearse(nights=14, policy="worst", rows_cap=0, seed=1, verbose=True, trace=(), signals=False):
    work = tempfile.mkdtemp(prefix="rehearse_registry_")
    src = _rows(os.path.join(ROOT, "companies.csv"))
    if rows_cap:
        parked = [r for r in src if r[4] == "false"][:rows_cap]
        src = parked + [r for r in src if r[4] == "true"][:10]
    with open(os.path.join(work, "companies.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["company_name", "ats_platform", "token", "api_url", "active", "notes"])
        w.writerows(src)
    os.makedirs(os.path.join(work, "cloud_state"))
    for f in ("candidate_probe.json", "scan_seen.json"):
        p = os.path.join(ROOT, "cloud_state", f)
        if os.path.exists(p):
            shutil.copy(p, os.path.join(work, "cloud_state", f))
    with open(os.path.join(work, "scraped_cache.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    os.chdir(work)
    os.environ.update({"BRIGHTDATA_API_KEY": "", "BRIGHTDATA_ZONE": "", "SERPAPI_KEY": "",
                       "HUNT_TIME_BUDGET_MIN": "0", "CRACK_TIME_BUDGET_MIN": "0",
                       "TRIAGE_LLM_CAP": "0", "AUDIT_TIME_BUDGET_MIN": "0",
                       "AUDIT_DEEP_BUDGET_MIN": "0", "PROBE_TIME_BUDGET_MIN": "0",
                       "SCAN_TIME_BUDGET_MIN": "0", "PAGE_UNLOCK_BUDGET": "0",
                       "REPAIR_URL_TIME_BUDGET_MIN": "0",
                       # PRODUCTION's configuration: no workflow sets VALIDATE_EMPTY_SIGNALS,
                       # so the rehearsal must not either (attacker 2: with the pin, the
                       # token arm's erosion was invisible). `--signals` opts in.
                       "VALIDATE_EMPTY_SIGNALS": "1" if signals else "0"})
    _forbid_sockets()
    rng = random.Random(seed)
    import registry_health as RH
    import importlib
    mods = {name: importlib.import_module(name) for _, name, _, _ in SCHEDULE}
    _stub_all(policy, rng)
    day0 = _dt.date(2026, 8, 26)
    _set_day(day0)
    rows0 = _rows()
    pools0 = _pools(rows0)
    census0 = {"//pools//": {k.split(" (")[0]: len(v) for k, v in pools0.items()}}
    # `domain-dead` is the one terminal token a tool legitimately CLEARS (scan_dead_domains,
    # when the domain answers again), so the "terminal stays terminal" invariant excludes
    # rows whose only terminal token was that one
    from pipeline.verdicts import TERM_RX as _T
    term0 = {r[0] for r in rows0 if RH.is_terminal_note(r[5] or "")
             and any(t.lower() != "domain-dead" for t in _T.findall(r[5] or ""))}
    orph0 = set(RH.orphans(rows0))
    keys = list(pools0)
    if verbose:
        print("night  " + "  ".join(k.split(" (")[0][:12].rjust(12) for k in keys) + "  orphans")
        print("    0  " + "  ".join(str(len(pools0[k])).rjust(12) for k in keys) + f"  {len(orph0)}")
    failures = []
    # The pool's own tool acting on a row is a legitimate exit -- see the note below.
    _OWN_STAMP = {"listing_hunt": "listing-hunt", "crack_walled": "crack-walled",
                  "triage_dark": "dark-triage", "deep_validate": "deep-validated",
                  "probe_candidates": "probe-woken"}
    acted_ever = {k: set() for k in keys}
    for n in range(1, nights + 1):
        day = day0 + _dt.timedelta(days=n)
        _set_day(day)
        for label, name, argv, wd in SCHEDULE:
            if wd is not None and day.weekday() != wd:
                continue
            try:
                _run(mods[name], argv)
            except _NoNet as e:
                failures.append(f"night {n} {label}: {e}")
                break
            except Exception as e:  # noqa: BLE001
                failures.append(f"night {n} {label}: crashed {type(e).__name__}: {str(e)[:80]}")
                break
        # the blocking gate once per night (it is ~70 % of a per-writer run's wall time; a
        # broken registry is still caught the same night, and named by the night)
        ok, tail = _invariants_ok()
        if ok is False:
            failures.append(f"night {n}: check_invariants red after the day's writers: {tail[-160:]}")
        rows = _rows()
        pools = _pools(rows)
        for t in trace:
            r = next((x for x in rows if x[0] == t), None)
            print(f"      trace {t}: {r[1] if r else '?'} | {(r[3] if r else '')[:50]} | {r[4] if r else '?'} | "
                  f"{(r[5] if r else '')[-150:]}")
            print(f"      in: {[k.split(' (')[0] for k, v in pools.items() if t in v]}")
        active = {r[0] for r in rows if r[4] == "true"}
        term = {r[0] for r in rows if RH.is_terminal_note(r[5] or "")}
        no_http = {r[0] for r in rows if not (r[3] or "").startswith("http")}
        orph = set(RH.orphans(rows))
        if verbose:
            print(f"{n:5}  " + "  ".join(str(len(pools[k])).rjust(12) for k in keys) + f"  {len(orph)}")
        # Per-pool retention is a `worst`-policy invariant: with every verdict at its most
        # eroding, nothing legitimately MOVES between pools. Under `mixed`, rows do move
        # (a re-triaged mode leaves extract-gap for the hunt; a woken row leaves triage
        # for the fast path), so there only the union invariants below apply.
        if policy == "worst":
            # A FIFTH legitimate exit, alongside active / terminal / no-http: the pool's own
            # tool ran on the row tonight and its verdict moved the row on. The worked case
            # is the documented probe -> hunt handoff (ARCHITECTURE.md section 2): the probe
            # wakes a `page-empty` row, the hunt fast-paths it, and `_consume_wake` strips the
            # wake as it writes its verdict -- after which `_triaged_page_empty` excludes the
            # row again and the probe owns it once more. That is the cycle working, not
            # erosion, and `orphans` stays 0 throughout because triage / probe / audit / deep
            # still claim the row.
            #
            # Keying on the tool's OWN stamp dated TONIGHT is what keeps this narrow: a row
            # that silently falls out of a pool nothing touched is still a failure, which is
            # the whole point of the invariant. Before 2026-08-27 this fired on night 4 for a
            # row whose wake had been EVICTED by an unrelated tool's stamp before any hunt
            # saw it -- a real defect, fixed in `pipeline/notes.py` by protecting the wake.
            # CUMULATIVE, because `lost` is measured against night 0 every night: a row that
            # legitimately left on night 5 must not be re-reported on night 6.
            for k in keys:
                marker = _OWN_STAMP.get(k.split(" (")[0], "")
                if marker:
                    acted_ever[k] |= {r[0] for r in rows if len(r) > 5
                                      and f"{marker} {day.isoformat()}" in (r[5] or "").lower()}
                lost = pools0[k] - pools[k] - active - term - no_http - acted_ever[k]
                if lost:
                    failures.append(f"night {n}: pool {k} lost {len(lost)} rows it should keep: {sorted(lost)[:6]}")
        floor = [x for x in RH.pool_floor(rows, census0)
                 if policy == "worst" or "COLLAPSED" in x]
        if floor:
            failures.append(f"night {n}: pool_floor alarmed: {floor}")
        owned_now = set().union(*pools.values()) if pools else set()
        owned0 = set().union(*pools0.values()) if pools0 else set()
        left_all = owned0 - owned_now - active - term - no_http
        if left_all:
            failures.append(f"night {n}: {len(left_all)} rows left EVERY pool: {sorted(left_all)[:6]}")
        if not orph <= orph0:
            failures.append(f"night {n}: new orphans {sorted(orph - orph0)[:6]}")
        if not term0 <= term:
            failures.append(f"night {n}: terminal rows lost their token: {sorted(term0 - term)[:6]}")
        if failures:
            break
    shutil.rmtree(work, ignore_errors=True)
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nights", type=int, default=14)
    ap.add_argument("--policy", choices=("worst", "mixed"), default="worst")
    ap.add_argument("--rows", type=int, default=0, help="parked-row cap (0 = all)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--trace", default="", help="comma-separated company names to print each night")
    ap.add_argument("--signals", action="store_true", help="VALIDATE_EMPTY_SIGNALS=1 (staged; not production)")
    a = ap.parse_args()
    failures = rehearse(a.nights, a.policy, a.rows, a.seed, signals=a.signals,
                        trace=[t.strip() for t in a.trace.split(",") if t.strip()])
    for f in failures:
        print("FAIL " + f)
    print("rehearsal %s: %d night(s), policy %s" % ("FAILED" if failures else "OK", a.nights, a.policy))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
