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
import json
import os
import sqlite3
import sys

from pipeline.jdfill import (DESC_MAX, MIN_DESC, RETRY_DAYS, Item, Unlocker, _REPO_ROOT,
                             alarm_for, load_secrets, looks_like_jd, record_enrich,
                             run_backfill, stamp_path_for, unfillable as _unfillable,
                             why_string)

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
    conn.execute("UPDATE matched SET description=? WHERE mkey=?", (text, mkey))
    return True


def _ensure_column(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(matched)")}
    if "jd_attempted" not in cols:
        conn.execute("ALTER TABLE matched ADD COLUMN jd_attempted TEXT")
        conn.commit()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--cache", default=os.path.join(_REPO_ROOT, CACHE),
                    help="the scrape cache to read sibling text from (never written)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cooldown-days", type=int, default=RETRY_DAYS)
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
    _ensure_column(conn)
    # COALESCE, not a bare `!=`: insert_matched writes NULL and roles.reconcile writes '', and
    # `status != 'superseded'` is NULL for every NULL row — which would silently select
    # nothing and, before the `jd-nothing-attempted` alarm existed, say nothing about it.
    # `looks_like_jd`, not `length < MIN_DESC`: sqlite can count characters but cannot tell a
    # job description from a navigation menu, and 4 of the 70 open roles on 2026-08-28 held
    # 4,000 characters of Webflow furniture that cleared the length gate and locked the role
    # out of the fetch for good. The SELECT stays cheap and wide; the JD test runs in Python.
    rows = [r for r in conn.execute(
        """SELECT mkey, company, title, url, COALESCE(jd_attempted,''), COALESCE(seen_ids,''),
                  COALESCE(description,'')
           FROM matched WHERE COALESCE(status,'') != 'superseded'
           ORDER BY last_seen DESC, first_seen DESC""").fetchall()
            if not looks_like_jd(r[6])]

    state_dir = os.path.dirname(os.path.abspath(args.db))
    dead, ledger_status = dead_role_ids(os.path.join(state_dir, "roles.jsonl"))
    alarms = [] if dead is not None else [f"matched:ledger-{ledger_status}"]
    alive = [r for r in rows if dead is None or r[0] not in dead]
    n_dead = len(rows) - len(alive)
    texts, cache_status = cache_texts(args.cache)
    if cache_status != "ok":
        alarms.append(f"matched:cache-{cache_status}")

    # The one sibling rung: text we ALREADY hold, for an address that names this company.
    # There is no fetch-the-siblings pass — wave 1 measured its yield at 0 and its risk at
    # publishing another employer's job description under this company's name.
    from_cache, foreign, still = 0, 0, []
    for mkey, comp, title, url, att, seen_ids, have in alive:
        best = ""
        for sib in sibling_urls(seen_ids, url):
            if not _own_address(comp, sib):
                foreign += 1
                continue
            text = texts.get((str(comp).strip().lower(), sib), "")
            if len(text) > len(best):
                best = text
        if looks_like_jd(best):
            from_cache += 1
            print(f"  [OK ] {(comp + ' | ' + title)[:64]:<64} cache/own-address {len(best)}",
                  flush=True)
            if not args.dry_run:
                _store_text(conn, mkey, best, have)
                conn.commit()
        else:
            still.append((mkey, comp, title, url, att))

    items = [Item(mkey, url, f"{comp} | {title}", att, comp, title)
             for mkey, comp, title, url, att in still if str(url or "").startswith("http")]
    print(f"{len(rows)} matched roles without a job description, {n_dead} closed or superseded "
          f"(skipped), {from_cache} filled from another of the role's own addresses, "
          f"{foreign} sibling addresses refused (they name another company), "
          f"{len(items)} to fetch"
          + (f"; attempting at most {args.limit}" if args.limit else ""), flush=True)

    bd = Unlocker(cap=int(os.environ.get("MATCHED_JD_BD_CAP", str(BD_CAP))))

    have_by_key = {r[0]: r[6] for r in rows}

    def save(item, text, stamp_v):
        if text:
            _store_text(conn, item.key, text, have_by_key.get(item.key, ""))
        conn.execute("UPDATE matched SET jd_attempted=? WHERE mkey=?", (stamp_v, item.key))
        conn.commit()

    c = run_backfill(items, save=save,
                     minutes=float(os.environ.get("MATCHED_JD_TIME_BUDGET_MIN", "25")),
                     bd=bd, dry_run=args.dry_run, retry_days=args.cooldown_days,
                     count_cap=args.limit, log=lambda s: print(s, flush=True))

    still_short = [r[:2] for r in conn.execute(
        """SELECT mkey, COALESCE(url,''), COALESCE(description,'') FROM matched
           WHERE COALESCE(status,'') != 'superseded'""").fetchall() if not looks_like_jd(r[2])]
    short_left = len(still_short)
    # how many of those anything could still act on: not a closed role, not a refused host
    actionable = sum(1 for mkey, u in still_short
                     if (dead is None or mkey not in dead) and not _unfillable(u))
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
                      matched_actionable=actionable, matched_why=why_string(c))
    print(f"=== matched JD backfill: {c['filled'] + from_cache} filled "
          f"({c['bd']} via Bright Data, {from_cache} from another of the role's own addresses), "
          f"{c['fail']} unfetchable (retry in {args.cooldown_days}d), {c['cooldown']} in cooldown, "
          f"{bd.used} Bright Data requests spent, {short_left} roles still without a JD "
          f"({actionable} of them actionable)"
          + (f" [{bd.unavailable}]" if bd.unavailable else "") + " ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
