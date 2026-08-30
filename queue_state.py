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
RUNGS = ("own-site", "slug-probe", "comeet-token", "search", "resolve-llm", "hunt")
# ...and `resolve-llm` sits AFTER `search` because that is the order they ran in: the
# paid search supplies the candidate pages the LLM tier reasons from, so a name reaching
# the tier has already been searched. The first draft had them the other way round and
# `disposition()` then reported 599 names by their SEARCH verdict when 200 of them had a
# later, more informative one.

# A verdict that ENDS a name: no later rung will do better, so it stops being owed. Matched
# EXACTLY, never as a prefix -- the first draft used `startswith` and `resolved-domain` (rung 1
# finding the company's own SITE, which is evidence and not a board) counted 55 names as
# settled that still had every later rung to run.
TERMINAL = frozenset(("resolved", "already-a-row", "agency", "junk", "no-web-presence"))


class QueueStateUnreadable(SystemExit):
    """The attempt log exists and cannot be read. ABSENT is not CORRUPT."""


def load(path=PATH):
    """The log, or {} when there is none yet. A corrupt file is a HARD STOP, never {}.

    `load` used to answer {} to every exception, and `save` writes whatever it was handed:
    one truncated file and the next `--ingest` would have persisted ~120 names over a log
    of 1,037 names and 6,589 attempts, after which every name in the queue reads as never
    tried and is re-bought. `pipeline/discovery_queue.py` learned the same lesson for the
    queue file; this is that rule for the attempt log.
    """
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:                                        # noqa: BLE001
        raise QueueStateUnreadable("queue_state: %s is unreadable (%s: %s) -- refusing to "
                                   "treat a corrupt attempt log as an empty one"
                                   % (path, type(e).__name__, str(e)[:80]))
    if not isinstance(d, dict):
        raise QueueStateUnreadable("queue_state: %s holds a %s, not the name -> attempts "
                                   "map -- refusing to treat it as empty"
                                   % (path, type(d).__name__))
    return d


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
    unsettled = [n for n in names if not is_settled(state, n, have)]

    # "STILL OWED AN ANSWER" was ONE number over three different states, and every plan
    # written against this census was sized against the wrong one: on 2026-08-30 it read
    # 546 when the work actually available was 172. The other 374 were not owed anything.
    # A name is OWED only if the rung that drains the queue would select it TODAY, so the
    # count is the drain's own selector, imported rather than re-derived -- a census that
    # can disagree with the thing it measures is how 546 happened.
    owed_now, on_cadence, answered = [], [], []
    try:
        import queue_disposition as QD
        import queue_resolve_search as QRS
        disp, sel = QD.load(), set(QRS.targets())
        for n in unsettled:
            if n in sel:
                owed_now.append(n)               # actionable tonight
            elif QD.is_retired(n, disp) or n.strip().lower() in have:
                answered.append(n)               # the answer is on disk; --retire-settled folds it out
            else:
                on_cadence.append(n)             # a rung answered it inside its 14-day cadence
    except Exception as e:                                        # noqa: BLE001
        out("\n(could not split the queue by state: %s)" % str(e)[:80])
        owed_now = unsettled

    out("\nSETTLED %d - UNSETTLED %d, and they are THREE different states:"
        % (len(settled), len(unsettled)))
    out("  OWED (the drain would select it tonight)      %d" % len(owed_now))
    out("  on cadence (answered, waiting out 14 days)    %d" % len(on_cadence))
    out("  answered on disk (--retire-settled folds out) %d" % len(answered))
    out("\nOWED, by the cheapest rung that has not answered:")
    for r, c in collections.Counter(next_rung(state, n) for n in owed_now).most_common():
        out("  next rung %-28s %d" % (r or "(every rung tried)", c))
    return by_v


def queue_states(state=None, queue=None):
    """`(owed, on_cadence, answered_on_disk)` counts -- the split `census` prints, for the
    stamp that puts the OWED number in the daily mail."""
    import queue_disposition as QD
    import queue_resolve_search as QRS
    if state is None:
        state = load()
    if queue is None:
        with open(QUEUE, encoding="utf-8") as f:
            queue = json.load(f)
    have = registry_names()
    names = [(e.get("name") or "").strip() for e in queue]
    disp, sel = QD.load(), set(QRS.targets())
    owed = cadence = answered = 0
    for n in names:
        if not n or is_settled(state, n, have):
            continue
        if n in sel:
            owed += 1
        elif QD.is_retired(n, disp) or n.strip().lower() in have:
            answered += 1
        else:
            cadence += 1
    return owed, cadence, answered


def ingest(state, paths, day=None):
    """Fold a hunt arm's PROPOSAL FILES into the attempt log — the step that was missing.

    The queue arm runs as several concurrent shards, and `queue_state.json` is one JSON
    document: if each shard recorded its own attempts as it went, the last shard to save
    would silently drop every other shard's names. So the shards write only their own
    proposal file (flushed per name, so a kill costs nothing) and the attempts are folded
    in HERE, by one process, afterwards.

    Skipping this step is not cosmetic. An unrecorded attempt is an attempt that never
    happened as far as `tried_within` is concerned, so `queue_targets` hands the same names
    back the next night for ever — the exact re-walk this module exists to stop. On
    2026-08-29 the fold was an ad-hoc script, was forgotten once, and 57 names were hunted
    twice for nothing.

    Idempotent: an attempt with the same (rung, verdict, date) is not appended twice, so
    re-running over the same files is free.
    """
    import glob as _glob
    day = day or dt.date.today().isoformat()
    n_new = 0
    for pat in paths:
        for fn in sorted(_glob.glob(pat)):
            try:
                with open(fn, encoding="utf-8") as f:
                    doc = json.load(f)
            except Exception as e:                                # noqa: BLE001
                # A shard killed mid-write used to be skipped in SILENCE, and a night whose
                # attempts were never folded in reads exactly like a night nobody ran: the
                # names sort first again tomorrow and buy their searches twice. The writers
                # swap atomically now (`pipeline.atomic`), so this should be unreachable --
                # which is the reason to say it out loud rather than to drop it (`502`).
                print("::warning::ingest: %s unreadable (%s) -- that shard's attempts are "
                      "NOT recorded" % (fn, e.__class__.__name__), flush=True)
                continue
            stamp = (doc.get("generated") or day)[:10]
            for p in doc.get("proposals") or []:
                name = (p.get("name") or "").strip()
                if not name:
                    continue
                rung = p.get("rung") or "hunt"
                kind = p.get("kind")
                if kind == "scrape":
                    verdict = "found"
                elif kind == "monitor":
                    verdict = "documented"
                else:
                    verdict = p.get("why") or "no-listing"
                have = [a for a in (state.get(name) or {}).get("tried") or []
                        if a.get("rung") == rung and a.get("verdict") == verdict
                        and a.get("date") == stamp]
                if have:
                    continue
                record(state, name, rung, verdict, day=stamp,
                       url=((p.get("evidence") or {}).get("candidate_url")
                            or (p.get("evidence") or {}).get("url") or ""))
                n_new += 1
    return n_new


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--unresolved", action="store_true")
    ap.add_argument("--name", default="")
    ap.add_argument("--ingest", nargs="+", default=None,
                    metavar="GLOB", help="fold hunt proposal files into the log")
    a = ap.parse_args(argv)
    state = load()
    if a.ingest:
        n = ingest(state, a.ingest)
        save(state)
        print("ingested %d new attempts from %s" % (n, " ".join(a.ingest)))
        return 0
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
