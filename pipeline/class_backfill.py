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

**What it does NOT do.** It never re-judges a record carrying a live-contract `accept` —
that is the drain's job and its caps exist to bound it — and it never turns an accept into a
reject, in any pool, by any arm.

**The one verdict it does re-judge** (2026-09-18, `621`): a published `reject` cell that is
not current. Since that morning a `reject` cell REMOVES the row (`roles.Ledger.
_withdraw_rejected`), so it is no longer a label a reader can weigh — it is a deletion, and
a deletion made under retired rules, or contradicted by the live contract's own cached
verdict for the same job, has to be re-decided. `reject_owed` is the predicate and it is
one-way and self-draining. The channel for taking a row out on purpose is unchanged: a
human writes a line into `cloud_state/roles_retractions.jsonl` (the `roles` lane's
machinery; the seam prints an alarm naming the count so nobody has to notice on their own).

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


def reject_owed(rid, rec, cache=None, contract=None):
    """Is this published record's `reject` cell owed a verdict under the rules live today?

    A `reject` cell is the one verdict with a consequence a reader can see: since
    2026-09-18 `roles.Ledger._withdraw_rejected` takes the row out of the dataset on it. So
    it must be CURRENT, and until this predicate existed nothing could make it current —
    `class_unjudged` reads "has a decision naming some contract" as judged, `reject_map`
    only stamps a role the run fetched, and the contract drain only re-judges what the run
    fetched too. Measured on 2026-09-18: **11 published rows carried a `reject` cell**, all
    closed, and no writer in the system could put one back.

    Three arms, all of them reject-to-accept only (`roles.class_refillable` states the
    one-way rule) and all of them self-draining — a row leaves this pool the moment it
    carries a live-contract verdict, so at steady state it is empty:

    1. a **written adjudication** — `seniority.ADJUDICATED`, the role_ids a decision record
       settled on a tell the seam cannot read. Costs no call.
    2. the cell names a **retired contract**. A published row judged out of scope under
       rules that are no longer the rules is the operator's bar failing in the direction
       that removes data, and it is the only arm that survives a contract bump: the bump
       supersedes every cached verdict, so arm 3 is empty for the mornings the drain takes
       to refill it.
    3. the **live contract's own `|jd` cache row** says YES. A `|bare` row is NOT an
       authority and the distinction is load-bearing: of the three published cells that
       disagreed with some live-contract row on 2026-09-18, two (`amitim`, `אסם`) were
       contradicted only by a `|bare` verdict while their own `|jd` row agreed with the
       cell, and a `|bare` verdict is provisional by construction. Restricted to `|jd`, the
       class was exactly ONE: `navina|data researcher`, whose cell read `reject/keyword`
       "no analytics signal in title" because the card it was stamped from had no text.

    A *superseded* `|jd` YES is deliberately NOT an arm of its own. It would re-select every
    one of the eleven every morning for ever: the judge re-decides under the live contract,
    writes `reject` again where it still means it, and the stale YES would still be sitting
    there tomorrow. Arm 2 reaches the same rows exactly once."""
    cls = rec.get("class") or {}
    if cls.get("decision") != "reject":
        return False
    if _seniority().adjudicated(_job(rid, rec)):
        return True
    if cls.get("contract") != (contract or _seniority().CONTRACT):
        return True
    if not cache:
        return False
    _here, jd_key, _bare, _legacy = _seniority().cache_keys(
        _job(rid, rec), True, contract or _seniority().CONTRACT)
    return cache.get(jd_key) is True


def _seniority():
    from . import seniority               # late: seniority imports nothing from here
    return seniority


def candidates(records, *, cache=None, contract=None):
    """[(role_id, record)] — every record the backfill may judge, in a stable order.

    Two pools since 2026-09-18, and `cache`/`contract` are what the second needs. Omitting
    them keeps the first pool alone, which is what every caller that has no store in hand
    gets (and what `--dry-run` shows).

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
    while looking judged to this queue.

    **And a decision with no contract is owed one too** (`roles.class_unjudged`, 2026-09-13):
    30 published rows carried a decision stamped before the verdict recorded which rules
    made it, every one `closed`, and this queue -- the only thing that reaches a closed
    record -- read "has a decision" as "judged". The meta called them `rows_unknown` and
    nothing drained them."""
    out = []
    for rid, rec in sorted(records.items()):
        if not rec.get("title") or (rec.get("status") or "open") not in PUBLISHED:
            continue
        if _roles.class_unjudged(rec) or reject_owed(rid, rec, cache, contract):
            out.append((rid, rec))
    return out


def _job(rid, rec):
    """The record as the classifier's seam expects a posting. `description` is already on
    the record: `Ledger._open_sync` hydrates it from `roles_text.jsonl` (or sqlite) for
    every record, so a closed role that has not been fetched in a fortnight still has the
    text it was captured with."""
    return {"title": rec.get("title") or "", "company": rec.get("company") or "",
            "location": rec.get("location") or "", "url": rec.get("url") or rid,
            "description": rec.get("description") or "", "role_id": rid}


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
    records = getattr(ledger, "records", {}) or {}
    rows = candidates(records, cache=getattr(clf, "cache", None), contract=clf.contract)
    refills = sum(1 for rid, rec in rows
                  if reject_owed(rid, rec, getattr(clf, "cache", None), clf.contract))
    for rid, rec in rows:
        r = clf.judge_backfill(_job(rid, rec),
                               published=(rec.get("status") or "open") in PUBLISHED)
        if not r:
            continue                       # capped, breaker open, or the call failed
        out[rid] = {k: r[k] for k in ("decision", "path", "reason", "contract")
                    if r.get(k) is not None}
        if verbose and r["path"] != "keyword":
            # `_ascii`, like every other print in this seam: two of the 42 records measured
            # on 2026-08-31 carry U+FFFD in the title, and a bare print of one of those on a
            # cp1252 console raises AFTER the calls are paid for -- inside `run.py` the guard
            # would swallow it and discard the WHOLE map with no alarm.
            print(f"  [backfill] {_ascii(rec.get('company'), 40)} | "
                  f"{_ascii(rec.get('title'), 60)} -> "
                  f"{r['decision']}: {_ascii(r['reason'], 120)}", flush=True)
    # The three clauses do not overlap, and that is deliberate: a `reject` cell HAS a
    # decision and a contract, so counting it as "an unknown-contract decision" would have
    # made the second number grow every time the third did, and a reader of the step log
    # would have had no way to tell the two pools apart.
    unknown = sum(1 for _r, x in rows
                  if _roles.class_unjudged(x) and (x.get("class") or {}).get("decision"))
    line = (f"backfill: {len(rows)} verdict-less record(s) "
            f"({unknown} of them an unknown-contract decision"
            + (f", {refills} a published reject owed a live verdict" if refills else "")
            + f"), {clf.backfill_judged} judged "
            f"({clf.backfill_yes} yes, {clf.backfill_no} no) + {clf.backfill_cached} cached "
            f"+ {clf.backfill_keyword} keyword, {clf.backfill_held} held")
    return out, line


def apply_to(records, verdicts, run_date):
    """Fill an EMPTY or unknown-contract `class` from the map. Returns the role_ids it changed.

    The same rule `Ledger.record_run` applies -- an empty cell takes any verdict, an
    unknown-contract cell only one that names its contract -- so running the CLI and the
    in-run hook on the same day cannot produce two different answers for one role."""
    changed = []
    for rid, cls in (verdicts or {}).items():
        rec = records.get(rid)
        if rec is None or not cls or not _roles.class_refillable(rec, cls):
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
    # the cache and the contract BEFORE the pool, because the second pool is defined
    # against them: a dry run that listed a different set from the one the real pass judges
    # is the confident-but-false report this repo punishes hardest.
    if a.cap is not None:
        os.environ["CLASSIFY_BACKFILL_CAP"] = str(a.cap)
    cache = st.load_llm_cache()
    clf = seniority.Classifier(llm_cache=cache)
    rows = candidates(ledger.records, cache=cache, contract=clf.contract)
    print(f"{len(rows)} record(s) owed a verdict in {ledger.path}")
    if a.dry_run:
        for rid, rec in rows:
            why = (" | reject owed a re-judge"
                   if reject_owed(rid, rec, cache, clf.contract) else "")
            print(f"  {rec.get('company')} | {rec.get('title')} "
                  f"| {len(rec.get('description') or '')} chars | {rec.get('status')}{why}")
        return 0
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
