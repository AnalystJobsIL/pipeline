#!/usr/bin/env python3
"""Re-attack 'unreachable' companies efficiently until none are left.

For each, try ALTERNATE careers URLs (the research URL was often just wrong/stale). Each alt is
first fetched over plain HTTP (instant): if the HTML carries an embedded ATS/Comeet signature we
resolve it via its API with no browser; if it merely has job content we render+scrape that one URL.
A company is 'unreachable' only if no alternate returns a usable page.

Reads unreachable rows from companies.csv; rewrites them in place (or per-shard files with --shard).
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.request
from urllib.parse import urlsplit

_MODIFIED = set()      # company names this run actually rewrote (single-writer merge)

from pipeline import israel
from ingest_research import PROBE_FAST, _cand_slugs, _try
from resolve_deep import ATS_PATTERNS, _verify
from scrape_universal import ISRAEL_LOC, scrape
from pipeline import identity_gate as _gate
from pipeline.atomic import write_csv_rows
from pipeline.notes import replace_own as _note_replace
from pipeline.verdicts import is_terminal

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_UID = re.compile(r"comeet_uid[\"'\s:=]+[\"']?([0-9A-Za-z]{2}\.[0-9A-Za-z]{3})")
_TOK = re.compile(r"comeet_token[\"'\s:=]+[\"']?([0-9A-Fa-f]{20,})")
_BADSLUG = {"www", "api", "jobs", "boards", "apply", "job-boards", "careers", "en", "com"}


def alt_urls(url):
    p = urlsplit(url if "://" in url else "https://" + url)
    host = p.netloc or p.path.split("/")[0]
    root = host[4:] if host.startswith("www.") else host
    base = f"https://{host}"
    cands = [url, f"{base}/careers", f"{base}/careers/", f"{base}/jobs", f"{base}/careers/jobs",
             f"{base}/company/careers", f"{base}/about/careers", f"{base}/join-us",
             f"https://careers.{root}", f"https://jobs.{root}", f"https://www.{root}/careers"]
    out = []
    for c in cands:
        if c not in out:
            out.append(c)
    return out


def _http(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=7) as r:
            return r.geturl(), r.read(400000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None, ""


def attempt(name, url):
    """Return ('ats', tuple) | ('scrape', jobs) | ('empty', None) | ('unreachable', None)."""
    # 1) the company site is often anti-bot-blocked, but its ATS board is on a different, open host.
    for s in _cand_slugs(name, url)[:3]:
        for plat in PROBE_FAST:
            r = _try(plat, s, name)
            if r and r["jobs"] and r["il"] > 0:
                url2 = {"greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
                        "lever": f"https://api.lever.co/v0/postings/{s}?mode=json",
                        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{s}",
                        "workable": f"https://apply.workable.com/api/v1/widget/accounts/{s}?details=true",
                        "recruitee": f"https://{s}.recruitee.com/api/offers/"}[plat]
                return ("ats", (name, plat, s, url2, r["jobs"], r["il"]))
    reached = False
    for alt in alt_urls(url):
        final, html = _http(alt)
        if not html or len(html) < 400:
            continue
        reached = True
        low = html.lower()
        # embedded ATS signature -> resolve via API, no browser
        for plat, rx, build in ATS_PATTERNS:
            m = rx.search(html)
            if m and m.group(1) not in _BADSLUG:
                v = _verify(name, plat, m.group(1), build(m.group(1)))
                if v and v[0]:
                    return ("ats", (name, plat, m.group(1), build(m.group(1)), v[0], v[1]))
        u, t = _UID.search(html), _TOK.search(html)          # embedded Comeet config
        if u and t:
            api = f"https://www.comeet.com/careers-api/2.0/company/{u.group(1)}/positions?token={t.group(1)}"
            v = _verify(name, "comeet", u.group(1), api)
            if v and v[0]:
                return ("ats", (name, "comeet", u.group(1), api, v[0], v[1]))
        # page looks like it lists jobs -> render + scrape this one URL
        if "myworkdayjobs" in low or "greenhouse" in low or "job" in low or ISRAEL_LOC.search(html):
            try:
                jobs = scrape(name, final or alt)
            except Exception:  # noqa: BLE001
                jobs = []
            il = [j for j in jobs if israel.is_israel_job(j)]
            if il:
                return ("scrape", (il, final or alt))   # keep the URL that worked
    return ("empty", None) if reached else ("unreachable", None)


def _today():
    import datetime as _dtm
    return _dtm.date.today().isoformat()


def _note(base, segment, disproved=True):
    """This tool's verdict, APPENDED to what the row already carries (rule 3).

    Until 2026-08-25 every branch rebuilt the notes cell from a literal, so a night's
    `unreachable; could not scan` deleted listing-hunt's `no IL listing; monitored candidate`
    and bd_rescue's paid `scanned via brightdata` verdict 90 seconds after it was written
    (`git show b3d1d49 -- companies.csv`: 9 rows, every night, `recovered 0`). `retry` is the
    one marker for every branch, so a row carries one current verdict from this tool; the
    `unreachable` token is removed only when this attempt DISPROVED it (the page answered),
    because that token is the selector of this tool and of bd_rescue.
    """
    if disproved:
        base = _note_replace(base, "unreachable", "")
    return _note_replace(base, "retry", segment)


def _row_for(name, url, kind, payload, cache, note=""):
    """The one seam every branch of this tool passes through, so the gate lives here.

    Until 2026-08-24 the `ats` and `scrape` branches returned an ACTIVE row straight from
    `resolve()`'s payload with no identity evidence. This tool runs 02:30 daily and rewrites
    rows already marked `unreachable`, which is exactly the population whose stored address
    is least trustworthy. `note` is the row's CURRENT cell: every branch appends to it
    through `_note` rather than replacing it (the default keeps the older one-argument
    fixtures valid: with an empty base each branch yields exactly its own segment).
    """
    if kind == "ats":
        nm, plat, tok, api, n_all, il = payload
        if not _gate.activation_ok(nm, api, n_all):
            # The refusal note MUST carry a re-check-pool token. The first version of
            # this string carried none and REPLACED the whole cell, so the 9 rows whose
            # only token was `unreachable` left every pool at once -- including this
            # tool's own selector -- became orphans, and 11 orphans trip
            # check_invariants' bad(), which blocks the digest commit. `no listing found`
            # is the deliberate hand-off: this tool could not find the RIGHT board, which
            # is listing_hunt's job, and it is the same convention listing_hunt's own
            # identity refusal uses.
            return [nm, "scrape", url, url, "false",
                    _note(note, "retry: another company's board; no listing found")]
        return [nm, plat, tok, api, "true", _note(note, f"retry-resolved; {n_all}/{il} IL")]
    if kind == "scrape":
        jobs2, good_url = payload if isinstance(payload, tuple) else (payload, url)
        if not _gate.activation_ok(name, good_url, len(jobs2)):
            return [name, "scrape", url, url, "false",
                    _note(note, "retry: another company's page; no listing found")]
        cache[name] = jobs2
        return [name, "scrape", good_url, good_url, "true",
                _note(note, f"retry-scrape; {len(jobs2)} IL")]
    if kind == "empty":
        return [name, "scrape", url, url, "false",
                _note(note, f"retry {_today()}: scanned; no open Israel roles now")]
    # still unreachable: the token STAYS (it is this tool's and bd_rescue's selector) and
    # nothing else on the row is touched -- the base note is exactly what came in.
    return [name, "scrape", url, url, "false",
            _note(note, f"retry {_today()}: still unreachable", disproved=False)]


def main():
    limit = int(os.environ.get("RETRY_LIMIT", "0"))
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    # `unreachable` is the selector; a terminal row (`defunct`, `alias-of`, ...) that also
    # carries it must never be re-attempted -- an alias row points at a board that WORKS.
    idx = {r[0].strip(): (i, r[3]) for i, r in enumerate(rows)
           if len(r) >= 6 and "unreachable" in (r[5] or "").lower()
           and not is_terminal(r[5] or "")}
    names = list(idx)
    if limit:
        names = names[:limit]
    sharded = "--shard" in sys.argv
    if sharded:
        i, n = int(sys.argv[sys.argv.index("--shard") + 1]), int(sys.argv[sys.argv.index("--shard") + 2])
        names = names[i::n]

    try:
        cache = json.load(open("scraped_cache.json", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cache = {}
    fixed = still = 0
    for name in names:
        rowi, url = idx[name]
        try:
            kind, payload = attempt(name, url)
        except Exception:  # noqa: BLE001
            kind, payload = "unreachable", None
        newrow = _row_for(name, url, kind, payload, cache,
                          note=rows[rowi][5] if len(rows[rowi]) > 5 else "")
        still += (kind == "unreachable")
        fixed += (kind != "unreachable")
        if sharded:
            with open(os.environ.get("SCRAPE_CSV_OUT", "out/retry_rows.csv"), "a",
                      newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(newrow)
        else:
            rows[rowi] = newrow
            _MODIFIED.add(name)
        print(f"  {kind[:4]:4} {name}", flush=True)

    if sharded:
        with open(os.environ.get("SCRAPE_CACHE_OUT", "out/retry_cache.json"), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    else:
        # single-writer discipline: merge back ONLY the rows this run actually modified.
        # (Merging the whole snapshot reverts every row another writer touched during the
        # run — the exact lost-update this rule exists to prevent.)
        changed = {r[0]: r for r in rows
                   if r and len(r) > 5 and r[0] in _MODIFIED}
        fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
        for pos, fr in enumerate(fresh):
            if fr and len(fr) > 5 and fr[0] in changed and changed[fr[0]] != fr:
                fresh[pos] = changed[fr[0]]
        write_csv_rows("companies.csv", fresh)
        with open("scraped_cache.json", "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"=== recovered {fixed}, still unreachable {still} ===", flush=True)


if __name__ == "__main__":
    main()
