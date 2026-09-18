"""Re-judge named role records on their own stored text, and forget the verdicts they had.
(lane: classifier)

`llm_cache` keys a verdict on `contract|company|title|jd`, with no hash of the text it was
judged on (`docs/BACKLOG.md` 551 b). So when a description is REPAIRED -- another posting's
page replaced by the role's own -- the verdict reached on the wrong text is served for ever:
Ballerine's `|jd` NO was bought on 2026-09-02 over 2,671 characters of site chrome, jd-text
replaced the text on 09-11, and the 09-12 digest stamped the record `reject` from that
cached NO. `_versioned` serves a superseded prefix by the job's suffix, so an invalidation
has to delete the job's key under EVERY prefix, and until today that was hand-run SQL
(`551`'s three `techbiz global` keys). This is that SQL made repeatable and reviewable.

It never bumps the contract (which re-supersedes ~560 cells to reach a handful) and never
writes the role ledger: the next digest stamps the record from the cache it finds -- WITH
ONE CLASS OF EXCEPTION, corrected here on 2026-09-18 after it cost a session a wrong
prediction. A record that is `closed` and whose cell already NAMES a contract is reached by
nothing: the drain only re-judges roles the run fetched, and `class_backfill.candidates`
read "has a decision under the live contract" as "judged". Forgetting such a row's keys and
re-judging leaves the ledger cell exactly as it was. Since 2026-09-18 the backfill has a
second pool for the one direction that is safe (a `reject` cell against a live-contract
`|jd` YES, or against a written adjudication in `seniority.ADJUDICATED`), so a
`--forget --judge` that lands a YES is picked up the next morning; an accept-to-reject
still needs `roles_retractions.jsonl`.

    python tools/rejudge_rows.py --role-id "ballerine|ai fraud data analyst senior"
    python tools/rejudge_rows.py --role-id "<id>" --forget --judge --votes 2
    python tools/rejudge_rows.py --unknown-contract --judge        # the backfill's new pool

Default is a dry run: the keys under every prefix, the ledger's cell, the stored text length.
`--forget` deletes those keys. `--judge` re-judges each record through
`Classifier.judge_backfill` -- the cron's own path, geography head, shared-text guard and all
-- and saves the verdict; `--votes N` asks the seam N more times WITHOUT caching, so a flap
can be told from a stable answer before anyone writes a retraction line. A paid rung: run it
from the shared checkout, which holds the login.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import class_backfill, roles, seniority            # noqa: E402
from pipeline.store import SeenStore                               # noqa: E402


def job_keys(conn, job):
    """Every `llm_cache` key that answers for this job: its `company|title` under any
    contract prefix (`seniority._versioned`), `|jd` or `|bare`, plus the legacy raw row."""
    title = seniority._norm(job.get("title")) or str(job.get("title") or "").strip().lower()
    base = "%s|%s" % (seniority._norm_company(job.get("company")), title)
    legacy = "%s|%s" % ((job.get("company") or "").strip().lower(),
                        (job.get("title") or "").lower().strip())
    out = []
    for key, verdict, updated in conn.execute("select title_key, verdict, updated from llm_cache"):
        split = seniority._versioned(key)
        if (split and split[0].rsplit("|", 1)[0] == base) or key == legacy:
            out.append((key, verdict, updated or ""))
    return sorted(out, key=lambda r: (r[2], r[0]))


def forget(conn, keys):
    conn.executemany("delete from llm_cache where title_key = ?", [(k,) for k in keys])
    conn.commit()
    return len(keys)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=os.path.join(ROOT, "cloud_state", "seen.db"))
    ap.add_argument("--role-id", action="append", default=[], help="repeatable")
    ap.add_argument("--unknown-contract", action="store_true",
                    help="every published record whose cell names no contract")
    ap.add_argument("--forget", action="store_true", help="delete the keys under every prefix")
    ap.add_argument("--judge", action="store_true", help="re-judge and cache (spends calls)")
    ap.add_argument("--votes", type=int, default=0, help="extra uncached seam calls per record")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    st = SeenStore(a.db)
    date = dt.datetime.now(dt.timezone.utc).date().isoformat()
    ledger = roles.Ledger(st, date)
    ledger.open_sync()
    ids = list(a.role_id)
    if a.unknown_contract:
        ids += [rid for rid, rec in class_backfill.candidates(ledger.records)
                if (rec.get("class") or {}).get("decision") and rid not in ids]
    if not ids:
        ap.error("name --role-id or --unknown-contract")

    jobs = {}
    for rid in ids:
        rec = ledger.records.get(rid)
        if rec is None:
            print("NOT IN THE LEDGER: %s" % rid)
            continue
        job = class_backfill._job(rid, rec)
        jobs[rid] = (rec, job)
        cell = rec.get("class") or {}
        keys = job_keys(st.conn, job)
        print("%s | %s | %s/%s contract=%s | text %d chars"
              % (rid, rec.get("status"), cell.get("decision"), cell.get("path"),
                 cell.get("contract") or "-", len(job["description"])))
        for k, v, u in keys:
            print("    %s => %s  (%s)" % (k, v, u))
        if a.forget and keys:
            print("    forgot %d key(s)" % forget(st.conn, [k for k, _v, _u in keys]))

    if a.judge or a.votes:
        cache = st.load_llm_cache()
        clf = seniority.Classifier(llm_cache=cache, cache_dates=st.load_llm_cache_dates())
        clf.backfill_cap = max(clf.backfill_cap, len(jobs))
        tally = {"kept": 0, "flipped": 0, "held": 0}
        for rid, (rec, job) in jobs.items():
            was = (rec.get("class") or {}).get("decision")
            r = clf.judge_backfill(dict(job)) if a.judge else None
            votes = []
            for _ in range(max(0, a.votes)):
                v, why = clf._judge(dict(job))
                votes.append("YES" if v else ("NO" if v is False else "?"))
            now = r["decision"] if r else None
            if r is None and a.judge:
                tally["held"] += 1
            elif r is not None:
                tally["kept" if now == was else "flipped"] += 1
            print("%-8s %s | %s -> %s via %s | votes %s | %s"
                  % ("FLIP" if r and now != was else ("HELD" if a.judge and not r else "same"),
                     rid, was, now, r and r["path"], "/".join(votes) or "-",
                     (r or {}).get("reason", "")[:160]))
        written = clf.commit() if a.judge else 0
        if written:
            st.save_llm_cache(cache, date)
        print("\n%s; %d verdict(s) cached; seam attempts %d; contract %s"
              % (tally, written, clf.attempts, clf.contract))
    st.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
