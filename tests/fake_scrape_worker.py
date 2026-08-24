"""A module-level worker for the refresh's process-pool test (pickled into spawned children,
so it cannot be a lambda or a monkeypatch). Behaviour is chosen by the company NAME."""
from __future__ import annotations

import time


def fake_worker(task):
    name, url = task
    if name.startswith("slow"):
        time.sleep(float(name.split("-")[1]))
    if name.startswith("err"):
        return {"name": name, "jobs": [], "status": "error", "error": "http:403",
                "http_status": 403, "strategy": "", "seconds": 0.0}
    if name.startswith("empty"):
        return {"name": name, "jobs": [], "status": "empty", "error": "",
                "http_status": 200, "strategy": "", "seconds": 0.0}
    if name.startswith("boom"):
        raise RuntimeError("worker exploded")
    return {"name": name, "status": "ok", "error": "", "http_status": 200, "strategy": "dom",
            "seconds": 0.0,
            "jobs": [{"company": name, "title": "Senior Data Analyst", "location": "Tel Aviv",
                      "country_code": "", "url": url + "#1", "posted_date": "",
                      "ats_platform": "scrape", "job_id": "1", "description": ""}]}
