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
import queue_pipeline as _QP                           # noqa: E402  (row_name_for)

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


def _name_kin(name, allnames):
    """Existing row names this one CONTAINS or is contained by. A HOLD, never a refusal.

    The six exact keys all miss the commonest real twin, and the reason is structural: they
    key on an ADDRESS, and a native-ATS row has no company domain to key on. Measured on
    2026-08-28 over the 49 scrape candidates:

        monday.com AI engineering -> monday.com/careers   vs ACTIVE `monday.com` on ashby
        REAL                      -> real.dev/careers     vs ACTIVE `REAL DEV INC` on workable
        COMMIT Offshore           -> comm-it.com          vs ACTIVE `CommIT` on comeet

    Three second ACTIVE rows for one employer -- the `alias-of` shape section 2 calls
    terminal, every role republished under two names -- and `check_invariants` check B cannot
    see any of them, because it compares names for EQUALITY and these differ.

    It cannot be a gate, because containment is not identity: `REAL` is also contained in the
    unrelated `RealPlay`, and `Blink` in `Blink Ops` which may or may not be the same firm.
    So it prints the colliding rows and stops, and `--allow-domain-collision "<name>"`
    releases one after a human has read the pair. Twenty written and proven beats a twin.

    Minimum length 4 on the shorter side: below that, containment matches most of the
    registry (`Hud`, `AI`, `REE`), and a HOLD that fires on everything is a HOLD nobody
    reads."""
    a = _norm(name)
    if len(a) < 4:
        return set()
    out = set()
    for other_norm, other_raw in allnames:
        if len(other_norm) < 4 or other_norm == a:
            continue
        if a in other_norm or other_norm in a:
            out.add(other_raw)
    return out


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
         "comeet": set(), "domains": {}, "terminal": set(), "allnames": set()}
    for r in rows:
        if len(r) < 6:
            continue
        nm = (r[0] or "").strip()
        k["names"].add(nm.lower())
        k["names"].add(_norm_company(nm))
        k["allnames"].add((_norm(nm), nm))
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
# --------------------------------------------------------------------------------------- #
# The board's own name for itself
# --------------------------------------------------------------------------------------- #
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
# Every shape the six path-tenant ATSes actually emit, measured over the 12 slug-probe
# candidates of 2026-08-28: "Careers at AbbVie", "Jobs at Meridial", "Mixtiles Careers",
# "Airwallex Jobs", "Careers at Harness: Open Positions & Job Opportunities".
_TITLE_STRIP = (
    re.compile(r"^\s*(?:careers|jobs|open\s+positions|current\s+openings)\s+(?:at|with)\s+",
               re.I),
    re.compile(r"\s*[-|:]\s*(?:careers|jobs|open\s+positions).*$", re.I),
    re.compile(r"\s+(?:careers|jobs)\s*$", re.I),
)


def board_employer(html):
    """Who does this board page say it belongs to? '' when it does not say.

    The board's `<title>` is the one identity claim on the page that the TENANT wrote and we
    did not derive. That distinction is the whole point -- see `_board_is_this_company`."""
    m = _TITLE.search(html or "")
    if not m:
        return ""
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    for rx in _TITLE_STRIP:
        t = rx.sub("", t).strip()
    return t


def _board_is_this_company(name, html):
    """(ok, employer_the_board_names). The check `activation_verdict` cannot make.

    **For a slug we synthesised from the company name, the shipped gate is a no-op.** Proven
    on 2026-08-28 against `Agency` -> greenhouse `agency`:

        board_vouches("Agency", "agency", ...)            -> True
        activation_verdict("Agency", ..., 1)              -> "ok"    (never reads the page)
        page_names_company("Agency", <the board's page>)  -> True

    ...and that board's own title is **"Jobs at Meridial"**. It is someone else's, with 821
    postings, and every one of them would have been republished under the name "Agency".
    `board_vouches` near-equals a name-derived token BY CONSTRUCTION -- zero bits, exactly
    `317@registry` -- and `page_names_company` then agrees because the word "agency" appears
    somewhere in Meridial's page text. Two tests, one shared assumption, and a one-word
    generic name defeats both.

    So this is a THIRD, independent signal, and it is independent because the tenant wrote it:
    the board page's own title names the employer. It is the same evidence the Comeet rung
    gets for free from the API's `company_name` field, which is why that rung needs no
    equivalent.

    Containment, not equality, and both directions -- measured over all 12 slug-probe
    candidates of 2026-08-28. Equality alone refuses `Harnessinc` (its board says "Harness"),
    which is a real company and a real board, so equality costs a true positive:

        3D Sellers  -> "3Dsellers"     KEEP     Airwallex   -> "Airwallex"     KEEP
        Abbvie      -> "AbbVie"        KEEP     Fund Well   -> "Fundwell"      KEEP
        Grafana Labs-> "Grafana Labs"  KEEP     Harnessinc  -> "Harness"       KEEP (prefix)
        Mixtiles    -> "Mixtiles"      KEEP     NielsenIQ   -> "NielsenIQ"     KEEP
        PSI CRO     -> "PSI CRO"       KEEP     Quanthealth -> "QuantHealth"   KEEP
        Speechify   -> "Speechify"     KEEP     Agency      -> "Meridial"      REFUSE
    ->  11 kept, 1 refused, and the 1 is the impostor. Hit 1/1, false positives 0/11.

    A minimum length of 4 on the shorter side, because containment on a 2-3 character stem
    matches most of the alphabet -- `_UID`-shaped and initialism names are the class that
    would otherwise sail through, and refusing them is correct here: an unread title is
    already a refusal.
    """
    emp = board_employer(html)
    if not emp:
        return False, ""
    a, b = _norm(name), _norm(emp)
    if not a or not b:
        return False, emp
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return (len(short) >= 4 and short in long), emp


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _fetch(url, timeout=20, cap=400_000):
    """One bounded GET. `cap` and `timeout` are both real bounds: an unbounded read from an
    arbitrary third-party host is how a previous wave got a 33-hour fetch out of a
    `timeout=5` that was per-recv rather than total."""
    import urllib.request
    try:
        rq = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(rq, timeout=timeout) as f:
            return f.read(cap).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


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
    """Build the row, or return (None, verdict) -- and returning None is the important half.

    THIS TOOL WRITES ONLY ROWS THAT ASSERT PRESENCE. It never writes "no IL listing", "no
    listing found", "unreachable" or any other statement that a company has nothing, because
    it has not earned one. Operator rule, 2026-08-28: *every company we record as having no
    roles, or as unreachable, must be hunted AND LLM-verified.* A rung that failed to find a
    board has measured its own reach, not the company -- and the previous applier wrote 51
    such verdicts in one batch on exactly that evidence.

    What happens to a name we cannot activate: NOTHING. No row. It stays in
    `research_companies.json`, which since `332@registry` is itself a worked pool --
    `listing_hunt.queue_targets()` feeds it to `hunt_one` for 60 minutes every night at
    19:00. So refusing to write costs no coverage; it costs a row that would have carried an
    unearned claim into four re-check pools and into the next reader's premises. The verdict
    a `confirm_zero` pass earns can be written later, with its evidence.

    Two deliberate choices about the gate call, each of which the previous applier got wrong:

    * the VERDICT form, not `activation_ok`, which collapses `not-ours` (PROVEN someone
      else's) and `unverified` (we could not tell) into one False. `Enlight Renewable Energy
      Ltd (ENLT)` is refused by the strict full-name test because its page says "Enlight",
      and it has 14 Israel jobs -- it is `unverified`, and calling that "another company's
      board" is a false claim written permanently onto a live row.
    * `html=` is the page we already hold, and NO `token=`. A supplied token makes
      `board_vouches` return True and short-circuits before any page is read -- handing the
      gate a token we synthesised from the name is handing it its own answer.
    """
    name, api = p["name"], p["api_url"]
    held = html if html and len(html) >= 2000 else ""
    verdict = _gate.activation_verdict(name, api, n_il, html=held)
    rung = p.get("rung") or "queue-drain"
    # The token came from the NAME, so the gate's two tests are not independent evidence
    # (see `_board_is_this_company`). Ask the board who it belongs to, and believe it over
    # both. Comeet is exempt because its API states `company_name` outright, which the drain
    # already recorded and compared.
    if verdict == "ok" and rung == "slug-probe":
        human = _gate.human_board_url(api) or api
        page = _fetch(human)
        ok, emp = _board_is_this_company(name, page)
        if not ok:
            return None, ("board-says-%s" % (emp or "nothing"))[:40]
        # The board named its employer, and that is the one identity claim on this page the
        # TENANT wrote. Use it to NAME the row when the name we came in with is the address:
        # `queue-drain` landed a row called `withfaye` -- the Comeet slug -- for the employer
        # `Faye`, and `company_name` is the join key for firmographics, the roles ledger and
        # the published board, so the slug split one employer into two identities and the
        # queue then never credited `Faye`. `row_name_for` keeps a real queue name.
        name = _QP.row_name_for(name, api, board_title=emp)
    elif verdict == "ok":
        # The same signal, free, for every other rung: the Comeet drain already recorded what
        # the board's API says its `company_name` is (`board_asserts_company`) and nothing
        # read it. `Faye`'s board asserts a real employer name while the URL says `withfaye`.
        asserts = (p.get("evidence") or {}).get("board_asserts_company") or []
        name = _QP.row_name_for(name, api,
                                board_title=(asserts[0] if len(asserts) == 1 else ""))
    if verdict == "ok" and n_il >= 1:
        seg = "queue-drain %s %s; %d/%d IL" % (today, rung, n_all, n_il)
        return [name, p["platform"], p.get("token") or "", api, "true", seg], verdict
    return None, verdict


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
    # `monitor` is the third kind, and it exists because writing NO row was worse. A hunt that
    # FOUND the company's careers page and saw no Israel role today holds an ADDRESS, which is
    # not a claim that the company has nothing -- and a parked row carrying that address is
    # what puts it in `probe_candidates`' DAILY pool, the one mechanism that wakes it the
    # morning it posts. Without the row it falls to `queue_targets` at 60 names a night out of
    # ~700: a ~12-day cycle with no daily watch at all.
    props = [p for p in doc["proposals"] if p.get("kind") in ("ats", "scrape", "monitor")]
    if a.kind:
        props = [p for p in props if p["kind"] == a.kind]
    allow = {x.strip().lower() for x in a.allow_domain_collision.split(",") if x.strip()}
    today = dt.date.today().isoformat()
    age_h = (dt.date.today() - dt.date.fromisoformat(doc.get("generated", today))).days * 24

    stats = {"written": 0, "active": 0, "deferred": 0, "held": 0, "skipped": 0}
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
            for key in ("names", "boards", "urls", "hostpath", "comeet", "terminal",
                        "allnames"):
                k[key] |= batch_keys[key]
            for d, ns in batch_keys["domains"].items():
                k["domains"].setdefault(d, set()).update(ns)

        if is_recruiter(name) or looks_like_junk(name):
            why[name] = "agency-or-junk"; stats["skipped"] += 1; continue
        # AGGREGATOR FIRST, then identity. They answer different questions: `is_aggregator`
        # asks "is this a board for many employers", the gate asks "is this THIS company's
        # page", and an aggregator's company page passes the second by naming the company
        # correctly. Reversing them is how Menora Mivtachim was activated on jobkarov.com.
        # ...and the WHOLE TRAIL, not just where it ended. A search rung resolves an
        # aggregator's page to the ATS board behind it, and the final api_url is then
        # `comeet.com/...`, which no aggregator test can refuse. `44 Ventures` is a VC that
        # `pipeline/aggregators.py` already lists WITH EVIDENCE (its page served
        # `programmaticx`'s board); its own Comeet tenant carries 7 Israel jobs that are its
        # PORTFOLIO's, and the row would publish them under the VC's name. That is the
        # Menora Mivtachim / jobkarov shape with one more indirection.
        trail = [p.get("api_url") or "", (p.get("evidence") or {}).get("candidate_url") or "",
                 (p.get("evidence") or {}).get("seed_url") or ""]
        agg = next((u for u in trail[:2] if u and is_aggregator(u)), "")
        if agg:
            why[name] = "aggregator (%s)" % agg[:44]
            stats["skipped"] += 1
            continue
        dup = _collides(p, k)
        if dup:
            why[name] = dup; stats["skipped"] += 1; continue
        dom = _own_domain(p.get("api_url") or "")
        clash = sorted(k["domains"].get(dom, set())) if dom else []
        kin = _name_kin(name, k["allnames"])
        if (clash or kin) and name.lower() not in allow:
            bits = []
            if clash:
                bits.append("domain=%s shared with %s" % (dom, ", ".join(clash[:3])))
            if kin:
                bits.append("name overlaps %s" % ", ".join(sorted(kin)[:3]))
            why[name] = "HOLD " + "; ".join(bits)
            stats["held"] += 1
            continue

        if p["kind"] == "monitor":
            # NOTHING about roles is asserted. The note names the address and carries
            # `monitored candidate` (a `verdicts.TOKENS` token, so `listing_hunt`'s pool owns
            # it too). It must never say `no IL listing` or `no listing found` --
            # `test_the_applier_never_records_a_company_as_empty_or_unreachable` enforces that.
            if not (p.get("api_url") or "").startswith("http"):
                why[name] = "monitor with no address"
                stats["skipped"] += 1
                continue
            seg = "queue-hunt %s: careers page documented; monitored candidate" % today
            row, verdict = [name, "scrape", "", p["api_url"], "false", seg], "monitor"
        elif p["kind"] == "ats":
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

        # `html=""` ON PURPOSE, and the docstring above used to imply otherwise. The proposal
        # file carries `evidence.page_chars`, not the page, so there is nothing to hand over;
        # `activation_verdict` therefore does one live GET of `human_board_url(api)` per `ats`
        # proposal. That costs no credit -- `_UNLOCK_BUDGET` is 0 -- but it is a request per
        # row, which is worth knowing before a batch of 100.
        html = ""
        if p["kind"] != "monitor":            # a monitor row is built above and asserts no roles
            row, verdict = _row_for(p, n_all, n_il, html, today)
        if row is None:
            # NOT a park. The name keeps its place in the queue, where listing_hunt's
            # 19:00 arm re-works it; writing a "no listing" row here would be a claim about
            # the company made on the strength of a rung's reach.
            why[name] = "no row: gate=%s il=%d (deferred to the hunt; NOT recorded empty)" % (
                verdict, n_il)
            stats["deferred"] += 1
            continue
        # the note goes through pipeline/notes.py even on a fresh row, so the 220-char cap and
        # the protected-segment rule are ONE code path rather than two
        row[5] = _notes.append("", row[5])
        print("  %-5s %-34s %-6s %-9s %s"
              % ("write" if a.apply else "[dry]", name[:34], row[4], verdict,
                 (row[5] or "")[:64]))
        if a.apply:
            _append(row)
        stats["written"] += 1
        stats["active"] += 1 if row[4] == "true" else 0
        stats["monitored"] = stats.get("monitored", 0) + (1 if row[4] == "false" else 0)
        for key, val in (("names", name.lower()), ("names", _norm_company(name))):
            batch_keys[key].add(val)
        batch_keys["allnames"].add((_norm(name), name))
        if row[1] and row[2]:
            batch_keys["boards"].add((row[1].lower(), row[2].lower()))
        if (row[3] or "").startswith("http"):
            lo, hp = _url_keys(row[3])
            batch_keys["urls"].add(lo)
            batch_keys["hostpath"].add(hp)
            m = COMEET_UID.search(row[3])
            if m:
                batch_keys["comeet"].add(m.group(1).lower())
        # the domain HOLD carries forward too. Every OTHER key did; this one did not, so two
        # proposals in ONE batch on the same registrable own-domain -- the `ERGO NEXT
        # Insurance` / `Next Insurance` shape, which is why the HOLD exists -- passed each
        # other and only the NEXT run's fresh read would have caught them.
        d_ = _own_domain(row[3] or "")
        if d_:
            batch_keys["domains"].setdefault(d_, set()).add(name)

    print("\n=== %s: %s ===" % ("APPLIED" if a.apply else "DRY RUN", stats))
    # EVERY refusal, not the first 40. This tool's whole contract is "dry-run, read the HOLDs,
    # then apply", and `--batch` defaults to 100: a report that silently dropped 60 of them
    # asked for a review it made impossible. Grouped by reason so the HOLDs -- the only class
    # that wants a human -- are read together rather than sorted in among the de-dups.
    by_reason = {}
    for n, w in why.items():
        by_reason.setdefault(w.split(" ")[0] if not w.startswith("HOLD") else "HOLD", []).append((n, w))
    for reason in sorted(by_reason, key=lambda r: (r != "HOLD", r != "no", r)):
        rows_ = sorted(by_reason[reason])
        print("   -- %s (%d)" % (reason, len(rows_)))
        for n, w in rows_:
            print("   skip %-34s %s" % (n[:34], w))
    if stats["active"] and a.apply:
        print("\nNEXT, and the batch is NOT done until it has run: a `scrape` row ships "
              "nothing until it is cached.\n    python refresh_scrape_cache.py --only-missing --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
