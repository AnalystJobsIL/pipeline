"""Companies the researcher found dead or absorbed, proposed for parking. READ-ONLY.

`docs/BACKLOG.md` 244, and preamble item 10: firmographics research keeps discovering that a
listed company has shut down, been liquidated, or been absorbed — Believer Meats' insolvency,
Castor's court-ordered liquidation, XACT Robotics shutting down, Aporia into Coralogix, Qwak
into JFrog, Run:ai into NVIDIA — and that knowledge dies in a `stage_note` field while the
row stays active and its board is fetched every single morning.

THIS SCRIPT NEVER WRITES ANYTHING. It has no `--apply` and it cannot park a row, because
parking one is `registry`'s write and because the obvious automation is a trap: an ACQUIRED
company usually still hires (Wiz is `acquired-by-bigtech` and hiring hard). A plausible
automatic verdict that quietly removes a live employer is `ARCHITECTURE.md` §8's first
failure class. So it emits a proposal a human pastes through `pipeline/notes.py`.

TWO SIGNALS, both required:
  1. THIS lane's evidence — the record's prose matches a shutdown/absorption phrase AND the
     company is not `public` (which alone drops Ford and Nike, whose notes mention plant
     closures and brand exits).
  2. THE REGISTRY's own evidence — the row is active AND has produced no matched role in
     >= --quiet-days, or its notes already say the board is empty.

    python firmo_death_watch.py                     # the table
    python firmo_death_watch.py --json out/x.json   # same, machine-readable
    python firmo_death_watch.py --quiet-days 45
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from pipeline.companies import CSV_PATH  # noqa: E402
from pipeline.firmographics import SHARED_EXPORT, identity_key, not_a_company  # noqa: E402

# Deliberately narrow. Every phrase here means the company STOPPED, or was absorbed into
# another company's payroll — not merely that it was bought. "acquired by" on its own is NOT
# in this list: an acquired company usually keeps hiring under its own name.
_DEAD = re.compile(
    r"(?i)\b("
    r"shut down|shutting down|shuttered|ceased operations?|ceased trading|"
    r"wound down|winding down|wind-down|"
    r"liquidat\w+|receivership|insolven\w+|bankrupt\w+|administration|creditor protection|"
    r"defunct|dissolved|closed down|out of business|"
    r"no longer operat\w+|no longer exists?|"
    r"absorbed into|folded into|merged into|rolled into|"
    r"operations? (?:were |was )?(?:integrated|absorbed|folded)|"
    r"brand (?:was )?retired|discontinued the brand"
    r")\b")

# a note that says the ROW is empty is the registry's own half of signal 2
_EMPTY_NOTE = re.compile(r"(?i)page-empty|no open israel roles|no il listing|dead host|"
                         r"url-dead|acquired\b.*\bboard (?:gone|closed)")


def _rows():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _last_role(db):
    """company -> the most recent last_seen in `matched`, or None."""
    out = {}
    if not os.path.exists(db):
        return out
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for company, last in con.execute(
                "SELECT company, MAX(COALESCE(last_seen,'')) FROM matched GROUP BY company"):
            out[company] = last
        con.close()
    except Exception as e:  # noqa: BLE001
        print(f"(matched unreadable: {e!r})")
    return out


def candidates(records, rows, last_role, quiet_days, today=None):
    """(proposals, dropped) — proposals carry BOTH signals; dropped carry only the first."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=quiet_days)).isoformat()
    by_key = {}
    for r in rows:
        by_key.setdefault(identity_key(r["company_name"]), []).append(r)

    # A KNOWN LIMIT, stated because a reviewer will meet it: `stage_note` can describe a
    # THIRD party's fate -- Primis's note says "IPG merged into Omnicom", which is its
    # parent's parent, not Primis. No regex separates the subject from the sentence; that is
    # precisely why this script proposes and a human decides.
    proposals, dropped = [], []
    for name, rec in sorted(records.items()):
        if not_a_company(name):
            continue
        # `stage_note` ONLY. It is the lifecycle field -- ticker, acquirer+year, last round.
        # The others DESCRIBE the business, and scanning them proposed FundGuard (whose
        # sub_sector is "fund accounting and administration") and Ryltech ("database
        # administration") as insolvent. A word that names a company's product is not
        # evidence about its survival.
        prose = " ".join(str(rec.get("stage_note") or "").split())
        hit = _DEAD.search(prose)
        if not hit:
            continue
        # signal 1: a PUBLIC company's note mentioning a shutdown is almost always a
        # subsidiary, a plant or a product line — not the company (Ford, Nike)
        if str(rec.get("stage") or "").strip().lower() == "public":
            dropped.append((name, "stage=public", hit.group(0)))
            continue
        rows_for = by_key.get(identity_key(name)) or []
        active = [r for r in rows_for if r["active"].strip().lower() == "true"]
        if not active:
            dropped.append((name, "no active registry row", hit.group(0)))
            continue
        # signal 2: the registry's own evidence
        seen = max((last_role.get(r["company_name"], "") for r in active), default="")
        note = " ".join(r.get("notes", "") for r in active)
        quiet = (not seen) or seen < cutoff
        empty = bool(_EMPTY_NOTE.search(note))
        if not (quiet or empty):
            dropped.append((name, f"still producing roles (last {seen})", hit.group(0)))
            continue
        why = []
        if quiet:
            why.append(f"no matched role since {seen or 'ever'}")
        if empty:
            why.append("its own notes say the board is empty")
        proposals.append({
            "company": name,
            "registry_rows": [r["company_name"] for r in active],
            "evidence": " ".join(prose.split())[:200],
            "matched": hit.group(0),
            "stage": rec.get("stage"),
            "as_of": rec.get("as_of"),
            "registry_signal": "; ".join(why),
            # the exact shape ARCHITECTURE section 6 prescribes, ready to paste through
            # pipeline/notes.py -- this script must not write it
            "proposed_note": (f"defunct {today.isoformat()}: "
                              f"{' '.join(str(rec.get('stage_note') or '').split())[:120]}"
                              f"; firmographics as_of {rec.get('as_of')}"),
        })
    return proposals, dropped


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet-days", type=int, default=30,
                    help="a row with no matched role for this long counts as quiet")
    ap.add_argument("--db", default=os.path.join(HERE, "cloud_state", "seen.db"))
    ap.add_argument("--firmo", default=SHARED_EXPORT)
    ap.add_argument("--json", default="", help="also write the proposals here")
    ap.add_argument("--summary", action="store_true",
                    help="markdown for a workflow step summary")
    a = ap.parse_args()

    with open(a.firmo, encoding="utf-8") as f:
        records = json.load(f)
    rows = _rows()
    proposals, dropped = candidates(records, rows, _last_role(a.db), a.quiet_days)

    if a.summary:
        print(f"### Company death watch — {len(proposals)} proposal(s)\n")
        if not proposals:
            print("Nothing to propose: no profiled company reads as shut down while its "
                  "registry row is still active and quiet.")
        for p in proposals:
            print(f"- **{p['company']}** ({p['stage']}, as_of {p['as_of']}) — "
                  f"matched *{p['matched']}*; {p['registry_signal']}")
            print(f"  - rows: `{', '.join(p['registry_rows'])}`")
            print(f"  - proposed note: `{p['proposed_note']}`")
        if dropped:
            print(f"\n{len(dropped)} had this lane's signal but not the registry's "
                  f"(so they are NOT proposed): "
                  + ", ".join(f"{n} ({why})" for n, why, _ in dropped[:8]))
        print("\n*Read-only. Parking a row is the `registry` lane's write "
              "(`docs/BACKLOG.md` 244); an acquired company usually still hires.*")
    else:
        print(f"{len(records)} records, {len(rows)} registry rows, "
              f"quiet-days {a.quiet_days}\n")
        print(f"{len(proposals)} PROPOSED for parking (both signals):")
        for p in proposals:
            print(f"  {p['company']:28} {str(p['stage']):18} matched {p['matched']!r}")
            print(f"      rows: {', '.join(p['registry_rows'])}")
            print(f"      registry: {p['registry_signal']}")
            print(f"      note:  {p['proposed_note']}")
        print(f"\n{len(dropped)} had the record signal only, and are NOT proposed:")
        for n, why, m in dropped:
            print(f"  {n:28} {why:34} ({m})")

    if a.json:
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"generated": dt.date.today().isoformat(),
                       "proposals": proposals,
                       "record_signal_only": [{"company": n, "why": w, "matched": m}
                                              for n, w, m in dropped]}, f,
                      ensure_ascii=False, indent=1)
        print(f"\nwrote {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
