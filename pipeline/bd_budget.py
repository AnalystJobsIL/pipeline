"""The project's Bright Data ceiling, in one place, with a date on it (lane: infra).

    python -m pipeline.bd_budget            # report MTD vs the ceiling; 0 = spend, 1 = stop

WHY THIS EXISTS. Until 2026-08-28 the ceiling was a default argument in `discovery_daily`
(`BD_MONTHLY_BUDGET`, 5,000) that NO workflow set, and two documents disagreed about what it
should be: `docs/BACKLOG.md` 192 recorded the operator's decision of 2026-08-25 ("next month
must not pass 4,500"), while 335 quoted an instruction of 2026-08-27 ("self-sufficient at
5,000 monthly"). Nobody could tell which was current, and meanwhile `scrape-refresh.yml`
armed a paid rung with no cap at all and spent 72 credits a night unattended.

THE RULE has been settled twice, and both settlements live here because a ceiling nobody
re-derives is the whole point — this repo has already shipped a document that was
confidently wrong for three days:

  * **2026-08-28 (operator):** unlimited for the rest of August, 5,000 from 2026-09-01.
  * **2026-09-11 (operator):** *"unlimited budget for now; optimize once, then let it drive
    itself"* — no ceiling from 2026-09-11. The 5,000 stays as a SOFT line (`SOFT`), which
    alarms in the daily mail and refuses nothing, because 5,000 is Bright Data's free tier
    and everything past it is $1.50 per 1,000, not a wall.

What forced the second ruling: the ceiling reached 116% on the 11th of the month and the ONE
consumer that honours it is the digest's JD fill, so the only thing it stopped was the
dataset-critical one (49 postings judged on their titles alone in the 2026-09-11 mail) while
thirteen other tools kept buying. A ceiling that binds exactly one of fourteen spenders is
not a budget; `docs/decisions/2026-09-11-bd-unlimited-optimize-once.md` is the whole story.

Both dates are encoded here ONCE rather than in a workflow someone must remember to edit, and
`tests/test_units.py` pins EVERY side of both boundaries — so the rule changes itself on the
day, and a guard proves it did.

WHAT THE NUMBER IS. Month-to-date is read from the LIVE Bright Data account, not from a
counter in this repo. That matters more than it looks: every cap in this codebase is
per-PROCESS, each workflow job is a fresh process, and there is no persisted credit ledger
anywhere — so a repo-side counter could never see what the other nine workflows spent. The
account can. `discovery_daily.bd_spend_this_month()` already does exactly this read
(datasets + zone/cost, because `/customer/balance` is 403 for our token) and is reused rather
than re-implemented.

FAILING OPEN IS DELIBERATE. When the reading is unavailable — the API is down, the token is
rotated, the network blips — this reports UNKNOWN and lets the run spend. Throttling on a
number we could not fetch would silently zero a night's coverage, which is the worst failure
mode in this repo (`pipeline/sources.py` exists because of one), and the cost of the opposite
mistake is a few dollars. `budget_per_day` in `discovery_daily` already takes the same view.
The per-run `BD_RUN_CAP` in `bd_rescue` is the bound that does NOT depend on the network.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import sys

# `SWITCH` is the first day the 5,000 ceiling binds; `UNLIMITED_FROM` is the first day it
# stops binding again (the operator's ruling of 2026-09-11).
SWITCH = dt.date(2026, 9, 1)
UNLIMITED_FROM = dt.date(2026, 9, 11)
CEILING_AFTER = 5000
UNLIMITED = 0
# Bright Data's free tier, and the SOFT line the mail's `bd:` gauge alarms on once no ceiling
# binds. It refuses nothing: past it a credit costs $1.50/1,000, so the right response to
# crossing it is a sentence in the digest, not a night with no coverage.
SOFT = 5000


def ceiling(today=None):
    """The monthly credit ceiling in force on `today`. **0 means unlimited**, which is both
    August 2026 (before the first ruling) and 2026-09-11 onwards (after the second)."""
    today = today or dt.date.today()
    if os.environ.get("BD_MONTHLY_BUDGET"):         # an explicit override still wins
        try:
            return max(0, int(os.environ["BD_MONTHLY_BUDGET"]))
        except ValueError:
            pass
    if today < SWITCH or today >= UNLIMITED_FROM:
        return UNLIMITED
    return CEILING_AFTER


def spent_this_month(today=None):
    """(credits, breakdown) from the live account; (None, None) when it cannot be read."""
    try:
        from discovery_daily import bd_spend_this_month, _load_secrets
        try:
            _load_secrets()
        except Exception:  # noqa: BLE001 -- secrets.env is optional; the env may already hold them
            pass
        return bd_spend_this_month(today)
    except Exception as e:  # noqa: BLE001 -- a budget reader never costs the run it reports on
        print(f"  [bd-budget] spend unreadable ({e.__class__.__name__}) — not throttling",
              flush=True)
        return None, None


def verdict(today=None):
    """(may_spend, line). `line` is one sentence fit for a run page and a log."""
    today = today or dt.date.today()
    cap = ceiling(today)
    mtd, _ = spent_this_month(today)
    if cap == UNLIMITED:
        seen = "unknown" if mtd is None else f"{mtd:,}"
        if today < SWITCH:
            return True, (f"Bright Data: {seen} credits month-to-date, **no ceiling in force** "
                          f"until {SWITCH} (then {CEILING_AFTER:,}).")
        return True, (f"Bright Data: {seen} credits month-to-date, **no ceiling in force** "
                      f"(operator ruling {UNLIMITED_FROM}); the soft line is {SOFT:,}, the "
                      f"free tier — past it a credit costs $1.50/1,000 and the mail's `bd:` "
                      f"gauge says so.")
    if mtd is None:
        return True, (f"Bright Data: month-to-date UNREADABLE against a ceiling of {cap:,} — "
                      f"spending anyway, because throttling on a number we could not fetch "
                      f"is its own silent failure.")
    pct = mtd * 100.0 / cap
    if mtd >= cap:
        return False, (f"Bright Data: **{mtd:,} of {cap:,} credits ({pct:.0f}%) — CEILING "
                       f"REACHED.** Paid rungs are skipped this run.")
    return True, f"Bright Data: {mtd:,} of {cap:,} credits month-to-date ({pct:.0f}%)."


# ---------------------------------------------------------------- the gauge (infra, 2026-09-11)
# "Optimize once, then let it drive itself" (operator, 2026-09-11). A run page nobody opens is
# not an alarm and this repo has lost four crons to exactly that, so the meter goes where the
# operator already looks every morning: `bd:` on the mail's `Stage order:` line, and a
# `Stages:` clause when the month projects past the free tier.
LEDGER = os.path.join("cloud_state", "bd_spend.jsonl")
PAYG_PER_1K = 1.50          # brightdata.com/pricing/web-unlocker, read 2026-09-11
PURPOSES = ("search", "unlock", "discovery", "jd-fill")

# Ledger lines written before 2026-09-11 carry no `purpose`, so their tool name is the only
# evidence of what they bought. A tool is mapped by what its credits ARE, not by where it
# lives: everything that reaches `deep_validate.google_via_unlocker` is a Google SERP, and
# `bd_rescue.py` (the 02:30 pass) is the one tool whose credits are all page unlocks.
TOOL_PURPOSE = {
    "listing_hunt.py": "search", "crack_walled.py": "search",
    "queue_resolve_search.py": "search", "resolve_broken.py": "search",
    "audit_empty_rows.py": "search", "queue_pipeline.py": "search",
    "repair_dead_urls.py": "search", "repair_extract_gap.py": "search",
    "triage_dark.py": "search", "deep_validate.py": "search", "auto_expand.py": "search",
    "drain_queue.py": "search", "resolve_llm.py": "search", "registry_health.py": "search",
    "bd_rescue.py": "unlock",
    "discovery_daily.py": "discovery",
    "run.py": "jd-fill", "enrich_scrape_jd.py": "jd-fill", "enrich_matched_jd.py": "jd-fill",
}


def _ledger_lines(root="", days=7, today=None):
    """(date, purpose, credits) for the last `days` ending yesterday-inclusive of `today`."""
    today = today or dt.date.today()
    first = (today - dt.timedelta(days=days - 1)).isoformat()
    out = []
    try:
        with open(os.path.join(root, LEDGER), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue                      # a half-written line is not a reason to fail
                day = str(rec.get("at") or "")[:10]
                if not (first <= day <= today.isoformat()):
                    continue
                n = rec.get("credits") or 0
                by = rec.get("purpose") or {}
                if isinstance(by, dict) and by:
                    for k, v in by.items():
                        out.append((day, str(k), int(v or 0)))
                    # a line whose purposes do not add up to its credits (an old spender that
                    # books some calls and not others) keeps the remainder under its tool
                    rest = int(n) - sum(int(v or 0) for v in by.values())
                    if rest > 0:
                        out.append((day, TOOL_PURPOSE.get(str(rec.get("tool")), "unlock"), rest))
                elif n:
                    out.append((day, TOOL_PURPOSE.get(str(rec.get("tool")), "unlock"), int(n)))
    except OSError:
        return []
    return out


def rates(root="", days=7, today=None):
    """Credits per DAY per purpose over the last `days`, from the committed ledger.

    The ledger is the only per-purpose evidence that exists: the live account totals by
    PRODUCT (unlocker / SERP / dataset), which is a different question -- a search tool
    spends one SERP credit and then unlocks the pages it found, so it lands in both columns.
    The two are reported side by side and never added together."""
    lines = _ledger_lines(root, days, today)
    per = {p: 0 for p in PURPOSES}
    for _day, purpose, n in lines:
        per[purpose if purpose in per else "unlock"] += n
    return {p: round(v / float(max(1, days)), 1) for p, v in per.items()}


def gauge(root="", today=None, days=7):
    """What the mail says about Bright Data this morning.

    `mtd` is the LIVE account (None when it cannot be read -- reported as unknown, never as
    zero, because a zero would read as "we stopped spending"). The projection is the
    month-to-date plus the recent daily rate for the days that are left, and it is compared
    against `SOFT`, which alarms and stops nothing."""
    today = today or dt.date.today()
    mtd, _ = spent_this_month(today)
    per = rates(root, days, today)
    rate = round(sum(per.values()), 1)
    days_left = calendar.monthrange(today.year, today.month)[1] - today.day
    base = mtd if mtd is not None else round(rate * today.day)
    out = {"mtd": ("unknown" if mtd is None else int(mtd)),
           "rate": rate, "projected": int(round(base + rate * days_left)),
           "soft": SOFT, "days": days}
    out.update({p.replace("-", ""): per[p] for p in PURPOSES})
    if mtd is None:
        out["from_ledger"] = 1        # the projection is the repo's own count, not the account's
    return out


def alarm_line(g):
    """The `Stages:` clause, or "" when the month is inside the free tier."""
    if g["projected"] <= g["soft"]:
        return ""
    over = g["projected"] - g["soft"]
    return (f"bd projected {g['projected']:,} credits this month against a free tier of "
            f"{g['soft']:,} -- {over:,} over, about ${over * PAYG_PER_1K / 1000:.0f} at PAYG. "
            f"{g['days']}-day rate {g['rate']:.0f}/day: search {g['search']:.0f}, unlock "
            f"{g['unlock']:.0f}, discovery {g['discovery']:.0f}, jd-fill {g['jdfill']:.0f}")


def stamp(root="", today=None):
    """Write the `bd` stage stamp. Never raises: a gauge that can fail a run is a gauge that
    gets wrapped in `continue-on-error` and then believed when it says nothing."""
    try:
        g = gauge(root, today)
        line = alarm_line(g)
        from pipeline import stages
        stages.stamp("bd", **(dict(g, alarm=line) if line else g))
        print(f"[bd-gauge] mtd {g['mtd']} of a {g['soft']:,} free tier, {g['days']}-day rate "
              f"{g['rate']:.0f}/day (search {g['search']:.0f} unlock {g['unlock']:.0f} "
              f"discovery {g['discovery']:.0f} jd-fill {g['jdfill']:.0f}), projected "
              f"{g['projected']:,}", flush=True)
        if line:
            print(f"::warning::{line}", flush=True)
        return g
    except Exception as e:  # noqa: BLE001
        print(f"  [bd-gauge] not stamped ({e.__class__.__name__}: {str(e)[:80]})", flush=True)
        return {}


# ------------------------------------------------ per-purpose allowances: BUILT, and OFF
# `BD_ALLOWANCES=1` turns this from a no-op into an enforcing split of `SOFT` across the
# four purposes. It ships OFF, deliberately: there is no ceiling to enforce this month, and
# an allowance nobody asked for is a silent coverage cut waiting for a busy night.
#
# Why build it now rather than when it is needed: the hard part is the SEAM, not the
# arithmetic -- every one of the fourteen spenders has to reach one place, and that is only
# obvious while all fourteen are in view. The flag is the whole difference; a test
# parametrised over the spenders proves each one reaches the seam whether it is on or off.
#
# WHAT WOULD TURN IT ON: a second consecutive month projecting past `SOFT` with the operator
# unwilling to pay it. That is a decision, not a threshold, which is why no code makes it.
#
# The split follows the 2026-09-11 measurement (search 76%, unlock 19%, discovery 4%,
# jd-fill dark because the ceiling had stopped it) but deliberately does NOT copy it: the
# dataset-critical rung is the one that must never be the first to starve, so `jd-fill` is
# given the largest share AND the right to borrow. Every other class is capped where it
# stands today or a little under, which is what makes the split a budget rather than a
# description.
ALLOWANCES = {"jd-fill": 1500, "search": 2000, "unlock": 700, "discovery": 800}


def month_by_purpose(root="", today=None):
    """Credits spent this calendar month, per purpose, from the committed ledger."""
    today = today or dt.date.today()
    per = {}
    for _day, purpose, n in _ledger_lines(root, days=today.day, today=today):
        per[purpose if purpose in ALLOWANCES else "unlock"] = \
            per.get(purpose if purpose in ALLOWANCES else "unlock", 0) + n
    return per


def may_spend(consumer_class="unlock", today=None, root=""):
    """(may, why) for one PURPOSE, under the per-purpose allowances.

    Off (the shipped default) this is `(True, "allowances off")` and costs a dict lookup.

    On, `jd-fill` is privileged: when its own allowance is gone it may borrow whatever the
    other three have not spent, because a role published with no description is a defect in
    the product and a company re-checked a week late is not. Everything else stops at its
    own line.

    FAILING OPEN IS THE SAME DELIBERATE CHOICE AS EVERYWHERE ELSE HERE: an unreadable
    ledger reads as nothing spent, so a missing file or a half-written line can never zero a
    night's coverage. `BD_RUN_CAP` is the bound that needs no state at all."""
    if (os.environ.get("BD_ALLOWANCES") or "").strip() != "1":
        return True, "allowances off"
    cls = consumer_class if consumer_class in ALLOWANCES else "unlock"
    spent = month_by_purpose(root, today)
    used, allow = spent.get(cls, 0), ALLOWANCES[cls]
    if used < allow:
        return True, f"{cls} {used:,}/{allow:,}"
    if cls == "jd-fill":
        spare = sum(max(0, ALLOWANCES[p] - spent.get(p, 0)) for p in ALLOWANCES if p != cls)
        if used < allow + spare:
            return True, f"jd-fill {used:,}/{allow:,} borrowing {spare:,} unspent"
    return False, f"bd-allowance: {cls} has spent {used:,} of {allow:,} this month"


def main(argv=None):
    """Report to stdout and to the run page. Exit 1 means the paid rungs must not run.

    `python -m pipeline.bd_budget stamp` writes the daily gauge instead and always exits 0:
    it is a METER, not a gate, and the two must not be confused by a workflow author. The
    bare form stays exactly as the two preflights (`scrape-refresh`, `jd-archive`) read it."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "stamp":
        stamp()
        return 0
    may, line = verdict()
    print(f"[bd-budget] {line}", flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n- {line}\n")
        except OSError as e:
            print(f"  [bd-budget] step summary not written: {e}", flush=True)
    if not may:
        print("::warning::Bright Data ceiling reached — this run buys no credits", flush=True)
    return 0 if may else 1


if __name__ == "__main__":
    sys.exit(main())
