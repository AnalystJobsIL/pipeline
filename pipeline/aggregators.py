"""Single source of truth for job-aggregator hosts.

A scrape row pointing at an aggregator ingests that site's global/"similar jobs" listing —
other companies' postings attributed to this company. Every layer (resolution, activation,
runtime) must consult THIS list, not a local copy: builtin.com was missing from three
separate hand-maintained tuples and 13 rows were activated on the same global listing
(2026-08-22). Add new hosts here only.
"""
from __future__ import annotations

import re

HOSTS = (
    "linkedin.", "indeed.", "glassdoor.", "secrethunter.", "t.me",
    "builtin.com", "ziprecruiter.", "monster.", "dice.com", "simplyhired.",
    "careerbuilder.", "wellfound.com", "angel.co", "startup.jobs", "themuse.com",
    "jobvite.com/search", "talent.com", "jooble.", "neuvoo.", "adzuna.",
    "drushim.co.il", "alljobs.co.il", "jobmaster.co.il", "ethosia.", "gotfriends.",
)

_RX = re.compile(r"//[^/]*(" + "|".join(h.replace(".", r"\.") for h in HOSTS) + ")", re.I)


def is_aggregator(url: str) -> bool:
    """True if the URL points at a job aggregator rather than a company's own board."""
    return bool(_RX.search(url or ""))
