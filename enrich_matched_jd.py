#!/usr/bin/env python3
"""Backfill JD text for EVERY matched role, whatever its source or age.

`enrich_scrape_jd.py` fills descriptions in `scraped_cache.json` — only scrape-source
companies. But six list endpoints return no description at all (workday, smartrecruiters,
bamboohr, microsoft, eightfold, phenom — see `pipeline/jdfill.py`), so those roles reach the
board with a title and nothing else, and a classifier that judged on the title alone.

This walks the `matched` table itself — the one place that holds every role we ever
accepted — and fills any row whose stored description is too short to be a real JD. It is
deliberately age-blind about when a role was FIRST seen: a role first seen last week that we
never got the text for is exactly the case the board is missing today. It is not age-blind
about whether the role still exists (see `dead_role_ids`).

    text we already hold for THIS role at another of its own addresses   (no request at all)
      -> native JSON -> plain GET (+ schema.org) -> Bright Data Web Unlocker (capped)
      -> store, or stamp `jd_attempted` ("YYYY-MM-DD", or "YYYY-MM-DD transient" for a
         failure worth retrying tomorrow rather than in 7 days).

Idempotent, safe to re-run, never shortens a description it already has, and records what it
did — including what it SPENT — in the `enrich` stage stamp so the daily mail can say when it
failed.

Usage: python enrich_matched_jd.py [--db cloud_state/seen.db] [--limit N] [--dry-run]
                                   [--cooldown-days 7] [--cache scraped_cache.json]
Env:   MATCHED_JD_TIME_BUDGET_MIN (default 25), MATCHED_JD_BD_CAP (default 25)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
from collections import Counter
import hashlib
import sys
import time

from pipeline import jdfill
from pipeline.jdfill import (DESC_MAX, GONE_MARK, MIN_DESC, RETRY_DAYS, Item, Unlocker,
                             _REPO_ROOT, alarm_for, doc_names_role, due, fetch_jd, is_job_url,
                             jd_body, jd_quality, load_secrets, retry_days_for,
                             looks_like_jd, native_candidates, plain_fetch, quality_suspect,
                             role_addresses_on, source_copy_url, title_in_slug,
                             record_enrich, run_backfill, stamp_path_for,
                             unfillable as _unfillable, wayback_snapshot, why_string)

for _s in (sys.stdout, sys.stderr):        # a cp1252 pipe must not kill the report
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


DB = os.path.join("cloud_state", "seen.db")
CACHE = "scraped_cache.json"
# 2026-08-26: was 250, against a 5,000-credit MONTHLY pool already at 118 %. Measured need
# over the three preceding days: 4, 2, 3. This is a runaway backstop, not an allowance.
BD_CAP = 25
# `purged` too: `roles.sweep_store` treats it as not-live, and this filter must not be the one
# place in the repo that thinks a purged role is worth fetching.
DEAD_STATUSES = ("closed", "superseded", "purged")


def dead_role_ids(path):
    """`role_id`s the ledger says are closed, superseded or purged. The ledger (`roles` lane,
    ARCHITECTURE.md §7c) is the record of whether a role is still open; a closed role's
    posting has been deleted, so fetching it is guaranteed waste — on 2026-08-26 one such row
    (Taboola, last seen nine days earlier and gone from an 84-job board) spent a Bright Data
    credit while the shared pool stood at 118 % of the monthly free allowance.

    Reads through `roles.load`, the ledger's OWN reader, rather than parsing it here: that one
    decodes `utf-8-sig`, tolerates CRLF and skips the odd bad line, and resolves a duplicate
    `role_id` by the newer `updated`. A hand-written parser disagreed with it on all four —
    and a single BOM (which every PowerShell `>` redirect on this machine writes) turned the
    whole filter off, putting Taboola straight back into the todo.

    Never raises: the ledger belongs to another lane and may be absent, mid-write or corrupt.
    Returns `(None, why)` in that case, and the caller then filters NOTHING and alarms."""
    try:
        from pipeline import roles as _roles
        records, status, _skipped = _roles.load(path)
    except Exception:  # noqa: BLE001
        return None, "unreadable"
    if status != "ok":
        return None, status                  # `missing` and `corrupt` are different news
    return ({rid for rid, r in records.items()
             if str((r or {}).get("status") or "") in DEAD_STATUSES}, "ok")


def sibling_urls(seen_ids, canonical):
    """Every OTHER address this role was seen at, from `matched.seen_ids`.

    A role's canonical url is whichever copy won `store.merge_duplicates`, and that contest is
    decided by who carries a posted-date — not by who can be read. Zipher's Data Analyst is
    the worked example (2026-08-26): the record kept a 170-character Indeed snippet while the
    company's own posting, 2,021 characters of it, sat in `scraped_cache.json` under the
    `scrape:` seen_id of that same role.

    **`seen_ids` is not a list of this role's own addresses**, which is why every caller must
    also check identity. `store.merge_key` is `company|title` and `upsert_matched` unions
    `seen_ids` for ever, and `roles._resolve_claims` unions a losing company's ids into the
    winner's row — so `nift|data analyst` carries five OTHER employers' LinkedIn postings
    (elad-software-systems, g-stat, gotfriends, jobgether, mize), swept off one shared
    listing page. Publishing one of those as Nift's description would put a defence
    integrator's clearance requirement on Nift's card. See `_own_address`.

    A `seen_id` is `<source>:<url>` joined with "+", and "+" is legal in a url, so a column
    that could be ambiguous yields NOTHING rather than a truncated address."""
    parts = [p for p in (seen_ids or "").split("+") if p]
    if any(":" not in p for p in parts):
        return []                       # a "+" inside a url: the column is lossy, do not guess
    out = []
    for sid in parts:
        url = sid.split(":", 1)[1]
        if url.lower().startswith("http") and url != canonical and url not in out:
            out.append(url)
    return out


def _own_address(company, url):
    """Does this address positively name `company`? `pipeline.roles.names_in_url` is the
    repo's existing evidence rule — the same question the role record asks before it lets one
    posting speak for a company. Verified 2026-08-26: True for `zipher.ai/careers/data-analyst/`
    and for Modellama's comeet url (both real wins), False for the elad-software-systems url
    sitting in Nift's `seen_ids`."""
    try:
        from pipeline.roles import names_in_url
        return bool(names_in_url(company, url))
    except Exception:  # noqa: BLE001 - no evidence is not evidence
        return False


def _own_posting(company, title, url):
    """Both halves of the identity question: does this address name this COMPANY, and does
    it name this ROLE?

    The company half alone is what shipped on 2026-08-26, and wave 1 found what it misses:
    `seen_ids` is a merge group, `roles._resolve_claims` unions ids across titles, so a
    different posting at the right employer passes it -- and the cache rung takes the LONGEST
    text it finds. `percepto|senior product analyst` carries
    `/careers/data-insights-operations-ff-c6f/`, and 2,406 characters of that other role were
    stored on this one."""
    return _own_address(company, url) and title_in_slug(url, title)


def cache_texts(path):
    """({(company_lower, url): description}, status) from the scrape cache.

    Keyed by COMPANY as well as url: the cache files a card under the page it was swept from,
    so a url alone can hand one company's text to another. Read-only — the `scraper` lane owns
    this file. An unreadable cache is reported, never swallowed: it silently costs the driver
    its cheapest rung, and on 2026-08-26 that was the only rung that filled anything."""
    try:
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        return {}, "missing"
    except Exception:  # noqa: BLE001
        return {}, "corrupt"
    out = {}
    for comp, jobs in (cache or {}).items():
        for j in jobs or []:
            if isinstance(j, dict) and str(j.get("url") or "").startswith("http"):
                key = (str(comp).strip().lower(), j["url"])
                text = (j.get("description") or "").strip()
                if len(text) > len(out.get(key, "")):
                    out[key] = text
    return out, "ok"


def cache_by_merge_key(path):
    """{merge_key: [(url, description)]} over the scrape cache — the SAME cards `cache_texts`
    reads, indexed by the repo's own role identity instead of by address.

    The existing sibling rung can only see a card whose url is already in this role's
    `seen_ids`, and a card only gets there by being seen in the same run as the role. Questar
    is the counterexample that names the gap: its employer board was converted to
    `questar.applytojob.com` on 2026-08-26, five days after the role closed, so its own
    6,000-character posting was swept into this cache under a url the role has never heard
    of. `store.merge_key` is what says they are the same role, and it costs nothing to ask.

    Read-only; the `scraper` lane owns this file. Cards with no text are skipped — an index
    of empty strings is a slower way to find nothing."""
    try:
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:  # noqa: BLE001 - `cache_texts` already alarms on an unreadable cache
        return {}
    from pipeline.store import merge_key
    out = {}
    for comp, jobs in (cache or {}).items():
        for j in jobs or []:
            if not isinstance(j, dict) or not str(j.get("url") or "").startswith("http"):
                continue
            text = (j.get("description") or "").strip()
            if not text:
                continue
            # `merge_key` reaches `title`/`company`, which `cache_texts` never touches, so a
            # card with a non-string there took the whole driver down behind a
            # continue-on-error step (wave B). That file is the `scraper` lane's.
            j = dict(j, company=str(j.get("company") or comp), title=str(j.get("title") or ""))
            out.setdefault(merge_key(j), []).append((j["url"], text))
    return out


def _store_text(conn, mkey, text, have):
    """Write `text` unless what is already stored is a better JD.

    "Never shorten" was the whole rule, and it is right between two job descriptions — but it
    is exactly wrong between page furniture and a job description. Ecoppia's row held 3,999
    characters of Google Tag Manager and a nav bar; the clean 2,100-character JD the fetch
    returned is shorter, and the old UPDATE refused it. So: a real JD always beats text that is
    not one, and only after both sides are JDs does length decide."""
    text, have = (text or "")[:DESC_MAX], have or ""
    if looks_like_jd(have) and not looks_like_jd(text):
        return False
    if looks_like_jd(have) == looks_like_jd(text) and len(text) <= len(have):
        return False
    # A `structural:` reason is a claim that this row has NO readable description, and it is
    # published as such by the `roles` export. The moment any path writes one, that claim is
    # false — and the two paths that fill a row without going through the donor pass (the
    # cache-sibling rung, a re-clean) never touched `jd_why`, so a stale blocker outlived the
    # text that disproved it (wave A). This is the one choke point every write passes.
    # ...and the clause is written so a store WITHOUT the column still stores its text: the
    # column is added by `_ensure_columns` at driver start, but `_store_text` is a library
    # function and a caller may hand it any `matched`-shaped table.
    try:
        conn.execute("UPDATE matched SET description=?, "
                     "jd_why=CASE WHEN COALESCE(jd_why,'') LIKE 'structural:%' "
                     "THEN '' ELSE COALESCE(jd_why,'') END WHERE mkey=?", (text, mkey))
    except sqlite3.OperationalError:
        conn.execute("UPDATE matched SET description=? WHERE mkey=?", (text, mkey))
    return True


_QUALITY_CONTRACT = hashlib.sha1(
    (jdfill._QUALITY_SYSTEM + jdfill._QUALITY_SCHEMA + jdfill.JD_QUALITY_MODEL)
    .encode("utf-8")).hexdigest()[:12]
QUALITY_CAP = 60
# The tier runs BEFORE the fetch loop and is not inside its budget, so it needs its own or it
# spends the step timeout. Measured 2026-08-28: 7.8 s per uncached call, so the 60-call cap
# alone is 7.8 minutes on top of the 20-minute fetch budget -- 27.8 against a 25-minute step.
# Four minutes is about 30 calls, which is more than a day ever brings once the backlog is
# cleared, and it leaves the fetch budget whole.
QUALITY_BUDGET_MIN = 4.0
# A re-clean is a MASS change to stored text, and CLAUDE.md rule 2 says a mass result is a
# broken run until proven otherwise. On 2026-08-28 the honest number was 17 of 542 stored
# bodies (3.1 %%); anything above this ceiling means the furniture rule has started matching
# ordinary prose, and the run refuses rather than rewriting the store.
RECLEAN_MAX_SHARE = 0.15
# what the archived pass gets first refusal on, so it cannot be starved by the live one
ARCHIVED_BUDGET_SHARE = 0.25


def _reclean(conn, every, dry_run):
    """Cut the page furniture off the tail of text ALREADY in the store. No requests, no
    credits, and the only path in this lane permitted to shorten a description.

    `looks_like_jd` judges `jd_body(text)`, so a row whose furniture starts late still reads
    as a job description and never enters the todo -- but the board renders what is STORED,
    and on 2026-08-28 that was 60,015 characters of LinkedIn sign-in form across 17 bodies,
    twelve of them open. Judging the posting and publishing the page is the worst of both."""
    todo = [(r[0], r[6], jd_body(r[6])) for r in every]
    # `looks_like_jd(new)`, not `len(new) >= MIN_DESC`. The cut takes the EARLIEST marker,
    # and on a Hebrew LinkedIn page the sign-in block renders BEFORE the posting -- so for
    # three rows the rule kept 367-682 characters of navigation and deleted the description.
    # Migdal Group was left with `... | מקומות תעסוקה ב-LinkedIn / דילוג לתוכן הראשי ...` and 5,633
    # characters carrying דרישות / אחריות / ניסיון were thrown away (wave 2). It survived only
    # because the fetch that followed happened to answer; a rate limit or a spent budget and
    # the board would have shown a navigation menu with the posting unrecoverable from
    # either store. A cut whose RESULT is not a job description is not a cut worth making --
    # the row stays as it is, fails `looks_like_jd` anyway, and goes to the fetch.
    # Measured: 16 rows/56,463 chars under the old guard, 13 rows/39,969 under this one,
    # and the three spared are exactly the three that were damaged.
    todo = [(k, old, new) for k, old, new in todo if new != old and looks_like_jd(new)]
    if not todo:
        return 0, 0, {}
    share = len(todo) / float(len(every) or 1)
    if share > RECLEAN_MAX_SHARE:
        print(f"::warning::reclean REFUSED: {len(todo)} of {len(every)} rows "
              f"({share:.0%}) would be shortened, over the {RECLEAN_MAX_SHARE:.0%} ceiling. "
              f"That is a furniture rule matching prose, not a store full of login walls.",
              flush=True)
        return -len(todo), sum(len(o) - len(n) for _k, o, n in todo), {}
    cut = 0
    for mkey, old, new in todo:
        cut += len(old) - len(new)
        print(f"  [CUT] {mkey[:58]:<58} {len(old):>5} -> {len(new):<5} "
              f"(-{len(old) - len(new)} of page furniture)", flush=True)
        if not dry_run:
            conn.execute("UPDATE matched SET description=? WHERE mkey=?", (new, mkey))
    if not dry_run:
        conn.commit()
    return len(todo), cut, {k: new for k, _old, new in todo}


def _quality_pass(conn, every, dry_run):
    """Ask the LLM tier about the rows the keyword rules cannot settle, and return the set of
    `mkey`s whose stored text is NOT the employer complete posting.

    A tier, not a pass: `jdfill.quality_suspect` picks the candidates for nothing, and only
    those are paid for. Verdicts are cached on the sha1 of the TEXT in the existing
    `llm_cache` table under a `jdq1|` namespace -- `classifier` owns that table and every one
    of its keys begins `v2|`, so the two cannot collide and this needs no new state file
    (which would need an `infra` persist strategy and a section 5 row).

    An unavailable model returns nothing: the cheap rule verdict stands. A tier that could
    demote a role on an outage would empty the board every time the token expired."""
    if os.environ.get("JD_QUALITY", "1") == "0":
        return set(), Counter()
    # Keyed by the TEXT alone, never by (company, text). One careers page fanned across
    # SEVERAL EMPLOYERS is docs/BACKLOG.md 370 in its worst form, and a company-keyed
    # counter can never reach 2 for it: `otorio|senior data analyst` carries 3,556
    # characters that open "Armis, the cyber exposure management & security company",
    # byte-identical to the Armis row, and neither was flagged (wave 2).
    by_text = Counter(r[6] for r in every if looks_like_jd(r[6]))
    cand = []
    for r in every:
        if not looks_like_jd(r[6]):
            continue                       # already in the todo; nothing to adjudicate
        shared = by_text[r[6]] > 1
        why = quality_suspect(r[6], shared=shared)
        if why:
            cand.append((r, why))
    cache = dict(conn.execute(
        "SELECT title_key, verdict FROM llm_cache WHERE title_key LIKE 'jdq1|%'").fetchall())
    cap = int(os.environ.get("JD_QUALITY_LLM_CAP", str(QUALITY_CAP)))
    budget = float(os.environ.get("JD_QUALITY_TIME_BUDGET_MIN", str(QUALITY_BUDGET_MIN)))
    t0 = time.time()
    c, incomplete = Counter(), set()
    c["candidates"] = len(cand)
    for r, why in cand:
        body = jd_body(r[6])
        # The key carries the PROMPT it was judged under, not just the text. Editing the
        # question would otherwise leave every stored verdict standing for ever -- the trap
        # `classifier` closed with a contract-hashed key one day earlier. It also carries the
        # title and company, because the question is "is this the posting FOR THIS ROLE" and
        # two employers can hold byte-identical text (see `by_text` above).
        key = "jdq1|" + hashlib.sha1(("%s|%s|%s|%s" % (_QUALITY_CONTRACT, r[1], r[2], body))
                                     .encode("utf-8", "replace")).hexdigest()
        if key in cache:
            c["cached"] += 1
            ok = bool(cache[key])
        elif c["calls"] >= cap or (time.time() - t0) / 60 > budget:
            c["capped"] += 1
            continue                       # no verdict is not a demotion
        else:
            c["calls"] += 1
            ok, verdict = jd_quality(body, r[2], r[1])
            if ok is None:
                c["unavailable"] += 1
                c["why:" + str(verdict)] += 1
                continue                   # the cheap rule stands
            if not dry_run:
                conn.execute("INSERT INTO llm_cache (title_key, verdict, updated) "
                             "VALUES (?,?,?) ON CONFLICT(title_key) DO UPDATE SET "
                             "verdict=excluded.verdict, updated=excluded.updated",
                             (key, 1 if ok else 0,
                              dt.datetime.now(dt.timezone.utc).date().isoformat()))
                conn.commit()
        c["complete" if ok else "rejected"] += 1
        if ok:
            continue
        # An incomplete text is a TODO only when some rung of ours could improve it. A row
        # sitting exactly on `DESC_MAX` is incomplete because WE truncated it: re-fetching
        # returns the same 6,000 characters, `_store_text` correctly declines to rewrite them,
        # and the role would come back every week for ever having changed nothing. That is
        # docs/BACKLOG.md 341 and the cap is not this lane to raise (`DESC_MAX` is pinned to
        # the store cap by a test). So it is judged, counted and REPORTED as truncated -- the
        # same distinction the layer already draws with `unfillable`: nothing to fetch here,
        # and nobody failure.
        if why == "at-desc-max":
            c["truncated"] += 1
            print(f"  [LLM] {(r[1] + ' | ' + r[2])[:60]:<60} truncated at DESC_MAX "
                  f"({len(body)} chars) -> incomplete, and no rung of ours can fix it "
                  f"(BACKLOG 341)", flush=True)
            continue
        incomplete.add(r[0])
        print(f"  [LLM] {(r[1] + ' | ' + r[2])[:60]:<60} not a complete posting "
              f"({why}, {len(body)} chars) -> back in the todo", flush=True)
    return incomplete, c


def _ensure_columns(conn):
    """`jd_attempted` is declared by `pipeline/store.py`; `jd_tries` and `jd_why` are this
    layer's own and are added here, the same way `jd_attempted` was before the store adopted
    it. `jd_tries` counts DEFINITIVE failures only, and exists so the backoff can widen
    without a role ever leaving the pool (`jdfill.retry_days_for`). Declared to the `roles`
    and `infra` lanes, who own that table.

    `jd_why` (2026-08-31 evening) is the per-row REASON, which until now existed only inside
    a run: `jd_attempted` collapses every outcome to a date plus `transient`/`gone`, so the
    morning after, a row refused for `not-a-job-url` was indistinguishable from one refused
    for `auth-walled`, and no lane could state its own number without re-running the night
    (`docs/BACKLOG.md` 443, this lane's half). It carries both halves of what a reader needs:

        ok:<kind>:<where>     a fill, and WHICH copy of the role produced it
        structural:<reason>   every copy we hold has been tried and none can be read
        refused:identity(N)   N copies were found and none of them names this role

    The `structural:` prefix is written only by `_donor_pass`, and only once every donor class
    has actually been enumerated — it is a statement about the world, not about a budget. The
    `roles` lane reads it verbatim into `description_blocker` in the published dataset
    (agreed 2026-08-31 with that lane's session b; `ok:`/`refused:` are never blockers)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matched)")}
    for name, decl in (("jd_attempted", "TEXT"), ("jd_tries", "INTEGER"), ("jd_why", "TEXT")):
        if name not in cols:
            conn.execute("ALTER TABLE matched ADD COLUMN %s %s" % (name, decl))
    conn.commit()


# --------------------------------------------------------------- the role's other copies
# The last rung, and the one that answers the operator's 2026-08-31 rule: a role whose own
# board gives us nothing is not finished while we still hold another copy of THAT ROLE. Four
# donor classes, cheapest first, every one bound to the role rather than to the company:
#
#   own-address   the employer's own listing page links to this posting (`role_addresses_on`)
#   cache         a card another pass already swept, whose `store.merge_key` IS this row's
#   copy          a LinkedIn/Indeed copy this role's own `seen_ids` name
#   archive       a Wayback snapshot of the role's OWN canonical address
#
# `own-address`, `cache` and `archive` are identified structurally — an address on the
# employer's own page naming this role, the repo's own merge identity, the role's own url —
# so their text is admitted once it reads as a job description. `copy` is the dangerous one:
# it is fetched at an address that belongs to somebody else's site, so it is admitted ONLY
# when the fetched document DECLARES ITSELF to be this title at this employer
# (`doc_names_role`). That is deliberately not `names_in_url`, which `store._same_origin`
# refuses by measurement as an admission gate on foreign content, and deliberately not
# byte-similarity, which is the fanout SYMPTOM (`370`), not an identity.
DONOR_CLASSES = ("own-address", "cache", "copy", "archive")
# The donor pass runs AFTER the fetch passes have spent `MATCHED_JD_TIME_BUDGET_MIN` (20)
# inside a step `daily-digest.yml` gives 25 minutes, so it needs a bound of its own or it
# becomes the thing that ends the step. It is cheap per row today — 7 rows measured at ~2
# minutes worst case — but the pool it walks is "every row the ladder could not fill", which
# grows with the store. A budget in MINUTES rather than rows, for the same reason
# `run_backfill` uses one: the rows left over resume tomorrow, oldest first, and nothing is
# silently dropped.
DONOR_BUDGET_MIN = 4.0


def _donor_candidates(row, cache_by_key, log):
    """`([(kind, url, text)], complete)` — every copy of THIS role we could read, and whether
    the enumeration itself SUCCEEDED. `text` is set only for a donor we already hold (no
    fetch); the rest carry an address to try.

    Enumeration is allowed to be generous: nothing here is admitted, and the caller applies
    the gate that matches the class. It costs at most ONE free GET (the listing page), and
    only for a row whose canonical address cannot name a posting.

    `complete` is False when a class could not be asked rather than answering nothing — the
    listing page did not respond, the archive lookup failed. The caller may only write
    `structural:` when it is True: "no copy of this role can be read" is a claim about the
    world that another lane PUBLISHES, and a network error is not evidence for it (wave A)."""
    mkey, comp, title, url, att, seen_ids, _have, _tries, _last = row
    out, complete = [], True
    # 1. a card we already hold whose merge identity IS this role's. `store.merge_key` is the
    #    repo's own answer to "is this the same role", so a card carrying it would have merged
    #    into this row had the two been seen in one run — Questar's own-board posting was
    #    scraped five days AFTER the role closed, so it never was.
    #    A merge key is location-blind, so two requisitions can share it (measured: 1 of 1,305
    #    keys in today's cache, `applied materials israel|senior software engineer`). Two
    #    candidates that equally claim to be this role mean the cache cannot tell us which is
    #    ours, and taking the first is the coin flip `role_addresses_on` already refuses.
    own = [(c_url, c_text) for c_url, c_text in cache_by_key.get(mkey, [])
           if _own_posting(comp, title, c_url)]
    if len(own) == 1:
        out.append(("cache", own[0][0], own[0][1]))
    elif own:
        log(f"  [X  ] {(comp + ' | ' + title)[:56]:<56} {len(own)} cache cards claim this "
            f"role; none admitted (the cache cannot say which is ours)")
    # 2. the employer's own listing page names this posting. Only for a canonical that cannot
    #    identify a posting on its own — that is exactly the `not-a-job-url` class, 9 Bylith
    #    cards and 3 G Stat cards sharing one address each.
    if str(url or "").startswith("http") and not is_job_url(url, title):
        job_id = ""
        for sid in str(seen_ids or "").split("+"):
            if ":" in sid and not sid.split(":", 1)[1].lower().startswith("http"):
                job_id = sid.split(":", 1)[1]
                break
        status, body = plain_fetch(url, timeout=25)
        found = role_addresses_on(body, url, title, job_id) if body else []
        if not body:
            complete = False               # the page did not answer: we did not look
        log(f"  [LST] {(comp + ' | ' + title)[:56]:<56} listing page {status or 'no-answer'}"
            f" -> {len(found)} address(es) naming this role")
        out.extend(("own-address", a, "") for a in found)
    # 3. the copies this role's own seen_ids name. The http ones come through
    #    `sibling_urls`, which carries the lossy-column guard this used to re-implement
    #    without it — a `+` inside a url is indistinguishable from the store's own `+` join,
    #    and re-parsing by hand yielded a TRUNCATED address that was then fetched (wave B).
    #    The discovery ids are `<source>:<platform>:<id>`, which no rung could ever ask for.
    for addr in sibling_urls(seen_ids, url or ""):
        if addr not in [u for _k, u, _t in out]:
            out.append(("copy", addr, ""))
    for sid in str(seen_ids or "").split("+"):
        if ":" not in sid:
            continue
        addr = source_copy_url(sid.split(":", 1)[1])
        if addr and addr != url and addr not in [u for _k, u, _t in out]:
            out.append(("copy", addr, ""))
    # 4. the archive, for an address that no longer answers. Identity is exact: it is a
    #    snapshot OF this role's own url.
    if str(att or "").endswith(GONE_MARK) and str(url or "").startswith("http"):
        snap = wayback_snapshot(url)
        if snap is None:
            complete = False               # the CDX call failed: the archive was not asked
        elif snap:
            out.append(("archive", snap, ""))
    return out, complete


def _donor_pass(conn, rows, cache_by_key, bd, paid_keys, args, log, today=None,
                retry_days=RETRY_DAYS, count_cap=0):
    """Fill what the ladder could not, from another copy of the same role. Returns
    (filled, refused, Counter of `jd_why` values written).

    `paid_keys` is the set of `mkey`s allowed to reach the Unlocker; every other row is
    worked on the free rungs alone, and inside `paid_keys` the 7/14/28 cooldown still
    decides whether tonight is this row's turn to spend."""
    filled, refused, why_written = 0, 0, Counter()
    budget = float(os.environ.get("MATCHED_DONOR_BUDGET_MIN", str(DONOR_BUDGET_MIN)))
    today, t0, worked = today or dt.date.today(), time.time(), 0
    for row in rows:
        if budget and (time.time() - t0) / 60 > budget:
            why_written["budget-spent"] += 1
            continue                       # tomorrow's work, and the counter says so
        # `--limit N` is an operator saying "do N rows", and it bound the fetch passes while
        # this one walked everything behind it (wave B: `--limit 1` worked three rows and
        # spent four credits).
        if count_cap and worked >= count_cap:
            why_written["cap-spent"] += 1
            continue
        mkey, comp, title, url, att, seen_ids, have, tries, _last = row
        comp, title = str(comp or ""), str(title or "")
        # THE COOLDOWN GOVERNS THE PAID RUNG HERE TOO, and that single condition closes three
        # holes at once (wave B): a row stamped yesterday is not re-bought tonight; a
        # `gone`-terminal row never spends at all, because `due()` never brings a `gone` stamp
        # round again; and the nightly re-buy of a row that will never fill cannot happen,
        # because the fetch passes stamp it and the 7/14/28 ladder widens. The FREE donors run
        # for every row regardless — that is the whole point of the rung, and it costs nothing
        # (`run_backfill.free_rungs_ignore_cooldown`, the same split).
        row_bd = bd if (mkey in paid_keys
                        and due(att, today, definitive=retry_days_for(tries, retry_days))
                        ) else None
        label = (comp + " | " + title)[:56]
        # A donor is a LAST resort: it may fill a row that has no job description, never
        # improve one that has. `_store_text`'s ratchet is a LENGTH ratchet once both sides
        # are job descriptions, and `donor_rows` includes the rows the LLM tier judged
        # incomplete — which still pass `looks_like_jd` — so a longer DIFFERENT opening
        # replaced a role's own posting (wave A, reproduced). Nothing in this pass may
        # overwrite text that already reads as this role's description.
        if looks_like_jd(have):
            continue
        cands, complete = _donor_candidates(row, cache_by_key, log)
        worked += 1
        text, why, seen_identity = "", "", 0
        for kind, addr, held in cands:
            if _unfillable(addr):
                continue
            if held:                       # a donor we already hold: no request at all
                if looks_like_jd(held):
                    text, why = held, "ok:%s:%s" % (kind, jdfill._host_of(addr) or "cache")
                    break
                continue
            if jdfill.paid_only(addr) and row_bd is None:
                # the only rung that could read this copy is not running for this row: that
                # is a statement about the ladder, never about the page (jdfill's own rule)
                complete = False
                continue
            # An archived role reaches the PAID rung only under --archived-bd (`paid_keys`),
            # exactly as the fetch pass above: the 2026-08-26 lesson (a closed Taboola row
            # bought a credit while the pool stood at 118 %) is a budget rule, and it is not
            # repealed by a new rung. The free rungs run for every row, whatever its status.
            jd = fetch_jd(addr, bd=row_bd, company=comp, title=title, want_identity=True)
            if not jd.text:
                # A page we READ and found no posting in is evidence; a page we could not
                # reach is not. `jd.transient` is the ladder's own word for the second — a
                # timeout, a 5xx, an Unlocker that was down, a cap that bound — and a
                # `structural:` verdict built on one of those is a network error published as
                # a fact about the world (wave B: 503, `MATCHED_JD_BD_CAP=0` and an unreadable
                # ledger each produced one).
                if jd.transient or jd.reason in ("bd-unavailable", "bd-capped", "bd-parked"):
                    complete = False
                continue
            # the gate that matches the class: a copy at somebody else's address has to say
            # whose posting it is, and the structural classes already said it by construction
            if kind == "copy" and not doc_names_role(jd.decl, title, comp):
                seen_identity += 1
                log(f"  [X  ] {label:<56} {kind} {addr[:44]} REFUSED: the document names "
                    f"{(jd.decl or '(nothing)')[:60]!r}")
                continue
            text, why = jd.text, "ok:%s:%s" % (kind, jdfill._host_of(addr))
            break
        # every refusal counts, whether or not a later donor filled the row: the alarm this
        # feeds is "copies were found and none was admitted", and booking refusals only on
        # the not-filled path suppressed exactly the case worth seeing (wave A)
        refused += seen_identity
        if text and (args.dry_run or _store_text(conn, mkey, text, have)):
            filled += 1
            why_written[why.split(":")[1]] += 1
            log(f"  [OK ] {label:<56} {why} {len(text)}")
            if not args.dry_run:
                conn.execute("UPDATE matched SET jd_why=? WHERE mkey=?", (why, mkey))
                conn.commit()
            continue
        if text:
            # a donor was admitted and the ratchet kept what was already stored: the row is
            # not short of a description, so nothing structural may be said about it
            continue
        # Nothing left to try. The reason says WHICH world we are in, and it may only be
        # written here — after every class above has actually been enumerated for this row.
        if seen_identity:
            why = "refused:identity(%d)" % seen_identity
        elif not complete:
            # a class could not be ASKED (the listing page did not answer, the archive lookup
            # failed, the only rung that reads this copy was not running). The ladder's own
            # stamp already schedules the retry; writing a world-fact here would publish a
            # network error as "structurally unfillable" (wave A, P1-1).
            why = ""
        elif str(att or "").endswith(GONE_MARK):
            why = "structural:gone(donors:%d)" % len(cands)
        elif str(url or "").startswith("http") and not is_job_url(url, title):
            why = "structural:not-a-job-url(donors:%d)" % len(cands)
        elif _unfillable(url):
            why = "structural:%s(donors:%d)" % (_unfillable(url), len(cands))
        else:
            why = ""                       # an ordinary miss: the ladder's own stamp says it
        if why:
            why_written[why.split(":")[0] if why.startswith("refused") else why.split("(")[0]] += 1
            log(f"  [-- ] {label:<56} {why}")
            if not args.dry_run:
                conn.execute("UPDATE matched SET jd_why=? WHERE mkey=?", (why, mkey))
                conn.commit()
    return filled, refused, why_written


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--cache", default=os.path.join(_REPO_ROOT, CACHE),
                    help="the scrape cache to read sibling text from (never written)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cooldown-days", type=int, default=RETRY_DAYS)
    ap.add_argument("--archived-bd", action="store_true",
                    help="let CLOSED/PURGED roles reach the Bright Data rung too. Off on "
                         "the cron by design: an archived role is worked every cycle on the "
                         "rungs that cost nothing. Operator-only, for a one-time catch-up.")
    args = ap.parse_args(argv)
    stamp = stamp_path_for(args.db, DB)
    try:
        return _run(args, stamp)
    except Exception as e:  # noqa: BLE001 - say so in the mail, then fail the step loudly
        if not args.dry_run:            # a rehearsal must not write an alarm the mail quotes
            record_enrich(alarm=f"matched:crash:{type(e).__name__}", path=stamp, matched_ran=1)
        raise


def _run(args, stamp):
    load_secrets()
    if not os.path.exists(args.db):
        print(f"no {args.db}; nothing to enrich")
        return 0
    conn = sqlite3.connect(args.db)
    _ensure_columns(conn)
    # Bound BEFORE anything can append to it. Until 2026-08-29 the first binding was below the
    # re-clean, so the refused-re-clean clause -- "the loudest thing the layer can say" --
    # raised UnboundLocalError, the driver died into `matched:crash:UnboundLocalError`, and
    # the step was green (continue-on-error). The test that covered the refusal called
    # `_reclean` directly and never walked this function.
    alarms = []
    # COALESCE, not a bare `!=`: insert_matched writes NULL and roles.reconcile writes '', and
    # `status != 'superseded'` is NULL for every NULL row — which would silently select
    # nothing and, before the `jd-nothing-attempted` alarm existed, say nothing about it.
    # `looks_like_jd`, not `length < MIN_DESC`: sqlite can count characters but cannot tell a
    # job description from a navigation menu, and 4 of the 70 open roles on 2026-08-28 held
    # 4,000 characters of Webflow furniture that cleared the length gate and locked the role
    # out of the fetch for good. The SELECT stays cheap and wide; the JD test runs in Python.
    every = conn.execute(
        """SELECT mkey, company, title, COALESCE(url,''), COALESCE(jd_attempted,''), COALESCE(seen_ids,''),
                  COALESCE(description,''), COALESCE(jd_tries,0), COALESCE(last_seen,'')
           FROM matched WHERE COALESCE(status,'') != 'superseded'""").fetchall()
    # Oldest attempt first, never-attempted before that. The old ordering was
    # `last_seen DESC, first_seen DESC`, and `run_backfill` skips rather than breaks when the
    # budget runs out -- so the freshest rows were walked first EVERY morning and the tail of
    # the list was never reached at all. At 144 roles that is invisible; at the ~1,500 the
    # registry is heading for it is permanent starvation of exactly the roles that need the
    # work. Sorted this way the fixed budget becomes a round-robin over the whole store, and
    # `matched_cycle_days` says how long one lap takes.
    every.sort(key=lambda r: (r[7], r[4] or "", [-ord(ch) for ch in (r[8] or "")]))
    n_reclean, cut_chars, recleaned = _reclean(conn, every, args.dry_run)
    if n_reclean < 0:
        # A refusal used to print a `::warning::` into the step log and reach the mail not
        # at all, while `matched_ok` went on saying every row carried the employer own
        # posting -- so a store full of login walls was indistinguishable from a clean one
        # (wave 3). It is the exact failure this session was written to fix, re-armed above
        # the ceiling, so it is the loudest thing the layer can say.
        alarms.append(f"matched:reclean-refused({-n_reclean} rows, {cut_chars} chars of "
                      f"furniture still stored -- the board is rendering them)")
        n_reclean = 0
    if recleaned and not args.dry_run:
        # ONLY the rows `_reclean` actually wrote. Re-deriving `jd_body` over every row put
        # text in memory that the database does not hold -- including rows the floor above
        # deliberately refused -- and `_store_text` then compared "longer wins" against a
        # phantom length, so 250 characters of junk could overwrite a 6,000-character row.
        every = [(tuple(r[:6]) + (recleaned[r[0]],) + tuple(r[7:]))
                 if r[0] in recleaned else r for r in every]

    # The keyword rules first, then the model on what is left ambiguous. A row the tier
    # calls incomplete joins the todo exactly as a row that failed `looks_like_jd` does --
    # the two verdicts differ in how they were reached, never in what happens next.
    incomplete, q = _quality_pass(conn, every, args.dry_run)
    verdicts = q["cached"] + q["complete"] + q["rejected"] + q["truncated"]
    if q["candidates"] and not verdicts and (q["unavailable"] or q["capped"] or not q["calls"]):
        # The tier produced NO verdict for anyone. On 2026-08-29 that was 7 candidates, 7
        # calls, 7 unavailable -- the model down for the whole run -- and the bold line said
        # nothing, because `alarm_for` reads `run_backfill`s counter and has never seen `q`.
        # The cheap rule standing IS the documented fallback; a fallback the mail cannot tell
        # from a success is the failure class ARCHITECTURE.md section 8 is about.
        #
        # The condition is "no verdict for anyone", not "every call failed". `calls` is
        # incremented BEFORE the call, so `unavailable >= calls` was merely
        # `unavailable == calls` -- true of a HEALTHY run that served nine candidates from
        # cache and had one flaky call, which then reported "1 of 10 candidates" as though ten
        # roles had lost their verdict. And it was silent in the two states where the tier is
        # most thoroughly dead: `JD_QUALITY=0` (no candidates at all) and a cap of 0 (every
        # candidate `capped`, no call made). `JD_BD=0` announces itself as `bd-unavailable`;
        # this switch announces itself too (wave 3, P1-4).
        why = "+".join(f"{k[4:]}{v}" for k, v in sorted(q.items()) if k.startswith("why:"))
        alarms.append(f"matched:jd-quality-unavailable({q['candidates']} candidates, no verdict"
                      f"{': ' + why if why else ''})")
    rows = [r for r in every if not looks_like_jd(r[6]) or r[0] in incomplete]
    n_ok = len(every) - len(rows)

    state_dir = os.path.dirname(os.path.abspath(args.db))
    dead, ledger_status = dead_role_ids(os.path.join(state_dir, "roles.jsonl"))
    if dead is None:
        alarms.append(f"matched:ledger-{ledger_status}")     # append, never rebind
    # The ledger no longer REMOVES a row from the todo. Until 2026-08-28 a closed or purged
    # role was dropped here, which is why the driver had never once looked at Mobileye two
    # rows: they carried `jd_attempted = ''` since 2026-08-16 and nothing was ever going to
    # change that. The operator bar is that an archived role carries its description too --
    # an archived role without one has no value, and some are still live at their original
    # source. So liveness stops being a SELECTION rule and becomes a BUDGET rule: an archived
    # role is fetched every cycle on the rungs that cost nothing, and reaches the Unlocker
    # only in the one-time `--archived-bd` pass. That keeps the 2026-08-26 lesson (a closed
    # Taboola row bought a credit while the pool stood at 118 %) without paying for it in
    # coverage.
    # An unreadable ledger filters NOTHING -- that rule stands, and the 08-25 test pins it:
    # falling back to a liveness guess would disable the whole driver after any outage. But
    # "filters nothing" used to mean every row went to the pass that carries the Unlocker,
    # so a corrupt ledger put closed roles straight back on the paid rung and re-armed the
    # 2026-08-26 lesson (wave 1). Unknown liveness now means the FREE rungs: every row is
    # still worked, and the day nobody can say which roles are alive is not the day to spend.
    if dead is None:
        alive, archived = [], list(rows)
    else:
        alive = [r for r in rows if r[0] not in dead]
        archived = [r for r in rows if r[0] in dead]
    archived_keys = {r[0] for r in archived}   # by mkey, not by tuple equality: the row is
                                              # nine fields wide and this runs per row
    n_dead = len(archived) if dead is not None else 0
    texts, cache_status = cache_texts(args.cache)
    if cache_status != "ok":
        alarms.append(f"matched:cache-{cache_status}")
    cache_by_key = cache_by_merge_key(args.cache)

    # The one sibling rung: text we ALREADY hold, for an address that names this company.
    # There is no fetch-the-siblings pass — wave 1 measured its yield at 0 and its risk at
    # publishing another employer's job description under this company's name.
    from_cache, foreign, still, still_archived = 0, 0, [], []
    for row in alive + archived:
        mkey, comp, title, url, att, seen_ids, have, tries, _last = row
        best = ""
        for sib in sibling_urls(seen_ids, url or ""):
            if not _own_posting(comp, title, sib):
                foreign += 1
                continue
            text = texts.get((str(comp).strip().lower(), sib), "")
            if len(text) > len(best):
                best = text
        # `_store_text` is what DECIDES, so it is what counts. Incrementing first reported
        # fills that never happened -- and did it every morning, because the case where the
        # write is refused (both sides JDs, the new one shorter) is exactly the case the LLM
        # tier had just called incomplete: the row left the todo, nothing was written, and
        # the run announced two fills (wave 3).
        wrote = looks_like_jd(best) and (args.dry_run or _store_text(conn, mkey, best, have))
        if wrote:
            from_cache += 1
            print(f"  [OK ] {(comp + ' | ' + title)[:64]:<64} cache/own-address {len(best)}",
                  flush=True)
            if not args.dry_run:
                conn.commit()
        else:
            (still_archived if mkey in archived_keys else still).append(row)

    def _address(comp, title, url, seen_ids):
        """The address to FETCH this role at, which is not always the one it publishes.

        A role canonical url is whichever copy won `store.merge_duplicates`, and that contest
        is decided by who carries a posted-date -- not by who can be read. Zipher Data Analyst
        is the worked example: the record kept an Indeed address (then unreadable to every
        client we owned; a paid rung reads Indeed since 2026-08-31, `jdfill.paid_only`), and
        the company own posting at `zipher.ai/careers/data-analyst/` sat in that same role
        `seen_ids` being refused before a byte was fetched. When the published address is one
        the FREE rungs cannot read and the role own `seen_ids` name one they can, we fetch
        the free one -- an own-board page beats a paid aggregator copy on cost AND identity.

        The identity gate is the same one the cache rung already trusts -- `roles.names_in_url`
        via `_own_address`. It has to be: `seen_ids` is NOT a list of a role own addresses, and
        `nift|data analyst` carries five other employers postings. Publishing one of those as
        Nift description would put a defence integrator clearance requirement on Nift card."""
        # the None guard comes FIRST: `matched.url` is nullable (`roles._valid` accepts a
        # record without one and `store.insert_matched` writes it through), and
        # `unfillable(None)` raises TypeError -- which took the WHOLE driver down for the
        # day behind a continue-on-error step, with 144 roles getting nothing (wave 3).
        if (str(url or "").startswith("http") and not _unfillable(url)
                and not jdfill.paid_only(url)):
            return url
        for sib in sibling_urls(seen_ids, url):
            if _own_posting(comp, title, sib) and not _unfillable(sib) \
                    and not jdfill.paid_only(sib):
                print(f"  [ADR] {(comp + ' | ' + title)[:56]:<56} published address is "
                      f"unreadable free; using the role own {sib[:52]}", flush=True)
                return sib
        return url

    def _items(rs):
        out = []
        for mkey, comp, title, url, att, seen_ids, have, tries, _last in rs:
            addr = _address(comp, title, url or "", seen_ids)
            if str(addr or "").startswith("http") or native_candidates(addr, comp, seen_ids):
                out.append(Item(mkey, addr, f"{comp} | {title}", att, comp, title,
                                seen_ids, tries))
        return out

    items, items_archived = _items(still), _items(still_archived)
    # A row with no address at all and none derivable is not a todo the budget failed to
    # reach; it is a row nothing in this lane can act on. Counted, never silently dropped.
    n_no_address = (len(still) + len(still_archived)) - (len(items) + len(items_archived))
    n_final_gone = sum(1 for r in still + still_archived if str(r[4]).endswith(GONE_MARK))
    print(f"{len(every)} live matched rows: {n_ok} already carry the employer own posting, "
          f"{len(rows)} do not — {from_cache} filled from another of the role own addresses, "
          f"{foreign} sibling addresses refused (they name another company), "
          f"{n_no_address} with no address anything could read, {n_final_gone} gone at "
          f"source, {len(items)} live + {len(items_archived)} archived to fetch"
          + (f"; attempting at most {args.limit}" if args.limit else ""), flush=True)

    # Nothing may leave the pool unaccounted for. Silent exclusion is the failure class
    # ARCHITECTURE.md section 8 is about, and this driver has now been caught by it twice:
    # once by a character count that called furniture a description, once by a liveness
    # filter that removed archived roles from the todo entirely. The buckets must add up.
    _accounted = n_ok + from_cache + n_no_address + len(items) + len(items_archived)
    assert _accounted == len(every), (
        "bucket leak: %d rows, %d accounted (ok %d, cache %d, no-address %d, live %d, "
        "archived %d)" % (len(every), _accounted, n_ok, from_cache, n_no_address,
                          len(items), len(items_archived)))

    # `--dry-run` builds NO Unlocker at all, the scrape driver's rule (wave 2 P0-1 there).
    # `run_backfill(dry_run=...)` only gates `save`, and until 2026-08-31 every matched row
    # on a refused host was turned back before the paid rung could spend — with Indeed now
    # `paid_only`, a rehearsal on an armed machine would buy real pages.
    bd = None if args.dry_run else Unlocker(cap=int(os.environ.get("MATCHED_JD_BD_CAP",
                                                                   str(BD_CAP))))

    have_by_key = {r[0]: r[6] for r in rows}

    def save(item, text, stamp_v):
        if text:
            _store_text(conn, item.key, text, have_by_key.get(item.key, ""))
            # the canonical address answered: record THAT, so `jd_why` never leaves a stale
            # `structural:` verdict standing on a row that has since been filled
            conn.execute("UPDATE matched SET jd_why=? WHERE mkey=?",
                         ("ok:canonical:%s" % (jdfill._host_of(item.url) or "?"), item.key))
        # `jd_tries` counts DEFINITIVE failures only. A transient one (timeout, 5xx, an
        # Unlocker that was down) says nothing about the address, so widening the backoff on
        # it would let one bad morning push a perfectly readable role out to a month.
        definitive = not text and not stamp_v.endswith(" transient")
        conn.execute("UPDATE matched SET jd_attempted=?, jd_tries=COALESCE(jd_tries,0)+? "
                     "WHERE mkey=?", (stamp_v, 1 if definitive else 0, item.key))
        conn.commit()

    # ONE budget across both passes, and one canary per process: `probe_cell` is exactly the
    # shared-state hook `run_backfill` grew for a driver that walks the loop twice.
    minutes = float(os.environ.get("MATCHED_JD_TIME_BUDGET_MIN", "25"))
    # The archived pass runs second, and second with no floor means never: at 1,500 rows the
    # live pass filled the clock for twenty consecutive days and archived roles were reached
    # ZERO times, while the stamp reported 750 of them every morning (wave 3). "Liveness is a
    # budget rule now" is only true if the budget actually reserves something. A quarter is
    # enough to keep the archive moving without taking the board off the live roles.
    live_minutes = minutes * (1 - ARCHIVED_BUDGET_SHARE) if items_archived else minutes
    probe_cell = set()
    t0 = time.time()
    c = run_backfill(items, save=save, minutes=live_minutes,
                     bd=bd, dry_run=args.dry_run, retry_days=args.cooldown_days,
                     count_cap=args.limit, log=lambda s: print(s, flush=True),
                     probe_cell=probe_cell)
    left = None if minutes is None else max(0.0, minutes - (time.time() - t0) / 60)
    if items_archived:
        print(f"-- {len(items_archived)} archived roles, "
              f"{'free rungs only' if not args.archived_bd else 'FULL ladder (--archived-bd)'}",
              flush=True)
        # `--limit` is an operator saying "do N", not "do N and then all the archived ones"
        left_cap = max(0, args.limit - (c["tried"] - c["probe"])) if args.limit else 0
        c += run_backfill(items_archived, save=save, minutes=left,
                          bd=bd if args.archived_bd else None, dry_run=args.dry_run,
                          retry_days=args.cooldown_days, count_cap=left_cap,
                          log=lambda s: print(s, flush=True), probe_cell=probe_cell)

    # THE LAST RUNG: the role's other copies of itself, for everything the ladder above could
    # not fill. It runs here, after the fetches, because that is what makes it a last resort
    # rather than a shortcut past the role's own address — and because the rows it must reach
    # include the ones `run_backfill` never walks at all: a `gone`-terminal role is counted
    # and skipped up there, and an archived role's canonical may have been dead for weeks
    # while its LinkedIn copy still renders. Re-read from the store so it sees this run's own
    # fills rather than the snapshot they were computed from.
    donor_rows = [r for r in conn.execute(
        """SELECT mkey, COALESCE(company,''), COALESCE(title,''), COALESCE(url,''),
                  COALESCE(jd_attempted,''),
                  COALESCE(seen_ids,''), COALESCE(description,''), COALESCE(jd_tries,0),
                  COALESCE(last_seen,'')
           FROM matched WHERE COALESCE(status,'') != 'superseded'""").fetchall()
        if not looks_like_jd(r[6]) or r[0] in incomplete]
    # Which rows may spend: a LIVE row keeps the paid rung the fetch passes already gave it;
    # an archived one is free-only unless `--archived-bd`. When the ledger is unreadable
    # nobody spends, the same rule the fetch passes follow — the day we cannot say which
    # roles are alive is not the day to buy pages for them.
    paid_keys = set() if dead is None else {
        r[0] for r in donor_rows if r[0] not in dead or args.archived_bd}
    from_donor, donor_refused, donor_why = 0, 0, Counter()
    if donor_rows:
        print(f"-- {len(donor_rows)} rows the ladder could not fill: asking the role's own "
              f"other copies ({len(paid_keys)} may reach the paid rung)", flush=True)
        from_donor, donor_refused, donor_why = _donor_pass(
            conn, donor_rows, cache_by_key, bd, paid_keys, args,
            log=lambda s: print(s, flush=True), retry_days=args.cooldown_days,
            count_cap=max(0, args.limit - (c["tried"] - c["probe"])) if args.limit else 0)
        # The one way this rung dies quietly: `doc_names_role` tightens (a source changes how
        # it writes its own title, a normalisation drifts) and every copy is refused, which
        # looks exactly like a night with no donors at all. Refusals ARE the rung working
        # when a copy really is another employer's, so the alarm needs both halves — copies
        # were found and NONE was admitted — and a floor of 3, because one nift-class row
        # refusing for ever is the designed behaviour and an alarm that fires every morning
        # is one that gets trained away.
        if donor_refused >= 3 and not from_donor:
            alarms.append(f"matched:donor-all-refused({donor_refused} copies of this role's "
                          f"own addresses named a different role or employer, 0 admitted)")

    # `incomplete` too: a row the model judged a fragment is a row still without the
    # employer posting, and reporting "0 roles still without a JD" on a run that had just
    # judged two of them incomplete is the layer contradicting itself in one stamp (wave 3).
    # rows standing on a written structural verdict — the count the `roles` export turns into
    # `description_blocker`, and the one a reader can check between runs
    n_structural = conn.execute(
        "SELECT COUNT(*) FROM matched WHERE COALESCE(jd_why,'') LIKE 'structural:%' "
        "AND COALESCE(status,'') != 'superseded'").fetchone()[0]
    still_short = [r[:2] for r in conn.execute(
        """SELECT mkey, COALESCE(url,''), COALESCE(description,'') FROM matched
           WHERE COALESCE(status,'') != 'superseded'""").fetchall()
        if not looks_like_jd(r[2]) or r[0] in incomplete]
    short_left = len(still_short)
    # how many of those anything could still act on. Archived roles are NOT excluded any
    # more -- they are fetched on the free rungs, so they are actionable by definition.
    actionable = sum(1 for mkey, u in still_short if not _unfillable(u))
    # How many days one lap of the whole todo now takes. The budget is fixed and the store
    # is not: this is the number that goes red slowly, and without it the tail of the list
    # simply stops being reached with nothing anywhere saying so.
    # ROWS WORKED, and nothing else. Counting the cooled-down ones as lap progress made
    # this number FALL as starvation grew -- at 1,500 rows and a true 25-day lap it read
    # 3.5, and it read greener the fuller the cooldown pool got (wave 3). It is the one
    # number introduced to detect starvation, so it may only ever count real work.
    _worked = c["tried"] - c["probe"]
    cycle_days = round(c["todo"] / _worked, 1) if _worked else 0
    conn.close()
    if not args.dry_run:
        alarm = "; ".join(a for a in ([alarm_for(c, bd, driver="matched",
                                                    operator_cap=bool(args.limit))] + alarms) if a)
        record_enrich(alarm=alarm, path=stamp, matched_ran=1,
                      matched_filled=c["filled"], matched_bd=c["bd"], matched_fail=c["fail"],
                      matched_bd_unavailable=c["bd_unavailable"], matched_cooldown=c["cooldown"],
                      matched_unfillable=c["unfillable"], matched_todo=c["todo"],
                      matched_dead=n_dead, matched_from_cache=from_cache,
                      matched_foreign_sibling=foreign, matched_bd_calls=bd.used,
                      matched_bd_ok=bd.ok, matched_skipped=c["skipped_budget"],
                      matched_probe=c["probe"], matched_short=short_left,
                      matched_bd_shell=c["bd_shell"], matched_bd_rendered=getattr(bd, "rendered", 0),
                      matched_bd_parked=c["bd_parked"],
                      matched_ok=n_ok, matched_archived=len(items_archived),
                      matched_llm_calls=q["calls"], matched_llm_cached=q["cached"],
                      matched_llm_rejected=q["rejected"],
                      matched_llm_truncated=q["truncated"],
                      matched_recleaned=n_reclean, matched_furniture_cut=cut_chars,
                      matched_llm_candidates=q["candidates"],
                      matched_llm_unavailable=q["unavailable"],
                      matched_llm_capped=q["capped"],
                      matched_via_sibling=from_donor,
                      matched_sibling_refused=donor_refused,
                      # a GAUGE, like `matched_terminal` and for the same reason: it counts
                      # ROWS STANDING in that state, so a second dispatch on one day restates
                      # it instead of summing the same rows twice
                      matched_structural=n_structural,
                      matched_donor_why="+".join(f"{k}{v}" for k, v in
                                                 sorted(donor_why.items())),
                      matched_no_address=n_no_address, matched_gone=c["gone"],
                      matched_terminal=n_final_gone, matched_cycle_days=cycle_days,
                      matched_actionable=actionable, matched_why=why_string(c))
    # `bd` is None on --dry-run (no Unlocker is built at all), so the report reads it
    # through getattr; the record_enrich block above needs no guard because it is
    # dry-run-gated, and dry-run is the only way `bd` is None
    print(f"=== matched JD backfill: {c['filled'] + from_cache + from_donor} filled "
          f"({c['bd']} via Bright Data, {from_cache} from another of the role's own addresses, "
          f"{from_donor} from another copy of the role — {donor_refused} copies refused for "
          f"not naming it, {n_structural} rows standing on a structural reason), "
          f"{c['fail']} unfetchable (retry in {args.cooldown_days}d), {c['cooldown']} in cooldown, "
          f"{getattr(bd, 'used', 0)} Bright Data requests spent, {short_left} roles still without a JD "
          f"({actionable} of them actionable)"
          + (f" [{bd.unavailable}]" if getattr(bd, "unavailable", "") else "") + " ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
