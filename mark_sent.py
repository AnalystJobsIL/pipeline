#!/usr/bin/env python3
"""Mark the postings in a produced digest as SENT, so they won't reappear tomorrow.

Run this ONLY after the digest email has actually been sent (via the Gmail MCP tools).
Kept separate from `pipeline.run` on purpose: producing the digest is safe/idempotent,
but recording postings as sent is a one-way action that suppresses them going forward.

Usage:
  python mark_sent.py out/digest-2026-08-14.json
  python mark_sent.py out/digest-2026-08-14.json --db cloud_state/seen.db
"""
from __future__ import annotations

import json
import sys

from pipeline import store


def main(argv):
    db = None
    rest = argv[1:]
    if "--db" in rest:
        i = rest.index("--db")
        db = rest[i + 1] if i + 1 < len(rest) else None
        rest = rest[:i] + rest[i + 2:]
    if len(rest) != 1:
        print(__doc__)
        return 2
    with open(rest[0], encoding="utf-8") as f:
        payload = json.load(f)
    run_date = payload.get("run_date", "")
    jobs = payload.get("jobs", [])
    st = store.SeenStore(db) if db else store.SeenStore()
    for j in jobs:
        st.mark_sent(j, run_date)  # uses j["seen_ids"]
    total = st.count_sent()
    st.close()
    print(f"marked {len(jobs)} digest postings sent (store now holds {total} sent seen_ids)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
