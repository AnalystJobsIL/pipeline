"""Fetch the job-description text for a role that arrived without one.

Four list endpoints simply do not carry the JD — `workday` (88 active companies),
`smartrecruiters` (19), `bamboohr` (12), `microsoft` (1) — so their roles used to reach
the classifier as a bare title. The LLM tier exists to read the description and judge; with
none it is guessing, and the board renders no requirements, skills or tags for them.

So before classifying, fill it from the posting's own URL. Only for jobs that could
plausibly be accepted (the cheap title gate first — never spend a fetch on a role we would
reject on the title anyway), and only within a wall-clock budget so a slow ATS cannot eat
the digest's timeout.

Deliberately plain HTTP: this runs over hundreds of roles inside the daily digest, and the
Bright Data fallback belongs in the offline backfill (`enrich_matched_jd.py`), not here.
"""
from __future__ import annotations

import os
import time

_MIN_DESC = 300


class JDFiller:
    def __init__(self, budget_min=None, enabled=None):
        self.budget = float(os.environ.get("JDFILL_TIME_BUDGET_MIN", budget_min or 20))
        env = os.environ.get("JDFILL", "")
        self.enabled = (env == "1") if env else (True if enabled is None else enabled)
        self.t0 = time.time()
        self.filled = 0
        self.tried = 0
        self.skipped_budget = 0
        self._extract = None

    def _lazy(self):
        if self._extract is None:
            # imported lazily: enrich_scrape_jd lives at the repo root and pulls in
            # bd_rescue, which we do not want to import for a --no-llm unit run
            from enrich_scrape_jd import _plain_fetch, extract_jd
            self._extract = (_plain_fetch, extract_jd)
        return self._extract

    def spent(self):
        return self.budget and (time.time() - self.t0) / 60 > self.budget

    def maybe_fill(self, job):
        """Fill job['description'] in place when it is missing. Returns True if filled."""
        if not self.enabled:
            return False
        if len((job.get("description") or "").strip()) >= _MIN_DESC:
            return False
        url = job.get("url") or ""
        if not url.startswith("http"):
            return False
        from .seniority import _relevance
        if _relevance((job.get("title") or "").lower()) in ("excluded", "none"):
            return False
        if self.spent():
            self.skipped_budget += 1
            return False
        plain_fetch, extract_jd = self._lazy()
        self.tried += 1
        try:
            html = plain_fetch(url, timeout=15)
            jd = extract_jd(html) if html else ""
        except Exception:  # noqa: BLE001
            jd = ""
        if jd:
            job["description"] = jd
            self.filled += 1
            return True
        return False

    def summary(self):
        return (f"jd-fill: {self.filled}/{self.tried} descriptions fetched inline"
                + (f", {self.skipped_budget} skipped (budget {self.budget:g}m spent)"
                   if self.skipped_budget else ""))
