#!/usr/bin/env python3
"""What has been TRIED for a queue name — the thing `research_companies.json` cannot say.

    python queue_state.py                 # the census: what is left, and why
    python queue_state.py --unresolved    # one line per name no rung could answer
    python queue_state.py --name "Wix"    # everything ever tried for one name

**Why this exists.** A queue entry carries four keys — `name`, `careers_url`, `ats`, `slug` —
and no attempt count, no date, no reason. State is scattered across `auto_expand_seen` (770),
`resolve_attempts` (194) and `candidate_probe` (361); on 2026-08-29, **484 of the 877 appear in
`auto_expand_seen` and 393 appear in none of them**. So a name tried twenty times is
indistinguishable from one never touched: every tool re-walks the same prefix, and nothing can
retire a name that is genuinely unfindable. "820 remain" is not an answer to "what is left".

This is `docs/BACKLOG.md` 407 one level up. A row in `companies.csv` gets a verdict, a date and
a pool; a NAME gets none of the three, so it has no owner and no cadence. This gives it all
three, and deliberately copies the model that already works rather than inventing one:

  * **An APPEND-LOG, like the notes column.** `pipeline/notes.py` exists because one tool
    overwriting another's verdict is how coverage silently vanishes. The same hazard applies
    here — `auto_expand`, `listing_hunt`'s queue arm and `drain_queue` all touch the same names
    — so an attempt is APPENDED and nothing is ever rewritten. Unlike the notes column there is
    no 220-char cap, so no eviction rule is needed and none is invented.
  * **A DATE on every attempt**, so a cadence is possible at all. `verdicts.stale` reads the
    latest stamp for a tool; `tried_within` here is the same question asked of a name.
  * **A POOL predicate** (`in_queue_pool`), so "which names does this rung still owe an answer
    to" is a function and not a guess. Every re-check pool in the registry lane exports one and
    `registry_health.pools()` imports the tool's own; this follows that rule.

**A verdict here is never a claim about the COMPANY.** It is a record of what a RUNG did:
`no-linkback`, `no-proposal`, `search-page-no-ats`. The operator's rule — nothing is recorded
as having no roles without a hunt and an LLM read — is about `companies.csv`, and this file
cannot activate or park anything. It exists so that the next session knows what NOT to re-run.

lane: `registry`.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PATH = os.path.join("cloud_state", "queue_state.json")
QUEUE = "research_companies.json"

# The rungs a name can be owed an answer by, cheapest first. The ORDER is the ladder's, and it
# is here so `next_rung` cannot drift from what the tools actually do.
RUNGS = ("own-site", "slug-probe", "comeet-token", "resolve-llm", "search", "hunt")

# A verdict that ENDS a name: no later rung will do better, so it stops being owed. Matched
# EXACTLY, never as a prefix -- the first draft used `startswith` and `resolved-domain` (rung 1
# finding the company's own SITE, which is evidence and not a board) counted 55 names as
# settled that still had every later rung to run.
TERMINAL = frozenset(("resolved", "already-a-row", "agency", "junk", "no-web-presence"))


def load(path=PATH):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:                                             # noqa: BLE001
        return {}


def save(state, path=PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    from pipeline.atomic import write_json
    write_json(path, state)


def record(state, name, rung, verdict, day=None, **evidence):
    """APPEND one attempt. Never rewrites an earlier one — that is the whole point."""
    day = day or dt.date.today().isoformat()
    e = state.setdefault(name, {"tried": []})
    e["tried"].append(dict({"rung": rung, "verdict": verdict, "date": day}, **evidence))
    e["last"] = day
    e["verdict"] = verdict
    return e


def attempts(state, name, rung=None):
    got = (state.get(name) or {}).get("tried") or []
    return [a for a in got if rung is None or a.get("rung") == rung]


def tried_within(state, name, rung, days):
    """Has `rung` answered this name inside `days`? The cadence question, per rung."""
    today = dt.date.today()
    for a in attempts(state, name, rung):
        try:
            if (today - dt.date.fromisoformat(a["date"])).days < days:
                return True
        except Exception:                                         # noqa: BLE001
            continue
    return False


def is_settled(state, name, have=None):
    """A name no rung is still owed: it resolved, or it is out of scope.

    Scans EVERY attempt, not just the newest. `verdict` is the last thing appended, and the
    log is not written in chronological order -- backfilling the drain's attempts after
    stamping `already-a-row` buried 64 of 65 settled names behind a later refusal, and the
    census then said 2 settled where 66 were. Once a name IS a row it stays one; a later rung
    failing to find its board says nothing about that.

    `have` (a set of lower-cased registry names) re-derives the commonest terminal state from
    `companies.csv` instead of trusting a stamp, which is this repo's standing rule.
    """
    if have is not None and name.strip().lower() in have:
        return True
    return any(str(a.get("verdict") or "") in TERMINAL
               for a in (state.get(name) or {}).get("tried") or [])


def registry_names():
    """Lower-cased names `companies.csv` already holds -- the authority for `already-a-row`."""
    try:
        from pipeline.companies import load_companies
        return {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    except Exception:                                             # noqa: BLE001
        return set()


def in_queue_pool(entry, state, rung, days=14, have=None):
    """THIS rung's own membership rule for a queue entry — the pool a `companies.csv` row has
    and a name did not. Composed with a cadence, exactly as the row pools are."""
    name = (entry.get("name") or "").strip()
    if not name or is_settled(state, name, have):
        return False
    return not tried_within(state, name, rung, days)


def next_rung(state, name):
    """The cheapest rung that has not answered this name, or "" when every one has."""
    for r in RUNGS:
        if not attempts(state, name, r):
            return r
    return ""


def census(state, queue=None, out=print):
    if queue is None:
        with open(QUEUE, encoding="utf-8") as f:
            queue = json.load(f)
    have = registry_names()
    names = [(e.get("name") or "").strip() for e in queue]
    known = [n for n in names if n in state]
    out("queue %d - with a recorded attempt %d - never tried %d"
        % (len(names), len(known), len(names) - len(known)))
    by_v = collections.Counter((state[n].get("verdict") or "?") for n in known)
    out("\nCURRENT VERDICT")
    for v, c in by_v.most_common():
        out("  %-34s %d" % (v[:34], c))
    by_r = collections.Counter(a["rung"] for n in known for a in attempts(state, n))
    out("\nATTEMPTS BY RUNG")
    for r, c in by_r.most_common():
        out("  %-34s %d" % (r, c))
    settled = [n for n in names if is_settled(state, n, have)]
    owed = collections.Counter(next_rung(state, n) for n in names
                               if not is_settled(state, n, have))
    out("\nSETTLED %d - STILL OWED AN ANSWER %d" % (len(settled), len(names) - len(settled)))
    for r, c in owed.most_common():
        out("  next rung %-28s %d" % (r or "(every rung tried)", c))
    return by_v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unresolved", action="store_true")
    ap.add_argument("--name", default="")
    a = ap.parse_args(argv)
    state = load()
    if a.name:
        e = state.get(a.name)
        if not e:
            print("no record for %r" % a.name)
            return 0
        print("%s  last=%s  verdict=%s" % (a.name, e.get("last"), e.get("verdict")))
        for t in e.get("tried") or []:
            print("   %-12s %-24s %s  %s" % (t.get("date"), t.get("rung"), t.get("verdict"),
                                             {k: v for k, v in t.items()
                                              if k not in ("date", "rung", "verdict")} or ""))
        return 0
    if a.unresolved:
        have = registry_names()
        for n in sorted(state):
            if not is_settled(state, n, have) and not next_rung(state, n):
                e = state[n]
                print("%-38s %s" % (n[:38], "; ".join(
                    "%s=%s" % (t["rung"], t["verdict"]) for t in e.get("tried") or [])[:110]))
        return 0
    census(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
