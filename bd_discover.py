#!/usr/bin/env python3
"""Bright Data Jobs-Scraper discovery test: trigger LinkedIn/Glassdoor/Indeed job discovery for
Israel analytics roles (small limits), poll until ready, and print samples. Also the base for the
daily discovery layer."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

from bd_rescue import _load_secrets

DATASETS = {
    "linkedin": ("gd_lpfll7v5hcqtkxl6l", "keyword",
                 [{"location": "Israel", "keyword": "data analyst", "country": "IL"}]),
    "glassdoor": ("gd_lpfbbndm1xnopbrcr0", "keyword",
                  [{"location": "Israel", "keyword": "data analyst"}]),
    "indeed": ("gd_l4dx9j9sscpvs7no2", "keyword",
               [{"country": "IL", "domain": "il.indeed.com", "keyword_search": "data analyst",
                 "location": "Israel"}]),
}


def _req(url, data=None, method="GET"):
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read().decode("utf-8", "replace")


def trigger(name, limit=10):
    ds, disc, inputs = DATASETS[name]
    q = urllib.parse.urlencode({"dataset_id": ds, "type": "discover_new", "discover_by": disc,
                                "limit_per_input": str(limit)})
    st, body = _req(f"https://api.brightdata.com/datasets/v3/trigger?{q}",
                    data=json.dumps(inputs).encode(), method="POST")
    j = json.loads(body)
    sid = j.get("snapshot_id")
    print(f"[{name}] trigger -> {st} snapshot={sid or body[:160]}")
    return sid


def wait_snapshot(sid, name, timeout_s=600):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st, body = _req(f"https://api.brightdata.com/datasets/v3/progress/{sid}")
        j = json.loads(body)
        status = j.get("status")
        if status == "ready":
            return True
        if status in ("failed", "error"):
            print(f"[{name}] FAILED: {body[:200]}")
            return False
        time.sleep(15)
    print(f"[{name}] timeout")
    return False


def fetch(sid, name):
    st, body = _req(f"https://api.brightdata.com/datasets/v3/snapshot/{sid}?format=json")
    try:
        rows = json.loads(body)
    except Exception:  # noqa: BLE001
        rows = [json.loads(l) for l in body.splitlines() if l.strip()]
    print(f"[{name}] {len(rows)} records")
    for r in rows[:5]:
        title = r.get("job_title") or r.get("title") or r.get("job_title_text") or "?"
        comp = r.get("company_name") or r.get("company") or "?"
        loc = r.get("job_location") or r.get("location") or "?"
        url = (r.get("apply_link") or r.get("url") or r.get("job_url") or "")[:70]
        print(f"    - {str(title)[:44]:44} | {str(comp)[:22]:22} | {str(loc)[:20]:20} | {url}")
    return rows


if __name__ == "__main__":
    _load_secrets()
    names = sys.argv[1:] or ["linkedin", "glassdoor", "indeed"]
    sids = {}
    for n in names:
        try:
            sid = trigger(n, limit=10)
            if sid:
                sids[n] = sid
        except Exception as e:  # noqa: BLE001
            print(f"[{n}] trigger ERR {type(e).__name__}: {str(e)[:200]}")
    out = {}
    for n, sid in sids.items():
        if wait_snapshot(sid, n):
            out[n] = fetch(sid, n)
    with open("out/bd_discover_test.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved -> out/bd_discover_test.json")
