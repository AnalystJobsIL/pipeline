"""Explicit ordering contract between the nightly stages.

The pipeline's order is real but IMPLICIT — it depends on cron spacing and nothing verifies
it. The intended sequence is:

    1  repair    19:00  repair_dead_urls -> repair_extract_gap -> listing_hunt -> crack_walled
    2  collect   00:00  refresh_scrape_cache   (needs stage 1: fixed URLs)
    2  collect   05:00  discovery_daily / discovery_telegram
    3  expand    08:00  auto_expand            (new companies -> tomorrow's stage 1)
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

ORDER = ["repair", "collect", "expand", "enrich", "publish"]


def _load() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def stamp(stage: str, **detail) -> None:
    """Record that `stage` completed, with whatever counts the caller wants to keep."""
    data = _load()
    data[stage] = {"finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "date": dt.date.today().isoformat(), **detail}
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, PATH)


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
