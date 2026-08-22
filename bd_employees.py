#!/usr/bin/env python3
"""Fill missing employee counts from LinkedIn company pages via Bright Data Web Unlocker.

Targets ONLY firmographics records with null employees_global (the researcher's honest
"couldn't find a published number" cases — mostly small privates and acquired subsidiaries).
For each, guesses the LinkedIn company slug from the name, fetches the public page through
the Unlocker (1 credit/page), and extracts:
  - the member-linked employee count (JSON-LD numberOfEmployees / "N employees" text)
  - the self-reported size bucket ("51-200 employees") -> confirms/fills size_band

Updates the store in place (employees_source: "linkedin", employees_as_of stamped); a page
that can't be fetched or doesn't clearly match the company name is skipped, never guessed.

Needs BRIGHTDATA_API_KEY + BRIGHTDATA_ZONE in the environment or secrets.env. Never prints
the key. Cap per run with BD_LIMIT (default 60 — a full null-employee pass is ~49 credits).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import urllib.request

from pipeline.store import SeenStore

ROOT = os.path.dirname(os.path.abspath(__file__))


def _load_secrets():
    p = os.path.join(ROOT, "secrets.env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)


def unlock(url, timeout=90):
    """Fetch url through Web Unlocker; returns HTML ('' on failure)."""
    body = json.dumps({"zone": os.environ["BRIGHTDATA_ZONE"], "url": url,
                       "format": "raw"}).encode()
    req = urllib.request.Request("https://api.brightdata.com/request", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(2_000_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


_SUFFIX = re.compile(r"\s+(ltd|inc|llc|corp|co|gmbh|group|technologies|solutions)\.?$", re.I)


def slug_candidates(name):
    """Best-guess LinkedIn /company/ slugs for a display name, most likely first."""
    base = re.sub(r"\([^)]*\)", "", name).strip()          # "Habana Labs (Intel)" -> "Habana Labs"
    base = _SUFFIX.sub("", base)
    cands = []
    for form in (base, base.replace(".", " "), base.replace(".", "")):
        s = re.sub(r"[^0-9a-z]+", "-", form.lower().replace("&", " and ")).strip("-")
        s = re.sub(r"-+", "-", s)
        if s and s not in cands:
            cands.append(s)
    return cands[:3]


# LinkedIn's self-reported size buckets -> our size_band
_BUCKETS = [(200, "S"), (1000, "M"), (5000, "L"), (10 ** 9, "XL")]


def band_for(n):
    return next(b for cap, b in _BUCKETS if n < cap)


def parse_page(html, name):
    """Return (employee_count|None, range_str|None) if the page matches `name`, else None."""
    # match guard: the company's first significant name word must appear in the page title
    title = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    first_word = re.sub(r"[^0-9a-z]+", " ", name.lower()).split()[0]
    if not title or first_word not in title.group(1).lower():
        return None
    count = None
    m = re.search(r'"numberOfEmployees"\s*:\s*\{[^}]*"value"\s*:\s*(\d+)', html)
    if m:
        count = int(m.group(1))
    else:
        m = re.search(r'>([\d,]{1,7})\s+employees<', html)
        if m:
            count = int(m.group(1).replace(",", ""))
    rng = None
    m = re.search(r'([\d,]+)\s*-\s*([\d,]+)\s+employees|([\d,]+)\+\s+employees', html)
    if m:
        rng = m.group(0).replace(" employees", "").replace(",", "").strip()
    if count is not None and not (1 <= count <= 5_000_000):
        count = None
    return (count, rng) if (count or rng) else None


def main():
    _load_secrets()
    if not (os.environ.get("BRIGHTDATA_API_KEY") and os.environ.get("BRIGHTDATA_ZONE")):
        print("BRIGHTDATA_API_KEY / BRIGHTDATA_ZONE not set — run setup_brightdata.py first")
        return
    limit = int(os.environ.get("BD_LIMIT", "60"))
    st = SeenStore()
    recs = st.load_firmographics()
    targets = sorted(c for c, r in recs.items() if not r.get("employees_global"))[:limit]
    today = dt.date.today().isoformat()
    print(f"linkedin employee lookup for {len(targets)} companies ...")
    got = rng_only = miss = 0
    for name in targets:
        found = None
        for slug in slug_candidates(name):
            html = unlock(f"https://www.linkedin.com/company/{slug}")
            if len(html) < 1000:
                continue
            found = parse_page(html, name)
            if found:
                break
        time.sleep(1)
        if not found:
            miss += 1
            print(f"  miss {name}", flush=True)
            continue
        count, rng = found
        rec = recs[name]
        rec["employees_source"] = "linkedin"
        rec["employees_as_of"] = today
        if rng:
            rec["employees_range"] = rng
        if count:
            rec["employees_global"] = count
            if not rec.get("size_band"):
                rec["size_band"] = band_for(count)
            got += 1
            print(f"  ok   {name}: {count} employees" + (f" (bucket {rng})" if rng else ""), flush=True)
        else:
            # bucket only: keep count null (honest), but use the bucket's floor for size_band
            if not rec.get("size_band"):
                floor = int(re.split(r"[-+]", rng)[0] or 0)
                rec["size_band"] = band_for(max(floor, 1))
            rng_only += 1
            print(f"  rng  {name}: bucket {rng}, no member count", flush=True)
        st.save_firmographics({name: rec}, today)
    print(f"=== counts {got} · bucket-only {rng_only} · miss {miss} ===")


if __name__ == "__main__":
    main()
