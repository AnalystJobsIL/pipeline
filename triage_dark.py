#!/usr/bin/env python3
"""Triage dark rows by FAILURE MODE, so each retry targets the actual problem.

Why this exists: ~348 rows carried the single verdict "no listing found". Re-running the
same hunt against all of them produced the same result, because they do not share a cause.
A sample of 12 showed at least four distinct modes — stale 404s, live pages with roles our
extractor missed, live pages with genuinely no roles, and JS shells needing XHR capture.
One bucket cannot be fixed; four can.

This records the mode in the row note as `dark-triage <date>: <mode>` and lets each mode be
routed to the tool that can actually fix it:

  url-dead          URL 404s / DNS fails      -> listing_hunt must re-FIND the URL
  page-empty        live page, no role text   -> correct verdict; probe daily for change
  extract-gap       role text present, we got 0 -> extractor/LLM problem; retry with LLM on
  js-shell          tiny HTML + job XHRs      -> needs render+XHR capture, not plain fetch
  blocked           403/429/anti-bot          -> needs Bright Data Unlocker
  wrong-page        LLM says it is not this company's careers page -> re-find
  no-url            nothing to check          -> re-discovery

Design notes (long-term soundness):
  * Cheap first: a plain GET classifies most rows; rendering only when the GET is ambiguous.
  * Idempotent + resumable: rows already triaged today are skipped; `--force` re-triages.
  * Single-writer discipline (re-read + name match) and atomic writes, like every other
    csv writer here.
  * The mode is DATA, not control flow: tools select on it, so adding a mode never
    silently strands a row (see ARCHITECTURE "verdict-string rule" — modes are appended,
    the row's original pool token is preserved).

Usage: python triage_dark.py [--apply] [--limit N] [--force] [--render]
Env:   TRIAGE_TIME_BUDGET_MIN
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import sys
import time
import urllib.request

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
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# a page that lists jobs says so, in English or Hebrew
_JOBS_LANG = re.compile(r"open position|current opening|job opening|apply now|we'?re hiring|"
                        r"view (all )?jobs|join our team|משרות|דרושים|הצטרפו", re.I)
# a role-shaped phrase: Title Case words ending in a role noun
_ROLE_PHRASE = re.compile(
    r"[A-Z][A-Za-z/&+.\- ]{3,44}\b(Engineer|Analyst|Manager|Developer|Scientist|Designer|"
    r"Architect|Specialist|Lead|Director|Researcher|Consultant|Associate)\b")
_ACQUIRED = re.compile(
    r"(is |has been |was )?(now )?(part of|acquired by|joins?|joining) ([A-Z][A-Za-z0-9.\- ]{2,30})|"
    r"acquisition of|we(?:'| a)re now ([A-Z][A-Za-z0-9.\- ]{2,30})", re.I)
_JOB_XHR = re.compile(r"(api|graphql)[^\"']*(job|position|opening|career|search)|"
                      r"(job|position|opening)[^\"']*(api|json)", re.I)

# `dark-triage` is in this pool ON PURPOSE: triage rewrites the note it matched on, and the
# 220-char cap trims the base a little more on each re-stamp. Rows whose original verdict got
# eroded (Ford's "no IL listing; monitored candidate" was chopped to "no ") then matched
# nothing and left every recurring pool — 8 companies were owned by no scheduled tool at all.
# Matching our own stamp makes triage self-sustaining regardless of base-note erosion.
TARGET_NOTES = re.compile(r"no listing found|no IL listing|no ATS detected|dark-triage", re.I)
SKIP_NOTES = re.compile(r"defunct|domain-dead|recruiter|duplicate|redundant|alias-of",
                        re.I)


def fetch(url, timeout=15):
    """Returns (status, html). status None = unreachable; -1 = blocked."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                                   "Accept-Language": "en,he;q=0.8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(800_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return (-1 if e.code in (401, 403, 429) else e.code), ""
    except Exception:  # noqa: BLE001
        return None, ""


_LLM_USED = {"n": 0}


def llm_page_verdict(company, url, text):
    """Ask Claude two things a regex cannot judge: is this actually THIS company's careers
    page, and does it list open roles? Used to confirm `page-empty` (a regex saying "no
    roles" is an unverified assumption — it may be the wrong page, or roles in Hebrew /
    an unusual format). Returns (verdict, detail) or None if unavailable.
      verdict: 'confirmed-empty' | 'has-roles' | 'wrong-page'
    """
    import shutil
    import subprocess
    cap = int(os.environ.get("TRIAGE_LLM_CAP", "120"))
    if _LLM_USED["n"] >= cap or not shutil.which("claude"):
        return None
    _LLM_USED["n"] += 1
    nl = chr(10)
    prompt = (
        'Company: "' + company + '"' + nl
        + "Page URL: " + url + nl + nl
        + "Below is the visible text of a web page. Answer STRICTLY as JSON:" + nl
        + '{"is_careers_page_for_this_company": true/false, '
        + '"open_roles": ["exact role titles listed; [] if none"], '
        + '"note": "one short phrase"}' + nl
        + "Count a role only if the page actually lists it as an open position (ignore "
        + "'no openings' / 'send us your CV' text, team blurbs and testimonials). "
        + "Roles may be in Hebrew." + nl + nl + "PAGE TEXT:" + nl + text[:7000])
    try:
        p = subprocess.run(["claude", "-p"], input=prompt, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120,
                           shell=(os.name == "nt"))
        import json as _json
        m = re.search(r"\{.*\}", p.stdout or "", re.S)
        if not m:
            return None
        d = _json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    if not d.get("is_careers_page_for_this_company", True):
        return ("wrong-page", f"LLM: not {company}'s careers page ({str(d.get('note',''))[:40]})")
    roles = [r for r in (d.get("open_roles") or []) if isinstance(r, str) and r.strip()]
    if roles:
        return ("has-roles", f"LLM found {len(roles)}: {', '.join(roles[:2])[:60]}")
    return ("confirmed-empty", f"LLM confirms no open roles ({str(d.get('note',''))[:34]})")


def classify(url, render=False, company=""):
    """-> (mode, detail). Cheap GET first; optional render for js-shell confirmation."""
    if not url or not url.startswith("http"):
        return "no-url", "no url on the row"
    status, html = fetch(url)
    if status is None or status == -1 or status >= 400:
        # Before declaring a URL dead: (a) anti-bot 403s are NOT dead — retry via the
        # unlocker; (b) a 404 careers page on a live domain is often an ACQUISITION, whose
        # fix is recording the acquirer, not re-hunting. Check the homepage.
        import urllib.parse as _up
        host = _up.urlparse(url).netloc
        home_st, home_html = fetch(f"https://{host}/") if host else (None, "")
        if home_st and home_st < 400 and home_html:
            plain = re.sub(r"<[^>]+>", " ", home_html)
            head = re.sub(r"\s+", " ", plain)[:1200]
            m = _ACQUIRED.search(head)
            if m:
                return "acquired", f"homepage says: {m.group(0)[:60]}"
        if status == -1 and os.environ.get("BRIGHTDATA_API_KEY"):
            try:
                from bd_rescue import unlock
                un = unlock(url)
                if un and len(un) > 2000:
                    html, status = un, 200      # unblocked — continue classification below
                else:
                    return "blocked", "403/429, unlocker also failed"
            except Exception:  # noqa: BLE001
                return "blocked", "403/429 — needs unlocker"
        elif status == -1:
            return "blocked", "403/429 — needs unlocker"
        elif status is None:
            return "url-dead", "unreachable (dns/conn)"
        else:
            return "url-dead", f"http {status}"

    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    roles = set(_ROLE_PHRASE.findall(text)) if _ROLE_PHRASE.search(text) else set()
    n_roles = len(set(m.group(0) for m in _ROLE_PHRASE.finditer(text)))
    has_lang = bool(_JOBS_LANG.search(text))

    if n_roles >= 2:
        # Role-shaped phrases are NOT proof of open positions: staff bios ("Anne Hopkins
        # DevOps Engineer") and testimonial walls match the same pattern. page-empty was
        # already LLM-confirmed; extract-gap must be too, or we send the repair loop after
        # team pages. The LLM decides open-roles vs bios, and returns js-shell when the
        # plain fetch shows nothing a render would.
        v = llm_page_verdict(company, url, text) if company else None
        if v:
            kind, detail = v
            if kind == "has-roles":
                return "extract-gap", detail
            if kind == "wrong-page":
                return "wrong-page", detail
            return "page-empty", f"{detail} (role phrases were bios/testimonials)"
        return "extract-gap", f"{n_roles} role phrases in plain HTML, extractor got 0 (unconfirmed)"
    if len(html) < 60_000 and _JOB_XHR.search(html):
        return "js-shell", "thin html + job-ish XHR — needs render+capture"
    if render:
        try:
            from deep_validate import Renderer
            with Renderer() as rend:
                rhtml, reqs, _ = rend.sniff(url)
            rtext = re.sub(r"<[^>]+>", " ", rhtml or "")
            rn = len(set(m.group(0) for m in _ROLE_PHRASE.finditer(rtext)))
            if rn >= 2:
                return "extract-gap", f"{rn} role phrases after render"
            if any(_JOB_XHR.search(q) for q in reqs):
                return "js-shell", "job XHRs seen during render"
        except Exception:  # noqa: BLE001
            pass
    # A regex "no roles" is an assumption. Confirm with the LLM: right page? really empty?
    v = llm_page_verdict(company, url, text) if company else None
    if v:
        kind, detail = v
        if kind == "has-roles":
            return "extract-gap", detail          # roles exist -> our extractor is the gap
        if kind == "wrong-page":
            return "wrong-page", detail           # need to find the real careers page
        return "page-empty", detail               # LLM-confirmed empty
    if has_lang:
        return "page-empty", "careers page live, no roles listed (regex only, unconfirmed)"
    return "page-empty", "no jobs language and no roles (regex only, unconfirmed)"


TRIAGE_TTL_DAYS = 10


def _triage_age(row):
    """Days since this row was last triaged; 9999 if never."""
    m = re.search(r"dark-triage (\d{4}-\d{2}-\d{2})", row[5] or "")
    if not m:
        return 9999
    return (dt.date.today() - dt.date.fromisoformat(m.group(1))).days


def _needs_triage(note: str) -> bool:
    """Re-triage only STALE rows, not everything not done today.

    A nightly re-stamp is not merely wasteful: `listing_hunt._actionable_mode` treats a
    triage date >= the hunt stamp as "hunt this now", so re-dating all 352 rows every night
    cancelled the hunt's 14-day cooldown and pinned it to the same prefix of the pool.
    """
    m = re.search(r"dark-triage (\d{4}-\d{2}-\d{2})", note or "")
    if not m:
        return True
    return (dt.date.today() - dt.date.fromisoformat(m.group(1))).days >= TRIAGE_TTL_DAYS


def main():
    apply = "--apply" in sys.argv
    force = "--force" in sys.argv
    render = "--render" in sys.argv
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    budget = int(os.environ.get("TRIAGE_TIME_BUDGET_MIN", "0"))

    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    targets = [r for r in rows
               if r and len(r) >= 6 and r[4] == "false"
               and TARGET_NOTES.search(r[5] or "") and not SKIP_NOTES.search(r[5] or "")
               and (force or _needs_triage(r[5] or ""))]
    # Oldest verdict first. With a time budget and file-order targets, the same prefix gets
    # re-processed every night and the tail is NEVER reached; sorting by staleness makes the
    # budget walk the whole pool over successive nights.
    targets.sort(key=_triage_age, reverse=True)
    if limit:
        targets = targets[:limit]
    print(f"triaging {len(targets)} dark rows (render={render})\n", flush=True)

    counts, t0 = {}, time.time()
    for n, r in enumerate(targets, 1):
        if budget and (time.time() - t0) / 60 > budget:
            print(f"time budget {budget}min reached — stopping cleanly", flush=True)
            break
        mode, detail = classify(r[3], render=render, company=r[0])
        counts[mode] = counts.get(mode, 0) + 1
        print(f"  [{mode:11}] {n}/{len(targets)} {r[0][:30]:30} {detail[:44]}", flush=True)
        if apply:
            fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
            for fr in fresh:
                if fr and fr[0] == r[0] and len(fr) >= 6:
                    # Drop OLD WHOLE segments to make room. Slicing the base cut the
                    # newest segment in half instead — 87 rows read `page-emp`, and one
                    # `pa` — and a mode no filter matches drops the row from its pool.
                    fr[5] = _note_replace(fr[5], "dark-triage",
                                          f"dark-triage {TODAY}: {mode} ({detail})")
            write_csv_rows("companies.csv", fresh)
        time.sleep(0.2)

    print(f"\n=== triage: {counts} ===", flush=True)
    print("routing: url-dead/no-url -> listing_hunt re-find · extract-gap -> LLM extraction "
          "· js-shell -> render+capture · blocked -> unlocker · page-empty -> daily probe",
          flush=True)


if __name__ == "__main__":
    main()
