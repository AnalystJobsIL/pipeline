"""Per-source liveness: did each discovery source actually return anything today?

The Bright Data Indeed dataset returned literally zero records on every run for five days
(`error_codes: {"rate_limit": 15}` on every snapshot). The step printed `[indeed] 0 records`
and exited 0, the workflow was green, and nothing anywhere said "a source died". A zero from
a source that used to produce is the single most valuable signal this pipeline can emit and
it was being thrown away — same class as the dead capabilities in HANDOFF §1c.

One JSON file, one record per source: how many it returned, when it last returned anything.
`stale()` is what the digest audit prints.
"""
from __future__ import annotations

import datetime as dt
import json
import os

PATH = os.path.join(os.path.dirname(__file__), "..", "cloud_state", "source_health.json")


def _load() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def record(counts: dict) -> None:
    """counts: {source_name: n_records_this_run}."""
    data = _load()
    today = dt.date.today().isoformat()
    for name, n in counts.items():
        e = data.get(name) or {}
        e["last_run"] = today
        e["last_count"] = int(n)
        if int(n) > 0:
            e["last_nonzero"] = today
        e.setdefault("last_nonzero", "")
        data[name] = e
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, PATH)


def stale(max_quiet_days: int = 2) -> list:
    """Sources that ran recently but have produced nothing for `max_quiet_days`.

    A source that has NEVER produced is reported too — that is how a mis-wired one looks.
    """
    data = _load()
    today = dt.date.today()
    out = []
    for name, e in sorted(data.items()):
        if not e.get("last_run"):
            continue
        nz = e.get("last_nonzero") or ""
        if not nz:
            out.append(f"{name}: has NEVER returned a record")
            continue
        try:
            quiet = (today - dt.date.fromisoformat(nz)).days
        except ValueError:
            continue
        if quiet > max_quiet_days:
            out.append(f"{name}: nothing for {quiet}d (last {nz})")
    return out
