#!/usr/bin/env python3
"""Apply `drain_queue.py`'s proposal file to companies.csv, in REVIEWED BATCHES.

    python apply_proposals.py --proposals out/queue_proposals.json --kind ats --batch 30
    python apply_proposals.py --proposals out/queue_proposals.json --kind ats --batch 30 --apply

DRY-RUN BY DEFAULT. `--batch N` means "apply at most N proposals that are STILL MISSING",
never "skip the first N" -- that distinction is what makes this tool idempotent, and
idempotency is what makes it survive `git pull --rebase` on a file origin moves ~30 times a
day. It holds no run state: no checkpoint, no `--resume`, no offset. Every de-dup key is
recomputed from a FRESH read of companies.csv before every single write (rule 4), and no
existing row is ever modified. So a rebase that drops the append is repaired by running the
same command again: the survivors are skipped, the missing rows are recreated.

WHY THIS IS NOT A MODE ON `apply_resolved.py`. That tool is line-based on purpose -- it
matches a line by field 0 and rewrites fields 2-4 of that one line, so the other 1,464 rows
come back byte-identical. Every proposal here needs a NEW row, which is a different
concurrency class (append-only, the one ARCHITECTURE section 2 calls safe). `apply_resolved`
is also SCHEDULED (self-heal, 06:00), so a defect in a new mode there is a defect in a cron
that writes the registry. And its gate is a VETO on proven foreignness -- right for
re-pointing a board that was already verified, wrong for activating a new row, which needs
`activation_verdict`'s positive chain. Two gate shapes in one file is what the picker table
at `pipeline/identity_gate.py:36` exists to prevent.

THE FOUR DEFECTS OF THE PREVIOUS ONE-OFF APPLIER, which are this module's specification
(`docs/sessions/2026-08-27-registry.md`, "Continuation state"):

  1. it de-duplicated by NAME only, and two of 44 activations were twins of an existing row.
     Six keys here, and the board key is lower-cased on BOTH sides -- the miss that wrote
     `Imagry | Autonomous Driving` as a second ACTIVE row on `comeet/B7.00F`, because
     `_boards_now()` lower-cases what it stores and the lookup did not, so the guard was
     blind to exactly one platform: Comeet, whose token is an uppercase uid.
  2. an Israeli aggregator's company page passed the identity gate -- it names the company
     correctly, which is why the gate cannot catch this class. The hosts are now in
     `pipeline/aggregators.py` (`340@discovery`), not in a local copy: a private blocklist is
     how `builtin.com` came to be missing from three separate hand-maintained tuples.
  3. a new `scrape` row ships NOTHING until it is in `scraped_cache.json`. 0 of its first 42
     were cached. This tool prints the exact `refresh_scrape_cache.py` command afterwards and
     the definition of done is not met until it has run.
  4. (found 2026-08-28) it wrote note segments prefixed `listing-hunt`. `listing_hunt` calls
     `notes.replace_own(base, "listing-hunt", ...)` on its own rows, so the next 19:00 cron
     DELETES the whole provenance segment -- rung, verified IL count and origin -- with no
     error. The marker here is `queue-drain`, which nothing else rewrites.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# The same four locks the drain carries, and for the same reason: `secrets.env` on the
# operator's disk is `setdefault`ed into os.environ by eight root modules, so "I did not
# export the key" is not a guarantee. See drain_queue._lock_the_paid_rungs.
os.environ["PAGE_UNLOCK_BUDGET"] = "0"
os.environ.pop("BRIGHTDATA_API_KEY", None)
os.environ.pop("BRIGHTDATA_ZONE", None)
# NOT `sys.modules["bd_rescue"] = None`: that form of the lock poisons the whole interpreter
# and broke 77 tests that import bd_rescue through discovery_daily. See drain_queue.

from pipeline import identity_gate as _gate            # noqa: E402

# ...and again on the module object, because the env lock alone is ORDER-DEPENDENT: the gate
# reads PAGE_UNLOCK_BUDGET at ITS import (`identity_gate.py:80`), so anything that imported
# it first -- a test module, another tool, an interactive session -- has already fixed the
# budget at 100 and the env variable arrives too late to matter. Found by this module's own
# guard, which imports the gate at the top of the test file. Setting the attribute is the
# only form of the lock that does not depend on who imported what first.
_gate._UNLOCK_BUDGET = 0
from pipeline import notes as _notes                   # noqa: E402
from pipeline.aggregators import is_aggregator         # noqa: E402
from pipeline.company_identity import ATS_HOST, registrable   # noqa: E402
from pipeline.firmographics import looks_like_junk     # noqa: E402
from pipeline.recruiters import is_recruiter           # noqa: E402
from pipeline.store import _norm_company               # noqa: E402
from pipeline.verdicts import is_terminal_row          # noqa: E402

CSV_PATH = "companies.csv"
COMEET_UID = re.compile(
    r"comeet\.com/(?:careers-api/2\.0/company/|jobs/[^/]+/)([0-9A-Za-z]{2}\.[0-9A-Za-z]{3})",
    re.I)
MAX_AGE_H = 6.0


# --------------------------------------------------------------------------------------- #
# de-dup
# --------------------------------------------------------------------------------------- #
def _url_keys(u):
    """(lower api_url, (host, path)) -- the second catches query-string twins."""
    u = (u or "").strip()
    p = urllib.parse.urlparse(u)
    return u.lower(), (p.netloc.lower(), (p.path or "").rstrip("/").lower())


def _own_domain(u):
    """The registrable domain of a URL, but ONLY when it is the company's own.

    Two traps, both found by this tool's own guards before a row was written:

      * `company_identity.registrable` takes a HOST, not a URL. Handed a URL it returns
        `"https"` -- for every proposal -- so the domain HOLD collided everything with
        everything and the applier wrote nothing while reporting each row as held.
      * on an ATS host the key is meaningless by construction: every Comeet tenant shares
        `comeet`, every Greenhouse tenant shares `greenhouse`. Holding on that is not
        over-blocking at the margin, it is refusing the entire native-ATS path -- which is
        the half of this work that needs no scrape cache. The HOLD exists for the case it can
        actually speak to: two rows on one COMPANY's own domain (`Nebius Group`/`Nebius`,
        `Blink`/`Blink Ops`), which no other key sees."""
    host = urllib.parse.urlparse(u or "").netloc.lower()
    if not host or ATS_HOST.search(host):
        return ""
    return registrable(host)


def _keys(rows):
    """Every identity a row already claims. LOWER-CASED ON BOTH SIDES, everywhere.

    Six keys, because each of the first five has let a twin through in this repo:

      names      exact, and `store._norm_company` (one trailing corporate suffix stripped),
                 which is what separates `Investing.com` from `Investing`
      boards     (platform, token) -- the key `check_invariants` check B cannot express,
                 because the two names differ by a legal suffix and B compares names
      urls       byte-equal api_url
      hostpath   host + path, so `?token=` variants collapse
      comeet     the uid pulled from EITHER url shape. The registry stores the
                 `careers-api/2.0/company/<uid>/positions` form and a proposal carries the
                 `jobs/<slug>/<uid>` form, so no string key sees these as the same board.
      domains    registrable domain -> the row names that hold it. NOT a refusal: it
                 over-blocks on shared ATS hosts (every greenhouse row collides with every
                 other). A HOLD, released per name by --allow-domain-collision.
    """
    k = {"names": set(), "boards": set(), "urls": set(), "hostpath": set(),
         "comeet": set(), "domains": {}, "terminal": set()}
    for r in rows:
        if len(r) < 6:
            continue
        nm = (r[0] or "").strip()
        k["names"].add(nm.lower())
        k["names"].add(_norm_company(nm))
        if (r[1] or "").strip() and (r[2] or "").strip():
            k["boards"].add(((r[1] or "").strip().lower(), (r[2] or "").strip().lower()))
        for u in (r[3], r[2]):
            if (u or "").startswith("http"):
                lo, hp = _url_keys(u)
                k["urls"].add(lo)
                k["hostpath"].add(hp)
                d = _own_domain(u)
                if d:
                    k["domains"].setdefault(d, set()).add(nm)
        m = COMEET_UID.search(r[3] or "")
        if m:
            k["comeet"].add(m.group(1).lower())
        if is_terminal_row(r):
            k["terminal"].add(nm.lower())
    return k


def _collides(p, k):
    """Why this proposal must not be appended -- or "" if nothing objects.

    Presence is checked REGARDLESS of `active`: re-activating a row somebody deliberately
    parked `alias-of` or `defunct` is exactly what those verdicts exist to stop, and a
    presence test that only looked at live rows would walk straight into it."""
    nm = (p.get("name") or "").strip()
    api = p.get("api_url") or ""
    plat, tok = (p.get("platform") or "").strip().lower(), (p.get("token") or "").strip().lower()
    if nm.lower() in k["names"] or _norm_company(nm) in k["names"]:
        return "dup-name"
    if plat and tok and (plat, tok) in k["boards"]:
        return "dup-board"
    lo, hp = _url_keys(api)
    if lo and lo in k["urls"]:
        return "dup-url"
    if hp[0] and hp in k["hostpath"]:
        return "dup-hostpath"
    m = COMEET_UID.search(api)
    if m and m.group(1).lower() in k["comeet"]:
        return "dup-comeet-uid"
    return ""


# --------------------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------------------- #
def _reverify_ats(p):
    """Re-fetch through the PRODUCTION path. `il >= 1` is only a gate while it is current.

    The proposal's counts can be a day old (`drain_queue` replays a previous night's sweep),
    and a board that emptied overnight would otherwise be activated on a stale number. One
    API call. `pipeline.israel.is_israel_job` decides, never a local predicate -- an ad-hoc
    "is 'israel' in the location blob" check over raw Comeet JSON scored a real 19-Israel-job
    board as 0 while this was being written."""
    from pipeline.fetchers import fetch_company
    from pipeline.israel import is_israel_job
    jobs = fetch_company({"company_name": p["name"], "ats_platform": p["platform"],
                          "token": p.get("token") or "", "api_url": p["api_url"]})
    return jobs, [j for j in jobs if is_israel_job(j)]


def _row_for(p, n_all, n_il, html, today):
    """Build the row and stamp it. The gate call is `activation_verdict`, not `activation_ok`.

    Two deliberate choices, each of which the previous applier got wrong:

    * the VERDICT form, so a refusal can be NAMED. `activation_ok` collapses `not-ours`
      (a board PROVEN to be someone else's) and `unverified` (we could not tell) into one
      `False`, and the previous applier stamped "another company's board" on both. That is a
      claim, permanently, on a row that merely had an unreadable page --
      `Enlight Renewable Energy Ltd (ENLT)` is refused by the strict full-name test because
      its page says "Enlight", and it has 14 Israel jobs.
    * `html=` is the page we already hold, and NO `token=`. A supplied token makes
      `board_vouches` return True and short-circuits before any page is read -- handing the
      gate a token we synthesised from the name is handing it its own answer
      (`docs/sessions/2026-08-27-registry.md`, correction 1). And a held page >= 2000 chars is
      what keeps `page_names_company` from fetching, which is what keeps it from unlocking.
    """
    name, api = p["name"], p["api_url"]
    held = html if html and len(html) >= 2000 else ""
    verdict = _gate.activation_verdict(name, api, n_il, html=held)
    rung = p.get("rung") or "queue-drain"
    if verdict == "ok" and n_il >= 1:
        seg = "queue-drain %s %s; %d/%d IL" % (today, rung, n_all, n_il)
        return [name, p["platform"], p.get("token") or "", api, "true", seg], verdict
    if verdict == "not-ours":
        # PROVEN someone else's. This is the only branch that may say so, and the address is
        # not persisted: writing it into cols 2-3 moves the mistake to the next night, where
        # `retry_unreachable` re-fetches it with no identity test of its own.
        seg = "queue-drain %s %s; another company's board; no listing found" % (today, rung)
        return [name, "scrape", "", "", "false", seg], verdict
    if verdict == "unverified":
        seg = "queue-drain %s %s; unverified (page unreadable); no listing found" % (today, rung)
        return [name, "scrape", "", "", "false", seg], verdict
    # `empty` / `not-listing`: the board is real and readable, it just has no Israel role
    # today. Keep the address -- it is what puts the row in the daily probe pool.
    seg = "queue-drain %s %s; %d/%d IL; no IL listing; monitored candidate" % (
        today, rung, n_all, n_il)
    return [name, p["platform"], p.get("token") or "", api, "false", seg], verdict


def _read_rows():
    with open(CSV_PATH, encoding="utf-8") as f:
        return list(csv.reader(f))


def _append(row):
    """Append-only, one row, flushed and fsynced.

    NOT `pipeline.atomic.write_csv_rows`, despite that being the shared writer: a whole-file
    replace between two concurrent writers is the lost update the single-writer rule forbids,
    and nine lanes share this checkout. A torn append leaves half a line, which
    `check_invariants` check A (every row has exactly 6 fields) catches before any commit."""
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)
        f.flush()
        os.fsync(f.fileno())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--proposals", required=True)
    ap.add_argument("--kind", default="", help="ats | scrape (default: both)")
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-age", type=float, default=MAX_AGE_H,
                    help="hours; a scrape proposal older than this is parked, not activated")
    ap.add_argument("--allow-domain-collision", default="",
                    help="comma-separated names whose registrable-domain HOLD you have read")
    a = ap.parse_args(argv)

    with open(a.proposals, encoding="utf-8") as f:
        doc = json.load(f)
    props = [p for p in doc["proposals"] if p.get("kind") in ("ats", "scrape")]
    if a.kind:
        props = [p for p in props if p["kind"] == a.kind]
    allow = {x.strip().lower() for x in a.allow_domain_collision.split(",") if x.strip()}
    today = dt.date.today().isoformat()
    age_h = (dt.date.today() - dt.date.fromisoformat(doc.get("generated", today))).days * 24

    stats = {"written": 0, "active": 0, "parked": 0, "held": 0, "skipped": 0}
    why = {}
    # intra-batch identities: two queue NAMES can be one board (`Faye`/`withfaye`), and the
    # registry cannot object to a row this run has not written yet
    batch_keys = None
    for p in props:
        if stats["written"] >= a.batch:
            break
        name = (p.get("name") or "").strip()
        rows = _read_rows()[1:]            # RE-READ before every write (rule 4)
        k = _keys(rows)
        if batch_keys is None:
            batch_keys = k
        else:                              # the live file plus what this run already added
            for key in ("names", "boards", "urls", "hostpath", "comeet", "terminal"):
                k[key] |= batch_keys[key]
            for d, ns in batch_keys["domains"].items():
                k["domains"].setdefault(d, set()).update(ns)

        if is_recruiter(name) or looks_like_junk(name):
            why[name] = "agency-or-junk"; stats["skipped"] += 1; continue
        # AGGREGATOR FIRST, then identity. They answer different questions: `is_aggregator`
        # asks "is this a board for many employers", the gate asks "is this THIS company's
        # page", and an aggregator's company page passes the second by naming the company
        # correctly. Reversing them is how Menora Mivtachim was activated on jobkarov.com.
        if is_aggregator(p.get("api_url") or ""):
            why[name] = "aggregator"; stats["skipped"] += 1; continue
        dup = _collides(p, k)
        if dup:
            why[name] = dup; stats["skipped"] += 1; continue
        dom = _own_domain(p.get("api_url") or "")
        clash = sorted(k["domains"].get(dom, set())) if dom else []
        if clash and name.lower() not in allow:
            why[name] = "HOLD domain=%s shared with %s" % (dom, ", ".join(clash[:3]))
            stats["held"] += 1
            continue

        if p["kind"] == "ats":
            try:
                jobs, il = _reverify_ats(p)
            except Exception as e:                                # noqa: BLE001
                why[name] = "refetch:%s" % e.__class__.__name__
                stats["skipped"] += 1
                continue
            n_all, n_il = len(jobs), len(il)
        else:
            n_all = p.get("evidence", {}).get("n_il_when_hunted") or 0
            n_il = n_all if age_h <= a.max_age else 0     # stale => park, never activate

        html = ""
        row, verdict = _row_for(p, n_all, n_il, html, today)
        # the note goes through pipeline/notes.py even on a fresh row, so the 220-char cap and
        # the protected-segment rule are ONE code path rather than two
        row[5] = _notes.append("", row[5])
        print("  %-5s %-34s %-6s %-9s %s"
              % ("write" if a.apply else "[dry]", name[:34], row[4], verdict,
                 (row[5] or "")[:64]))
        if a.apply:
            _append(row)
        stats["written"] += 1
        stats["active" if row[4] == "true" else "parked"] += 1
        for key, val in (("names", name.lower()), ("names", _norm_company(name))):
            batch_keys[key].add(val)
        if row[1] and row[2]:
            batch_keys["boards"].add((row[1].lower(), row[2].lower()))
        if (row[3] or "").startswith("http"):
            lo, hp = _url_keys(row[3])
            batch_keys["urls"].add(lo)
            batch_keys["hostpath"].add(hp)
            m = COMEET_UID.search(row[3])
            if m:
                batch_keys["comeet"].add(m.group(1).lower())

    print("\n=== %s: %s ===" % ("APPLIED" if a.apply else "DRY RUN", stats))
    for n, w in sorted(why.items(), key=lambda x: x[1])[:40]:
        print("   skip %-34s %s" % (n[:34], w))
    if stats["active"] and a.apply:
        print("\nNEXT, and the batch is NOT done until it has run: a `scrape` row ships "
              "nothing until it is cached.\n    python refresh_scrape_cache.py --only-missing --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
