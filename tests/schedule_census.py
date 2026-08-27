#!/usr/bin/env python3
"""Did every cron actually fire? Read-only census of scheduled dispatches (lane: infra).

A lane harness, beside `tests/rehearse_infra.py`, not a pipeline module: nothing runs it
on a schedule and it answers one question for one lane. It reaches the network (`gh run
list`) and writes nothing.

    python tests/schedule_census.py                 # the last 7 days, this repo
    python tests/schedule_census.py --days 21       # a longer window
    python tests/schedule_census.py --repo AnalystJobsIL/inbox --days 7

WHY THIS EXISTS (2026-08-27). The 05:00 digest was not dispatched, nor were the 02:30,
06:00 and 08:00 crons; the 00:00 refresh arrived at 05:41. No board, no email, and no
alarm anywhere, because every "the run broke" path in this repo fires from INSIDE a later
digest. GitHub documents the cause -- scheduled events are delayed under load and "if the
load is sufficiently high enough, some queued jobs may be dropped" -- so this is not a bug
here and cannot be fixed here.

What CAN be decided here is whether a second, offset digest cron would help, and that is a
measurement, not an opinion. A recovery cron only pays if drops are INDEPENDENT: if slot A
being dropped tells you nothing about slot B. On 2026-08-27 four consecutive slots spanning
eight hours were dropped together, in two different repositories, and across the whole of
2026-08-23..08-26 every one of 33 due dispatches fired. So at the time of writing the
answer was: **zero isolated drops, therefore no recovery cron.**

The re-measurement is pre-committed in HANDOFF.md rather than left to the next bad morning:

    >= 3 isolated single-slot drops in the window  =>  build the recovery cron.
    Otherwise it stays rejected.

An "isolated drop" is a day on which exactly one due slot did not fire and at least one
other did. That is the shape a second slot can rescue; a day where everything is dropped
is not, because the recovery cron is served by the same scheduler.

A slot only counts as due from the moment its cron string reached the default branch
(`cron_since`), because the first draft of this tool reported FOUR isolated drops -- every
one of them `firmographics 10:00` on days before that workflow existed -- and would have
answered its own pre-committed question with an artefact. A cron is not missed on a day it
did not yet exist.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REPO = "AnalystJobsIL/pipeline"


def workflow_slots(root=ROOT):
    """{workflow stem: [(minute-of-day, weekday or None, cron string), ...]}.

    Only the shapes this repo actually uses are expanded: a literal or comma list of hours,
    a literal minute, and `* * D` for the Sunday audit. Anything else is reported and
    skipped rather than silently scored as never-firing."""
    out, skipped = {}, []
    for path in sorted(glob.glob(os.path.join(root, ".github", "workflows", "*.yml"))):
        stem = os.path.basename(path)[:-4]
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for m in re.finditer(r'^\s*-\s*cron:\s*["\']([^"\']+)["\']', text, re.M):
            cron = " ".join(m.group(1).split())
            parts = cron.split()
            if len(parts) != 5 or not re.fullmatch(r"\d+", parts[0]) \
                    or not re.fullmatch(r"[\d,]+", parts[1]) or parts[2] != "*" or parts[3] != "*":
                skipped.append((stem, cron))
                continue
            dow = None if parts[4] == "*" else (int(parts[4]) % 7 if parts[4].isdigit() else None)
            if parts[4] != "*" and dow is None:
                skipped.append((stem, cron))
                continue
            for hh in parts[1].split(","):
                out.setdefault(stem, []).append((int(hh) * 60 + int(parts[0]), dow, cron))
    for stem in out:
        out[stem].sort()
    return out, skipped


def cron_since(stem, cron, root=ROOT):
    """When this exact cron string first appeared in this workflow on the current branch,
    as a UTC datetime -- or None when git cannot say.

    Without this the census scores a workflow against days it did not exist: the first
    draft reported four `firmographics 10:00` drops for 2026-08-22..08-26, when the file
    landed on 08-26 at 19:50 UTC and its first real slot was 10:00 the next morning. Same
    for `scrape-refresh`, whose cron was Mon/Thu before it became daily. Walking newest to
    oldest and stopping at the first commit WITHOUT the string finds the most recent
    introduction, which is the one the runs in the window were served from."""
    path = ".github/workflows/%s.yml" % stem
    p = subprocess.run(["git", "log", "--format=%H %cI", "--", path],
                       cwd=root, capture_output=True)
    if p.returncode != 0:
        return None
    found = None
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        sha, _, when = line.partition(" ")
        blob = subprocess.run(["git", "show", "%s:%s" % (sha, path)], cwd=root, capture_output=True)
        if blob.returncode != 0 or cron not in " ".join(blob.stdout.decode("utf-8", "replace").split()):
            break
        found = when.strip()
    if not found:
        return None
    return dt.datetime.fromisoformat(found).astimezone(dt.timezone.utc)


def fetch_runs(repo, limit=1000):
    """[(datetime UTC, workflow display name)] for every `schedule` run `gh` will give us."""
    p = subprocess.run(["gh", "run", "list", "--repo", repo, "--limit", str(limit),
                        "--json", "name,event,createdAt,workflowName"],
                       capture_output=True)
    if p.returncode != 0:
        raise SystemExit("gh run list failed: " + p.stderr.decode("utf-8", "replace").strip()[:300])
    rows = json.loads(p.stdout.decode("utf-8", "replace") or "[]")
    out = []
    for r in rows:
        if r.get("event") != "schedule":
            continue
        when = dt.datetime.strptime(r["createdAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        out.append((when, r.get("workflowName") or r.get("name") or ""))
    return sorted(out)


def name_index(root=ROOT):
    """{workflow display name: file stem} -- `gh` reports the `name:` field, not the file."""
    idx = {}
    for path in sorted(glob.glob(os.path.join(root, ".github", "workflows", "*.yml"))):
        with open(path, encoding="utf-8") as f:
            m = re.search(r'^name:\s*(.+?)\s*$', f.read(), re.M)
        if m:
            idx[m.group(1).strip().strip('"\'')] = os.path.basename(path)[:-4]
    return idx


def census(runs, slots, days, now, grace_min, since=None):
    """One row per (day, workflow, slot): fired with its lag, dropped, or still pending.

    `since` is {(stem, cron): datetime} from `cron_since`. A slot earlier than its cron's
    arrival on the branch is not counted at all -- without that, the first draft of this
    tool answered its own pre-committed question with four drops of a workflow that did
    not exist yet."""
    since = since or {}
    by_wf = collections.defaultdict(list)
    for when, stem in runs:
        by_wf[stem].append(when)
    rows = []
    start = (now - dt.timedelta(days=days - 1)).date()
    for stem, wf_slots in sorted(slots.items()):
        pool = sorted(by_wf.get(stem, []))
        for n in range(days):
            day = start + dt.timedelta(days=n)
            for minute, dow, cron in wf_slots:
                if dow is not None and day.weekday() != (6 if dow == 0 else dow - 1):
                    continue                       # cron 0=Sunday; weekday() 6=Sunday
                due = dt.datetime.combine(day, dt.time(minute // 60, minute % 60), dt.timezone.utc)
                if due > now:
                    continue
                born = since.get((stem, cron))
                if born is None:
                    continue               # undatable: see the warning in main(). NEVER score
                if due < born:
                    continue               # the cron did not exist yet: not a missed dispatch
                hit = next((w for w in pool if w >= due), None)
                # a run belongs to the LAST slot it is after, so 22:53 is auto-expand's
                # 20:00 and not a five-hour-late 08:00
                nxt = [d for d in (dt.datetime.combine(day, dt.time(m // 60, m % 60), dt.timezone.utc)
                                   for m, _, _ in wf_slots) if d > due]
                nxt = min(nxt) if nxt else due + dt.timedelta(days=1)
                if hit is not None and hit < nxt:
                    pool.remove(hit)
                    rows.append((day, stem, due, "fired", int((hit - due).total_seconds() // 60)))
                elif (now - due).total_seconds() / 60 < grace_min:
                    rows.append((day, stem, due, "pending", None))
                else:
                    rows.append((day, stem, due, "dropped", None))
    return sorted(rows)


def report(rows, grace_min):
    per_day = collections.defaultdict(list)
    for day, stem, due, state, lag in rows:
        per_day[day].append((stem, due, state, lag))
    isolated, total_due, total_fired = 0, 0, 0
    print(f"{'day':12} {'due':>4} {'fired':>6} {'dropped':>8} {'pending':>8}   worst lag")
    for day in sorted(per_day):
        items = per_day[day]
        fired = [i for i in items if i[2] == "fired"]
        dropped = [i for i in items if i[2] == "dropped"]
        pending = [i for i in items if i[2] == "pending"]
        due = len(fired) + len(dropped)
        total_due += due
        total_fired += len(fired)
        worst = max((i[3] for i in fired), default=None)
        if len(dropped) == 1 and fired:
            isolated += 1
        print(f"{day.isoformat():12} {due:>4} {len(fired):>6} {len(dropped):>8} {len(pending):>8}   "
              + (f"+{worst} min ({max(fired, key=lambda i: i[3])[0]})" if worst is not None else "-"))
        for stem, dueat, state, _lag in dropped:
            print(f"{'':12}   dropped: {stem} {dueat.strftime('%H:%M')}")
    print()
    print(f"due {total_due} · fired {total_fired} · dropped {total_due - total_fired}"
          f" · grace {grace_min} min (a slot younger than this is 'pending', not dropped)")
    print(f"ISOLATED SINGLE-SLOT DROPS: {isolated}")
    print("  >= 3 => build the recovery digest cron (HANDOFF morning check, due 2026-09-10).")
    print("  Otherwise it stays rejected: a second cron in the same repo has no measured")
    print("  independence from the first, so it would not have caught 2026-08-27.")
    return isolated


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--grace", type=int, default=180,
                    help="minutes after a slot before a missing run counts as dropped "
                         "(default 180 -- three times the worst lag observed on a good day)")
    a = ap.parse_args(argv)
    slots, skipped = workflow_slots()
    for stem, cron in skipped:
        print(f"::warning::schedule_census: {stem} cron `{cron}` is a shape this tool does "
              f"not expand; it is NOT counted", flush=True)
    since = {}
    for stem, wf_slots in slots.items():
        for _, _, cron in wf_slots:
            since.setdefault((stem, cron), cron_since(stem, cron))
    idx = name_index()
    runs = [(when, idx.get(name, name)) for when, name in fetch_runs(a.repo)]
    now = dt.datetime.now(dt.timezone.utc)
    print(f"# scheduled dispatches, {a.repo}, last {a.days} days (now {now:%Y-%m-%dT%H:%MZ})")
    print("# a slot counts as due only from the moment its cron reached the branch")
    for (stem, cron), born in sorted(since.items()):
        if born is None:
            print(f"::warning::schedule_census: {stem} `{cron}` is not in git history (an "
                  f"uncommitted draft?) -- SKIPPED ENTIRELY, not scored. Scoring it would "
                  f"count every slot since the window opened as a drop, and drops are what "
                  f"this tool is asked to decide on.")
        elif born > now - dt.timedelta(days=a.days):
            print(f"# {stem} `{cron}` reached the branch {born:%Y-%m-%dT%H:%MZ}; "
                  f"earlier slots are not counted")
    print()
    report(census(runs, slots, a.days, now, a.grace, since), a.grace)
    return 0


if __name__ == "__main__":
    sys.exit(main())
