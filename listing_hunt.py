#!/usr/bin/env python3
"""Hunt the real job-LISTINGS page for every still-dark / walled-ATS company.

Insight (user-proven with Intuit & Google, then Qualcomm): companies with 'no machine-
readable ATS' almost always still have a server-rendered or XHR-backed LISTINGS page —
the failure was pointing at marketing /careers pages instead of the actual list. And the
Playwright scraper's response-capture defeats bot-walled ATSes (Eightfold/Phenom) that
block plain HTTP.

Per company: render the careers page, harvest candidate links (jobs/positions/search/
Israel-filtered), let Claude pick the most likely listings URL from the link list (with
an honest empty answer allowed), then VALIDATE by running scrape_universal on it — a row
is only activated when the scrape yields >=1 Israel job. Verdicts persist in the row note.

Env: HUNT_LIMIT (0=all) · HUNT_TIME_BUDGET_MIN · HUNT_LLM_CAP (default 200)
Usage: python listing_hunt.py [--apply]
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
import urllib.parse

from deep_validate import Renderer, ddg
from audit_empty_rows import AGG
from pipeline.aggregators import is_aggregator
from pipeline.recruiters import is_recruiter
from resolve_llm import _ask_claude
from pipeline.atomic import write_csv_rows

TODAY = dt.date.today().isoformat()
_LINKISH = re.compile(r"job|position|opening|vacanc|search|career|role|משרות|דרושים|join", re.I)
_IL = re.compile(r"israel|tel.?aviv|herzliya|haifa|jerusalem|ramat|petah|netanya|beer.?sheva", re.I)

_PICK_PROMPT = """You are locating the page that LISTS open job positions for the company
"{name}" (has an Israel office). Below are links harvested from its careers/website pages,
as "text -> url" lines. Pick the ONE url most likely to show the actual list of open
positions — prefer an Israel-filtered listing when present. If a url pattern supports an
obvious Israel filter (e.g. ?location=Israel), you may add it.
Respond ONLY a JSON object: {{"url": "<listings url or empty if none plausible>"}}

Links:
{links}
"""


def harvest_links(rend, url):
    html, reqs, _ = rend.sniff(url)
    out = []
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.{0,120}?)</a>', html or "", re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        absu = urllib.parse.urljoin(url, href)
        if is_aggregator(absu):
            continue
        if _LINKISH.search(href) or _LINKISH.search(text) or _IL.search(text):
            out.append((text[:60], absu))
    seen, uniq = set(), []
    for t, u in out:
        if u not in seen:
            seen.add(u)
            uniq.append((t, u))
    return uniq[:40], bool(html)


def _resolve_rebrand(url):
    """Follow redirects; a cross-domain landing means the company rebranded (Piiano->a16y.ai).
    Returns (final_url, rebrand_domain_or_empty)."""
    import urllib.request as _ur
    try:
        req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        with _ur.urlopen(req, timeout=15) as r:
            final = r.geturl()
    except Exception:  # noqa: BLE001
        return url, ""
    d0 = ".".join(urllib.parse.urlparse(url).netloc.split(".")[-2:])
    d1 = ".".join(urllib.parse.urlparse(final).netloc.split(".")[-2:])
    return final, (d1 if d0 != d1 else "")


def hunt_one(name, seed, documented=False):
    from deep_validate import google_via_unlocker
    # fast-path for probe-woken / documented candidates: the listings URL is already known —
    # just pull it (scrape + verify); the full search dance only runs if that fails
    if documented and seed and seed.startswith("http"):
        from scrape_universal import scrape
        from pipeline.israel import is_israel_job
        try:
            il = [j for j in (scrape(name, seed) or []) if is_israel_job(j)]
        except Exception:  # noqa: BLE001
            il = []
        if il:
            return ("found", seed, len(il), "fast-path")
    rebrand = ""
    if seed and not is_aggregator(seed):
        final, rebrand = _resolve_rebrand(seed)
        if rebrand:
            # An ACQUISITION also redirects cross-domain (deci.ai -> nvidia.com). Following
            # it would verify the ACQUIRER's Israel jobs and attribute them to this company
            # — the CyberArk->PANW class, arriving through the one unguarded path.
            from audit_empty_rows import _slug_matches
            if not _slug_matches(name, rebrand.split(".")[0]):
                # Can't distinguish a rebrand (piiano->a16y.ai, legitimate) from an
                # ACQUISITION (deci.ai->nvidia.com, whose global board would verify with
                # the acquirer's Israel jobs) automatically. Document, never auto-follow.
                print(f"       (cross-domain redirect -> {rebrand}: unverifiable as rebrand; "
                      f"documented for review, not followed)", flush=True)
                return ("redirected", None, 0, f"redirects to {rebrand} — verify manually "
                        f"(rebrand vs acquisition) before activating")
            seed = final
            print(f"       (rebrand detected -> {rebrand})", flush=True)
    cands = [] if not seed or is_aggregator(seed) else [seed]
    if rebrand:
        cands += [f"https://{rebrand}/careers", f"https://{rebrand}/careers/"]
    cands += [u for u in ddg(f"{name} jobs") if u not in cands]
    if len(cands) < 2:                     # DDG blocked/empty (datacenter IPs) — paid fallback
        cands += [u for u in google_via_unlocker(f"{name} careers") if u not in cands]
    links, reachable = [], False
    # IMPORTANT: harvest with a SHORT-LIVED Renderer and close it BEFORE calling scrape() —
    # scrape_universal starts its own sync Playwright; two sync instances in one thread throw,
    # which silently zeroed an entire hunt cycle.
    with Renderer() as rend:
        for u in cands[:2]:
            ls, ok = harvest_links(rend, u)
            reachable = reachable or ok
            links += [(t, l) for t, l in ls if (t, l) not in links]
            links.append(("(the page itself)", u))
    if not links:
        return ("dead", None, 0, "no pages reachable" if not reachable else "no links")
    picked = ""
    if shutil.which("claude"):
        p = _ask_claude(_PICK_PROMPT.format(
            name=name, links="\n".join(f"{t} -> {u}" for t, u in links[:40])))
        picked = str((p or {}).get("url") or "").strip()
    ordered = ([picked] if picked.startswith("http") else [])
    ordered += [u for _, u in links if _IL.search(u)][:1]
    ordered += [u for t, u in links if re.search(r"open|position|all jobs|search|view", t, re.I)][:1]
    ordered += [cands[0]] if cands else []
    tried = []
    from scrape_universal import scrape
    from pipeline.israel import is_israel_job
    for u in dict.fromkeys(ordered).keys():
        if len(tried) >= 2:
            break
        tried.append(u)
        try:
            jobs = scrape(name, u) or []
        except Exception:  # noqa: BLE001
            jobs = []
        il = [j for j in jobs if is_israel_job(j)]
        if il and not is_aggregator(u):
            return ("found", u, len(il), "")
    # DOCUMENT where we looked: the best candidate page survives in the row so future
    # re-hunts and humans check the right place (a real board with 0 IL roles today —
    # e.g. Fabric on Rippling — must not be indistinguishable from "no board exists").
    best = next(iter(dict.fromkeys(ordered)), (cands[0] if cands else ""))
    return ("nolisting", best, 0, f"tried {len(tried)} candidates")


def main():
    from bd_rescue import _load_secrets
    _load_secrets()
    os.environ["SCRAPE_ASSUME_IL"] = "1"   # targets are pre-vetted Israel-relevant companies
    apply = "--apply" in sys.argv
    limit = int(os.environ.get("HUNT_LIMIT", "0"))
    budget_min = int(os.environ.get("HUNT_TIME_BUDGET_MIN", "0"))
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    def _stale_hunt(note):
        """Re-hunt ANY hunted row after 14 days — a board empty today isn't empty forever.
        NOTE: this used to require the literal 'monitored candidate', which made the
        'no listing found' verdict TERMINAL (rows silently retired from the pool forever,
        so one broken cycle could permanently delete hundreds of companies' coverage)."""
        m = re.search(r"listing-hunt (\d{4}-\d{2}-\d{2})", note or "")
        if not m:
            return False
        age = (dt.date.today() - dt.date.fromisoformat(m.group(1))).days
        return age >= 14

    targets = [(i, r) for i, r in enumerate(rows)
               if r and len(r) >= 6 and r[4] == "false"
               # every parked shape that could still hide a real listing — NOT just the
               # hunt-produced notes (chrome-verified "monitored candidate" rows and
               # auto_expand's "scanned; no open"/"unreachable" were invisible before)
               # NOTE: any NEW verdict string must be added here or it silently retires
               # the row from the hunt pool forever.
               and re.search(r"no ATS detected|unsupported ATS|scrape rotted|monitored candidate|"
                             r"host documented|probe-woken|scanned; no open|unreachable|"
                             r"aggregator URL|no listing found|redirects to|scanned via brightdata|empty-but-suspect|needs re-resolution|needs manual resolution", r[5] or "")
               and not re.search(r"defunct|domain-dead", r[5] or "")
               and not is_recruiter(r[0])   # agencies are never activated
               and ("listing-hunt" not in (r[5] or "") or _stale_hunt(r[5]))]
    if limit:
        targets = targets[:limit]
    print(f"listing-hunting {len(targets)} companies\n", flush=True)
    stats = {"found": 0, "nolisting": 0, "dead": 0, "redirected": 0}
    t0 = time.time()
    if True:
        for n, (i, r) in enumerate(targets, 1):
            if budget_min and (time.time() - t0) / 60 > budget_min:
                print("time budget reached — stopping cleanly", flush=True)
                break
            name = r[0]
            try:
                doc = bool(re.search(r"probe-woken|monitored candidate|host documented", r[5] or ""))
                verdict, url, n_il, detail = hunt_one(name, r[3], documented=doc)
            except Exception as e:  # noqa: BLE001
                verdict, url, n_il, detail = "dead", None, 0, f"error {str(e)[:50]}"
            stats[verdict] += 1
            print(f"  [{'OK' if verdict == 'found' else '--'}] {n}/{len(targets)} {name}: "
                  f"{url or detail}{f' ({n_il} IL)' if n_il else ''}", flush=True)
            if apply:
                # single-writer discipline: re-read before every write; a start-of-run
                # snapshot silently reverts other writers' verdicts (§5 ARCHITECTURE.md)
                fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
                for fr in fresh:
                    if not fr or fr[0] != name or len(fr) < 6:
                        continue
                    if verdict == "found":
                        fr[1], fr[2], fr[3] = "scrape", "", url
                        fr[4] = "true"
                        fr[5] = f"listing-hunt {TODAY}: verified {n_il} IL via {url[:60]}"
                    elif verdict == "nolisting" and url:
                        fr[3] = url                       # persist the candidate page
                        base = re.sub(r"\s\|\s?listing-hunt [^|]*", "", fr[5])
                        fr[5] = (base + f" | listing-hunt {TODAY}: no IL listing; "
                                 f"monitored candidate")[:220]
                    else:
                        fr[5] = (re.sub(r"\s\|\s?listing-hunt [^|]*", "", fr[5])
                                 + f" | listing-hunt {TODAY}: "
                                 + ("no listing found" if verdict == "nolisting" else detail))[:220]
                write_csv_rows("companies.csv", fresh)
    print(f"\n=== listing hunt: {stats} ===", flush=True)


if __name__ == "__main__":
    main()
