"""The dataset's verdict backfill — every published role carries a classifier decision.

*lane: `classifier` (`ARCHITECTURE.md` §7b). It reads the `roles` lane's ledger and writes
only the `class` field, through the map `Ledger.record_run` applies.*

**The gap this closes.** `cloud_state/roles.csv` publishes a `class_decision` column, and on
2026-08-31 **33 of its 167 rows were empty** — every one of them `closed`, 30 of them
carrying a real job description. `rec["class"]` has exactly one writer (`roles.py`, from the
jobs this run fetched and accepted), so a role that closed before that field existed
(2026-08-25) is never in `merged` again and its cell stays empty for ever. The contract
drain cannot reach them either: it re-judges RECORDED verdicts, and these have none.

"Included in the dataset" must not be allowed to mean "never judged". A closed role belongs
in the dataset — that is the operator's rule and the reason the window keeps 90 days — but a
published row with no verdict is a row nobody can check, and three of the operator's own
examples (`AppsFlyer | Senior FinOps Analyst`, `AppsFlyer | Senior Product Manager -
Analytics`, `Amazon | Sr GTM SSA Analytics`) were rows the current contract would decide
differently from whatever put them on the board.

**What it does NOT do.** It never re-judges a record that already carries a verdict — that
is the drain's job and its caps exist to bound it. It never removes a row: a record judged
`reject` keeps its line and its reason, and leaves the public file only when a human writes
a line into `cloud_state/roles_retractions.jsonl` (the `roles` lane's machinery; the seam
prints an alarm naming the count so nobody has to notice on their own).

Two entry points, deliberately the same code:

* `backfill_verdicts(ledger, clf)` — called by `pipeline/run.py` after both classify sites,
  so this runs automatically every morning and the column cannot silently refill.
* `python -m pipeline.class_backfill --db cloud_state/seen.db` — the one-shot for a backlog
  that should not wait for tomorrow's cron. Same judgements, same cache, same contract.
"""

import argparse
import datetime as dt
import os
import sys

from . import roles as _roles
from .llm import _ascii            # the one ASCII/one-line printer the seam already uses


PUBLISHED = ("open", "closed")     # the only statuses `roles.build_rows` emits a row for


def candidates(records):
    """[(role_id, record)] — every record with no classifier verdict, in a stable order.

    Only `open` and `closed` records: those are the ones `roles.build_rows` publishes, in
    `roles.csv` and in `roles_archive.csv`. `superseded` is the second copy of a posting
    kept under another company name; `purged` and `withdrawn` are rows a human or a
    predicate has already taken out of every product.

    The first draft of this function kept those three, on the reasoning that they would be
    "cheap (a keyword reject or a cache hit for most)" and that a record returning from a
    retraction should not then be the one empty cell. **Measured on the 2026-08-31 pool:
    9 of the 42 candidates were purged or withdrawn and all 9 were `strong` relevance —
    every one needed a paid call, 21 % of the pass, to fill a cell no reader can see.** Seven
    were the staffing agencies the pipeline had already purged as never ours. A rationale
    that a measurement contradicts is not a rationale; a record that a lifted retraction
    returns to `closed` is judged on the run that returns it.

    The verdict is read as `class["decision"]`, not as "is `class` truthy": a record whose
    class dict lost its decision would otherwise ship an empty `class_decision` for ever
    while looking judged to this queue."""
    return [(rid, rec) for rid, rec in sorted(records.items())
            if not (rec.get("class") or {}).get("decision") and rec.get("title")
            and (rec.get("status") or "open") in PUBLISHED]


def _job(rid, rec):
    """The record as the classifier's seam expects a posting. `description` is already on
    the record: `Ledger._open_sync` hydrates it from `roles_text.jsonl` (or sqlite) for
    every record, so a closed role that has not been fetched in a fortnight still has the
    text it was captured with."""
    return {"title": rec.get("title") or "", "company": rec.get("company") or "",
            "location": rec.get("location") or "", "url": rec.get("url") or rid,
            "description": rec.get("description") or ""}


def backfill_verdicts(ledger, clf, *, verbose=True):
    """Judge the verdict-less records. Returns ({role_id: {decision, path, reason}}, line).

    The map is applied by `Ledger.record_run(class_backfill=...)`, which fills only an EMPTY
    `class` — this run's own live verdict always wins, so a record that reopened this morning
    is never overwritten by a backlog pass.

    The line is for the step log, and it is printed rather than returned alone because the
    per-role reasons are what a human needs in order to write a retraction line for a NO.
    It is emitted even when there is NOTHING to do — at steady state that is every morning,
    and a hook that goes silent when it succeeds is a hook nobody can prove ran. `backfill:
    0 verdict-less record(s)` is the line that answers "did it run?", which is the only
    question the morning after asks.
    """
    out = {}
    rows = candidates(getattr(ledger, "records", {}) or {})
    for rid, rec in rows:
        r = clf.judge_backfill(_job(rid, rec),
                               published=(rec.get("status") or "open") in PUBLISHED)
        if not r:
            continue                       # capped, breaker open, or the call failed
        out[rid] = {k: r[k] for k in ("decision", "path", "reason") if r.get(k) is not None}
        if verbose and r["path"] != "keyword":
            # `_ascii`, like every other print in this seam: two of the 42 records measured
            # on 2026-08-31 carry U+FFFD in the title, and a bare print of one of those on a
            # cp1252 console raises AFTER the calls are paid for -- inside `run.py` the guard
            # would swallow it and discard the WHOLE map with no alarm.
            print(f"  [backfill] {_ascii(rec.get('company'), 40)} | "
                  f"{_ascii(rec.get('title'), 60)} -> "
                  f"{r['decision']}: {_ascii(r['reason'], 120)}", flush=True)
    line = (f"backfill: {len(rows)} verdict-less record(s), {clf.backfill_judged} judged "
            f"({clf.backfill_yes} yes, {clf.backfill_no} no) + {clf.backfill_cached} cached "
            f"+ {clf.backfill_keyword} keyword, {clf.backfill_held} held")
    return out, line


def apply_to(records, verdicts, run_date):
    """Fill an EMPTY `class` from the map. Returns the role_ids it changed.

    Fill-only-empty, the same rule `Ledger` applies, so running the CLI and the in-run hook
    on the same day cannot produce two different answers for one role."""
    changed = []
    for rid, cls in (verdicts or {}).items():
        rec = records.get(rid)
        if rec is None or (rec.get("class") or {}).get("decision") or not cls:
            continue
        rec["class"] = dict(cls)
        rec["updated"] = run_date
        changed.append(rid)
    return changed


def _writable(records):
    """The ledger as `Ledger.flush` would write it: no `description`, no `_`-prefixed key.

    `Ledger._absorb` puts the description on the record IN MEMORY and `flush` strips it
    again; `roles.dump` does not. Writing `ledger.records` straight to disk therefore
    duplicated the whole of `roles_text.jsonl` into the record ledger — 267 kB to 914 kB,
    193 of 193 records — and the inline copy then SHADOWS the text file at the next
    `open_sync` for any record with no sqlite row. Measured before this guard existed."""
    return {rid: {k: v for k, v in rec.items()
                  if k != "description" and not str(k).startswith("_")}
            for rid, rec in records.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=os.path.join("cloud_state", "seen.db"))
    ap.add_argument("--date", default=None,
                    help="the run date to stamp (default: today, UTC)")
    ap.add_argument("--cap", type=int, default=None, help="LLM calls this pass may buy")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what WOULD be judged; spends nothing, writes nothing")
    a = ap.parse_args(argv)

    from .store import SeenStore
    from . import seniority

    st = SeenStore(a.db)
    # UTC, like `run.py`: `dt.date.today()` is local, and `roles.load` breaks a duplicate
    # role_id line by `max(updated)`, so an evening pass in UTC+3 stamps TOMORROW and
    # outranks the cloud's next-day line (the shape of BACKLOG 269).
    ledger = _roles.Ledger(st, a.date or dt.datetime.now(dt.timezone.utc).date().isoformat())
    ledger.open_sync()
    rows = candidates(ledger.records)
    print(f"{len(rows)} verdict-less record(s) in {ledger.path}")
    if a.dry_run:
        for rid, rec in rows:
            print(f"  {rec.get('company')} | {rec.get('title')} "
                  f"| {len(rec.get('description') or '')} chars | {rec.get('status')}")
        return 0
    if a.cap is not None:
        os.environ["CLASSIFY_BACKFILL_CAP"] = str(a.cap)
    cache = st.load_llm_cache()
    clf = seniority.Classifier(llm_cache=cache)
    verdicts, line = backfill_verdicts(ledger, clf)
    changed = apply_to(ledger.records, verdicts, ledger.run_date)
    written = clf.commit()
    if written:
        st.save_llm_cache(cache, ledger.run_date)
    if changed:
        _roles.dump(ledger.path, _writable(ledger.records))
    print("  " + line)
    print(f"  contract {clf.contract}; {len(changed)} record(s) stamped, "
          f"{written} verdict(s) cached")
    if changed:
        print("  the DATASET is not regenerated here: run `python -m pipeline.roles export "
              f"--db {a.db}` to see the new class_decision column, or let the next digest do it")
    for a_ in clf.alarms():
        print("  ALARM: " + a_)
    return 0


if __name__ == "__main__":
    sys.exit(main())
