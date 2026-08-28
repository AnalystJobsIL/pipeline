#!/usr/bin/env python3
"""The one path every workflow uses to commit state back to the repo (lane: infra).

    python persist_state.py commit --as NAME -m MSG --own PATH... [--branch B]
    python persist_state.py outcome [--commit]        # the run's verdict on itself (daily-digest)
    python persist_state.py deliver --date D           # the digest -> latest.md, or why not
    python persist_state.py merge-file STRATEGY BASE OURS THEIRS OUT
    python persist_state.py table                     # the strategy table, one line per path

Until 2026-08-25 nine workflows carried their own copy of a 50-line shell block: `git add`,
`git commit`, five `git pull --rebase` attempts, and on a conflict `git reset --hard origin`
followed by copying the run's CHECKOUT-ERA files back over origin's newer ones. Two files
were merged (`merge_csv_rows.py`, `merge_json_cache.py`); everything else was last-writer-
wins on a stale copy. The lessons those nine blocks had accumulated, now enforced here:

  * `cloud_state/pipeline_stages.json` is one dict of independent stage keys. auto-expand's
    conflict path restored its 20:00 copy at 23:40 and deleted the `repair` stamp that
    listing-hunt had landed at 22:12 (commits 82d425c -> 0b41823, and 33d0306 -> bab228f
    the day before), so the mail read `repair: never run`. Stamps merge per key here.
  * `cp -r ours/cloud_state cloud_state` into an EXISTING directory nests it and commits
    origin's seen.db / board / digest instead of the run's (4 conflict days; BACKLOG 125).
    Nothing is copied here: every owned path is read from the run's own commit (`git show`).
  * A missing optional path in `git add a b missing` under `bash -e` discarded a whole
    night's registry writes (the registry_ladder lesson). A missing owned path is a notice.
  * `git add -A .` on the conflict path staged whatever the reset left behind. Only the
    owned paths are ever staged.
  * A runner timeout killed the job before the commit step, so nothing the run paid for
    survived (BACKLOG 39/128). The step is `if: always()`, and the gates below make that
    safe: a file that does not parse, a store that fails `quick_check`, a registry that
    fails `check_invariants.py` is restored from the checkout commit and the run exits 1 --
    everything else still lands.
  * `merge_json_cache` could not express a deletion (BACKLOG 95) and turned a corrupt file
    into `{}` silently; the deletion rule lives there now and a corrupt side is a warning.
  * The base for every three-way merge is the checkout commit itself (`git show HEAD:path`
    before anything is committed), so the nine "Snapshot baseline" steps are gone.

The strategy table (`table`) is pinned by a test to every `--own` path in every workflow:
a path with no strategy is taken from ours with a `::warning::`, never silently.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale); the summaries print
# company names. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------- what this run did to the keyed caches
# Every `commit` measures the keyed caches it is about to push against the tree it started
# from, prints the delta, and appends one line here. Nothing in this repo could see a
# shrinking cache before 2026-08-28: the in-process abort in refresh_scrape_cache needs
# >20%, `s_company_dict`'s guard needs >25% AND only runs on a push conflict, and
# check_invariants never opens the cache -- so three consecutive nights lost 16, 16 and 24
# boards in silence (docs/BACKLOG.md 356). This is the measurement, not a block: a bad
# alarm costs attention, a bad block costs coverage, and legitimate deletions (parked rows,
# alias merges) must keep working.
PERSIST_LOG = "cloud_state/persist_log.jsonl"
# What each process bought, written by `bd_rescue._report_spend`. Same shape and same
# reason: the run page dies with the run record, and this repo deletes run records.
BD_SPEND_LOG = "cloud_state/bd_spend.jsonl"
PERSIST_LOG_MAX = 400                       # ~a month at 10-15 commits/day
# PROVISIONAL, n=3. Tuned on the only three regressions ever measured -- 16/279 (5.7%),
# 16/221 (7.2%) and 24/243 (9.9%) -- to fire on all of them while staying quiet for the
# 1-4 key deletions a parked row or an alias merge makes. The floor stops noise on a small
# cache, the percentage stops it on a large one. RE-MEASURE once persist_log.jsonl holds a
# fortnight (morning check 2026-09-11): a threshold nobody trusts is worse than none.
SHRINK_MIN_KEYS = 10
SHRINK_MIN_PCT = 3.0


# ---------------------------------------------------------------- git plumbing
def git(*args, cwd=None, check=True, input_bytes=None):
    """Run git, return stdout as text (UTF-8, replace). Raises on failure when `check`."""
    p = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, input=input_bytes)
    out = p.stdout.decode("utf-8", "replace")
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({p.returncode}): "
                           f"{p.stderr.decode('utf-8', 'replace').strip()[:400]}")
    return out


def git_ok(*args, cwd=None):
    """True when the git command exits 0 (its output is discarded)."""
    return subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True).returncode == 0


def git_show(rev, path, cwd=None):
    """The file's bytes at `rev`, or None when it does not exist there."""
    p = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=cwd or ROOT, capture_output=True)
    return p.stdout if p.returncode == 0 else None


def _write_bytes(path, data):
    """Atomic replace (same directory temp + os.replace), like pipeline.atomic for bytes."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=os.path.basename(path))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _log(kind, msg):
    print(f"::{kind}::persist_state: {msg}" if kind else f"persist_state: {msg}", flush=True)


# ---------------------------------------------------------------- merge strategies
# Each takes the three versions as bytes (None = absent) and returns the merged bytes
# (None = the path should not exist). `theirs` is origin's current version.
def _dumps(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _well_formed(path, data):
    """Cheap shape check on BYTES, mirroring `run_gates`' per-extension gates.

    `s_ours` yields to origin when this run did not touch the file. That is right until
    origin's copy is BROKEN: the run then adopts the corruption, `run_gates` re-gates it
    against origin and "restores" the same bytes, the step exits 1 -- and it repeats every
    night for as long as the owner keeps abstaining, because nothing can clear it. The old
    unconditional `ours` healed that by accident on the first conflict. Keep the heal."""
    if data is None:
        return False
    p = path.replace("\\", "/")
    try:
        if p.endswith(".jsonl"):
            for line in data.splitlines():
                if line.strip():
                    json.loads(line.decode("utf-8"))
        elif p.endswith(".json"):
            json.loads(data.decode("utf-8"))
        elif p.endswith(".md"):
            return data.lstrip().startswith(b"#")
        elif p.endswith(".html"):
            return len(data) >= 500
    except Exception:  # noqa: BLE001 -- a shape check reports, it never raises
        return False
    return True


def s_ours(base, ours, theirs):
    """Single cloud writer: the run's own bytes win -- unless the run never wrote the file.

    `ours == base` means this run did not touch this path, so it has no opinion about it and
    origin's newer version stands. Without that clause `ours` won unconditionally, and a run
    that DELIBERATELY declined to write a file still pushed its checkout-era copy over a
    newer one -- silently, because `merge_conflicted` suppresses the overwrite notice for
    exactly these `SINGLE_WRITER` paths. An attacker reproduced it on 2026-08-27 against the
    one path where it costs a day's mail: `deliver` refuses to replace origin's fresh digest
    with a thinner one, and the persist step's conflict path then put the stale one there
    anyway. BACKLOG 160 NAMES that suppressed warning and stays
    open: what it asks for is a guard against a SECOND writer, which this clause is not."""
    if ours is None:
        return theirs
    if base is not None and ours == base and theirs is not None:
        return theirs
    return ours


def s_company_dict(base, ours, theirs):
    """A `{key: value}` cache with several writers: per key, ours-changed wins, a key ours
    deleted while origin left it alone stays deleted, origin's new keys survive. A corrupt
    side is a warning and yields to the other -- never `{}` written back (BACKLOG 95)."""
    import merge_json_cache as M
    b, o, t = _safe_loads(base), _safe_loads(ours), _safe_loads(theirs)
    if ours is not None and not isinstance(o, dict):
        _log("warning", "ours is not a JSON dict; origin's copy kept")
        return theirs
    if theirs is not None and not isinstance(t, dict):
        _log("warning", "origin's copy is not a JSON dict; ours kept")
        return ours
    b = b if isinstance(b, dict) else {}
    o, t = o or {}, t or {}
    gone = [k for k in b if k not in o]
    if len(b) >= 20 and len(gone) > 0.25 * len(b):
        # CLAUDE.md rule 2: a run that lost a quarter of the cache did not measure it --
        # keep origin's copies of what it dropped (wave-1 attacker)
        _log("warning", f"ours dropped {len(gone)} of {len(b)} keys -- a broken run, not deletions; kept")
        o = dict(o, **{k: b[k] for k in gone})
    out, _, _ = M.merge(b, o, t)
    return _dumps(out)


def _safe_loads(b):
    try:
        return None if b is None else json.loads(b.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def s_jsonl_union(base, ours, theirs):
    """An append-only `.jsonl` audit log written by every workflow: the union of the lines,
    oldest first, capped. There is no conflict to resolve -- two runs appending different
    lines both said something true -- so a union is the whole merge, and it is the reason
    this log can have many writers without a single-writer claim. Deduped on the exact line
    so a rebase that replays the same append twice does not double it."""
    seen, out = set(), []
    for side in (theirs, ours):                 # ours last: a same-key re-run wins the order
        for line in (side or b"").splitlines():
            line = line.strip()
            if line and line not in seen:
                seen.add(line)
                out.append(line)
    out.sort(key=_log_sort_key)
    return b"\n".join(out[-PERSIST_LOG_MAX:]) + b"\n" if out else b""


def _log_sort_key(line):
    """`at` if the line is the shape we write, else the empty string -- a foreign line keeps
    its place at the front rather than raising and losing the whole log."""
    rec = _safe_loads(line)
    at = rec.get("at") if isinstance(rec, dict) else None
    return at if isinstance(at, str) else ""      # `{"at": 1}` used to raise and lose the log


def s_stage_stamps(base, ours, theirs):
    """`cloud_state/pipeline_stages.json`: one dict of independent stage keys, stamped by
    four workflows. Per key: the side that did not touch it yields; both touched -> the
    newer `finished_at`; a key is never deleted (a stamp is a fact about the night)."""
    b, o, t = _safe_loads(base), _safe_loads(ours), _safe_loads(theirs)
    if theirs is not None and not isinstance(t, dict):
        _log("warning", "origin's stamp file is not a JSON dict; ours kept")
    if ours is not None and not isinstance(o, dict):
        _log("warning", "ours stamp file is not a JSON dict; origin's kept")
    b = b if isinstance(b, dict) else {}
    o = o if isinstance(o, dict) else {}
    t = t if isinstance(t, dict) else {}
    out = {}
    for k in sorted(set(o) | set(t)):
        ov, tv = o.get(k), t.get(k)
        ov = ov if isinstance(ov, dict) else None
        tv = tv if isinstance(tv, dict) else None
        if ov is None:
            out[k] = tv
        elif tv is None:
            out[k] = ov
        elif ov == b.get(k):
            out[k] = tv
        elif tv == b.get(k):
            out[k] = ov
        else:
            out[k] = ov if str(ov.get("finished_at", "")) >= str(tv.get("finished_at", "")) else tv
    return _dumps(out)


def _keyed_list(keyfn):
    """A JSON LIST with a natural key (discovered_cache.json, research_companies.json):
    merged as a dict by that key, origin's order kept, ours' additions appended."""
    def strategy(base, ours, theirs):
        import merge_json_cache as M
        def as_map(b):
            v = _safe_loads(b)
            if not isinstance(v, list):
                return {}
            m = {}
            for e in v:
                if isinstance(e, dict):
                    m.setdefault(keyfn(e), e)
            return m
        bm, om, tm = as_map(base), as_map(ours), as_map(theirs)
        if ours is not None and not isinstance(_safe_loads(ours), list):
            _log("warning", "ours is not a JSON list; origin's copy kept")
            return theirs
        if theirs is not None and not isinstance(_safe_loads(theirs), list):
            _log("warning", "origin's copy is not a JSON list; ours kept")
            return ours
        merged, _, _ = M.merge(bm, om, tm)
        ordered = [merged[k] for k in tm if k in merged] + [v for k, v in merged.items() if k not in tm]
        return (json.dumps(ordered, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    return strategy


def s_csv_rows(base, ours, theirs):
    """`companies.csv`: rows by company name, note segments unioned per tool, a segment ours
    deliberately deleted stays deleted (merge_csv_rows.merge, base-aware)."""
    import merge_csv_rows as C
    if ours is None:
        return theirs
    if theirs is None or base is None:
        return ours
    with tempfile.TemporaryDirectory() as d:
        pb, po, pt = (os.path.join(d, n) for n in ("base.csv", "ours.csv", "target.csv"))
        for p, data in ((pb, base), (po, ours), (pt, theirs)):
            with open(p, "wb") as f:
                f.write(data)
        C.merge(pb, po, pt)
        with open(pt, "rb") as f:
            return f.read()


def _job_key(e):
    return ((e.get("company") or "").lower(), (e.get("title") or "").lower())


def _name_key(e):
    return (e.get("name") or "").strip().lower()


# path -> (strategy, why). Exact paths only; anything else is `ours` with a warning.
STRATEGY = {
    "companies.csv": (s_csv_rows, "rows by name, note segments per tool (merge_csv_rows)"),
    "scraped_cache.json": (s_company_dict, "eight writers; per company key, deletions honoured"),
    "cloud_state/firmographics.json": (s_company_dict, "per company record; local chain + digest"),
    # Written by the 10:00 firmographics cron ONLY. `daily-digest.yml` owns `cloud_state`
    # wholesale so it also COMMITS this path, but it never writes it -- `ours == base`
    # there, so no key of base is missing from ours and the deletion arm cannot fire.
    # Deletion IS the right semantics: dropping a key is the only way this ledger can say
    # "researched since, strike cleared", and the merge is base-aware, so a concurrent ADD
    # by the other writer is kept while a deliberate drop is honoured.
    "cloud_state/firmo_failed.json": (s_company_dict, "research strikes; written by the 10:00 cron, per company"),
    "cloud_state/health_baseline.json": (s_company_dict, "digest + self-heal; per company"),
    "cloud_state/stale.json": (s_company_dict, "digest + self-heal's Monday sweep; per company"),
    "cloud_state/scan_seen.json": (s_company_dict, "digest + Sunday audit; per company"),
    "cloud_state/auto_expand_seen.json": (s_company_dict, "auto-expand's rotation key; per company name"),
    "cloud_state/audit_seen.json": (s_company_dict, "the Sunday audit's rotation key; per company name"),
    "cloud_state/pipeline_stages.json": (s_stage_stamps, "per stage key, newer finished_at wins, never deleted"),
    "discovered_cache.json": (_keyed_list(_job_key), "list keyed (company, title); two discovery writers"),
    "research_companies.json": (_keyed_list(_name_key), "list keyed name; two discovery writers"),
    PERSIST_LOG: (s_jsonl_union, "append-only audit log; the union of every workflow's lines"),
    BD_SPEND_LOG: (s_jsonl_union, "append-only Bright Data spend, one line per process"),
}
SINGLE_WRITER = {   # documented `ours` paths (one cloud writer each); anything else warns
    "cloud_state/seen.db": "daily-digest", "cloud_state/roles.jsonl": "daily-digest",
    "cloud_state/roles_text.jsonl": "daily-digest",
    "cloud_state/source_health.json": "daily-digest", "cloud_state/telegram_seen.json": "daily-digest",
    "cloud_state/candidate_probe.json": "daily-digest", "cloud_state/registry_census.json": "daily-digest",
    "cloud_state/registry_alarms.json": "daily-digest", "cloud_state/last_run.json": "daily-digest",
    "cloud_state/last_delivered.json": "daily-digest",
    "cloud_state/registry_ladder.json": "listing-hunt", "cloud_state/scrape_rot.json": "scrape-refresh",
    "cloud_state/resolve_attempts.json": "self-heal", "digests/latest.md": "daily-digest",
    "docs/index.html": "daily-digest", "docs/archive.html": "daily-digest",
}


def strategy_for(path):
    p = path.replace("\\", "/")
    if p in STRATEGY:
        return STRATEGY[p][0], STRATEGY[p][1]
    if p in SINGLE_WRITER:
        return s_ours, f"single writer ({SINGLE_WRITER[p]})"
    return s_ours, "NO STRATEGY -- ours wins"


def table():
    for p, (_, why) in STRATEGY.items():
        print(f"{p:40} merge   {why}")
    for p, w in SINGLE_WRITER.items():
        print(f"{p:40} ours    single writer ({w})")


# ---------------------------------------------------------------- gates
def _gate_json(path):
    with open(path, "rb") as f:
        data = f.read()
    if path.endswith(".jsonl"):
        for i, line in enumerate(data.splitlines(), 1):
            if line.strip():
                json.loads(line.decode("utf-8"))
    else:
        json.loads(data.decode("utf-8"))


def _gate_sqlite(path):
    # read-WRITE on purpose: a hot rollback journal (a step killed mid-transaction) is
    # replayed by the open; a read-only open raises "attempt to write a readonly database"
    # and the whole night's store would be thrown away as corrupt (wave-1 attacker)
    con = sqlite3.connect(path)
    try:
        row = con.execute("PRAGMA quick_check").fetchone()
    finally:
        con.close()
    if not row or row[0] != "ok":
        raise ValueError(f"quick_check: {row}")


# A file and the receipt that describes it are persisted together or not at all. `run_gates`
# restores ONE failing path from base and lets the rest of the commit push, which would leave
# origin carrying a receipt for a digest that is not there (2026-08-27 attacker).
# ONE-WAY on purpose. If the DIGEST fails its gate the receipt describing it must go too,
# or origin carries a receipt for a file it does not have. The reverse is not true: a corrupt
# receipt is metadata, and withdrawing a good digest over it would cost the day's mail --
# after `mark_sent` has already burned the roles, since that step runs before `persist`.
PAIRED = {"digests/latest.md": "cloud_state/last_delivered.json"}


def run_gates(paths, base, gate_cmd, cwd):
    """Check every owned path; a failing one is restored from `base`. Returns the failures."""
    failed = []
    for p in paths:
        full = os.path.join(cwd, p)
        if not os.path.exists(full):
            continue
        try:
            if p.endswith((".json", ".jsonl")):
                _gate_json(full)
            elif p.endswith(".db"):
                _gate_sqlite(full)
            elif p.endswith(".md"):
                head = open(full, "rb").read(200)
                if not head.lstrip().startswith(b"#"):
                    raise ValueError("a digest starts with a heading")
            elif p.endswith(".html"):
                if os.path.getsize(full) < 500:
                    raise ValueError(f"{os.path.getsize(full)} bytes is not a board")
            elif p == "companies.csv" and gate_cmd:
                r = subprocess.run(gate_cmd, cwd=cwd, shell=True, capture_output=True)
                if r.returncode != 0:
                    raise ValueError(r.stderr.decode("utf-8", "replace").strip()[-300:]
                                     or r.stdout.decode("utf-8", "replace").strip()[-300:])
        except Exception as e:  # noqa: BLE001 -- a gate failure is a report, then a restore
            failed.append((p, f"{e.__class__.__name__}: {str(e)[:200]}"))
            if git_show(base, p, cwd) is not None:
                git("checkout", base, "--", p, cwd=cwd)
                _log("error", f"{p} failed its gate ({failed[-1][1]}) -- restored from {base[:8]}, NOT persisted")
            else:
                os.unlink(full)
                _log("error", f"{p} failed its gate ({failed[-1][1]}) -- removed, NOT persisted")
    for p, _why in list(failed):
        mate = PAIRED.get(p.replace("\\", "/"))
        if not mate or mate not in paths or mate in [f[0] for f in failed]:
            continue
        if git_show(base, mate, cwd) is not None:
            git("checkout", base, "--", mate, cwd=cwd)
            _log("error", f"{mate} restored from {base[:8]} too -- it is paired with {p}, and "
                          f"persisting one without the other leaves origin describing a file "
                          f"it does not have")
        else:
            # the mate is UNTRACKED at base (its first ever run). Restoring is impossible, so
            # remove it: shipping it alone is the exact state the pairing exists to prevent,
            # and the previous version silently did nothing here.
            full = os.path.join(cwd, mate)
            if os.path.exists(full):
                os.unlink(full)
                _log("error", f"{mate} removed -- it is paired with {p}, which failed its gate, "
                              f"and there is no version at {base[:8]} to restore it to")
    return failed


# ---------------------------------------------------------------- commit
_SIDE_FILES = ("-journal", "-wal", "-shm", ".tmp")   # sqlite side files, atomic-write leftovers


def _is_side_file(p):
    base = os.path.basename(p)
    return base.startswith(".tmp_") or base.endswith(_SIDE_FILES)


def expand_owned(paths, cwd):
    """Owned paths -> concrete files: a directory expands to its tracked + untracked (not
    ignored) files, minus sqlite journals and atomic-write leftovers; a tracked file that
    vanished -- under an owned directory or owned by name -- is restored from HEAD (a state
    file disappearing mid-run is a broken run, and `--own cloud_state` on an empty directory
    used to commit the deletion of every state file and report success -- wave-1 attacker /
    wave-2 confirmer); a path that exists nowhere is a notice, never an abort."""
    out = []
    for p in paths:
        p = p.replace("\\", "/").rstrip("/")
        full = os.path.join(cwd, p)
        tracked = [x for x in git("ls-files", "--", p, cwd=cwd).split("\n") if x]
        is_dir = os.path.isdir(full) or (len(tracked) > 1 or (tracked and tracked[0] != p))
        if is_dir:
            listed = [x for x in git("ls-files", "-co", "--exclude-standard", "--", p, cwd=cwd).split("\n")
                      if x and not _is_side_file(x)]
            gone = [x for x in tracked if not os.path.exists(os.path.join(cwd, x))]
            if gone:
                _log("warning", f"{len(gone)} tracked file(s) under {p} vanished this run -- restored from HEAD so the "
                                f"deletion is not pushed: {gone[:5]}. On a CONFLICT this run then counts "
                                f"as not having touched them, so origin's version stands unless it is malformed")
                git("checkout", "HEAD", "--", *gone, cwd=cwd)
            out.extend(x for x in listed if x)
        elif os.path.exists(full):
            out.append(p)
        elif tracked:
            # no tool in this repo deletes an owned file on purpose; a vanished one is a
            # broken run, and its deletion used to be pushed ungated (wave-2 confirmer)
            _log("warning", f"owned file {p} vanished this run -- restored from HEAD, not deleted")
            git("checkout", "HEAD", "--", p, cwd=cwd)
            out.append(p)
        else:
            _log("notice", f"owned path {p} does not exist this run -- skipped")
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def merge_conflicted(owned, base, ours_rev, theirs_rev, cwd):
    """After `reset --hard origin`: rebuild every owned path from the three versions."""
    for p in owned:
        strat, why = strategy_for(p)
        b, o, t = git_show(base, p, cwd), git_show(ours_rev, p, cwd), git_show(theirs_rev, p, cwd)
        if o == t:
            continue
        if strat is s_ours and o is not None and b is not None and o == b \
                and not _well_formed(p, t):
            # this run abstained, but origin's copy is broken -- adopting it would wedge the
            # gate on every future abstaining run. Heal from the checkout instead, loudly.
            _log("error", f"{p}: this run did not write it and origin's copy is malformed -- "
                          f"healing from the checkout ({len(o)} bytes) rather than adopting it")
            _write_bytes(os.path.join(cwd, p), o)
            print(f"  merged {p}: {why} (origin was malformed; healed)", flush=True)
            continue
        if strat is s_ours and p not in SINGLE_WRITER and t is not None and o != t:
            _log("warning", f"{p}: {why} (origin's version overwritten)")
        try:
            merged = strat(b, o, t)
        except Exception as e:  # noqa: BLE001 -- never lose the run over one file
            _log("warning", f"{p}: merge raised {e.__class__.__name__}: {str(e)[:120]} -- ours kept")
            merged = o if o is not None else t
        full = os.path.join(cwd, p)
        if merged is None:
            if os.path.exists(full):
                os.unlink(full)
        else:
            _write_bytes(full, merged)
        print(f"  merged {p}: {why}", flush=True)


def _identity(name):
    """The bot identity for this process only -- rebase, autostash and commit all need one
    and a runner has none (`actions/checkout` sets nothing; `x@host.(none)` is refused).
    Env, never `.git/config`: a local run used to overwrite the checkout's `ajil-bot`
    identity (CLAUDE.local.md rule 1) for every later manual commit (wave-2 confirmer)."""
    for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        os.environ[k] = name
    for k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        os.environ[k] = f"{name}@users.noreply.github.com"


def _commit(cwd, name, msg):
    git("commit", "-q", "-m", msg, cwd=cwd)


def key_deltas(owned, base, cwd):
    """What this run did to every keyed cache it owns, measured against `base` (the tree the
    run checked out). One record per path: keys before, keys after, and the names it lost.

    Scope comes from the STRATEGY table -- exactly the paths merged by `s_company_dict`, i.e.
    the ones that ARE a `{key: value}` cache -- so there is no second list to keep in step.
    A side that is absent or not a dict yields no record rather than a wrong one: the first
    run of a new cache has nothing to compare against and must not read as a total loss."""
    out = []
    for p in owned:
        if strategy_for(p)[0] is not s_company_dict:
            continue
        before = _safe_loads(git_show(base, p, cwd))
        try:
            with open(os.path.join(cwd, p), "rb") as f:
                after = _safe_loads(f.read())
        except OSError:
            continue
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        lost = sorted(set(before) - set(after))
        gained = len(set(after) - set(before))
        if not lost and not gained:
            continue          # an unchanged cache is not news: reporting it made EVERY run
                              # commit (the `nothing to commit` path became unreachable) and
                              # made this log the one hunk every workflow appends to, i.e. a
                              # guaranteed rebase conflict. Found by an adversarial pass.
        out.append({"path": p, "before": len(before), "after": len(after),
                    "lost": len(lost), "gained": gained, "names": lost[:25]})
    return out


def shrank(d):
    """Is this delta the shape that has been costing boards? Both bars, so a small cache
    losing two keys and a big one losing 0.5% stay quiet."""
    return d["lost"] >= SHRINK_MIN_KEYS and d["lost"] * 100.0 >= SHRINK_MIN_PCT * max(1, d["before"])


def report_deltas(deltas, cwd, message="", base=""):
    """Say it on the run page FIRST, then leave it where tomorrow can read it back.

    The run page is primary on purpose: the digest's alarm line only reaches a human if the
    mail goes out, and on 2026-08-27 and -28 it did not (docs/decisions/2026-08-28-relay-
    trigger.md). A number that is only in an email nobody received is not a measurement."""
    if not deltas:
        return
    lines = []
    for d in deltas:
        arrow = f"{d['path']}: {d['before']} -> {d['after']} keys (+{d['gained']} / -{d['lost']})"
        if shrank(d):
            pct = d["lost"] * 100.0 / max(1, d["before"])
            names = ", ".join(" ".join(str(n).split()) for n in d["names"]) or "-"
            _log("warning", f"{arrow} -- lost {d['lost']} of {d['before']} ({pct:.1f}%). "
                            f"First 25: {names}")   # collapsed: a newline ends an annotation
            lines.append(f"- **{arrow} -- {pct:.1f}% LOST**")
        else:
            print(f"persist_state: {arrow}", flush=True)
            lines.append(f"- {arrow}")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("\n### Keyed caches this run\n" + "\n".join(lines) + "\n")
        except OSError as e:
            print(f"  [deltas] step summary not written: {e}", flush=True)
    # `base` is the tree the run checked out. On the conflict path `merge_conflicted` runs
    # AFTER this, so what finally lands can differ from what is recorded here -- stamping the
    # base makes the record interpretable instead of merely wrong (BACKLOG 365).
    rec = {"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "base": (base or "")[:8],
           "run": os.environ.get("RUN_URL", "") or os.environ.get("GITHUB_RUN_ID", ""),
           "msg": " ".join(str(message or "").split())[:120],
           "paths": [{k: d[k] for k in ("path", "before", "after", "lost", "gained")}
                     for d in deltas]}
    full = os.path.join(cwd, PERSIST_LOG)
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        old = b""
        if os.path.exists(full):
            with open(full, "rb") as f:
                old = f.read()
        keep = [x for x in old.splitlines() if x.strip()][-(PERSIST_LOG_MAX - 1):]
        # NOT _dumps: it indents, and an indented record is several lines, none of which is
        # valid JSON on its own -- `run_gates` parses a .jsonl line by line and would fail
        # the very log it is meant to keep. One record, one line.
        line = json.dumps(rec, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        _write_bytes(full, b"\n".join(keep + [line]) + b"\n")
    except OSError as e:                # an audit log never costs the commit it describes
        print(f"  [deltas] {PERSIST_LOG} not written: {e}", flush=True)


def commit(a):
    cwd = a.cwd or ROOT
    branch = a.branch or os.environ.get("GITHUB_REF_NAME") or "master"
    _identity(a.as_name)
    base = git("rev-parse", "HEAD", cwd=cwd).strip()
    owned = expand_owned(a.own, cwd)
    if not owned:
        _log("notice", "nothing owned exists; nothing to commit")
        return 0
    failures = run_gates(owned, base, a.gate, cwd)
    # AFTER the gates: a path a gate restored is back to base, and reporting a loss the
    # commit is not going to make would be a false alarm. The log is owned by this layer,
    # not by the caller -- every workflow gets the audit line without naming it in `--own`,
    # so the record cannot drift out of step with who commits.
    try:
        report_deltas(key_deltas(owned, base, cwd), cwd, a.message, base)
    except Exception as e:  # noqa: BLE001 -- an audit line never costs the commit it describes
        _log("warning", f"cache delta report skipped: {e.__class__.__name__}: {str(e)[:120]}")
    for audit in (PERSIST_LOG, BD_SPEND_LOG):
        if audit not in owned and os.path.exists(os.path.join(cwd, audit)):
            owned.append(audit)

    def stage():
        # a path a gate removed (untracked, failed) must not reach `git add`: one missing
        # pathspec is fatal and used to discard the whole run (wave-1 attacker)
        present = [p for p in owned if os.path.exists(os.path.join(cwd, p))
                   or git("ls-files", "--", p, cwd=cwd).strip()]
        if present:
            git("add", "-f", "--", *present, cwd=cwd)     # -f: an owned path is wanted even if ignored
        return bool(git("status", "--porcelain", "--", *owned, cwd=cwd).strip())

    if not stage():
        print("persist_state: nothing to commit", flush=True)
        return 1 if failures else 0
    _commit(cwd, a.as_name, a.message)
    for i in range(1, a.retries + 1):
        before = git("rev-parse", "HEAD", cwd=cwd).strip()
        conflicted = not git_ok("pull", "--rebase", "--autostash", "origin", branch, cwd=cwd)
        if not conflicted:
            # git's line-wise merge of two JSON edits can parse or not: re-gate ONLY what the
            # rebase actually rewrote (re-gating everything looped forever on a file whose
            # gate is a constant failure)
            rewritten = [p for p in git("diff", "--name-only", before, "HEAD", "--", *owned, cwd=cwd).splitlines() if p]
            bad = run_gates(rewritten, base, a.gate, cwd) if rewritten else []
            if bad:
                _log("warning", f"the rebased tree failed a gate ({[p for p, _ in bad]}); merging per file instead")
                failures += bad
                conflicted = True
            elif git_ok("push", "origin", f"HEAD:{branch}", cwd=cwd):
                print(f"persist_state: pushed {len(owned)} paths to {branch} (attempt {i})", flush=True)
                return 1 if failures else 0
            else:
                _log("warning", f"push rejected on attempt {i}; retrying")
        if conflicted:
            # CONFLICT: rebuild every owned path onto origin's current tree, per file.
            # `before` is the run's own commit (after a clean-but-ungateable rebase HEAD
            # would be the corrupt merge, and the run's bytes would be lost -- wave-2)
            git_ok("rebase", "--abort", cwd=cwd)
            ours_rev = before
            try:
                git("fetch", "origin", branch, cwd=cwd)
                theirs_rev = git("rev-parse", f"origin/{branch}", cwd=cwd).strip()
                git("reset", "--hard", theirs_rev, cwd=cwd)
            except RuntimeError as e:          # a network blip: keep the commit, try again
                _log("warning", f"attempt {i}: {e}")
                git_ok("reset", "--hard", ours_rev, cwd=cwd)
                time.sleep(i * a.sleep)
                continue
            print(f"persist_state: conflict on attempt {i}: merging {len(owned)} paths onto {theirs_rev[:8]}", flush=True)
            merge_conflicted(owned, base, ours_rev, theirs_rev, cwd)
            failures += run_gates(owned, theirs_rev, a.gate, cwd)
            if stage():
                _commit(cwd, a.as_name, f"{a.message} (row-merged)")
            else:
                print("persist_state: origin already holds everything this run produced", flush=True)
                return 1 if failures else 0
            # the merged commit already contains origin@now; a second conflict must be
            # judged against THAT, or origin's later edits look like ours (wave-1 attacker)
            base = theirs_rev
        time.sleep(i * a.sleep)
    _log("error", f"push failed after {a.retries} attempts")
    return 1


# ---------------------------------------------------------------- outcome (daily-digest)
# steps that run at or before the persist step: a failure here means the mail is missing
CRITICAL_STEPS = ("pipeline", "gate", "persist")
# the notice is the one markdown this repo builds outside pipeline/digest.py, and an
# exception message can carry a scraped page's bytes (fetchers interpolate response text):
# escape what digest._md_line escapes -- markdown, tags, @mentions -- and fold newlines
_MD = re.compile(r"[\\`\[\]@]|<(?=[A-Za-z/!])")


def _esc(s):
    # a backslash does not escape inside a code span, so a backtick is swapped for U+02CB
    # (looks the same, closes nothing); the rest is backslash-escaped like digest._md_line
    return _MD.sub(lambda m: "\u02cb" if m.group(0) == "`" else "\\" + m.group(0),
                   " ".join(str(s or "").split()))


def build_last_run(steps, job_status, run_url, run_date):
    failed = {k: v.get("outcome") for k, v in steps.items()
              if isinstance(v, dict) and v.get("outcome") in ("failure", "cancelled")}
    return {"date": run_date, "status": job_status or "unknown", "run_url": run_url,
            "failed_steps": failed}


def notice_warranted(steps, job_status):
    """Only a failure that cost the day's mail earns a notice: the pipeline, the gate, the
    persist step, or a job cancelled/failed before persist could succeed. A failed pre-step
    is an alarm inside a delivered digest; a failed board publish reaches tomorrow's mail."""
    if any(isinstance(steps.get(k), dict) and steps[k].get("outcome") in ("failure", "cancelled")
           for k in CRITICAL_STEPS):
        return True
    persisted = isinstance(steps.get("persist"), dict) and steps["persist"].get("outcome") == "success"
    ran = isinstance(steps.get("pipeline"), dict) and steps["pipeline"].get("outcome") == "success"
    # a red job where persist succeeded but the pipeline never RAN (skipped behind a failed
    # checkout / setup / CLI install) is a lost digest, not a delivered one (wave-1 attacker)
    return (job_status or "").lower() in ("failure", "cancelled") and (not persisted or not ran)


def build_notice(steps, job_status, crash, stamps_line, run_url, run_date, digest_built, digest_new,
                 marked_sent=False):
    failed = [k for k in steps if isinstance(steps[k], dict)
              and steps[k].get("outcome") in ("failure", "cancelled")]
    # the step that COST the digest leads; a tolerated pre-step that also failed is listed
    # after it (the rehearsal of 2026-08-25 named `liveness` and hid `pipeline`)
    failed.sort(key=lambda k: (k not in CRITICAL_STEPS, CRITICAL_STEPS.index(k) if k in CRITICAL_STEPS else 0))
    first = failed[0] if failed else "(no step outcome recorded)"
    outcome = steps.get(first, {}).get("outcome", job_status or "unknown") if failed else (job_status or "unknown")
    lines = [f"# ⚠️ No digest for {run_date} — the daily run failed", ""]
    what = f"- **Failed at:** `{_esc(first)}` (outcome: {_esc(outcome)})"
    if crash:
        what += (f" · phase `{_esc(crash.get('phase', '?'))}` · `{_esc(crash.get('exc_type', ''))}: "
                 f"{_esc(str(crash.get('message', ''))[:160])}`")
    what += f" — [run log]({run_url})" if re.fullmatch(r"https://[\w./-]+", run_url or "") else ""
    lines.append(what)
    if len(failed) > 1:
        lines.append("- **Also failed:** " + ", ".join(f"`{_esc(k)}`" for k in failed[1:]))
    lines.append(f"- **What did run tonight:** {_esc(stamps_line) or 'no stage stamps readable'}")
    persisted = isinstance(steps.get("persist"), dict) and steps["persist"].get("outcome") == "success"
    if digest_built:
        lines.append(f"- **Digest:** built with {int(digest_new)} role(s) but not delivered"
                     + (" — those roles were already marked sent and will NOT be re-mailed"
                        if marked_sent else
                        " — nothing was marked sent, so they are re-offered to the next digest"
                        " on their own `posted_date`"))
    else:
        lines.append("- **Digest:** none was built; nothing was marked sent")
    pub = steps.get("publish", {}).get("outcome") if isinstance(steps.get("publish"), dict) else None
    lines.append("- **Board:** " + ("published" if pub == "success" else
                                   "yesterday's board stays published (nothing new was written)"))
    lines.append("- **This run's caches and verdicts:** "
                 + ("saved" if persisted else
                    "partly saved (the persist step was red — see the run log for what it refused)"
                    if isinstance(steps.get("persist"), dict) and steps["persist"].get("outcome") == "failure"
                    else "not saved (the persist step did not run)"))
    if crash and crash.get("traceback_tail"):
        lines += ["", "<details><summary>traceback</summary>", "", "```",
                  *[str(x).rstrip().replace("```", "'" * 3) for x in crash["traceback_tail"][:15]], "```", "</details>"]
    lines += ["", f"_The next scheduled run is tomorrow 05:00 UTC; this notice was written by the run's final step at "
              f"{dt.datetime.now(dt.timezone.utc).strftime('%H:%M')} UTC._", ""]
    return "\n".join(lines)


def _stamps_line():
    try:
        from pipeline import stages
        return stages.summary()
    except Exception as e:  # noqa: BLE001 -- the notice must never depend on the package importing
        return f"(stage stamps unreadable: {e.__class__.__name__})"


# ---------------------------------------------------------------- deliver
# `digests/latest.md` IS the mail: the private relay polls it, sha256-dedups it against the
# last issue it posted, and emails whatever it finds. Until 2026-08-27 the digest step ended
# in an unconditional `cp`, which left three failures possible:
#
#   * A SECOND run the same day copied a WORSE digest over a good one. `store.filter_new`
#     drops roles already in `sent`, so run #2 renders `0 new senior analytics roles`, the
#     relay sees new bytes and mails an EMPTY digest that replaces the real morning's. This
#     is why the recovery cron proposed on 2026-08-27 was rejected rather than guarded
#     (ARCHITECTURE section 4): the defect is the unconditional copy, not the schedule. It
#     is also what made an operator re-run unsafe.
#   * A run finishing after the relay's LAST poll still marked its roles `sent` and was
#     never mailed -- `mark_sent` records intent, not delivery (BACKLOG 6). Those roles do
#     not come back: `filter_new` drops them tomorrow too.
#   * Nothing recorded that a digest HAD reached the mail, so no later run could tell a
#     quiet morning from a missing one. `last_run.json` is not that record: it is written
#     ONLY when a run failed, so on a healthy day it is silent and stale by design.
#
# So: refuse a weaker same-date replacement, defer past the relay's cutoff, and write a
# receipt for what actually landed. The receipt is staged by the SAME
# `persist_state.py commit --own cloud_state digests/latest.md ...` step, so it is atomic
# with the file it describes -- never a second writer of `digests/latest.md`.

def _env_int(name, default):
    """A bad env var must not raise at IMPORT: this module is also `commit` and `outcome`,
    and a typo in one workflow's env would take the whole delivery path down with it."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        _log("warning", f"{name}={os.environ.get(name)!r} is not an integer; using {default}")
        return int(default)


RELAY_LAST_POLL = os.environ.get("RELAY_LAST_POLL_UTC", "10:17")      # ARCHITECTURE section 4
DELIVER_MARGIN_MIN = _env_int("DELIVER_MARGIN_MIN", 20)               # mark_sent+gate+persist
LAST_DELIVERED = "cloud_state/last_delivered.json"
NOTICE_H1 = "# ⚠️ No digest"


def digest_sha(body):
    """The receipt's fingerprint for a digest: sha256 of the bytes with CRLF normalised to LF.

    Normalised, and it matters. `core.autocrlf=true` is the default on Windows, so the same
    digest is CRLF in the operator's checkout and LF in the committed blob and on every
    Ubuntu runner. Hashing raw bytes made the receipt's sha depend on which machine wrote
    it: a receipt written in the cloud never matched the same file read locally, and
    `run.py::_receipt_alarms` would report `something replaced it` about a file nothing had
    touched. Found before this ever ran in production, by hashing the seed both ways:
    `0a3aa0fa...` in a Windows worktree against `71ef0dcb...` for the identical blob.

    This is OUR fingerprint, not the relay's -- the relay computes its own `sha256sum` over
    the raw bytes it fetches, and nothing here compares against that."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    return hashlib.sha256(bytes(body).replace(b"\r\n", b"\n")).hexdigest()


def digest_delivered(head, run_date):
    """True when `head` (the first bytes of `digests/latest.md`) is a REAL digest for
    run_date. A dated failure notice is not a delivery, and neither is yesterday's file.
    One definition, used by `deliver` and by `outcome`'s notice suppressor, so the two
    cannot drift apart."""
    text = head.decode("utf-8", "replace") if isinstance(head, (bytes, bytearray)) else str(head or "")
    lines = text.lstrip().splitlines()
    if not lines:
        return False
    first = lines[0]
    return first.startswith("#") and run_date in first and not first.startswith(NOTICE_H1)


def weak_digest(first_line, roles, delivered_roles=None):
    """A digest that must never replace a real same-date one.

    Three shapes, and the third is the one an attacker found on 2026-08-27: weakness is
    RELATIVE, not absolute. A stale re-run whose `seen.db` predates the morning's marks
    re-emits only the boards that still answered -- 3 roles where the morning had 8 -- and
    an absolute `roles <= 0` test waves it through. The other five are already `sent` on
    origin, so `filter_new` drops them tomorrow too: they are never mailed, ever.

      * no roles at all (a same-day re-run once `filter_new` has drained `sent`);
      * `digest.py`'s render stub -- the most RECOVERABLE failure there is, because
        `run.py` zeroes `email_jobs` for it and nothing was marked sent;
      * FEWER roles than the receipt says today already delivered."""
    if int(roles) <= 0 or "could not be rendered" in str(first_line):
        return True
    return delivered_roles is not None and int(roles) < int(delivered_roles)


def _read_receipt(into, rev=None):
    """The receipt decides whether to bypass the cutoff, so it is read from ORIGIN for the
    same reason `digests/latest.md` is: a checkout-era copy let a three-day-old tree open
    the break-glass on a day that had already delivered (2026-08-27 attack). The worktree
    is the fallback, and an unreadable file is REPORTED -- it used to be silence on both
    sides at once (`deliver` defaulting to break-glass, `_receipt_alarms` to no alarm)."""
    raw = git_show(rev, LAST_DELIVERED, cwd=into) if rev else None
    if raw is None:
        try:
            with open(os.path.join(into, LAST_DELIVERED), "rb") as f:
                raw = f.read()
        except OSError:
            return {}
    try:
        rec = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        _log("warning", f"{LAST_DELIVERED} does not parse; treating this run as having no receipt")
        return {}
    if not isinstance(rec, dict):
        _log("warning", f"{LAST_DELIVERED} is not an object; treating this run as having no receipt")
        return {}
    if "roles" in rec:
        # `weak_digest` does int(prior). An unguarded int() here exits 1, fails the pipeline
        # step (which is not continue-on-error) and turns the whole day into a failure
        # notice -- the same blast radius `_env_int` was written to prevent one field over.
        try:
            rec["roles"] = int(rec["roles"])
        except (TypeError, ValueError):
            _log("warning", f"{LAST_DELIVERED} has roles={rec['roles']!r}, not a number; ignoring it")
            rec.pop("roles", None)
    return rec


def cutoff_overshoot(now_minutes, last_poll=None, margin=None):
    """Minutes by which a delivery started at `now_minutes` would overshoot the relay's
    last poll of the day, counting the margin the remaining steps need. Positive means the
    file would land after the last poller of the day has been and gone.

    It is NOT true that such a file "is never sent" -- the relay runs again tomorrow at
    06:17 and would find it. What is true is that tomorrow's own digest run pushes at
    ~06:10, before that poll, and `digests/latest.md` is a single-slot mailbox: the unread
    file is overwritten. Same outcome, honest reason. Minutes-of-day arithmetic, so a run
    at 20:00 overshoots by ten hours -- which is correct, not a wraparound bug."""
    try:
        hh, mm = (int(x) for x in str(last_poll or RELAY_LAST_POLL).split(":"))
    except ValueError:
        _log("warning", f"RELAY_LAST_POLL_UTC={RELAY_LAST_POLL!r} is not HH:MM; using 10:17")
        hh, mm = 10, 17
    margin = DELIVER_MARGIN_MIN if margin is None else margin
    return (now_minutes + margin) - (hh * 60 + mm)


def _carry_note(into, out_dir, run_date, roles):
    """How many of the deferred roles will actually reach the NEXT digest, counted -- not
    asserted. The old sentence promised the deferred roles would lead the next digest, and it
    was only half true, because `run.py` selected the mail on TWO clocks -- `get_matched_since(today - 1
    day)` on `first_seen` and `_posted_in` on `posted_date` -- over a window that moved
    daily, so a role could fall out on either. The first version of this note counted only
    `first_seen` and reported "20 of 20 lead the next digest" on a day when none of them did.

    **The `roles` lane made that call on 2026-08-27 (BACKLOG 309/310): `first_seen` now gates
    nothing and the mail is selected over every live role by `posted_date` alone.** So the
    count below drops its `first_seen` term -- keeping it would under-report every deferred
    role first seen before today, which is most of them, and would be the same class of
    confidently wrong number in the other direction."""
    try:
        with open(os.path.join(into, out_dir, f"digest-{run_date}.json"), encoding="utf-8") as f:
            jobs = json.load(f).get("jobs") or []
        seen = [(str(j.get("first_seen") or "")[:10], str(j.get("posted_date") or "")[:10])
                for j in jobs if isinstance(j, dict)]
    except (OSError, ValueError, AttributeError):
        return f", and {roles} role(s) are unmarked (payload unreadable: carry-over unknown)"
    if not seen:
        return f", and {roles} role(s) are unmarked (no jobs in the payload: carry-over unknown)"
    # Tomorrow's cutoff is TODAY, and since 2026-08-27 a dated role has to clear exactly ONE
    # test to be mailed then: `_posted_in` on its own `posted_date`. `run.py` selects from
    # every live role, so `first_seen` no longer removes anything. `_posted_in` still has a
    # second branch (an undated role at a company we have history for) that depends on
    # `seen_before`, which is not in this payload -- those are reported as AT RISK rather
    # than guessed either way.
    ok = sum(1 for _fs, pd in seen if len(pd) == 10 and pd >= run_date)
    stale = sum(1 for _fs, pd in seen if len(pd) == 10 and pd < run_date)
    undated = len(seen) - ok - stale
    note = f", so {ok} of {len(seen)} role(s) still meet tomorrow's window on their own dates"
    if stale:
        note += f"; {stale} carry an older `posted_date` and will not"
    if undated:
        note += (f"; {undated} undated, which reach it only through `_posted_in`'s `first_seen`"
                 f" fallback at a company we already have history for")
    return note


def deliver(a):
    """Copy the run's digest to `digests/latest.md` -- or refuse, and say why."""
    run_date = a.date or dt.datetime.now(dt.timezone.utc).date().isoformat()
    into = a.into or ROOT
    src = os.path.join(into, a.out, f"digest-{run_date}.md")
    if not os.path.exists(src):
        # a green run with no digest file (a dispatch straddling UTC midnight) would
        # otherwise be a silent day: no mail, no notice. Unchanged from the shell block.
        _log("error", f"pipeline exited 0 but wrote no {a.out}/digest-{run_date}.md")
        return 1
    with open(src, "rb") as f:
        body = f.read()
    lines = body.decode("utf-8", "replace").lstrip().splitlines()
    first = lines[0] if lines else ""
    roles = 0
    try:
        with open(os.path.join(into, a.out, f"digest-{run_date}.json"), encoding="utf-8") as f:
            jobs = json.load(f).get("jobs")
        roles = len(jobs) if isinstance(jobs, list) else 0
    except (OSError, ValueError, AttributeError):
        pass

    # ORIGIN, never the checkout. `actions/checkout` resolves `github.sha` when the RUN is
    # created, not when the runner starts, so a queued or re-dispatched job can hold a tree
    # that predates today's own digest and would overwrite it while believing it was first.
    branch = a.branch or os.environ.get("GITHUB_REF_NAME") or "master"
    whence, trusted = f"origin/{branch}", True
    if not a.no_fetch and not git_ok("fetch", "origin", branch, cwd=into):
        # NOT a discarded bool. `actions/checkout` leaves refs/remotes/origin/<branch> at
        # the run-creation sha, so a failed fetch makes `git show origin/...` succeed while
        # returning exactly the stale view this function exists to distrust -- and the log
        # line still said "origin". An attacker reproduced an empty digest replacing the
        # morning's mail through that one unchecked return value (2026-08-27).
        trusted = False
        whence = f"STALE origin/{branch} (fetch failed)"
        _log("error", f"could not fetch origin/{branch}; the delivery guard is reading a "
                      f"possibly stale ref and will refuse anything it cannot prove is safe")
    rev = f"origin/{branch}"
    cur = git_show(rev, "digests/latest.md", cwd=into)
    if cur is None:                       # a rehearsal repo, or no origin at all
        whence, rev = "worktree", None
        try:
            with open(os.path.join(into, "digests", "latest.md"), "rb") as f:
                cur = f.read()
        except OSError:
            cur = b""
    # untrusted read -> assume origin MAY already carry today's digest, so a weak candidate
    # is refused. The safe direction is always "do not destroy".
    on_origin = digest_delivered(cur[:400], run_date) or not trusted

    rec = _read_receipt(into, rev)
    try:
        stale = (dt.date.fromisoformat(run_date) - dt.date.fromisoformat(str(rec.get("date")))).days
    except (TypeError, ValueError):
        stale = None
    if stale is not None and stale < 0:
        # a receipt dated in the FUTURE (an operator `--date`, clock skew) would otherwise
        # hold the cutoff shut for ever while `_receipt_alarms` stayed silent about it:
        # silent, total, indefinite mail loss. Treat it as no receipt, and say so.
        _log("warning", f"{LAST_DELIVERED} is dated {rec.get('date')}, {-stale}d in the FUTURE "
                        f"of this run -- ignoring it rather than deferring every day")
        stale = None
    prior = rec.get("roles") if str(rec.get("date")) == run_date else None
    now = dt.datetime.now(dt.timezone.utc)
    over = cutoff_overshoot(now.hour * 60 + now.minute)
    # BREAK GLASS. A cutoff that fires every day would defer for ever, and the alarm for
    # that lives in `run.py::_receipt_alarms` -- i.e. in the mail it is deferring. After two
    # mornings with no mail, a late mail beats another day of silence. No receipt at all
    # (a fresh checkout, or the first run after this shipped) counts as broken glass: never
    # defer a day's mail on the strength of a file that has never existed.
    glass = stale is None or stale >= 2

    verdict, weak_ok = None, True
    # The candidate is checked FIRST and unconditionally. `weak_digest` only ever ran behind
    # `on_origin`, which is False on a normal morning (origin carries YESTERDAY's digest) --
    # so on the one run that actually mails, `deliver` validated nothing at all. A zero-byte
    # file, a body-less heading, or yesterday's digest re-copied under today's name all
    # sailed through (2026-08-27 wave-4 attacker). `digest_delivered` is the same predicate
    # used to recognise a delivered digest on origin: it must start with `#`, carry THIS
    # run's date, and not be a `# no digest` notice.
    rest = [x for x in lines[1:] if x.strip()]
    if not digest_delivered(body[:400], run_date) or not rest:
        _log("error", f"{a.out}/digest-{run_date}.md is not a digest for {run_date} "
                      f"(first line {first[:80]!r}, {len(rest)} further non-blank line(s), "
                      f"{len(body)} bytes) -- refusing to publish it "
                      f"as the mail; the run produced something the renderer should not have")
        return 1
    if on_origin and weak_digest(first, roles, prior):
        why = (f"{roles} role(s)" + ("; render stub" if "could not be rendered" in first else "")
               + (f"; origin's receipt says {prior} were already delivered today"
                  if prior is not None and int(roles) < int(prior) else ""))
        verdict = (f"{'origin already carries' if trusted else 'origin MAY already carry'} a "
                   f"digest for {run_date} and this one is weaker ({why}) -- a thinner mail "
                   f"must never replace a delivered one")
        # NOT a benign no-op. This run produced something worse than what is already
        # delivered, and `publish` is gated only on the pipeline step succeeding -- so an
        # exit 0 here ships that same thin run's board to the public repo while origin keeps
        # the fat digest. Only the cutoff DEFERRAL is a quiet exit 0.
        weak_ok = False
    elif over > 0 and not a.ignore_cutoff and not glass:
        verdict = (f"{over} min past the relay's last poll ({RELAY_LAST_POLL} UTC less a "
                   f"{DELIVER_MARGIN_MIN} min margin) -- nothing is marked sent"
                   + _carry_note(into, a.out, run_date, roles))

    if verdict:
        # Neither `digests/latest.md` NOR `DIGEST_JSON`. The existing `mark_sent` step is
        # already guarded on DIGEST_JSON being non-empty, so withholding it is exactly what
        # keeps the roles unmarked -- and `build_notice` already prints the right sentence.
        _log("warning", f"digest for {run_date} NOT delivered: {verdict}")
        # Leave the worktree's copy IDENTICAL to origin's. The persist step still owns
        # `digests/latest.md`, and on a push conflict `merge_conflicted` rebuilds every
        # owned path -- `s_ours` would push this run's checkout-era bytes over origin's
        # newer digest, with the warning suppressed because the path is SINGLE_WRITER.
        # Making ours == theirs takes the `if o == t: continue` branch instead.
        # `cur is not None`, not `cur`: origin's file being EMPTY is exactly when leaving
        # this run's checkout-era bytes in place is worst, because the persist step then
        # pushes them over origin under `s_ours`.
        if rev is not None and cur is not None:
            try:
                _write_bytes(os.path.join(into, "digests", "latest.md"), cur)
            except OSError as e:  # noqa: BLE001 -- a refusal must not become a crash
                _log("warning", f"could not re-sync digests/latest.md with origin: {e}")
        print(f"deliver: refused ({whence}); receipt is "
              f"{'absent' if stale is None else str(stale) + 'd old'}", flush=True)
        if not weak_ok:
            # A refusal we could not JUSTIFY is a different animal from one we could. When
            # the fetch failed we refused on suspicion, and returning 0 there makes a green
            # run that mails nothing and writes no notice -- silence, which is the whole
            # failure class this session is about. Exit 1 so `outcome` writes the dated
            # notice and the relay mails THAT.
            return 1
        return 0

    bits = ["replaces today's own digest" if on_origin else "first delivery for the day"]
    if over > 0:
        bits.append("%s %d min past the %s cutoff (%s)"
                    % ("operator override" if not glass else "break-glass", over, RELAY_LAST_POLL,
                       "no receipt yet" if stale is None else "%dd since the last delivery" % stale))
    reason = "; ".join(bits)
    if a.dry_run:
        print(f"deliver: WOULD deliver {run_date} ({roles} role(s), {reason}); "
              f"origin read from {whence}", flush=True)
        return 0
    _write_bytes(os.path.join(into, "digests", "latest.md"), body)
    # `past_cutoff` is what stops break-glass silencing its own alarm. A write made after
    # the relay's last poll is very likely never mailed (tomorrow's run overwrites it before
    # tomorrow's first poll), but it still stamps today's date on the receipt -- so the next
    # day reads `age = 1`, goes quiet, and a chronically-late pipeline alternates
    # defer / break-glass / defer for ever at zero mail with nothing saying so. Two
    # attackers found the same loop independently (2026-08-27).
    receipt = {"date": run_date, "sha256": digest_sha(body), "past_cutoff": over > 0,
               "roles": roles, "first_line": first[:200], "reason": reason,
               "run_url": os.environ.get("RUN_URL", ""),
               "written_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    _write_bytes(os.path.join(into, LAST_DELIVERED), _dumps(receipt))
    # DIGEST_JSON is what lets the `mark_sent` step burn these roles, and it is exported
    # ONLY inside the relay's window. Break-glass and an operator override still WRITE the
    # file -- a poll may yet find it, and the operator can see it on origin -- but they
    # never mark: a digest written after the last poll is overwritten by tomorrow's run
    # before tomorrow's first poll, so marking it sent would burn roles that were never
    # mailed. A role emailed twice is this repo's stated preference over one withheld.
    env = os.environ.get("GITHUB_ENV")
    if over > 0:
        _log("warning", f"delivered past the cutoff, so nothing is marked sent: these "
                        f"{roles} role(s) may be re-offered tomorrow rather than lost")
    elif env:
        with open(env, "a", encoding="utf-8") as f:
            f.write(f"DIGEST_JSON={a.out}/digest-{run_date}.json\n")
    print(f"deliver: {run_date} delivered -- {roles} role(s), sha "
          f"{receipt['sha256'][:12]}, {reason} (origin read from {whence})", flush=True)
    return 0


def outcome(a):
    # UTC, like `deliver` and `pipeline.run`: this date is compared against the H1 of
    # digests/latest.md, and a local clock is a different one on the operator's machine.
    run_date = a.date or dt.datetime.now(dt.timezone.utc).date().isoformat()
    try:
        steps = json.loads(os.environ.get("STEPS_JSON") or "{}")
        if not isinstance(steps, dict):
            steps = {}
    except ValueError:
        _log("warning", "STEPS_JSON is not JSON; outcomes unknown")
        steps = {}
    job_status = os.environ.get("JOB_STATUS", "")
    run_url = os.environ.get("RUN_URL", "")
    crash = None
    cpath = os.path.join(ROOT, "out", "crash.json")
    if os.path.exists(cpath):
        try:
            crash = json.load(open(cpath, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            crash = {"exc_type": "unreadable crash.json"}
    digest_built, digest_new = False, 0
    dpath = os.path.join(ROOT, "out", f"digest-{run_date}.json")
    if os.path.exists(dpath):
        digest_built = True
        try:
            digest_new = len(json.load(open(dpath, encoding="utf-8")).get("jobs", []))
        except Exception:  # noqa: BLE001
            pass
    last = build_last_run(steps, job_status, run_url, run_date)
    healthy = (job_status or "").lower() == "success" and not last["failed_steps"]
    if healthy:
        print(f"persist_state: run {run_date} healthy; nothing to report", flush=True)
        return 0
    into = a.into
    branch = a.branch or os.environ.get("GITHUB_REF_NAME") or "master"
    _identity(a.as_name)
    if a.commit:
        into = os.path.join(tempfile.gettempdir(), "persist-outcome")
        shutil.rmtree(into, ignore_errors=True)
        git_ok("worktree", "prune", cwd=ROOT)
        git("fetch", "origin", branch, cwd=ROOT)
    try:
        if a.commit:
            git("worktree", "add", "-q", into, f"origin/{branch}", cwd=ROOT)
        # DELIVERY decides, not step outcomes: a persist step that pushed the digest and
        # then exited 1 over one refused file, or a red gate with persist `if: always()`,
        # leaves today's digest on origin -- a notice would overwrite a delivered mail and
        # lie about it (wave-1 attacker, 2026-08-25). If origin's latest.md IS today's
        # digest, the red step is tomorrow's line, never a notice.
        # origin already carries a digest for today (this run's, or an earlier run's
        # the same day -- a re-run's fresh runner has no out/): never replace it. The
        # same predicate `deliver` refuses a weaker replacement with, so a change to
        # one can never leave the other behind.
        try:
            with open(os.path.join(into, "digests", "latest.md"), "rb") as f:
                delivered = digest_delivered(f.read(400), run_date)
        except OSError:
            delivered = False
        warranted = notice_warranted(steps, job_status) and not delivered
        last["notice"] = warranted
        last["delivered"] = delivered
        marked = isinstance(steps.get("mark_sent"), dict) and steps["mark_sent"].get("outcome") == "success" \
            and digest_built and digest_new > 0
        notice = build_notice(steps, job_status, crash, _stamps_line(), run_url, run_date,
                              digest_built, digest_new, marked_sent=marked) if warranted else None
        os.makedirs(os.path.join(into, "cloud_state"), exist_ok=True)
        _write_bytes(os.path.join(into, "cloud_state", "last_run.json"), _dumps(last))
        wrote = ["cloud_state/last_run.json"]
        if notice:
            os.makedirs(os.path.join(into, "digests"), exist_ok=True)
            _write_bytes(os.path.join(into, "digests", "latest.md"), notice.encode("utf-8"))
            wrote.append("digests/latest.md")
        print(f"persist_state: wrote {', '.join(wrote)} (status {last['status']}, failed {last['failed_steps']}"
              f"{', digest delivered' if delivered else ''})", flush=True)
        if not a.commit:
            return 0
        git("add", "--", *wrote, cwd=into)
        if not git("status", "--porcelain", "--", *wrote, cwd=into).strip():
            print("persist_state: outcome already recorded on origin", flush=True)
            return 0
        _commit(into, a.as_name, f"run outcome {run_date}: {last['status']} [skip ci]")
        for i in range(1, 4):
            if git_ok("pull", "--rebase", "origin", branch, cwd=into) and git_ok("push", "origin", f"HEAD:{branch}", cwd=into):
                print("persist_state: outcome pushed", flush=True)
                return 0
            git_ok("rebase", "--abort", cwd=into)
            time.sleep(i * a.sleep)
        _log("error", "could not push the run outcome")
        return 1
    finally:
        if a.commit:
            git_ok("worktree", "remove", "--force", into, cwd=ROOT)


# ---------------------------------------------------------------- cli
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("commit", help="stage the owned paths, commit, push; merge per file on a conflict")
    c.add_argument("--as", dest="as_name", required=True, help="commit author (bot name)")
    c.add_argument("-m", "--message", required=True)
    c.add_argument("--own", nargs="+", required=True, help="paths this job owns (dirs expand)")
    c.add_argument("--branch")
    c.add_argument("--retries", type=int, default=5)
    c.add_argument("--sleep", type=float, default=15.0, help="seconds, times the attempt number")
    c.add_argument("--gate", default=f'"{sys.executable}" check_invariants.py',
                   help="command run when companies.csv is owned; '' disables")
    c.add_argument("--cwd", help=argparse.SUPPRESS)
    o = sub.add_parser("outcome", help="record the run's outcome; a failure notice reaches the mail")
    o.add_argument("--commit", action="store_true", help="commit the two files alone from a fresh worktree")
    o.add_argument("--into", default=ROOT, help="where to write when not committing")
    o.add_argument("--as", dest="as_name", default="github-actions[bot]")
    o.add_argument("--branch")
    o.add_argument("--date")
    o.add_argument("--sleep", type=float, default=10.0)
    d = sub.add_parser("deliver", help="the digest -> digests/latest.md, or refuse and say why")
    d.add_argument("--date", help="run-date label (YYYY-MM-DD); default today UTC")
    d.add_argument("--out", default="out", help="where pipeline.run wrote digest-<date>.md")
    d.add_argument("--into", default=ROOT, help=argparse.SUPPRESS)
    d.add_argument("--branch")
    d.add_argument("--dry-run", action="store_true", help="print the verdict, write nothing")
    d.add_argument("--no-fetch", action="store_true", help=argparse.SUPPRESS)
    d.add_argument("--ignore-cutoff", action="store_true",
                   help="deliver even past the relay's last poll (an operator re-run)")
    m = sub.add_parser("merge-file", help="apply one strategy to three files (repro/debug)")
    m.add_argument("strategy", help="a path from `table`, e.g. cloud_state/pipeline_stages.json")
    m.add_argument("base"); m.add_argument("ours"); m.add_argument("theirs"); m.add_argument("out")
    sub.add_parser("table", help="print the strategy table")
    a = ap.parse_args(argv)
    if a.cmd == "commit":
        return commit(a)
    if a.cmd == "outcome":
        return outcome(a)
    if a.cmd == "deliver":
        return deliver(a)
    if a.cmd == "table":
        table()
        return 0
    strat, why = strategy_for(a.strategy)
    rd = lambda p: open(p, "rb").read() if os.path.exists(p) else None  # noqa: E731
    merged = strat(rd(a.base), rd(a.ours), rd(a.theirs))
    if merged is not None:
        _write_bytes(a.out, merged)
    print(f"{a.strategy}: {why} -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
