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
from urllib.parse import urlparse

from pipeline.company_identity import is_foreign, ATS_HOST
from crack_walled import _ok_to_write
from pipeline.firmographics import looks_like_junk
from pipeline.company_identity import looks_like_a_job_listing_page
from resolve_llm import _ask_claude
from pipeline.atomic import write_csv_rows
from pipeline.notes import append as _note_append, replace_own as _note_replace

# stdout may be a cp1252 pipe (Windows, or a runner with an odd locale). These scripts print
# company names and arrows in their summaries, and an UnicodeEncodeError there kills the
# process AFTER the useful work — in the cloud conflict path that is a `|| true`, so the
# whole merge is discarded silently. Report, never raise, on the report itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


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


def _identity_ok(name, url):
    """May this url be activated, or persisted as the row's address?

    `is_foreign` is the right gate on an ordinary domain and it works there. On a
    multi-tenant ATS it returns **False for every host by design** (ARCHITECTURE.md section
    2, docs/BACKLOG.md 21: an acquirer's tenant is legitimate, `Momentis Surgical` really
    does post under `memic`), which left this tool - the one with the documented fast path -
    as the last activating path in that class with no identity test at all:

        NanoLock Security  gen.wd1.myworkdayjobs.com/careers/          is_foreign -> False
        Sight Diagnostics  recruiting2.ultipro.com/SIG1008SIGH/...     is_foreign -> False

    `Sight Sciences` is ALREADY ACTIVE on that same `SIG1008SIGH` board, so activating
    `Sight Diagnostics` on it publishes one company's roles under two company names - the
    duplicate-attribution failure section 2 spends a subsection on.

    Scoped deliberately: the page test runs **only** on ATS hosts, where `is_foreign` is
    inert. On an ordinary careers domain nothing changes, because `_page_names_company`
    returns `None` (no evidence) for any page under 2000 chars and a lot of legitimate
    company career pages are JS-rendered - routing those through it would trade this hole
    for silent exclusion, which is section 8's first bug class and exactly the mistake wave
    7 caught in `crack_walled._ok_to_write`.
    """
    if is_foreign(name, url):
        return False
    host = (urlparse(url or "").netloc or "").lower()
    if host and ATS_HOST.search(host):
        return _ok_to_write(name, url)
    return True


def _triaged_page_empty(note):
    """Triage proved this row has a LIVE page with genuinely no roles, so the hunt
    skips it and triage owns the re-check. Module-level on purpose: probe_candidates
    must strip this exact stamp to wake a row, and a private copy would drift."""
    return bool(re.search(r"dark-triage [^|]*:\s*page-empty", note or ""))


def hunt_one(name, seed, documented=False, mode=""):
    """`mode` comes from triage_dark.py and selects the strategy:
       url-dead / no-url  -> ignore the stored seed (it 404s), search first
       extract-gap        -> the page HAS roles; force LLM extraction on the stored URL
       js-shell           -> render+XHR capture (scrape_universal does this natively)
       blocked            -> fetch through the unlocker
       page-empty         -> nothing to hunt; the daily probe watches it
    """
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
        # NOTE: `is_foreign` is a constant False on every ATS host, so this is a weak gate
        # here - 17 rows carrying a fast-path token today have a walled-ATS address. A tenant
        # near-equality check WAS tried and reverted: it rejects 36 ACTIVE rows that are
        # legitimate acquisitions this repo names by name (Momentis Surgical really does post
        # under `memic`, Habana Labs under `intel`, Itamar Medical under `zoll`). An acquirer
        # tenant reached from a URL already documented FOR THIS COMPANY is inheritance, not
        # theft, and `page_mentions_company` cannot separate them either. docs/BACKLOG.md 21.
        if il and not is_foreign(name, seed):
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
    # `mode` was passed in but never read — the docstring above promised strategy routing
    # that did not exist. It matters most here: only cands[:2] are harvested, so for a
    # `url-dead` row the dead seed consumed half the budget and left ONE search result.
    seed_is_bad = mode in ("url-dead", "wrong-page", "no-url")
    cands = [] if (not seed or is_aggregator(seed) or seed_is_bad) else [seed]
    if rebrand:
        cands += [f"https://{rebrand}/careers", f"https://{rebrand}/careers/"]
    cands += [u for u in ddg(f"{name} jobs") if u not in cands]
    if seed_is_bad and seed:
        # keep the dead seed as a LAST resort: triage may have been wrong about it
        cands.append(seed)
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
            # "Real Israel jobs are here" is NOT "these are THIS company's jobs". Without
            # this check the search happily activated FairFly off fireflyspace.com (25
            # roles), COTI off jobs.citi.com, and factify off a DuckDuckGo results page.
            if is_foreign(name, u):
                print(f"       (page belongs to another company -> {u[:60]}: not activated)",
                      flush=True)
                return ("nolisting", u, 0, f"page belongs to another company ({u[:48]})")
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
    def _actionable_mode(note):
        """A fresh triage mode OVERRIDES the 14-day hunt cooldown.

        The cooldown means "the generic hunt already failed here". But a mode means we now
        know WHY it failed and will run a different strategy (search instead of the dead
        seed, LLM extraction instead of regex, unlocker instead of a plain fetch). Without
        this, every row triaged today stays suppressed for 14 days and the modes are dead
        weight — the hunt pool was literally 0 rows before this was added."""
        m = re.search(r"dark-triage (\d{4}-\d{2}-\d{2}): ([a-z-]+)", note or "")
        if not m:
            return False
        if m.group(2) in ("page-empty", "acquired"):
            return False                      # nothing to hunt; the daily probe owns these
        h = re.search(r"listing-hunt (\d{4}-\d{2}-\d{2})", note or "")
        return (not h) or m.group(1) >= h.group(1)   # mode is at least as new as the stamp

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
                             r"aggregator URL|no listing found|redirects to|scanned via brightdata|empty-but-suspect|needs re-resolution|needs manual resolution|"
                             # the stored address was an aggregator or another company's
                             # page: these rows need the hunt more than most
                             r"url-cleared|url-flagged", r[5] or "")
               # alias-of: a second row for a company we already scan at the same url.
               # Re-hunting it re-creates the duplicate this parking exists to remove.
               and not re.search(r"defunct|domain-dead|alias-of", r[5] or "")
               and not is_recruiter(r[0])   # agencies are never activated
               # discovery leaks job titles and category words in as company names
               # ("AppSec", "my team", "Sql developer - X"). Searching for a careers page
               # for a non-company burns the time budget and returns nonsense —
               # remoterocketship.com/company/guildmortgage for "AppSec".
               and not looks_like_junk(r[0])
               # triage proved page-empty rows have a live page with no roles — the daily
               # probe owns them; hunting them again just burns budget. (Explicit helper:
               # inlining this as and/or mixes precedence and silently empties the pool.)
               and not _triaged_page_empty(r[5] or "")
               and ("listing-hunt" not in (r[5] or "") or _stale_hunt(r[5])
                    or _actionable_mode(r[5] or ""))]
    # Least-recently-hunted first. The pool (212 rows) is larger than one night's time
    # budget, and in file order the budget re-walks the same prefix every night while the
    # tail is never touched. Staleness ordering guarantees progress across the whole pool.
    def _hunt_age(r):
        m = re.search(r"listing-hunt (\d{4}-\d{2}-\d{2})", r[1][5] or "")
        if not m:
            return 9999
        return (dt.date.today() - dt.date.fromisoformat(m.group(1))).days

    targets.sort(key=_hunt_age, reverse=True)
    # HUNT_SHARD="i/n" splits the pool across n concurrent processes (1-based i). Striding
    # rather than slicing keeps each shard's staleness mix even, so a shard that dies early
    # doesn't leave one age band untouched. Each shard MUST run in its own working copy —
    # two processes doing read-modify-write on companies.csv lose each other's rows — and the
    # copies are merged back with merge_csv_rows.py against a common base.
    shard = os.environ.get("HUNT_SHARD", "")
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        targets = targets[i - 1::n]
        print(f"shard {i}/{n}: {len(targets)} of the pool", flush=True)
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
                mm = re.search(r"dark-triage \d{4}-\d{2}-\d{2}: ([a-z-]+)", r[5] or "")
                verdict, url, n_il, detail = hunt_one(name, r[3], documented=doc,
                                                      mode=(mm.group(1) if mm else ""))
            except Exception as e:  # noqa: BLE001
                verdict, url, n_il, detail = "dead", None, 0, f"error {str(e)[:50]}"
            # decide BEFORE printing: a line that says [OK] for a row the write branch
            # then refuses is exactly the kind of log that hid a day of bugs here
            refused = ""
            if verdict == "found" and not looks_like_a_job_listing_page(url):
                refused = "not a listings page"
            elif verdict == "found" and not _identity_ok(name, url):
                # This branch sets fr[4] = "true". Until 2026-08-24 the ONLY thing between a
                # hunted URL and an active row was "does the path look like a listings
                # page" - no identity test whatsoever, on the tool whose documented
                # fast-path re-checks rows every night.
                refused = "another company's board"
            stats[verdict] += 1
            tag = "OK" if verdict == "found" and not refused else "XX" if refused else "--"
            print(f"  [{tag}] {n}/{len(targets)} {name}: "
                  f"{url or detail}{f' ({n_il} IL)' if n_il else ''}"
                  f"{f' — {refused}, not activated' if refused else ''}", flush=True)
            if apply:
                # single-writer discipline: re-read before every write; a start-of-run
                # snapshot silently reverts other writers' verdicts (§5 ARCHITECTURE.md)
                fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
                for fr in fresh:
                    if not fr or fr[0] != name or len(fr) < 6:
                        continue
                    if refused:
                        # SCRAPE_ASSUME_IL makes every card on the page an "Israel role", so
                        # a nav menu scores like a board: iai.co.il/solution/
                        # research-academy-space "verified 6 IL" — "Domain Operations",
                        # "Press Releases". A listings page says so in its URL.
                        # Fixed-length and url-free, for the reason crack_walled's note
                        # was cut from 101 to 49 two commits earlier - and this one was
                        # worse. At 97 chars, re-stamping it over the hunt pool evicted the
                        # OLDEST segment from 189 of 274 rows, and on this pool the oldest
                        # segment is `deep-validated ...: unsupported ATS <x>` - which is
                        # `crack_walled`'s ENTIRE pool predicate. Measured on a simulated
                        # night: crack_walled's pool 25 -> 2, and to 0 within 14 nights,
                        # with `check_invariants` and `registry_health` green throughout
                        # because neither has a per-tool floor. `listing_hunt` runs BEFORE
                        # `crack_walled` in listing-hunt.yml, so the collapse lands inside
                        # the same job.
                        #
                        # `refused` carries the real reason: an identity refusal and a
                        # page-shape refusal are different findings and used to be recorded
                        # with the same words, which is the diagnosis the next tool reads.
                        fr[5] = _note_replace(
                            fr[5], "listing-hunt",
                            f"listing-hunt {TODAY}: {refused}; no listing found")
                    elif verdict == "found":
                        fr[1], fr[2], fr[3] = "scrape", "", url
                        fr[4] = "true"
                        # replace only our own segment: the found-branch used to overwrite
                        # the cell and threw away the triage mode that routed the row here
                        fr[5] = _note_replace(
                            fr[5], "listing-hunt",
                            f"listing-hunt {TODAY}: verified {n_il} IL via "
                            f"{urlparse(url).netloc or url[:40]}")
                    elif verdict == "nolisting" and url:
                        # Document the candidate page so a human (and the next hunt) can see
                        # where we looked — but NEVER as the row's address when it provably
                        # belongs to someone else. QuantLR's best candidate was
                        # quantlab.com (a US trading firm) and FairFly's was
                        # fireflyspace.com; persisted, that reads as data, and every later
                        # tool honestly re-tests the wrong company's careers page. Note it
                        # in the note instead, which is text, not an endpoint.
                        if not _identity_ok(name, url):
                            # `is_foreign` alone was the gate here. It is False for every ATS
                            # host, so a walled candidate was persisted into fr[3] with a
                            # `monitored candidate` note - and this tool's own fast path
                            # re-reads that address the next night, so refusing to ACTIVATE
                            # while still writing the ADDRESS only delays the same mistake by
                            # 24 hours. That is the identical shape wave 6 fixed in
                            # `crack_walled` (`novrfy` persisting a `host documented` url).
                            #
                            # host only: the note has a 220-char budget shared with every
                            # other tool's verdict, and a full URL in one segment evicts
                            # them all. The address itself is not being stored anyway.
                            fr[5] = _note_replace(
                                fr[5], "listing-hunt",
                                f"listing-hunt {TODAY}: another company's board; "
                                f"no listing found")
                            continue
                        fr[3] = url                       # persist the candidate page
                        # drop OLD WHOLE segments to make room — slicing the base cut
                        # the newest one in half ("dark-triage 2026-08-22: page-emp")
                        fr[5] = _note_replace(
                            fr[5], "listing-hunt",
                            f"listing-hunt {TODAY}: no IL listing; monitored candidate")
                    else:
                        fr[5] = _note_replace(
                            fr[5], "listing-hunt",
                            f"listing-hunt {TODAY}: "
                            + ("no listing found" if verdict == "nolisting" else detail))
                write_csv_rows("companies.csv", fresh)
    print(f"\n=== listing hunt: {stats} ===", flush=True)


if __name__ == "__main__":
    main()
