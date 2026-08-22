"""Shared ATS-health recording.

Turns per-company fetch outcomes into a stale-board list + a persistent baseline. Called
INLINE by the daily run (pipeline.run) so detection is a free byproduct of the fetch that
already happens every morning — a broken board is noticed within a day, not a week. The
standalone weekly sweep (health_check.py) reuses the same logic as a backstop.

Stale reasons:
  misconfig-scrape-on-ats — set to `scrape` while the URL is a real ATS host
  fetch-error             — the endpoint 404s / 422s / times out
  regressed-to-zero       — had postings before (baseline > 0), now 0
  empty-board             — a real ATS returning literally 0 total postings (moved board /
                            stale token / anti-bot) — flagged even with no baseline
"""
from __future__ import annotations

import json
import os
import re

ATS_HOST = re.compile(r"greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|"
                      r"comeet\.co|workable\.com|recruitee\.com|myworkdayjobs|"
                      # added 2026-08-22 after pipeline/platform_check.py showed 6 native
                      # platforms missing here — a row misconfigured as `scrape` on one of
                      # these hosts was never flagged misconfig-scrape-on-ats
                      r"breezy\.hr|bamboohr\.com|oraclecloud\.com|applytojob\.com|"
                      r"jazz\.co|amazon\.jobs|careers\.microsoft\.com", re.I)
BASELINE = "cloud_state/health_baseline.json"   # committed, so it persists across cloud runs
STALE = "cloud_state/stale.json"                # committed, so the self-heal job can read it


def _load(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def stale_reason(platform, api_url, n, status, baseline_best):
    plat = (platform or "").strip()
    if plat == "scrape" and ATS_HOST.search(api_url or ""):
        return "misconfig-scrape-on-ats"
    if status == "error":
        return "fetch-error"
    if status == "empty" and baseline_best > 0:
        return "regressed-to-zero"
    # jazzhr has no public JSON API — fetch_jazzhr returns [] BY DESIGN, so without
    # this exemption every jazzhr row is flagged empty-board forever and the 06:00
    # self-heal re-attempts it every week (it was doing exactly that).
    if n == 0 and plat not in ("scrape", "discovery", "custom_json", "jazzhr"):
        return "empty-board"
    return None


def record(results, baseline_path=BASELINE, stale_path=STALE):
    """results: {company: {'platform','api','n','status'}}. Update baseline + write stale list.
    Returns the stale dict. Never raises on IO — health must never break the digest."""
    baseline = _load(baseline_path)
    stale = {}
    for name, r in results.items():
        n = int(r.get("n", 0))
        best = max(int(baseline.get(name, 0)), n)
        baseline[name] = best
        reason = stale_reason(r.get("platform", ""), r.get("api", ""), n,
                              r.get("status", "ok"), best)
        if reason:
            stale[name] = {"careers_url": r.get("api", ""),
                           "platform": (r.get("platform") or "").strip(), "reason": reason}
    try:
        for path, data in ((baseline_path, baseline), (stale_path, stale)):
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except OSError:
        pass
    return stale
