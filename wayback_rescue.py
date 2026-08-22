#!/usr/bin/env python3
"""Rescue 'unreachable' companies via the Wayback Machine.

The Internet Archive crawled these anti-bot-blocked careers pages from a real browser, so the
ARCHIVED HTML often exposes the company's real ATS (greenhouse/lever/ashby/comeet/workday
signatures). We read the latest snapshot from web.archive.org (which serves us freely), extract the
ATS reference, then hit the ATS's own API on its open host — bypassing the blocked site entirely.

Usage: python wayback_rescue.py            # all unreachable rows in companies.csv, updates in place
"""
from __future__ import annotations

import csv
import json
import re
import time
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

from pipeline import israel
from resolve_deep import ATS_PATTERNS, _verify
from pipeline.atomic import write_csv_rows

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"
_UID = re.compile(r"comeet_uid[\"'\s:=]+[\"']?([0-9A-Za-z]{2}\.[0-9A-Za-z]{3})")
_TOK = re.compile(r"comeet_token[\"'\s:=]+[\"']?([0-9A-Fa-f]{20,})")
_WD = re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com(?:/wday/cxs/([^/\"']+)/([^/\"']+))?", re.I)
_BADSLUG = {"www", "api", "jobs", "boards", "apply", "job-boards", "careers", "en", "com", "embed"}


def _get(url, timeout=45):
    """Polite fetch: retry 503/429 with backoff (archive.org throttles aggressively)."""
    import urllib.error
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(1_500_000).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            return ""
        except Exception:  # noqa: BLE001
            return ""
    return ""


def latest_snapshots(url, limit=4):
    """CDX API: newest successful snapshots for the exact careers URL, then the domain root."""
    p = urlsplit(url if "://" in url else "https://" + url)
    host = (p.netloc or url).replace("www.", "")
    path = p.path.strip("/")
    outs = []
    queries = [f"{host}/{path}"] if path else []
    queries += [f"{host}/careers", f"{host}/jobs", host]
    for q in queries:
        cdx = ("https://web.archive.org/cdx/search/cdx?url=" + urllib.parse.quote(q, safe="")
               + "&output=json&filter=statuscode:200&limit=-4&from=2023")   # -4 = last 4
        body = _get(cdx, timeout=45)
        try:
            rows = json.loads(body)
        except Exception:  # noqa: BLE001
            continue
        for r in rows[1:]:
            if len(r) >= 3:
                outs.append((r[1], r[2]))
        if len(outs) >= limit:
            break
    outs = sorted(set(outs), reverse=True)[:limit]
    return [f"https://web.archive.org/web/{ts}/{orig}" for ts, orig in outs]


def extract_ats(html, name):
    """Return ('platform', token, api_url) from archived HTML, else None."""
    m = _WD.search(html)
    if m and m.group(3) and m.group(4):
        t, wd, tenant, site = m.group(1), m.group(2), m.group(3), m.group(4)
        return ("workday", f"{t}/{site}",
                f"https://{t}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs")
    u, tk = _UID.search(html), _TOK.search(html)
    if u and tk:
        return ("comeet", u.group(1),
                f"https://www.comeet.com/careers-api/2.0/company/{u.group(1)}/positions?token={tk.group(1)}")
    for plat, rx, build in ATS_PATTERNS:
        m = rx.search(html)
        if m and m.group(1).lower() not in _BADSLUG:
            return (plat, m.group(1), build(m.group(1)))
    return None


def rescue(name, url):
    for snap in latest_snapshots(url):
        html = _get(snap)
        if len(html) < 500:
            continue
        det = extract_ats(html, name)
        if not det:
            continue
        plat, tok, api = det
        v = _verify(name, plat, tok, api)          # verify against the LIVE ATS API
        if v and v[0]:
            return (plat, tok, api, v[0], v[1])
        time.sleep(0.5)
    return None


_MODIFIED = set()   # names this run rewrote (single-writer merge)


def main():
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    idx = {r[0].strip(): (i, r[3]) for i, r in enumerate(rows)
           if len(r) >= 6 and "unreachable" in (r[5] or "").lower()}
    print(f"wayback-rescuing {len(idx)} unreachable companies ...")
    fixed = 0
    for name, (rowi, url) in idx.items():
        try:
            r = rescue(name, url)
        except Exception:  # noqa: BLE001
            r = None
        if r:
            plat, tok, api, n_all, il = r
            rows[rowi] = [name, plat, tok, api, "true", f"wayback-rescued; {n_all}/{il} IL"]
            _MODIFIED.add(name)
            fixed += 1
            print(f"  [OK] {name}: {plat} jobs={n_all} il={il}", flush=True)
        else:
            print(f"  [--] {name}", flush=True)
        time.sleep(4)                              # polite pacing — archive.org rate-limits hard
    # single-writer discipline: merge back only rows this run modified (a whole-snapshot
    # write after a multi-minute network loop reverts concurrent writers' verdicts)
    changed = {r[0]: r for r in rows if r and len(r) > 5 and r[0] in _MODIFIED}
    fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
    for _i, fr in enumerate(fresh):
        if fr and len(fr) > 5 and fr[0] in changed:
            fresh[_i] = changed[fr[0]]
    write_csv_rows("companies.csv", fresh)
    print(f"=== wayback-rescued {fixed} of {len(idx)} ===")


if __name__ == "__main__":
    main()
