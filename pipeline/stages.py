"""Explicit ordering contract between the nightly stages.

The pipeline's order is real but IMPLICIT — it depends on cron spacing and nothing verifies
it. The intended sequence is:

    1  repair    19:00  repair_dead_urls -> repair_extract_gap -> listing_hunt -> crack_walled
    2  collect   00:00  refresh_scrape_cache   (needs stage 1: fixed URLs)
    2  collect   05:00  discovery_daily / discovery_telegram
    3  expand    08:00  auto_expand            (new companies -> tomorrow's stage 1)
    4  firmo     10:00  research_firmographics (company facts for rows the registry added)
    4  enrich    05:00  enrich_scrape_jd       (JD text for every relevant role, any age)
    5  publish   05:00  pipeline.run           (classify -> email 48h -> board -> archive)

If stage 1 overruns its timeout or dies, stage 2 still runs on stale URLs and reports
success — which is how crack_walled sat NameError-dead for weeks behind continue-on-error.
Each stage stamps what it finished and how much it did; the next stage reads the stamp and
says so loudly when its prerequisite did not run today.

This deliberately does NOT block. A missing prerequisite means degraded input, not a reason
to skip the email — but it must be VISIBLE, so the digest surfaces it in its audit block.
"""
from __future__ import annotations

import datetime as dt
import json
import os

PATH = os.path.join(os.path.dirname(__file__), "..", "cloud_state", "pipeline_stages.json")

# `summary()` renders ORDER and nothing else, so a stage absent from this list is stamped to
# disk and read by nobody. On 2026-08-31 `pipeline_stages.json` carried TEN stamps and this
# list named eight: `queue` (the registry's, `owed`) and `intel` (company-intel's, carrying
# `backlog`/`blurbs`/`board`/`researched`) were both written nightly and rendered nowhere --
# so two of the four queues the operator wants named in the daily mail were invisible in the
# one place a human reads every day. Adding a stage here is the ONLY thing that puts its
# number in front of somebody. `queue`'s headline is `owed`: the count the drain would
# actually select, never the raw unsettled total (that was wrong by 3x -- section 3).
#
# Written by `registry` (2026-08-31), which owns neither this file nor the `intel` stamp:
# shared plumbing, changed loudly rather than filed, because a filed one-line diff is what
# `468` proved does not get applied.
#
# `wayback` (infra, 2026-09-04): `archive_evidence.py` on jd-archive.yml at 12:30 -- what it
# submitted to Save Page Now, what was refused, and the backlog. Its stamp is a day old at
# every 05:00 digest by construction; `run.py` alarms at two.
ORDER = ["repair", "collect", "expand", "firmo", "intel", "enrich", "wayback", "queue",
         "publish", "ci", "cron"]


def _load() -> dict:
    try:
        with open(PATH, encoding="utf-8-sig") as f:      # -sig: a BOM is not corruption
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _unreadable() -> str:
    """Why the stamp file cannot be read, or '' when it is absent or parses (BACKLOG 451).

    `_load()` answers `{}` for a missing file AND for a half-written or corrupt one, and a
    stamp over that `{}` used to rewrite the file holding only the new key -- every other
    workflow's night erased, and the next mail saying `collect never ran` about crons that
    ran. Readers may degrade to `{}`; a WRITER must not."""
    if not os.path.exists(PATH) or os.path.getsize(PATH) == 0:
        return ""                                        # absent or empty: nothing to erase
    try:
        with open(PATH, encoding="utf-8-sig") as f:
            return "" if isinstance(json.load(f), dict) else "not a JSON object"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {str(e)[:80]}"


def stamp(stage: str, **detail) -> bool:
    """Record that `stage` completed, with whatever counts the caller wants to keep.
    Returns False (and says why) when the file exists and cannot be read -- a writer never
    rebases on `{}`."""
    why = _unreadable()
    if why:
        print(f"::warning::stages: NOT stamping '{stage}' -- {PATH} exists and did not parse "
              f"({why}); writing would erase every other stage's stamp (BACKLOG 451)", flush=True)
        return False
    data = _load()
    data[stage] = {"finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "date": dt.date.today().isoformat(), **detail}
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, PATH)
    return True


def age_days(stage: str):
    """Days since `stage` last completed, or None if it never has."""
    e = _load().get(stage)
    if not e or not e.get("date"):
        return None
    try:
        return (dt.date.today() - dt.date.fromisoformat(e["date"])).days
    except Exception:  # noqa: BLE001
        return None


def require(stage: str, max_age_days: int = 1) -> bool:
    """Warn (never raise) when a prerequisite has not run recently. Returns True if fresh."""
    age = age_days(stage)
    if age is None:
        print(f"::warning::stage '{stage}' has NEVER completed — this run's input is "
              f"whatever was last committed, not fresh output of that stage", flush=True)
        return False
    if age > max_age_days:
        print(f"::warning::stage '{stage}' last completed {age}d ago (expected <= "
              f"{max_age_days}d) — proceeding on stale input", flush=True)
        return False
    return True


def alarms(stage: str = "collect", max_age_days: int = 0) -> list:
    """What the digest must SAY about a stage: it did not run within `max_age_days`, or it
    stamped an `alarm`. `require()` only warns when a stage is older than a day, so a refresh
    that crashed last night (stamp dated yesterday) and a mass-failure night (stamp dated
    today, `alarm=mass-failure-…`) were both invisible in the mail (docs/BACKLOG.md 85)."""
    e = _load().get(stage) or {}
    out = []
    age = age_days(stage)
    if age is None:
        out.append(f"{stage} never ran")
    elif age > max_age_days:
        out.append(f"{stage} last ran {age}d ago — the digest read stale input")
    if e.get("alarm"):
        out.append(f"{stage} {e['alarm']}")
    return out


def summary() -> str:
    """One line per stage for the digest audit block."""
    data = _load()
    out = []
    for s in ORDER:
        e = data.get(s)
        if not e:
            out.append(f"{s}: never run")
            continue
        age = age_days(s)
        extra = " ".join(f"{k}={v}" for k, v in e.items()
                         if k not in ("finished_at", "date"))
        out.append(f"{s}: {e['date']}"
                   + (" (TODAY)" if age == 0 else f" ({age}d ago)")
                   + (f" {extra}" if extra else ""))
    return " | ".join(out)


def _cli():
    """`python -m pipeline.stages stamp <stage> [k=v ...]` — for workflow YAML steps.

    A stage's work is spread over several scripts in one workflow job, so the stamp belongs
    to the JOB, not to any one script. Keeping it a one-liner means a new step can record
    itself without importing anything.
    """
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "stamp":
        stage = sys.argv[2]
        detail = {}
        for kv in sys.argv[3:]:
            if "=" in kv:
                k, v = kv.split("=", 1)
                detail[k] = int(v) if v.lstrip("-").isdigit() else v
        stamp(stage, **detail)
        print(f"stage '{stage}' stamped: {detail or '{}'}")
        return 0
    print(summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
