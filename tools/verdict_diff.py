"""What did the drain actually move between two commits? (lane: classifier)

`llm_cache` is `(title_key, verdict, updated)` and nothing else — no url, no location, no
text (`447@roles`). So when a scope change re-judges a few hundred verdicts, the movement is
real and invisible: the mail says how many were re-judged, and nobody can say WHICH. That
matters most in the days after a contract change, which is exactly when a large cohort moves.

This reconstructs the movement from the two `cloud_state/seen.db` blobs git already has. It
is READ-ONLY: it extracts each commit's database to a temp file and opens both `mode=ro`.

    python tools/verdict_diff.py <sha-before> <sha-after>
    python tools/verdict_diff.py <sha-before>                 # ...against the working tree

Verdicts are joined by the JOB a key names, not by the key itself — `company|title|jd` or
`|bare` with the contract prefix stripped (`seniority._versioned`), plus the legacy
`company|title` rows normalised the way production reads them. That is the only join under
which a contract change is a MOVE rather than 745 deletions and 745 insertions.
"""
from __future__ import annotations

import argparse
import collections
import os
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import seniority                                # noqa: E402

DB = "cloud_state/seen.db"


def _blob(ref):
    """`<ref>:cloud_state/seen.db` as a temp file, or the working tree when ref is None."""
    if ref is None:
        return os.path.abspath(DB), False
    out = subprocess.run(["git", "show", "%s:%s" % (ref, DB)], capture_output=True)
    if out.returncode != 0:
        raise SystemExit("git show %s:%s failed: %s" % (ref, DB, out.stderr.decode()[:200]))
    fd, path = tempfile.mkstemp(suffix=".db", prefix="verdicts-")
    with os.fdopen(fd, "wb") as f:
        f.write(out.stdout)
    return path, True


def _read(path):
    """{job -> (verdict, contract, kind, updated)} — the newest contract wins per job, which
    is the same precedence `Classifier._lookup` applies when several contracts answered."""
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    rows = con.execute("select title_key, verdict, updated from llm_cache").fetchall()
    con.close()
    best = {}
    for key, verdict, updated in rows:
        split = seniority._versioned(key)
        if split:
            suffix, prefix = split
            job, kind = suffix.rsplit("|", 1)
        elif str(key).startswith("jdq1|"):
            continue                       # enrich_matched_jd's JD-quality cache, not a verdict
        else:
            parts = str(key).split("|")
            if len(parts) != 2:
                continue                   # title-only rows: unreachable, and name no job
            job = seniority._norm_company(parts[0]) + "|" + seniority._norm(parts[1])
            prefix, kind = "legacy", "bare"
        prev = best.get(job)
        if prev is None or prefix > prev[1]:      # "v3.x" > "v2" > "legacy"
            best[job] = (bool(verdict), prefix, kind, updated)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after", nargs="?", default=None)
    ap.add_argument("--limit", type=int, default=60)
    a = ap.parse_args()

    paths = []
    try:
        p0, t0 = _blob(a.before); paths.append((p0, t0))
        p1, t1 = _blob(a.after); paths.append((p1, t1))
        old, new = _read(p0), _read(p1)
    finally:
        for p, temp in paths:
            if temp:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    tally = collections.Counter()
    moved, added, gone = [], [], []
    for job, (v, c, k, u) in new.items():
        if job not in old:
            tally["added"] += 1
            added.append((job, v, c, k, u))
            continue
        ov, oc, ok_, ou = old[job]
        if ov != v:
            tally["YES->NO" if ov else "NO->YES"] += 1
            moved.append((job, ov, v, oc, c, u))
        elif oc != c:
            tally["re-judged, verdict unchanged"] += 1
        else:
            tally["untouched"] += 1
    for job in old:
        if job not in new:
            tally["disappeared"] += 1
            gone.append(job)

    print("before %-10s %5d jobs" % (a.before, len(old)))
    print("after  %-10s %5d jobs" % (a.after or "(working tree)", len(new)))
    print()
    for k, v in tally.most_common():
        print("  %-30s %5d" % (k, v))
    if moved:
        print("\nVERDICTS THAT MOVED (%d):" % len(moved))
        for job, ov, v, oc, c, u in moved[:a.limit]:
            print("  %-8s %-9s -> %-11s %s   (%s)"
                  % ("YES->NO" if ov else "NO->YES", oc, c, job[:70], u))
        if len(moved) > a.limit:
            print("  ... %d more" % (len(moved) - a.limit))
    if added:
        print("\nNEW VERDICTS (%d, first %d):" % (len(added), min(a.limit, len(added))))
        for job, v, c, k, u in added[:a.limit]:
            print("  %-3s %-11s %-5s %s   (%s)" % ("YES" if v else "NO", c, k, job[:70], u))
    if gone:
        print("\nJOBS WHOSE VERDICT DISAPPEARED (%d) - a purge, or a re-keying that orphaned "
              "them:" % len(gone))
        for job in gone[:a.limit]:
            print("  %s" % job[:80])


if __name__ == "__main__":
    main()
