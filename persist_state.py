#!/usr/bin/env python3
"""The one path every workflow uses to commit state back to the repo (lane: infra).

    python persist_state.py commit --as NAME -m MSG --own PATH... [--branch B]
    python persist_state.py outcome [--commit]        # the run's verdict on itself (daily-digest)
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


def s_ours(base, ours, theirs):
    """Single cloud writer: the run's own bytes win; absent in ours -> keep theirs."""
    return ours if ours is not None else theirs


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
    "cloud_state/health_baseline.json": (s_company_dict, "digest + self-heal; per company"),
    "cloud_state/stale.json": (s_company_dict, "digest + self-heal's Monday sweep; per company"),
    "cloud_state/scan_seen.json": (s_company_dict, "digest + Sunday audit; per company"),
    "cloud_state/auto_expand_seen.json": (s_company_dict, "auto-expand's rotation key; per company name"),
    "cloud_state/pipeline_stages.json": (s_stage_stamps, "per stage key, newer finished_at wins, never deleted"),
    "discovered_cache.json": (_keyed_list(_job_key), "list keyed (company, title); two discovery writers"),
    "research_companies.json": (_keyed_list(_name_key), "list keyed name; two discovery writers"),
}
SINGLE_WRITER = {   # documented `ours` paths (one cloud writer each); anything else warns
    "cloud_state/seen.db": "daily-digest", "cloud_state/roles.jsonl": "daily-digest",
    "cloud_state/roles_text.jsonl": "daily-digest",
    "cloud_state/source_health.json": "daily-digest", "cloud_state/telegram_seen.json": "daily-digest",
    "cloud_state/candidate_probe.json": "daily-digest", "cloud_state/registry_census.json": "daily-digest",
    "cloud_state/registry_alarms.json": "daily-digest", "cloud_state/last_run.json": "daily-digest",
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
                _log("warning", f"{len(gone)} tracked file(s) under {p} vanished this run -- restored from HEAD, "
                                f"not deleted: {gone[:5]}")
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
                        " — nothing was marked sent, so those roles lead the next digest"))
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


def outcome(a):
    run_date = a.date or dt.date.today().isoformat()
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
        delivered = False
        lp = os.path.join(into, "digests", "latest.md")
        try:
            head = open(lp, "rb").read(300).decode("utf-8", "replace")
            # origin already carries a digest for today (this run's, or an earlier run's
            # the same day -- a re-run's fresh runner has no out/): never replace it
            delivered = head.lstrip().startswith("#") and run_date in head.lstrip().splitlines()[0] \
                and not head.lstrip().startswith("# ⚠️ No digest")
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
    m = sub.add_parser("merge-file", help="apply one strategy to three files (repro/debug)")
    m.add_argument("strategy", help="a path from `table`, e.g. cloud_state/pipeline_stages.json")
    m.add_argument("base"); m.add_argument("ours"); m.add_argument("theirs"); m.add_argument("out")
    sub.add_parser("table", help="print the strategy table")
    a = ap.parse_args(argv)
    if a.cmd == "commit":
        return commit(a)
    if a.cmd == "outcome":
        return outcome(a)
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
