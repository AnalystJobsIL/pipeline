"""Registry-lane guards. Each one is a bug that shipped; the docstring is the evidence.

**Why this file exists separately.** Five times in two days another session committed a
checkout-era `tests/test_units.py` over this lane's guards — 7, then 18, then 22, then 15
more. `pytest` is exactly as green with fewer tests and `docs/check_docs.py` validates paths,
not test names, so CI never went red once. The floor test written to catch it lived inside
the file being overwritten and died with the guards every time: a floor cannot protect itself
from there.

Nine sessions share one working tree. `pytest` collects `tests/test_*.py` automatically, so a
per-lane file costs nothing and cannot be deleted by a stale copy of somebody else's. This is
`docs/BACKLOG.md` item 14, applied. Other lanes should do the same.

`test_the_guard_count_never_falls` counts across ALL test files, so it still fires if any
lane's guards disappear — including this one's.
"""
import ast
import json
import os
import re

# The shared identity gate. Fixtures patch `IG.page_names_company`, NOT the alias
# re-exported by `crack_walled` - the gate calls its own module global, so patching
# the alias silently does nothing and the fixture hits the real network instead.
from pipeline import identity_gate as IG
import pytest    # noqa: F401  (parametrize is used below)


def test_no_activating_pool_can_re_open_a_terminal_row():
    """`alias-of` is the second row for a company we ALREADY scan at that same board. It is
    terminal by construction, and `pipeline.verdicts.TERMINAL` does not list it — so any pool
    built on `in_pool()` alone contains it. `audit_empty_rows` was such a pool AND activates
    directly (`fr[4] = "true"`), so its Sunday run would search, find that same working
    board, verify it with real Israel jobs and re-activate the duplicate: every eBay role
    published twice under two company names. Measured 2026-08-23: 2 rows in the pool
    (GE HealthCare Israel, eBay Israel) and 3 more in crack_walled's (which had no terminal
    exclusion at all). `listing_hunt` and `deep_validate` already spelled it out."""
    import audit_empty_rows
    import crack_walled
    for mod in (audit_empty_rows, crack_walled):
        for token in ("defunct", "domain-dead", "alias-of"):
            assert mod.TERMINAL.search(f"note | {token} 2026-08-23: x"), (
                f"{mod.__name__} would let a `{token}` row into an ACTIVATING pool")
        assert not mod.TERMINAL.search("listing-hunt 2026-08-23: no IL listing")

def test_the_weekly_audit_search_has_a_fallback_below_serpapi():
    """`audit_empty_rows.serp()` was SerpApi-only. The free quota has been exhausted since
    mid-August (checked 2026-08-23 against the live account: `total_searches_left: 0`,
    `this_month_usage: 250`), so it returned [] BEFORE making a request and phase 2 of the
    Sunday audit — the search that finds boards which MOVED rather than broke — was a silent
    no-op across the whole ~255-row parked pool. `resolve_broken` was given exactly this
    ladder on 2026-08-23 and it was never propagated. Structural, so it cannot regress
    without someone noticing."""
    import ast
    import inspect
    import audit_empty_rows
    src = inspect.getsource(audit_empty_rows.serp)
    names = {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    assert "_serpapi" in names, "the SerpApi rung must still be tried first (it is cheapest)"
    assert "ddg" in names, "the free DuckDuckGo rung is missing from serp()"
    assert "google_via_unlocker" in names, (
        "the Bright Data rung is missing — with SerpApi at 0 and DDG rate-limited, "
        "serp() has no way to return a URL at all")

def test_activation_branches_append_to_the_note_instead_of_replacing_it():
    """The three tools that flip a row to active used to assign the whole notes cell. That
    deletes every other tool's verdict in one statement — including the terminal tokens that
    keep the row out of the wrong pool and the `dark-triage` mode that routed it here. The
    append-log rule (ARCHITECTURE.md section 2) has no exception for activation.
    `test_every_note_writer_uses_the_append_log_helper` cannot see this: a whole-cell
    assignment does no hand-rolled trim, so it passes that check."""
    import ast
    import inspect
    import audit_empty_rows
    import crack_walled
    import deep_validate
    for mod in (audit_empty_rows, crack_walled, deep_validate):
        offenders = []
        for node in ast.walk(ast.parse(inspect.getsource(mod))):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                # `fr[5] = <something that is not a call into pipeline.notes>`
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(getattr(tgt, "slice", None), ast.Constant)
                        and tgt.slice.value == 5
                        and not isinstance(node.value, ast.Call)):
                    offenders.append(ast.unparse(node)[:70])
        assert not offenders, (
            f"{mod.__name__} still overwrites the whole notes cell: {offenders}")

def test_the_three_copies_of_the_re_check_pool_still_agree_where_they_are_supposed_to():
    """There are THREE hand-maintained lists of verdict tokens — `pipeline.verdicts.TOKENS`
    (the one that claims to be the single source of truth), `listing_hunt.main()`'s inline
    regex, and `check_invariants.POOL` — and on 2026-08-23 they disagreed. This pins the
    disagreement so it cannot grow silently while the real fix (collapse all three onto
    TOKENS) waits in docs/BACKLOG.md, "One re-check pool definition".

    When `url-cleared`/`url-flagged` are added to TOKENS, EXPECTED_GAP goes empty and the
    two inline copies can be deleted. Until then a row carrying only one of those tokens is
    invisible to `audit_empty_rows` and `deep_validate`: 57 rows carry one today."""
    import re
    import check_invariants
    from pipeline.verdicts import TOKENS
    tokens = {t.lower() for t in TOKENS}
    # the two tokens the inline copies know and TOKENS does not
    EXPECTED_GAP = {"url-cleared", "url-flagged"}
    ci = {t.lower() for t in check_invariants.POOL.split("|") if t and "(" not in t}
    assert EXPECTED_GAP <= ci, "check_invariants lost a token the registry writes"
    assert EXPECTED_GAP & tokens == set(), (
        "pipeline/verdicts.TOKENS gained url-cleared/url-flagged — good. Now delete this "
        "test's EXPECTED_GAP, point listing_hunt.main() and check_invariants.POOL at "
        "verdicts.in_pool, and close the BACKLOG item.")
    for t in tokens - EXPECTED_GAP - {"no il listing", "roles-text present"}:
        assert t in ci, f"check_invariants.POOL is missing the verdict token {t!r}"

def test_a_company_cannot_leave_the_registry_without_a_reason():
    """No tool deletes rows — but a human commit does, and nothing reported one. `Time To
    Know` was deleted on purpose (9c4372ef), RESURRECTED by a concurrent cloud run's conflict
    merge (8644d8fd `row-merged state`, 1190 -> 1191 rows), then re-deleted as a silent side
    effect of a commit about Oracle HCM (0180e755). `check_invariants.py` checks the registry's
    SHAPE, never its SIZE, so all three passed."""
    import registry_health
    prev = {"Alpha": "true", "Beta": "false", "Gamma": "false",
            "__notes__": {"Alpha": "", "Beta": "defunct: acquired 2024", "Gamma": ""}}
    rows = [["Alpha", "scrape", "", "https://a/careers", "true", ""]]
    d = registry_health.census_diff(rows, prev=prev)
    assert d["prev_rows"] == 3 and d["rows"] == 1
    assert {g["company"] for g in d["gone"]} == {"Beta", "Gamma"}
    assert {g["company"] for g in d["gone"] if g["explained"]} == {"Beta"}
    assert d["unexplained"] == ["Gamma"]
    lines = registry_health.alarms(rows, live=False, res={}, prev=prev)
    assert any("REMOVED from the registry with no reason" in x and "Gamma" in x
               for x in lines), lines
    assert any("removed (explained)" in x and "Beta" in x for x in lines), lines
    # and a registry that only GREW must stay quiet
    assert not [x for x in registry_health.alarms(
        [["Alpha", "scrape", "", "https://a/careers", "true", ""],
         ["Beta", "scrape", "", "https://b/careers", "false", "defunct: acquired 2024"],
         ["Gamma", "scrape", "", "https://c/careers", "false", ""],
         ["Delta", "scrape", "", "https://d/careers", "true", ""]],
        live=False, res={}, prev=prev) if "REMOVED" in x]

@pytest.mark.parametrize("company,url,accept", [
    # The bug, caught by a dry run on 2026-08-24: `_STOP` strips "Imaging" and "Analytics",
    # leaving the core `dia`; `registrable("www.dia.mil")` is also `dia`; `verdict` returns
    # a clean `match`. The page answered 403 with ZERO bytes, so nothing else could dispute
    # it, and repair_dead_urls printed
    #   [OK] DiA Imaging Analytics  www.dia-analytics.com -> https://www.dia.mil/dia-careers/
    # — an Israeli medical-imaging company repaired to the US Defense Intelligence Agency.
    ("DiA Imaging Analytics", "https://www.dia.mil/dia-careers/", False),
    # the same shape one layer along, already known: the stripped core is the WHOLE domain
    ("Time To Know", "https://time.com/careers/", False),
    # ...and a short domain that IS the whole name is still real evidence
    ("Wix", "https://www.wix.com/jobs", True),
    ("Fiverr", "https://www.fiverr.com/careers", True),
    # the deliberate cost of the rule: a genuinely bot-walled compound domain is no longer
    # auto-repaired. It is still recovered whenever the page answers 200, because then
    # `page_mentions_company` can confirm it.
    ("IDE Technologies", "https://ide-tech.com/careers/", False),
])
def test_a_bot_walled_page_needs_the_whole_name_in_the_domain(company, url, accept):
    """With a 403 there is no page to confirm against, so identity rests on the domain
    alone — and `verdict() == "match"` is not strong enough there, because it also fires on
    the name with its generic words stripped. Only `registrable(host) == _norm(company)`
    (or an ATS host, where verdict has already checked the tenant slug) may pass."""
    import urllib.parse
    from pipeline.company_identity import verdict, registrable, _norm
    v = verdict(company, url)
    whole = bool(_norm(company)) and registrable(
        urllib.parse.urlparse(url).netloc.lower()) == _norm(company)
    assert (v == "ats" or (v == "match" and whole)) is accept

def test_a_walled_ats_crack_must_confirm_the_page_names_the_company():
    """On a walled ATS the tenant lives in the SUBDOMAIN (`careers-bancorpbank.icims.com`),
    and `company_identity.verdict` only checks a tenant in the PATH — so it returns the
    blanket `"ats"`, which its own docstring defines as "we cannot tell", and `is_foreign`
    reads that as False. `_slug_matches("Bancor", "bancorpbank")` passes too, on plain
    containment. Both were true on 2026-08-24 and `crack_walled` was one `--apply` from
    moving Bancor (Israeli crypto, ex-Bprotocol) onto The Bancorp Bank's board — 3 "Israel"
    roles that are not its own, the CyberArk->PANW class arriving through a fifth path.

    Live check that day: the page says "Bancorp" 18 times and `\bBancor\b` zero times;
    `_page_names_company` returned False for Bancor, True for "Bancorp Bank" on the same
    URL, and True for Wix on careers.wix.com. Offline half of that, plus the structural
    assertion that the crack path still calls the gate."""
    import ast
    import inspect
    import crack_walled
    from pipeline.company_identity import page_mentions_company, verdict
    from audit_empty_rows import _slug_matches

    page = "<h1>Careers at The Bancorp Bank</h1>" + ("<p>Bancorp Bank benefits</p>" * 18)
    assert page_mentions_company("Bancor", page, strict=True) is False
    assert page_mentions_company("Bancorp Bank", page, strict=True) is True
    # the two gates that let it through, pinned so their weakness is not re-discovered
    url = "https://careers-bancorpbank.icims.com/jobs/search"
    assert verdict("Bancor", url) == "ats", "a subdomain tenant is still unchecked"
    assert _slug_matches("Bancor", "bancorpbank") is True, "still passes on containment"

    src = inspect.getsource(crack_walled.crack_one)
    calls = {getattr(n.func, "attr", getattr(n.func, "id", "")) for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call)}
    assert "page_names_company" in calls, (
        "the cracked-scrape branch must confirm the page names the company before it "
        "returns a verdict the write branch activates on")


# --- registry lane, wave 2: what two adversarial reviews found in the wave-1 commit --------

def test_a_proven_foreign_crack_is_never_written_into_api_url():
    """The `_page_names_company` gate shipped as a 24-hour DELAY, not a gate. It returned
    `novrfy`, and that branch does `fr[3] = got[1]` - writing the PROVEN-FOREIGN url in as
    the row's address and stamping `host documented`, which is a `probe_candidates` pool
    token AND `listing_hunt`'s documented fast-path token. So: 19:00 crack documents Bancor
    -> The Bancorp Bank, 05:00 probe polls it, 19:00 hunt fast-paths it and ACTIVATES,
    because `is_foreign` is blind to an ATS subdomain tenant. Same wrong outcome, one day
    later, under another tool's name. `listing_hunt` already refuses to persist a foreign URL
    for exactly this reason, with a comment explaining why."""
    import ast
    import inspect
    import crack_walled
    src = inspect.getsource(crack_walled.main)
    tree = ast.parse(src.lstrip())
    assigns = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "notours" not in ast.unparse(node.test):
            continue
        # this branch's OWN body only - ast.walk would descend into the elif chain and
        # collect the `novrfy` branch's fr[3] as if it belonged here
        for st in node.body:
            for sub in ast.walk(st):
                if isinstance(sub, ast.Assign):
                    assigns += [ast.unparse(x) for x in sub.targets]
        break
    assert assigns, "the `notours` branch is gone - a foreign crack has nowhere safe to land"
    assert all(a.endswith("[5]") for a in assigns), (
        "the proven-foreign branch writes %s - it may only touch the note. Writing fr[3] "
        "hands listing_hunt's fast-path another company's board." % assigns)
    assert "notours" in inspect.getsource(crack_walled.crack_one)

def test_the_identity_refetch_is_not_weaker_than_the_evidence_that_produced_it():
    """The first gate was a plain strict-TLS urllib fetch returning a bare bool, and an
    adversarial review measured it False on 12 of 60 rows the pipeline had ALREADY verified
    as that company's own board (Meta, Akamai, Ford, Microsoft Israel...). Three causes, each
    already a paid-for lesson here: a 403 to a plain fetch (`Bit`'s own page), strict TLS
    (ARCHITECTURE section 2: "strict TLS on the scanning machine produced 6 false
    positives"), and strict=True wanting the name's words consecutively when 46 registry rows
    are named "... Israel"."""
    import inspect
    import crack_walled
    src = inspect.getsource(IG.page_names_company)
    assert "_LENIENT" in src, "strict TLS re-introduces 6 known false positives"
    assert "unlock" in src, "a bot-walled page needs the residential fetch, not a refusal"
    assert "_NAME_STOP" in src, "`Microsoft Israel` on a page saying `Microsoft` is Microsoft"
    assert "return None" in src, "unreadable must be NO EVIDENCE, not disconfirmation"
    assert crack_walled._LENIENT.verify_mode.name == "CERT_NONE"
    page = "<h1>Careers at Microsoft</h1><p>Search jobs at Microsoft.</p>" * 40
    assert IG.page_names_company("Microsoft Israel", "", html=page) is True
    bancorp = ("<h1>Careers at The Bancorp Bank</h1>" + "<p>Bancorp Bank benefits</p>" * 90)
    assert IG.page_names_company("Bancor", "", html=bancorp) is False

def test_repair_dead_urls_applies_one_identity_rule_to_both_branches():
    """Hardening only the 403 branch left the headline case open: `DiA Imaging Analytics`
    scores verdict `match` (not `weak`), because `_STOP` strips its generic words down to the
    acronym `dia` - and it was refused ONLY because dia.mil answers 403. 125 of the 516 rows
    whose own URL scores `match` (24%) rest on such a stripped core, so any impostor that
    answers 200 sailed through. One rule now: whole-name domain, or an ATS host, or the page
    names the company."""
    import ast
    import inspect
    import repair_dead_urls
    src = inspect.getsource(repair_dead_urls.main)
    assert 'v in ("match", "ats")' not in src, (
        "the 200 branch still accepts a bare `match` with no page evidence")
    assert src.count("whole_name") >= 2, "the whole-name rule must gate the accept"
    # 2026-08-24: this asserted `strict=True` appeared inline, pinning a LOCAL
    # `page_mentions_company(name, html, strict=True)`. That local form was a two-valued
    # copy of `IG.page_names_company` - it folded "unreadable" into "not us" and
    # skipped both the unlocker fallback and the name-stripping retry. The shared predicate
    # calls `page_mentions_company(..., strict=True)` itself, so the phrase test is still
    # the phrase test; the assertion now names the predicate instead of its internals.
    assert "_gate.page_names_company(name, u, html=html) is True" in src, (
        "page evidence must come from the shared three-valued predicate, and `is True` "
        "must keep an unreadable page out")
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.For, ast.While)):
            for i, st in enumerate(node.body[:-1]):
                assert not isinstance(st, (ast.Continue, ast.Break, ast.Return)), (
                    "dead code after a control-flow statement in the repair branch")

@pytest.mark.parametrize("tool", ["scan_dead_domains", "probe_candidates"])
def test_a_time_budget_without_rotation_is_permanent_tail_blindness(tool):
    """Both budgets shipped over loops that iterate in CSV FILE ORDER whose target predicate
    carries no state term - so a truncated run re-walks the same prefix every night and the
    tail is NEVER reached. `scan_dead_domains` writes nothing for a row found ALIVE, and 211
    of its 211 current targets are in that state, which made the budget's own comment
    ("re-tested tomorrow") false. `probe_candidates` is worse: a wake needs two observations,
    so a row past the cut can never wake at all. After the fix, two consecutive 40-row
    truncated nights overlap on 0 companies; before, it was 40 of 40."""
    import importlib
    import inspect
    mod = importlib.import_module(tool)
    src = inspect.getsource(mod.main)
    assert "targets.sort(" in src, tool + " does not rotate: a budget then starves the tail"
    assert ("seen" in src) or ("last" in src), tool + " has no persisted rotation key"

def test_the_daily_mail_alarm_path_touches_no_credential_and_no_network():
    """`alarms()` reports the resolution ladder, and the ladder belongs to the JOB that runs
    it. `daily-digest.yml` installs no Playwright and sets BRIGHTDATA_* only on unrelated
    steps, so wiring `alarms()` into `pipeline/run.py` - which docs/BACKLOG.md item 3 used to
    prescribe - would have put two PERMANENTLY FALSE lines in the email every single day."""
    import ast
    import inspect
    import registry_health
    src = inspect.getsource(registry_health.alarms_state)
    tree = ast.parse(src.lstrip())
    called = {getattr(n.func, 'attr', getattr(n.func, 'id', '')) for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "resources" not in called, (
        "alarms_state must never probe the ladder - that is what put "
        "`rung DOWN: Playwright/Chromium` in a digest job that never installs it")
    assert "environ" not in src and "getenv" not in src

def test_the_ownership_matrix_is_built_from_the_tools_own_predicates():
    """ARCHITECTURE section 2 calls this matrix re-derived-from-the-code, and the first
    version RETYPED each tool's filter - making it the sixth hand-maintained copy of the pool
    definitions in a repo whose worst documented bug was three copies drifting. It had
    already drifted on the day it shipped: `triage_dark` 270 vs the tool's real 242 (the copy
    omitted SKIP_NOTES), `listing_hunt` 244 vs 243 (omitted looks_like_junk). Because
    `orphans()` subtracts this membership, an over-counting mirror can only ever
    UNDER-report orphans - the one direction that loses coverage silently."""
    import registry_health
    import triage_dark
    import listing_hunt
    from pipeline.firmographics import looks_like_junk

    rows = registry_health.read_rows()
    pools = registry_health.pools(rows)

    real_triage = [r for r in rows if r[4] == "false"
                   and triage_dark.TARGET_NOTES.search(r[5] or "")
                   and not triage_dark.SKIP_NOTES.search(r[5] or "")]
    assert len(pools["triage_dark (18:00 daily)"]) == len(real_triage), (
        "the triage mirror disagrees with triage_dark's own TARGET_NOTES/SKIP_NOTES")

    hunt = pools["listing_hunt (19:00 daily)"]
    assert not [r for r in hunt if looks_like_junk(r[0])], (
        "discovery-leaked non-companies are in the hunt mirror but not in the hunt")
    assert not [r for r in hunt if listing_hunt._triaged_page_empty(r[5] or "")]

def test_a_removal_reason_must_lead_a_note_segment():
    """`GOOD_REMOVAL` was a bare substring search over the whole note, so `SmartRecruiters`
    matched "recruiter" and the TO-DO note `aggregator URL; resolve real careers page before
    activating` matched "aggregator". Measured 2026-08-24: 45 rows - 7 of them ACTIVE, incl.
    Armis, HiBob, Chunk Foods, StarkWare - would have had their deletion filed under
    "removed (explained)", the line a reader skips. An aggregator URL is a to-do, never a
    tombstone."""
    import registry_health as rh
    from pipeline.recruiters import is_recruiter
    assert rh.explained("X", "defunct: acquired 2024") is True
    assert rh.explained("X", "alias-of Y 2026-08-23: identical board URL") is True
    assert rh.explained("X", "removed 2026-08-24: hand-checked, not an employer") is True
    assert rh.explained("Armis", "platform-fix: greenhouse armissecurity is the live board "
                                 "(the SmartRecruiters row showed 2)") is False
    assert rh.explained("Chunk Foods", "listing-hunt 2026-08-23: verified 10 IL | aggregator "
                                       "URL; resolve real careers page") is False
    assert rh.explained("HiBob", "re-audit 2026-08-21: deep-verified (smartrecruiters)") is False
    assert rh.explained("X", "") is False
    agency = next((n for n in ("SQLink Group", "Recruitx", "comblack") if is_recruiter(n)), None)
    assert agency is not None and rh.explained(agency, "") is True

def test_the_census_keeps_the_newest_note_segments_not_the_oldest():
    """`note[:200]` keeps the OLDEST text, and the newest segment lives at the END - the
    exact trim bug ARCHITECTURE section 2 documents for the notes cell, shipped inside the
    tool that documents it. A removal reason is written just before the row goes, so
    truncating the tail throws away the only thing the census needs."""
    import registry_health as rh
    note = ("aggregator URL (builtin.com-class global listing) auto-parked 2026-08-22 - would "
            "attribute third-party jobs to this row; needs a real careers page before it can "
            "ever be activated | dark-triage 2026-08-22: page-empty (LLM confirms no open "
            "roles) | removed 2026-08-24: not an Israeli employer")
    kept = rh._reason_tail(note)
    assert len(kept) <= 200
    assert "removed 2026-08-24" in kept, "the removal reason was trimmed away"
    assert rh.explained("X", kept) is True
    assert rh.explained("X", note[:200]) is False       # what the old code stored

def test_the_ats_queue_separates_build_from_wire():
    """`unsupported ATS <x>` means deep_validate recognised the platform, NOT that no fetcher
    exists. Three of the eight names in the registry already have one - `phenom` and
    `eightfold` both map to fetch_eightfold, `oraclecloud.com` to `oraclehcm` - so a BUILD
    queue that does not check hands the ats-fetch lane 33 of 54 rows of work already done.
    Those rows need WIRING (crack the tenant endpoint), not a new fetcher."""
    import registry_health as rh
    from pipeline.fetchers import FETCHERS
    q = rh.unsupported_ats(rh.read_rows())
    for plat in ("phenom", "eightfold.ai", "oraclecloud.com"):
        if plat in q:
            assert q[plat]["fetcher"], plat + " has a native fetcher and the queue must say so"
            assert q[plat]["fetcher"] in FETCHERS
    for plat in ("icims.com", "successfactors", "avature.net"):
        if plat in q:
            assert not q[plat]["fetcher"], plat + " genuinely has no fetcher"

def test_triage_does_not_consume_a_probe_wake_before_the_hunt_can_use_it():
    """Cron order is probe 05:00 -> triage 18:00 -> hunt 19:00, and
    `probe_candidates._wake_note` strips the `dark-triage` segment (the fix for the 105/105
    inert-wake bug). Stripping it also resets `_needs_triage` to True, so the woken row is
    re-triaged an hour BEFORE the hunt; if triage re-stamps `page-empty`,
    `listing_hunt._triaged_page_empty` drops it and `_actionable_mode` returns False. The
    wake is not recoverable - probe_candidates persists the new baseline before the wake
    test, so the signal is spent. Same class as the inert wake, opposite direction."""
    import inspect
    import triage_dark
    src = inspect.getsource(triage_dark.main)
    assert '"probe-woken" not in' in src, (
        "triage claims woken rows and burns the wake an hour before the hunt runs")

def test_the_search_ladder_warning_fires_on_a_trailing_window_not_the_whole_run():
    """The first gate was `produced == 0` for the RUN, so one productive search anywhere
    permanently disarmed it - a ladder that died at row 40 of 255 was never reported."""
    import audit_empty_rows as A
    import inspect
    src = inspect.getsource(A.serp)
    assert "recent" in src, "the warning still gates on a whole-run counter"
    assert '_SEARCH["produced"] == 0' not in src


# --- registry lane, wave 3: what three independent verdict agents found -------------------

def test_the_registry_health_cli_actually_runs():
    """`ARCHITECTURE.md` section 2 prints `python registry_health.py` as the command a
    newcomer types, and it exited 1 with `NameError: name 'res' is not defined` — `_report`
    called `resources()` inline in a for-header and never bound the name the `alarms(...)`
    call below it needed. `--census` runs `_report` FIRST, so the row-deletion baseline could
    not be re-created either: the lane's headline capability was unreachable through its own
    interface.

    This is the same bug class the commit that introduced it celebrates fixing in
    `crack_walled.main` ("REFERENCED in the loop below but never defined — every run raised
    NameError ... behind continue-on-error"). It shipped because every test called
    `alarms()`/`alarms_state()` directly and nothing executed the entry point. So execute it."""
    import subprocess
    import sys
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for args in ([], ["--ats"], ["--json"]):
        p = subprocess.run([sys.executable, "registry_health.py"] + args, cwd=root,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
        assert p.returncode == 0, (
            "`python registry_health.py %s` exited %s:\n%s" % (" ".join(args), p.returncode,
                                                               (p.stderr or "")[-1200:]))
        assert "Traceback" not in (p.stderr or "")

def test_crack_walled_never_persists_an_untested_url_as_the_rows_address():
    """`notours` closed the door only for a foreign board that HAPPENS to return Israel jobs.
    A walled board returning 0 IL — which is exactly what `host documented, 0 IL now` means,
    and the branch that fires most often — never ran the identity check at all, and `novrfy`
    then wrote that untested URL into `api_url` with the `host documented` stamp that
    `probe_candidates` pools on and `listing_hunt`'s fast-path activates on.

    A live row was already in that state in master: `SupPlant` (Israeli agri-tech) pointed at
    `careers.workable.com`, i.e. Workable's OWN corporate careers site. Identity must be
    tested before an ADDRESS is persisted, not only before a row is activated."""
    import ast
    import inspect
    import crack_walled
    src = inspect.getsource(crack_walled.crack_one)
    tree = ast.parse(src.lstrip())
    # every `return ("novrfy", ...)` must be preceded in the function by a call to the gate
    gate_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and getattr(n.func, "attr", getattr(n.func, "id", "")) == "page_names_company"]
    assert len(gate_calls) >= 2, (
        "the identity gate is called %d time(s); the 0-IL path that persists fr[3] via "
        "`novrfy` needs one of its own" % len(gate_calls))
    novrfy_lines = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Return)
                    and "novrfy" in ast.unparse(n)]
    assert novrfy_lines and min(g.lineno for g in gate_calls) < max(novrfy_lines)

def test_a_blanket_ats_verdict_is_not_evidence_of_identity():
    """`company_identity.verdict` returns `"ats"` BOTH when the tenant slug matched and when
    there is no checkable tenant token at all — its own docstring calls the latter "we cannot
    tell". `repair_dead_urls` accepted the blanket answer as evidence, so
    `careers-bancorpbank.icims.com` was acceptable for `Bancor` with no page read, on either
    branch. An ATS host counts only when there was a tenant to check."""
    import inspect
    import repair_dead_urls
    from pipeline.company_identity import verdict, _slug_candidates
    import urllib.parse
    src = inspect.getsource(repair_dead_urls.main)
    assert 'v == "ats" or' not in src, "the blanket `ats` verdict is still a standalone pass"
    assert "_slug_candidates" in src, "nothing distinguishes a checked tenant from `cannot tell`"
    # The tenant IS extracted from the subdomain - `_slug_candidates` returns
    # ['careers-bancorpbank']. What lets Bancor through is that `_slug_matches_company` is
    # plain CONTAINMENT, so the fix is a TIGHT tenant match, not a presence check.
    u = "https://careers-bancorpbank.icims.com/jobs/search"
    assert verdict("Bancor", u) == "ats"
    assert _slug_candidates(urllib.parse.urlparse(u)) == ["careers-bancorpbank"]
    from pipeline.company_identity import _norm

    def tight(company, url):
        cn = _norm(company)
        return any(abs(len(_norm(c)) - len(cn)) <= 1 and (_norm(c) in cn or cn in _norm(c))
                   for c in _slug_candidates(urllib.parse.urlparse(url)))

    assert tight("Bancor", u) is False               # the impostor
    assert tight("Wix", "https://boards.greenhouse.io/wix") is True
    assert tight("Sproutt", "https://jobs.lever.co/sproutt") is True

def test_the_guard_count_never_falls():
    """Three times in two days a session committed a checkout-era copy of this file and
    deleted another lane's guards: `9e4ce72` took 7, then `59e222b` took all 18 of the
    registry lane's. `pytest` is exactly as green with fewer tests and `docs/check_docs.py`
    checks paths, not test names, so nothing noticed either time — the registry lane's own
    commit said "170 passed" while HEAD collected 148.

    A floor is the cheapest thing that turns a silent deletion into a red build. Raise it
    deliberately when tests are added; never lower it to make a build pass — a lower number
    here means someone's guards are gone. (docs/BACKLOG.md item 14 wants the per-lane split
    that removes the collision; this is the tourniquet.)"""
    import os
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    n = 0
    for fn in os.listdir(here):
        if fn.startswith("test_") and fn.endswith(".py"):
            src = open(os.path.join(here, fn), encoding="utf-8").read()
            n += len(re.findall(r"^def (test_\w+)", src, re.M))
    # HEAD carries 81 in test_units.py + 25 here = 106. The floor sits a little under, so
    # ordinary churn in another lane's file does not fire it while a CLOBBER (which removes
    # 7-22 at a time, every time it has happened) does. Raise it deliberately when guards are
    # added; never lower it to make a build pass - a lower number means someone's guards are
    # gone. This test lives in tests/test_registry.py precisely so that overwriting
    # tests/test_units.py cannot delete the thing that detects overwriting test_units.py.
    FLOOR = 100
    assert n >= FLOOR, (
        "%d test functions collected, floor is %d. If you did not delete tests on purpose, "
        "someone committed a stale copy of tests/test_units.py over another lane's guards — "
        "check `git log -p -- tests/test_units.py` for a commit with a large deletion." % (n, FLOOR))

def test_a_rotation_only_probe_entry_is_not_mistaken_for_a_baseline():
    """The rotation fix wrote `{"last": <date>}` on the fetch-error path - an entry with no
    `sig`/`il`. The very next SUCCESSFUL probe of that row then did `prev["il"]` and raised
    KeyError *before* `json.dump`, so the state never advanced again and, behind the
    workflow's `|| echo "probe skipped"`, no candidate would ever wake again. Measured
    2026-08-24: 61 of 153 targets have no baseline and 39 of a 40-row sample error, so the
    first --apply run would poison ~59 rows and the second would kill the step. An
    incomplete entry is not a baseline."""
    import inspect
    import probe_candidates
    src = inspect.getsource(probe_candidates.main)
    assert '"il" in prev' in src and '"sig" in prev' in src, (
        "a rotation-only entry is still treated as a baseline; the next success KeyErrors")
    # and the comparison itself must be unreachable with an incomplete prev
    prev = {"last": "2026-08-24"}
    ok = isinstance(prev, dict) and "il" in prev and "sig" in prev
    assert ok is False

def test_no_crack_walled_branch_can_write_an_unconfirmed_url():
    """`crack_one` has several `cracked`/`novrfy` exits and gating them one at a time is how
    two 0-Israel-jobs paths were missed: `cracked-api` (oraclehcm) returns on
    `if n_il or n_all` and never consulted the identity gate at all - a row could be
    ACTIVATED with zero verified Israel jobs and a note reading "verified 0 IL" - and
    `novrfy` persisted the address whenever the page was merely UNREADABLE, which for a
    walled ATS is the normal outcome. The gate now sits on the WRITE, so a future `return`
    that forgets it cannot re-open the hole."""
    import ast
    import inspect
    import crack_walled
    assert hasattr(IG, "ok_to_write"), "the shared gate moved to pipeline/identity_gate.py"
    src = inspect.getsource(crack_walled.main)
    tree = ast.parse(src.lstrip())
    # every statement that assigns fr[3] or fr[4] must sit under a test of _ok_to_write
    guarded, unguarded = 0, []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "ok_to_write" not in ast.unparse(node.test):
            continue
        for st in ast.walk(node):
            if isinstance(st, ast.Assign):
                for t in st.targets:
                    u = ast.unparse(t)
                    if u.endswith("[3]") or u.endswith("[4]"):
                        guarded += 1
    # `unguarded` used to be collected here and never asserted on — a dead list that made
    # this test look like a completeness check when its only real assertion was
    # `guarded >= 1`, satisfied by the `novrfy` branch alone. Wave 8 reopened the ACTIVATING
    # branch with a one-token edit and this test stayed green. The AST walk cannot tell a
    # guarded write from an unguarded one without re-implementing scoping, so the
    # completeness claim now lives in a fixture that runs the code:
    # `test_crack_walled_main_cannot_activate_a_board_that_does_not_name_us`.
    del unguarded
    assert guarded >= 1, "no fr[3]/fr[4] write sits under an _ok_to_write test"
    # the gate itself must demand a POSITIVE confirmation, not merely "not False"
    g = inspect.getsource(IG.ok_to_write)
    assert "is True" in g, (
        "an UNREADABLE page (None) must not pass: novrfy writes an address that "
        "listing_hunt's fast-path later activates on")

def test_a_tenant_mismatch_alone_must_not_block_an_ats_row():
    """THE reason `is_foreign` returns False for every ATS host, measured.

    Three independent reviewers recommended the same root-cause fix: stop
    `company_identity.is_foreign` early-returning False on ATS hosts, and move a near-equality
    tenant rule into shared plumbing. It was built, wired into `listing_hunt`'s fast path and
    `deep_validate`'s recovered branch, measured against the live registry - and REVERTED,
    because it rejects **36 ACTIVE rows**, and they are overwhelmingly legitimate acquisitions
    and parent-company boards that this repo names by name:

        Momentis Surgical -> greenhouse/memic          (ARCHITECTURE section 2 cites this one)
        Itamar Medical    -> zoll.wd5.myworkdayjobs
        Habana Labs (Intel) -> intel.wd1.myworkdayjobs
        VMware (Broadcom) -> broadcom.wd1.myworkdayjobs
        Splunk (Cisco)    -> cisco.wd5.myworkdayjobs
        HP Indigo         -> hp.wd5.myworkdayjobs

    A tenant that names the acquirer is INHERITANCE, not theft, and `page_mentions_company`
    cannot separate the two either - the acquirer's board does not say the subsidiary's name.
    So the permissiveness is deliberate, and any future attempt to "fix" `is_foreign` has to
    carry a second signal.

    **Where the predicate actually lives now (2026-08-24).** An earlier version of this
    docstring said it "is used ONLY in `IG.ok_to_write` ... therefore no new false
    negative is possible". That was wrong in both directions within three commits, which is
    the whole reason this note is dated:

      * it is **not** in `_ok_to_write` any more. Wave 7 measured it refusing 7 of the 9
        active rows on crack_walled's own target platforms - Oracle CX pod ids are opaque and
        can never near-match a name - so the veto was removed and the mandatory
        `_page_names_company(...) is True` left as the only gate;
      * it **is** used in `audit_empty_rows.main` (as a first pass, with a second chance from
        the CANDIDATE page) and in `repair_dead_urls.main` (as a veto on an explicit ATS
        tenant mismatch, never as evidence FOR a write).

    So a false negative here IS possible and the claim that it was not was doing no work.
    What keeps it safe is that no path treats a `True` from this predicate as sufficient.

    This test exists so the next reviewer who proposes that fix finds the measurement first."""
    import csv
    import urllib.parse
    from audit_empty_rows import tenant_is_this_company
    from pipeline.company_identity import ATS_HOST, is_foreign

    rows = [r for r in csv.reader(open("companies.csv", encoding="utf-8"))
            if r and len(r) >= 6][1:]
    active_ats = [r for r in rows if r[4] == "true" and (r[3] or "").startswith("http")
                  and ATS_HOST.search(urllib.parse.urlparse(r[3]).netloc or "")]
    would_block = [r[0] for r in active_ats if not tenant_is_this_company(r[0], r[3])]
    assert len(active_ats) > 300, "sanity: most active rows are on an ATS host"
    assert len(would_block) > 20, (
        "the tenant rule no longer rejects a large set of ACTIVE rows. If that is because "
        "the rule got smarter, good - re-measure and update this test. If it is because it "
        "was quietly widened into an activation gate, do not: it blocks real acquisitions.")
    # and is_foreign, the thing it would have replaced, passes all of them by design
    assert not [r for r in active_ats if is_foreign(r[0], r[3])], (
        "is_foreign is permissive on ATS hosts on purpose; see this test's docstring")


def test_every_crack_walled_refusal_note_is_short_and_fixed_length():
    """The three refusal branches share one 220-char cell with every other tool's verdict,
    and `notes.append` evicts whole OLD segments to make room. Two of them were carefully cut
    to 49 chars; the third - the PRIMARY refusal path, taking every `cracked-api`/oraclehcm
    case and every loose-tenant iCIMS case - was left at 101 and nobody noticed.

    Measured over the real 25-row crack pool (mean note 202/220): the long form evicts
    another tool's `unsupported ATS` token from 22 of 25 rows against 13 for the short form,
    and one all-refusing night collapsed this tool's own pool from 25 to 3. The URL is
    already in column 3; repeating it in the note buys nothing and costs a row's coverage."""
    import ast
    import inspect
    import crack_walled
    src = inspect.getsource(crack_walled.main)
    tree = ast.parse(src.lstrip())
    long_ones = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "_note_replace"):
            continue
        seg = node.args[2] if len(node.args) > 2 else None
        if seg is None:
            continue
        txt = ast.unparse(seg)
        # a segment that interpolates a URL or a netloc is variable-length and long
        if "got[1]" in txt or "netloc" in txt or "urlparse" in txt:
            long_ones.append(txt[:70])
    assert not long_ones, (
        "these crack-walled note segments interpolate a URL and so are long and "
        "variable-length: %s" % long_ones)


def test_the_alarm_file_does_not_amplify_itself():
    """`alarms_state` re-emits the ladder lines it reads back from
    `cloud_state/registry_alarms.json`, and `--census` writes `alarms()` back to that same
    file. Without a prefix test each run re-reads its own output and prepends another
    "(ladder, as of ...)": 2 alarms, then 3, then 4, unbounded - into a git-tracked state
    file, and into the daily email once the mail hook lands. Measured before the fix:
    2 -> 3 -> 4 -> 5. After: 2 -> 3 -> 3 -> 3."""
    import inspect
    import registry_health
    src = inspect.getsource(registry_health.alarms_state)
    assert 'startswith("(ladder, as of' in src, (
        "alarms_state re-emits its own re-emissions; the alarm file grows without bound")


def test_the_weekly_audit_uses_the_tenant_gate_it_defines():
    """`audit_empty_rows` DEFINES `tenant_is_this_company` and `main()` never called it - its
    activation gate was `is_foreign` alone, which returns False for every ATS host, i.e. 460
    of the 846 active rows. A search proposing `novartis.wd3.myworkdayjobs.com/riskified` for
    Riskified therefore passed both `_slug_matches` (containment) and `is_foreign` (constant
    False) and activated. This tool SEARCHES for a board, which is exactly the Lili -> Eli
    Lilly / CyberArk -> PANW class, so it is the last place that gate should be missing.

    It also activated on `verify()` returning (0, 0): no jobs at all was treated as a
    recovery, re-creating the `empty-board` rows the self-heal exists to clean up."""
    import ast
    import inspect
    import audit_empty_rows
    src = inspect.getsource(audit_empty_rows.main)
    calls = {getattr(n.func, 'attr', getattr(n.func, 'id', '')) for n in ast.walk(ast.parse(src.lstrip()))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "tenant_is_this_company" in calls, (
        "main() still activates on is_foreign alone, which is False for every ATS host")
    assert "if not n_all:" in src, "verify() returning 0 jobs must not count as a recovery"


def test_the_tenant_gate_is_scoped_before_it_tests_mismatch():
    """Order matters, and getting it wrong costs real coverage. The `mismatch` early-return
    must sit INSIDE the subdomain-tenant scope: on a path-tenant platform like greenhouse,
    `Momentis Surgical` -> `memic` scores `mismatch` and is a legitimate acquirer board that
    ARCHITECTURE section 2 cites by name. Testing mismatch before scoping blocked it."""
    from audit_empty_rows import tenant_is_this_company as T
    # legitimate acquirer boards on PATH-tenant platforms must pass
    assert T("Momentis Surgical", "https://boards-api.greenhouse.io/v1/boards/memic/jobs")
    assert T("SentinelOne", "https://boards-api.greenhouse.io/v1/boards/sentinellabs/jobs")
    # the impostors on SUBDOMAIN-tenant platforms must not
    assert not T("Riskified", "https://novartis.wd3.myworkdayjobs.com/en-US/riskified")
    assert not T("Bancor", "https://careers-bancorpbank.icims.com/jobs")
    # ...and a company's own subdomain tenant still passes
    assert T("Riskified", "https://riskified.wd3.myworkdayjobs.com/careers")


def test_registry_state_writes_are_atomic():
    """`open(path, "w")` truncates immediately. Both of these files are git-tracked and both
    are written inside the 05:00 digest: a kill mid-write leaves a short file that parses as
    "no baselines", which silently costs a full wake cycle for every monitored candidate.
    Every sibling tool in this lane already goes through `pipeline.atomic`."""
    import inspect
    import probe_candidates
    import audit_empty_rows
    for mod in (probe_candidates, audit_empty_rows):
        src = inspect.getsource(mod)
        assert 'json.dump(state, open(' not in src and 'json.dump(done, open(' not in src, (
            "%s still writes state through a truncating open()" % mod.__name__)
        assert "write_json" in src


def test_repair_dead_urls_uses_the_shared_tenant_predicate():
    """Its inline `ats_checked` was a FLAT any() over `_slug_candidates`, which returns host
    labels and path segments in one list - the exact shape the shared predicate's docstring
    names as the bug. `novartis.wd3.myworkdayjobs.com/en-US/riskified` passed for Riskified
    because the PATH matched while the tenant is Novartis. This tool runs at 19:00
    immediately before listing_hunt in the same job, so a wrong address here reaches the
    fast path about thirty minutes later rather than a day later."""
    import inspect
    import repair_dead_urls
    src = inspect.getsource(repair_dead_urls.main)
    import ast
    assert "tenant_is_this_company" in src
    # check CODE, not prose - the explanatory comment legitimately names the old function
    tree = ast.parse(src.lstrip())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_slug_candidates" not in names, "the hand-rolled flat any() is still there"
    assert "tenant_is_this_company" in {
        getattr(n.func, 'attr', getattr(n.func, 'id', '')) for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


# ---------------------------------------------------------------------------------------
# Wave-7 behavioural guards.
#
# The three guards written in wave 6 (`..._uses_the_tenant_gate_it_defines`,
# `..._uses_the_shared_tenant_predicate`, `..._refusal_note_is_short`) are `inspect`/AST
# checks that a NAME appears in a function. Wave 7 found four write-path bugs and **all
# four passed those guards**: calling the gate and letting its `False` be overridden by a
# fallback looks identical to an AST check. These drive `main()` end-to-end against a
# scratch registry and assert on the bytes that land in `companies.csv`.
#
# Every one of them fails on the commit before the fix.
# ---------------------------------------------------------------------------------------

def _registry(tmp_path, rows):
    """Write a scratch companies.csv and chdir into it. Header + `rows`."""
    p = tmp_path / "companies.csv"
    body = "".join(",".join(r) + "\n" for r in rows)
    p.write_text("company_name,ats_platform,token,api_url,active,notes\n" + body,
                 encoding="utf-8")
    return p


def _read(tmp_path):
    import csv as _csv
    with open(tmp_path / "companies.csv", encoding="utf-8") as fh:
        return {r[0]: r for r in _csv.reader(fh) if r}


def test_the_weekly_audit_confirms_identity_from_the_candidate_not_the_rows_own_page(
        tmp_path, monkeypatch):
    """The audit's second chance must read the CANDIDATE board, never the row's own url.

    Between commits c9c18ac and this one the fallback was
    `fetch(api) or fetch(r[3])`. `r[3]` is the company's OWN careers page, so the check
    found "Riskified" on riskified.com and accepted that as proof that
    `novartis.wd3.myworkdayjobs.com/riskified` belongs to Riskified — it rubber-stamped
    every mismatch the gate exists to catch. It was not a corner case: a plain GET of the
    endpoints this tool proposes returns "" (Workday `/wday/cxs` is POST-only, Greenhouse
    blocks the UA), so the fallback fired on essentially every row.

    Fiverr is the positive control: remove it and a gate that refuses everything passes.
    """
    import os
    import sys
    import audit_empty_rows as A
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        # r[3] carries the company's OWN careers page — the realistic shape: 236 of the
        # 255 rows in the Sunday pool have one, and it is what the old fallback read.
        ["Riskified", "", "", "https://www.riskified.com/careers/", "false",
         "no listing found 2026-01-01: dark"],
        ["Fiverr", "", "", "https://www.fiverr.com/jobs", "false",
         "no listing found 2026-01-01: dark"],
    ])
    os.makedirs(tmp_path / "state", exist_ok=True)
    (tmp_path / "state" / "audit_done.json").write_text("{}", encoding="utf-8")

    FOREIGN = "https://novartis.wd3.myworkdayjobs.com/riskified"
    OWN = "https://www.riskified.com/careers/"
    FIVERR = "https://boards.greenhouse.io/fiverr"
    pages = {
        # The candidate is readable and carries a Workday signature, so the platform is
        # detected — it simply names NOVARTIS, not Riskified. That is the whole point: the
        # only page that names Riskified is Riskified's own, and reading it proves nothing
        # about who owns the Novartis board.
        FOREIGN: "<html>Novartis careers " + FOREIGN + " " + "y" * 3000 + "</html>",
        OWN: "<html>Riskified careers. Riskified is hiring. " + "x" * 3000 + "</html>",
        FIVERR: "<html>Fiverr careers " + FIVERR + " " + "w" * 3000 + "</html>",
    }
    monkeypatch.setattr(A, "fetch", lambda url, timeout=20: pages.get(url, ""))
    monkeypatch.setattr(A, "serp",
                        lambda name, limit=5: {"Riskified": [FOREIGN],
                                               "Fiverr": [FIVERR]}.get(name, []))
    monkeypatch.setattr(A, "verify", lambda name, plat, tok, api: (12, 5))
    # The audit's second chance now goes through the SHARED three-valued predicate, which
    # does its own fetching (and can reach the unlocker). Stub it, or this test makes real
    # network calls: hermetic tests are why the fixture exists.
    import crack_walled as C
    monkeypatch.setattr(IG, "page_names_company",
                        lambda name, url, html="": {"Riskified": False}.get(name))
    monkeypatch.setattr(sys, "argv", ["audit_empty_rows.py", "--apply"])
    A.main()

    out = _read(tmp_path)
    assert out["Riskified"][4] == "false", (
        "the audit activated Riskified on Novartis's board: %r" % (out["Riskified"],))
    assert "novartis" not in out["Riskified"][3].lower(), (
        "the audit persisted a foreign address into api_url: %r" % (out["Riskified"][3],))
    assert out["Fiverr"][4] == "true", (
        "positive control regressed — the gate now refuses everything: %r" % (out["Fiverr"],))


def test_deep_validate_refuses_the_three_shapes_its_twin_already_refuses(
        tmp_path, monkeypatch):
    """`deep_validate` had NO identity gate, 24h before its twin refuses the same rows.

    Its whole gate was `is_foreign(...) or not looks_like_a_job_listing_page(...)`, and
    `is_foreign` returns False for every ATS host by design (ARCHITECTURE.md section 2,
    docs/BACKLOG.md 21) — so on an ATS host there was no gate at all. It also had no
    `n_all` check, so a board that verifies with zero jobs counted as a recovery.

    `deep_validate` and `audit_empty_rows` select the IDENTICAL 255 rows
    (docs/BACKLOG.md 6) and run 24 hours apart, so Saturday silently re-opened what
    Sunday had closed.
    """
    import sys
    import deep_validate as D
    import crack_walled as C
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Riskified", "", "", "https://www.riskified.com/careers/", "false",
         "dark-triage 2026-01-01: page-empty"],
        ["Bancor", "", "", "https://www.bancor.network/careers", "false",
         "dark-triage 2026-01-01: page-empty"],
        ["ZeroBoard", "", "", "https://zeroboard.com/careers", "false",
         "dark-triage 2026-01-01: page-empty"],
        ["Fiverr", "", "", "https://www.fiverr.com/jobs", "false",
         "dark-triage 2026-01-01: page-empty"],
    ])

    class _Rend:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    res = {
        "Riskified": ("recovered", "workday", "novartis/riskified",
                      "https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/riskified/jobs",
                      12, 5, ""),
        "Bancor": ("recovered", "scrape", "bancorpbank",
                   "https://careers-bancorpbank.icims.com/jobs/search?ss=1", 30, 9, ""),
        "ZeroBoard": ("recovered", "greenhouse", "zeroboard",
                      "https://boards-api.greenhouse.io/v1/boards/zeroboard/jobs", 0, 0, ""),
        "Fiverr": ("recovered", "greenhouse", "fiverr",
                   "https://boards-api.greenhouse.io/v1/boards/fiverr/jobs", 40, 12, ""),
    }
    names = {"Fiverr": True, "ZeroBoard": True, "Riskified": False, "Bancor": False}
    monkeypatch.setattr(D, "Renderer", _Rend)
    monkeypatch.setattr(D, "validate_one", lambda rend, name, url: res[name])
    monkeypatch.setattr(IG, "page_names_company",
                        lambda name, url, html="": names.get(name))
    monkeypatch.setattr(sys, "argv", ["deep_validate.py", "--apply"])
    D.main()

    out = _read(tmp_path)
    assert out["Riskified"][4] == "false", "activated Novartis's board for Riskified"
    assert out["Bancor"][4] == "false", "activated The Bancorp Bank's board for Bancor"
    assert out["ZeroBoard"][4] == "false", (
        "a board that verifies with 0 jobs is the empty-board shape, not a recovery")
    assert out["Fiverr"][4] == "true", "positive control regressed"
    assert "boards-api.greenhouse.io" in out["Fiverr"][3]


def test_the_deep_validate_refusal_note_is_short_and_carries_no_url(tmp_path, monkeypatch):
    """A refusal note is written into a 220-char append-log; length is a coverage decision.

    The old form interpolated a 40-char URL and ran to 105 chars. Measured against the
    real `companies.csv` over `deep_validate`'s own 260-row pool, re-stamping that segment
    evicted an older segment from 142 rows and pushed 36 out of `in_pool` entirely. Since
    this tool's own filter IS `in_pool`, a row its refusal ejected could never be
    re-examined by it again — the refusal was self-sealing. The 51-char form: 12 and 9.
    """
    import re
    import inspect
    import deep_validate as D
    src = inspect.getsource(D.main)
    seg = re.search(r'f"deep-validated \{TODAY\}: ([^"]*)"', src)
    assert seg, "could not find the deep-validated refusal segment in main()"
    body = seg.group(1)
    assert "{" not in body, (
        "the refusal note interpolates %r — a variable-length note (usually a URL) is how "
        "this segment reached 105 chars and ejected 36 rows from the pool" % (body,))
    assert len("deep-validated 2026-08-24: ") + len(body) <= 60, (
        "refusal note is %d chars; its siblings in crack_walled are 49"
        % (len("deep-validated 2026-08-24: ") + len(body)))


def test_repair_needs_the_page_to_name_us_not_a_tenant_it_cannot_check(
        tmp_path, monkeypatch):
    """"Cannot tell" is not positive confirmation.

    `tenant_is_this_company` returns True when there is nothing checkable to match against
    (`if not labels: return True`). As the FIRST disjunct of the accept condition it
    short-circuited the page test, so a dead host was replaced by a bare ATS front door:
    `SupPlant -> https://careers.workable.com/`, whose every host label is Workable's own
    plumbing and whose page never says "SupPlant". The row keeps its `host documented`
    token, and `listing_hunt`'s fast path runs ~30 minutes later in the same 19:00 job.

    Two positive controls: 403-then-unlocker, and a plain 200 whose page names us.
    """
    import sys
    import repair_dead_urls as R
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["SupPlant", "scrape", "", "https://careers.supplant-dead.com", "false",
         "monitored candidate 2026-01-01: host documented"],
        ["WallCo", "scrape", "", "https://careers.wallco-dead.com", "false",
         "monitored candidate 2026-01-01: host documented"],
        ["GoodCo", "scrape", "", "https://www.goodco-dead.com", "false",
         "monitored candidate 2026-01-01: host documented"],
    ])
    cand = {"SupPlant": ["https://careers.workable.com/"],
            "WallCo": ["https://careers.wallco.example/jobs"],
            "GoodCo": ["https://www.goodco.example/careers"]}
    pages = {
        # Workable's own front door: names WORKABLE, never SupPlant
        "https://careers.workable.com/":
            (200, "<html>Workable is hiring. Join Workable. " + "a" * 2000 + "</html>"),
        "https://careers.wallco.example/jobs": (403, ""),
        "https://www.goodco.example/careers":
            (200, "<html>GoodCo careers - GoodCo is hiring " + "b" * 2000 + "</html>"),
    }
    monkeypatch.setattr(R, "resolves", lambda h, tries=3: not h.endswith("-dead.com"))
    monkeypatch.setattr(R, "candidates", lambda name, dead: cand.get(name, []))
    monkeypatch.setattr(R, "fetch", lambda u: pages.get(u, (0, "")))
    monkeypatch.setattr(R, "_unlock",
                        lambda u: ("<html>WallCo careers - WallCo is hiring "
                                   + "c" * 2000 + "</html>") if "wallco" in u else "")
    monkeypatch.setattr(sys, "argv", ["repair_dead_urls.py", "--apply"])
    R.main()

    out = _read(tmp_path)
    assert "workable.com" not in out["SupPlant"][3], (
        "repaired SupPlant to Workable's own front door: %r" % (out["SupPlant"][3],))
    assert out["SupPlant"][3] == "https://careers.supplant-dead.com"
    assert out["WallCo"][3] == "https://careers.wallco.example/jobs", "403 control regressed"
    assert out["GoodCo"][3] == "https://www.goodco.example/careers", "200 control regressed"


def test_the_write_gate_does_not_refuse_the_platforms_it_exists_to_crack():
    """A gate that refuses everything is not safe, it is silent exclusion (section 8, #1).

    `_ok_to_write` used `tenant_is_this_company` as a veto stacked on top of a page test
    that is already mandatory. Measured on the live registry 2026-08-24, that veto refused
    7 of the 9 active rows on `crack_walled`'s own target platforms — Oracle CX pod ids
    (`hctz`, `edel`, `iawmqy`) are opaque by construction and can never near-match a
    company name, so the `cracked-api`/oraclehcm branch could never write at all — and 31
    of the 433 active ATS rows. Each refusal also stamped a *wrong* "not this company's
    board" verdict into the row.

    Meanwhile `verdict()` calls the two boards we most need to refuse a plain `ats`. The
    tenant string is wrong in both directions; page content is the only discriminator that
    works, so it is the only one used.
    """
    import csv as _csv
    import os
    import re
    import crack_walled as cw
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    orig = IG.page_names_company
    try:
        IG.page_names_company = lambda n, u, html="": True      # perfect page evidence
        with open(os.path.join(root, "companies.csv"), encoding="utf-8") as fh:
            rows = [r for r in _csv.reader(fh) if r and len(r) >= 6][1:]
        plat = re.compile(r"oraclecloud|eightfold|icims|jobvite|taleo|avature|phenom", re.I)
        tgt = [r for r in rows
               if r[4].strip().lower() == "true" and r[3].startswith("http")
               and plat.search(r[3])]
        assert tgt, "fixture drift: no active rows on the target platforms"
        refused = [r[0] for r in tgt if not IG.ok_to_write(r[0], r[3])]
        assert not refused, (
            "%d of %d already-verified rows on this tool's own platforms are refused even "
            "with perfect page evidence: %s" % (len(refused), len(tgt), refused))

        IG.page_names_company = lambda n, u, html="": False
        assert not IG.ok_to_write(
            "Riskified", "https://novartis.wd3.myworkdayjobs.com/riskified")
        assert not IG.ok_to_write(
            "Bancor", "https://careers-bancorpbank.icims.com/jobs/search?ss=1")
        IG.page_names_company = lambda n, u, html="": None       # unreadable
        assert not IG.ok_to_write("Anyone", "https://x.icims.com/jobs/search?ss=1"), (
            "an unreadable page is no evidence and must never be written")
    finally:
        IG.page_names_company = orig


def test_the_hunt_needs_the_page_to_name_us_on_a_walled_ats(tmp_path, monkeypatch):
    """`listing_hunt` was the last activating path in the walled class with no page test.

    Its `found` branch sets `fr[4] = "true"`, and until 2026-08-24 the ONLY thing between a
    hunted URL and an active row was `looks_like_a_job_listing_page` — no identity test at
    all. Its `nolisting` branch persisted the candidate into `fr[3]` gated on `is_foreign`,
    which returns False for every ATS host by design, and this tool's own documented
    fast-path re-reads that address the next night.

    Two rows were queued against it on 2026-08-24: `NanoLock Security` ->
    `gen.wd1.myworkdayjobs.com` (Gen Digital's tenant) and `Sight Diagnostics` ->
    `recruiting2.ultipro.com/SIG1008SIGH`, a board on which `Sight Sciences` is ALREADY
    active — activating it publishes one company's roles under two company names.

    The ordinary-domain control is the other half: the page test is scoped to ATS hosts on
    purpose, because `_page_names_company` answers `None` for any page under 2000 chars and
    routing every JS-rendered careers page through it would trade this hole for silent
    exclusion.
    """
    import listing_hunt as L
    import crack_walled as C
    orig = IG.page_names_company
    try:
        IG.page_names_company = lambda n, u, html="": False     # the board never names us
        assert not IG.identity_ok(
            "NanoLock Security", "https://gen.wd1.myworkdayjobs.com/careers/")
        assert not IG.identity_ok(
            "Sight Diagnostics", "https://recruiting2.ultipro.com/SIG1008SIGH/JobBoard/x/")
        # ordinary careers domain: unchanged, still admitted without a page read
        assert IG.identity_ok("Acme", "https://www.acme.com/careers")
        IG.page_names_company = lambda n, u, html="": True
        assert IG.identity_ok("Nutanix", "https://nutanix.eightfold.ai/careers?location=IL")
        IG.page_names_company = lambda n, u, html="": None       # unreadable == no evidence
        assert not IG.identity_ok("Nutanix", "https://nutanix.eightfold.ai/careers?x=1")
    finally:
        IG.page_names_company = orig


def test_both_hunt_write_branches_route_through_the_identity_gate():
    """Refusing to ACTIVATE while still writing the ADDRESS only delays the mistake 24h.

    That is the shape wave 6 fixed in `crack_walled` (`novrfy` persisting a `host
    documented` url that `listing_hunt`'s fast path then activated), so both of this tool's
    write branches have to carry the same gate — the activating one and the one that merely
    persists a candidate.
    """
    import inspect
    import listing_hunt
    src = inspect.getsource(listing_hunt.main)
    assert src.count("_gate.identity_ok(name, url)") >= 2, (
        "both the `found` (activates) and `nolisting` (persists fr[3]) branches must gate "
        "on _identity_ok; found %d call(s)" % src.count("_gate.identity_ok(name, url)"))
    body = src[src.index('elif verdict == "nolisting"'):]
    assert body.index("_gate.identity_ok(name, url)") < body.index("fr[3] = url")


def test_crack_walled_main_cannot_activate_a_board_that_does_not_name_us(
        tmp_path, monkeypatch):
    """Drives `crack_walled.main()`. The ACTIVATING branch had no behavioural cover at all.

    `test_no_crack_walled_branch_can_write_an_unconfirmed_url` walks the AST, collects every
    unguarded `fr[3]`/`fr[4]` write into a list called `unguarded` — and never asserts on it.
    Its only assertions are `guarded >= 1`, satisfied by the `novrfy` branch alone, and
    `"is True" in <source of _ok_to_write>`. So a wave-8 reviewer changed

        if verdict.startswith("cracked") and not _ok_to_write(name, got[1]):
     -> if verdict == "cracked-scrape" and not _ok_to_write(name, got[1]) and n_il < 0:

    and `pytest` reported 224 passed while `cracked-api`/oraclehcm activated a row with
    `verified 0 IL` — verbatim the failure that test's own docstring describes.
    """
    import sys
    import crack_walled as C
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["OraCo", "", "", "https://oraco.com/careers", "false",
         "unsupported ATS oraclecloud.com"],
        ["GoodCo", "", "", "https://goodco.com/careers", "false",
         "unsupported ATS icims.com"],
    ])
    ora = ("https://hctz.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
           "recruitingCEJobRequisitions?onlyData=true")
    good = "https://goodco.icims.com/jobs/search?ss=1"
    res = {"OraCo": ("cracked-api", ("oraclehcm", ora), 0, "12 total"),
           "GoodCo": ("cracked-scrape", ("scrape", good), 4, "4 IL")}
    monkeypatch.setattr(C, "crack_one", lambda name, seed, plat: res[name])
    # OraCo's board does not name it; GoodCo's does. Positive control is mandatory: a gate
    # that refuses everything must not be able to pass this test.
    monkeypatch.setattr(IG, "page_names_company",
                        lambda name, url, html="": {"GoodCo": True}.get(name, False))
    monkeypatch.setattr(sys, "argv", ["crack_walled.py", "--apply"])
    C.main()

    out = _read(tmp_path)
    assert out["OraCo"][4] == "false", (
        "activated a row whose board never names it: %r" % (out["OraCo"],))
    assert "oraclecloud" not in out["OraCo"][3], (
        "persisted an unconfirmed endpoint into api_url: %r" % (out["OraCo"][3],))
    assert out["GoodCo"][4] == "true", "positive control regressed"
    assert out["GoodCo"][3] == good


def test_listing_hunt_main_cannot_activate_a_board_that_does_not_name_us(
        tmp_path, monkeypatch):
    """Drives `listing_hunt.main()`. Nothing did.

    `test_both_hunt_write_branches_route_through_the_identity_gate` asserts
    `src.count("_gate.identity_ok(name, url)") >= 2` — a source-string count. A wave-8 reviewer
    changed `not _identity_ok(name, url)` to `_identity_ok(name, url) is None`, preserving
    the text, and reopened the hole with `pytest` at 224 passed. The sibling guard calls
    `_identity_ok` directly, which tests the predicate, not the branch that uses it.
    """
    import sys
    import listing_hunt as L
    import crack_walled as C
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        # `no ATS detected` is a hunt-pool token; `page-empty` is deliberately NOT one
        # (the daily probe owns those rows), so it selects nothing.
        ["NanoLock Security", "", "", "https://nanolock.com/careers", "false",
         "dark-triage 2026-01-01: no ATS detected"],
        ["GoodCo", "", "", "https://goodco.com/careers", "false",
         "dark-triage 2026-01-01: no ATS detected"],
    ])
    foreign = "https://gen.wd1.myworkdayjobs.com/careers/"
    ownpage = "https://www.goodco.com/careers/openings"
    res = {"NanoLock Security": ("found", foreign, 7, ""),
           "GoodCo": ("found", ownpage, 5, "")}
    monkeypatch.setattr(L, "hunt_one",
                        lambda name, seed, documented=False, mode="": res[name])
    monkeypatch.setattr(IG, "page_names_company", lambda name, url, html="": False)
    monkeypatch.setattr(sys, "argv", ["listing_hunt.py", "--apply"])
    L.main()

    out = _read(tmp_path)
    assert out["NanoLock Security"][4] == "false", (
        "activated Gen Digital's Workday for NanoLock: %r" % (out["NanoLock Security"],))
    assert "myworkdayjobs" not in out["NanoLock Security"][3], (
        "persisted a foreign ATS board into api_url: %r" % (out["NanoLock Security"][3],))
    # ordinary domain: the page test is deliberately NOT applied there, so this still
    # activates even though `_page_names_company` is stubbed False. That scoping is the
    # reason JS-rendered careers pages are not silently excluded.
    assert out["GoodCo"][4] == "true", (
        "the ordinary-domain path must not be gated on a page read: %r" % (out["GoodCo"],))


def test_the_hunts_refusal_notes_are_short_and_carry_no_url():
    """A refusal note is written into a 220-char cell shared with every other tool.

    The two notes added with `_identity_ok` were 97 and 102 chars. Re-stamped over the hunt
    pool they evicted the OLDEST segment from ~190 of 274 rows — and on this pool the oldest
    segment is `deep-validated ...: unsupported ATS <x>`, which is `crack_walled`'s ENTIRE
    pool predicate. `listing_hunt` runs BEFORE `crack_walled` in listing-hunt.yml, so the
    collapse lands inside the same job: measured on the real registry, crack-pool survivors
    after one sweep were 4 of 30. At 62/66 chars they are 20 and 18 of 30.

    Neither `check_invariants` nor `registry_health` can see a pool falling to zero — both
    have only an aggregate floor — so this has to be a test.
    """
    import re
    import inspect
    import listing_hunt as L
    src = inspect.getsource(L.main)
    segs = re.findall(r'f"listing-hunt \{TODAY\}: ([^"]*)"', src)
    assert segs, "could not find the listing-hunt note segments"
    for body in segs:
        rendered = len("listing-hunt 2026-08-24: ") + len(body)
        assert "urlparse" not in body and "netloc" not in body, (
            "a URL in a refusal note is what took this segment to 97 chars: %r" % (body,))
        assert rendered <= 80, (
            "note segment %r renders to %d chars; the pool cannot afford it"
            % (body, rendered))


def test_repair_extract_gap_main_cannot_activate_a_foreign_board(tmp_path, monkeypatch):
    """The sixth activating tool had NO test of any kind, and its gate can be switched off.

    `test_every_activation_path_checks_company_identity` only asserts the string
    `company_identity` appears in the file — it does, via two imports, one of which
    (`is_foreign`) this tool no longer uses for identity. A wave-9 reviewer changed

        if il and not _identity_ok(r[0], r[3]):
     -> if il and _identity_ok(r[0], r[3]) is None:

    and `pytest` reported 227 passed while `NanoLock Security` activated onto
    `gen.wd1.myworkdayjobs.com` — Gen Digital's Workday.

    This tool runs at 19:00, THIRTY MINUTES BEFORE `listing_hunt`, and forces
    `SCRAPE_ASSUME_IL=1`, which makes every location-less card on an Israel-token page an
    Israel role. Its `il` count is the weakest evidence any activating path acts on.
    """
    import sys
    import repair_extract_gap as G
    import crack_walled as C
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["NanoLock Security", "", "", "https://gen.wd1.myworkdayjobs.com/en-US/careers/",
         "false", "dark-triage 2026-01-01: extract-gap (356 role phrases after render)"],
        ["GoodCo", "", "", "https://www.goodco.com/careers/openings", "false",
         "dark-triage 2026-01-01: extract-gap (12 role phrases after render)"],
    ])
    monkeypatch.setattr("scrape_universal.scrape",
                        lambda name, url: [{"title": "Engineer", "location": "Tel Aviv"}])
    monkeypatch.setattr(IG, "page_names_company", lambda name, url, html="": False)
    monkeypatch.setattr(sys, "argv", ["repair_extract_gap.py", "--apply"])
    G.main()

    out = _read(tmp_path)
    assert out["NanoLock Security"][4] == "false", (
        "activated Gen Digital's Workday: %r" % (out["NanoLock Security"],))
    # ordinary domain is deliberately not page-gated — positive control
    assert out["GoodCo"][4] == "true", (
        "the ordinary-domain path must still activate: %r" % (out["GoodCo"],))


def test_deep_validate_never_falls_back_to_the_rows_own_page(tmp_path, monkeypatch):
    """`_cand` must be the CANDIDATE, never `api or r[3]`.

    Every other fixture supplies a non-empty `api`, so the wave-7 bug — falling back to the
    row's own careers page when the LLM tier proposes `scrape` with no `api_url` — could be
    re-introduced textually (`_cand = api or ""` -> `_cand = api or r[3] or ""`) with the
    suite green. `fetch_scrape` keys on `company_name`, not the URL, so `verify()` succeeds
    and the row activates on an identity confirmed from the wrong page.
    """
    import sys
    import deep_validate as D
    import crack_walled as C
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Riskified", "", "", "https://www.riskified.com/careers/", "false",
         "dark-triage 2026-01-01: page-empty"],
    ])

    class _Rend:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(D, "Renderer", _Rend)
    # the LLM tier's shape: scrape, real jobs, and NO api_url
    monkeypatch.setattr(D, "validate_one",
                        lambda rend, name, url: ("recovered", "scrape", "riskified", "",
                                                 12, 5, ""))
    # the row's OWN page names it — the trap the fallback walked into
    monkeypatch.setattr(IG, "page_names_company", lambda name, url, html="": True)
    monkeypatch.setattr(sys, "argv", ["deep_validate.py", "--apply"])
    D.main()

    out = _read(tmp_path)
    assert out["Riskified"][4] == "false", (
        "activated on an empty candidate by reading the row's own page: %r"
        % (out["Riskified"],))


def test_the_walled_pool_survives_another_tools_note_rewrite():
    """`crack_walled`'s pool must not be a string a different tool owns and rewrites.

    It was the literal `unsupported ATS`, which `deep_validate` writes inside ITS OWN
    segment — so `notes.replace_own` deleted it on every verdict that is not `unsupported`.
    Measured on the real registry 2026-08-24: the token lived only in `deep_validate`'s
    segment on 24 of 25 pool rows, and one simulated all-dark Saturday took the pool 25 -> 0
    with every guard green. Membership now also derives from the row's HOST, which only this
    lane's tools write.
    """
    import csv as _csv
    import os as _os
    from pipeline.notes import replace_own
    import crack_walled as cw
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    with open(_os.path.join(root, "companies.csv"), encoding="utf-8") as fh:
        rows = [r for r in _csv.reader(fh) if r and len(r) >= 6][1:]
    pool = [r for r in rows if r[4] == "false" and IG.is_walled(r)]
    assert pool, "fixture drift: the walled pool is empty"

    survived = 0
    for r in pool:
        r2 = list(r)
        r2[5] = replace_own(r[5], "deep-validated",
                            "deep-validated 2026-08-24: no listing found; dark")
        if IG.is_walled(r2):
            survived += 1
    assert survived >= len(pool) // 3, (
        "one deep_validate night took the walled pool from %d to %d — the pool predicate is "
        "again a string another tool can delete" % (len(pool), survived))


# ---------------------------------------------------------------------------------------
# The derived registry-writer enumeration.
#
# Every hand-written list of "which tools activate a row" in this repo has been wrong. The
# guard in tests/test_units.py finds writers by looking for `ast.Assign` to a Subscript with
# constant slice 4 -- which sees 8 of the 22 modules that actually write the registry, because
# fourteen of them build a whole row literal [name, plat, tok, api, "true", note] in one
# statement and never subscript-assign anything. Five of those fourteen run on cron.
#
# So the list is derived here, from source, and a new writer is a red test rather than a
# discovery nine review waves later.
# ---------------------------------------------------------------------------------------

# The public names on `pipeline/identity_gate.py`, plus the `company_identity` primitives a
# tool may legitimately gate on directly. Tools call these through the module
# (`_gate.activation_ok(...)`), so the collector below reads `Call.func.attr` as well as
# `.id` -- a `from ... import x as _x` binding is what made two fixtures silently hit the
# live network, and it is not a spelling this repo uses for the gate any more.
_GATE_NAMES = {"activation_ok", "ok_to_write", "identity_ok", "page_names_company",
               "tenant_is_this_company", "is_foreign", "page_mentions_company",
               "looks_like_a_job_listing_page", "embedded_board_ok", "verdict",
               "identity_verdict"}
# `is_aggregator` is deliberately NOT in the set. It answers "is this a job board for many
# employers", not "is this THIS company's page" -- FairFly was activated off fireflyspace.com
# by a path that checked exactly and only is_aggregator. With it listed, a writer whose sole
# predicate is the aggregator test counts as identity-gated, which is the FairFly hole
# wearing the enumeration as camouflage. (Removed 2026-08-24; the enumeration stayed green,
# i.e. no current writer relies on it as their only gate.)

# Writers whose column-3/4 writes are NOT a proposal and so need no identity evidence.
# Each entry must say why, and each is checked below against what the workflows actually run.
#
# ONE file, `tests/writer_allowlist.json`, read by this test AND by `tools/mutate.py`'s
# coverage exemption. The driver used to re-derive the list by regexing THIS file's source
# for `"<name>.py": "` -- which matched any dict here with .py keys, so an unrelated test
# table could silently widen the mutation-coverage exemption. A shared literal cannot drift
# from itself.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "writer_allowlist.json"), encoding="utf-8") as _f:
    _ALLOWLIST = json.load(_f)
_RESTORE_ONLY = _ALLOWLIST["restore_only"]
_LEGACY_UNSCHEDULED = _ALLOWLIST["legacy_unscheduled"]


def _registry_writes(tree):
    """Every node that writes companies.csv column 3 (api_url) or activates column 4.

    Two shapes, because the repo uses both and the pre-existing guard only knew one:
      A  fr[3] = ...  /  fr[4] = "true"          -- subscript assignment
      B  [name, plat, tok, api, "true", note]    -- whole-row literal, in one statement

    `fr[4] = "false"` is deliberately NOT a write here: parking a row needs no identity
    evidence, only activating one does. refresh_scrape_cache parks rotted scrapes that way.
    """
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            # A target may be a bare Subscript (`fr[3] = ...`) or a TUPLE of them
            # (`fields[1], fields[2], fields[3] = plat, tok, api`). Only checking the bare
            # form made `apply_resolved.py:61` invisible -- a module `self-heal.yml` runs at
            # 06:00, which rewrites col 3 and never touches col 4, so nothing else caught it
            # either. That is the enumeration failing at the one job it exists for.
            targets = []
            for tg in n.targets:
                targets.extend(tg.elts if isinstance(tg, (ast.Tuple, ast.List)) else [tg])
            for i, tg in enumerate(targets):
                if not (isinstance(tg, ast.Subscript)
                        and isinstance(tg.slice, ast.Constant)):
                    continue
                if tg.slice.value == 3:
                    out.append(n)
                elif tg.slice.value == 4:
                    # For a tuple target the value is the matching element of the RHS tuple;
                    # for a bare target it is the whole value.
                    v = n.value
                    if isinstance(v, (ast.Tuple, ast.List)) and len(v.elts) == len(targets):
                        v = v.elts[i]
                    if isinstance(v, ast.Constant) and v.value == "true":
                        out.append(n)
        elif isinstance(n, ast.List) and len(n.elts) >= 6:
            e = n.elts[4]
            if isinstance(e, ast.Constant) and e.value == "true":
                out.append(n)
    return out


def _enclosing_function(tree, node):
    best = None
    for f in ast.walk(tree):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if f.lineno <= node.lineno <= (f.end_lineno or f.lineno):
                if best is None or f.lineno > best.lineno:
                    best = f
    return best


def _call_names(node):
    names = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def _modules_a_workflow_runs(root):
    """Derived the way docs/gen_modules.py derives it, so the two cannot disagree."""
    import glob as _glob
    runs = set()
    for wf in _glob.glob(os.path.join(root, ".github", "workflows", "*.yml")):
        text = open(wf, encoding="utf-8").read()
        for m in re.finditer(r"python3?\s+(?:-u\s+)?([A-Za-z0-9_]+)\.py\b", text):
            runs.add(m.group(1) + ".py")
    return runs


def _ungated_registry_writers():
    """{module: [line, ...]} for every col-3/4 write with no identity call above it."""
    import glob as _glob
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = {}
    for path in sorted(_glob.glob(os.path.join(root, "*.py"))):
        base = os.path.basename(path)
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        lines = []
        for w in _registry_writes(tree):
            scope = _enclosing_function(tree, w) or tree
            gated = any(n.lineno <= w.lineno for n in ast.walk(scope)
                        if isinstance(n, ast.Call) and (_call_names(n) & _GATE_NAMES))
            if not gated:
                lines.append(w.lineno)
        if lines:
            bad[base] = lines
    return bad


def test_the_writer_allow_list_only_covers_tools_no_workflow_runs():
    """An allow-listed writer that becomes scheduled must turn this red.

    The allow-list is the one hand-maintained thing left in the enumeration, so it is the one
    thing that can rot. `_LEGACY_UNSCHEDULED` is only defensible while nothing runs those
    modules; `_RESTORE_ONLY` is defensible regardless, because those writes restore a value
    rather than propose one -- but it has to say so.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scheduled = _modules_a_workflow_runs(root)
    leaked = sorted(set(_LEGACY_UNSCHEDULED) & scheduled)
    assert not leaked, (
        "these modules are allow-listed as one-shot/legacy but a workflow now runs them, so "
        "they write the registry on a schedule with no identity gate: %s" % leaked)
    for mod, why in list(_RESTORE_ONLY.items()) + list(_LEGACY_UNSCHEDULED.items()):
        assert why and len(why) > 20, "allow-listed %s without a real reason" % mod
        assert os.path.exists(os.path.join(root, mod)), (
            "the allow-list names %s, which no longer exists" % mod)


def test_every_registry_writer_consults_an_identity_predicate():
    """DERIVED, not hand-listed. This is the test the last nine review waves needed.

    A module that writes `api_url` or flips `active` to true must consult an identity
    predicate in the same function, at or above the write. That is deliberately weaker than
    proving the gate DOMINATES the write -- the behavioural fixtures and the mutation
    catalogue do that, per writer. What this test uniquely provides is COMPLETENESS: it finds
    the writers instead of trusting a list somebody typed.

    Measured when this was written: 22 modules write the registry, 14 of them via a whole-row
    literal that the guard in tests/test_units.py cannot see. Five of those fourteen are
    invoked by scheduled workflows -- bd_rescue and retry_unreachable (02:30 daily),
    wayback_rescue and validate_empty (Sun 04:00), auto_expand (08:00 and 20:00) -- and none
    of them mentioned an identity predicate at all.
    """
    bad = _ungated_registry_writers()
    for allowed in list(_RESTORE_ONLY) + list(_LEGACY_UNSCHEDULED):
        bad.pop(allowed, None)
    assert not bad, (
        "these modules write companies.csv column 3/4 with no identity predicate above the "
        "write: %s" % {k: v for k, v in sorted(bad.items())})


# ---------------------------------------------------------------------------------------
# The five schedule-driven writers that build a whole-row literal.
#
# Until 2026-08-24 none of these consulted any identity predicate, and none had a test of any
# kind. They were invisible to `tests/test_units.py::test_every_activation_path_checks_
# company_identity`, which looks for a subscript assignment to index 4 -- a list literal has
# none. Fourteen of this repo's 22 registry writers are that shape.
#
# Each fixture carries a POSITIVE CONTROL. A gate that refuses everything must not be able to
# pass: an over-block that would have silently refused 358 rows was caught by a positive
# control in this file and by nothing else.
#
# `page_names_company` is stubbed to a PER-COMPANY table, never a constant. A constant stub
# measures the constant -- that is how "7 -> 0" reached three documents and meant nothing.
# ---------------------------------------------------------------------------------------

_BANCORP = "https://careers-bancorpbank.icims.com/jobs/search?ss=1"
_FIVERR = "https://boards-api.greenhouse.io/v1/boards/fiverr/jobs"


def _names_only_fiverr(name, url, html=""):
    """True for Fiverr, False for Bancor, None for anything else (unreadable)."""
    return {"Fiverr": True, "Bancor": False}.get(name)


def test_bd_rescue_cannot_activate_a_board_whose_page_never_names_the_company(
        tmp_path, monkeypatch):
    """`bd_rescue` holds the unlocker HTML, so it gates on the page it already fetched.

    Runs 02:30 daily. It built `[name, plat, tok, api, "true", "brightdata-rescued; n/il IL"]`
    off whatever `extract_ats()` found in that HTML, with no check that the board belongs to
    this company -- and `extract_ats` returns whatever board a page EMBEDS.
    """
    import sys
    import bd_rescue as B
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Bancor", "", "", "https://www.bancor.network/careers", "false",
         "unreachable; could not scan"],
        ["Fiverr", "", "", "https://www.fiverr.com/jobs", "false",
         "unreachable; could not scan"],
    ])
    boards = {"bancor.network": ("icims", "bancorpbank", _BANCORP),
              "fiverr.com": ("greenhouse", "fiverr", _FIVERR)}
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "x")
    monkeypatch.setattr(B, "_load_secrets", lambda *a, **k: None)
    monkeypatch.setattr(B, "alt_urls", lambda url: [url])
    monkeypatch.setattr(B, "unlock", lambda u, timeout=90: "<html>" + "x" * 3000 + "</html>")
    monkeypatch.setattr(B, "extract_ats", lambda html, name: boards.get(
        "bancor.network" if name == "Bancor" else "fiverr.com"))
    monkeypatch.setattr(B, "_verify", lambda name, plat, tok, api: (12, 5))
    monkeypatch.setattr(B.time, "sleep", lambda *a: None)
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    monkeypatch.setattr(sys, "argv", ["bd_rescue.py"])
    B.main()

    out = _read(tmp_path)
    assert out["Bancor"][4] == "false", (
        "activated Bancor onto The Bancorp Bank's board: %r" % (out["Bancor"],))
    assert _BANCORP not in out["Bancor"][3]
    assert out["Fiverr"][4] == "true", "positive control regressed: %r" % (out["Fiverr"],)


def test_validate_empty_needs_the_board_to_be_this_companys(monkeypatch):
    """`validate_empty.check` promotes off `extract_ats` plus a job count. Sun 04:00.

    Its `promote` branch returned an active row with no identity evidence, so a careers page
    that embeds a DIFFERENT company's board promoted that board under this company's name.
    """
    import validate_empty as V
    from pipeline import identity_gate as G
    monkeypatch.setattr(V, "_get", lambda u, timeout=10: "<html>" + "x" * 3000 + "</html>")
    monkeypatch.setattr(V, "_verify", lambda name, plat, tok, api: (30, 9))
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)

    monkeypatch.setattr(V, "extract_ats",
                        lambda html, name: ("icims", "bancorpbank", _BANCORP))
    kind, row = V.check("Bancor", "https://www.bancor.network/careers")
    assert not (row and row[4] == "true"), (
        "promoted Bancor onto The Bancorp Bank's board: %r" % (row,))

    monkeypatch.setattr(V, "extract_ats",
                        lambda html, name: ("greenhouse", "fiverr", _FIVERR))
    kind, row = V.check("Fiverr", "https://www.fiverr.com/jobs")
    assert kind == "promote" and row and row[4] == "true", (
        "positive control regressed: %r %r" % (kind, row))

    # the 500-char floor in BOTH directions: drifted UP it refuses readable pages (killed
    # above -- the 3000-char pages), drifted DOWN it treats a sub-500 shell as evidence.
    # This page has 2 role-near-Israel hits and ~240 chars: "can't re-check", never suspect.
    monkeypatch.setattr(V, "_get", lambda u, timeout=10:
                        "<html>" + "Tel Aviv data analyst role. " * 8 + "</html>")
    kind, row = V.check("Fiverr", "https://www.fiverr.com/jobs")
    assert kind == "confirmed", (
        "a page under the readability floor is no evidence in either direction: %r" % (kind,))


def test_a_held_page_cannot_vouch_for_a_board_it_merely_embeds(tmp_path, monkeypatch):
    """Wave-4 R1 (B1, reproduced end-to-end): `validate_empty.check` fetches the row's
    CAREERS page, `extract_ats` returns whatever board that page embeds, and the gate was
    then asked about the BOARD with the page as evidence. A page that genuinely names this
    company -- Cogniteam's own page, naming Cogniteam 120 times -- carrying a Greenhouse
    embed left from a shared template promoted RISKIFIED's board, active=true, on the
    Sunday cron, behind continue-on-error. The page can refuse a board (it names someone
    else); it can never ADMIT one: its affirmative answer is about itself.

    The rule pinned here: a board discovered INSIDE a held page is promoted only when the
    board vouches for itself -- its tenant token near-matches the company name (the same
    near-equality `tenant_is_this_company` uses for subdomain tenants). Anything else is a
    VISIBLE refusal: a suspect line, never a silent promote, never a silent confirm. The
    cost (acquisition embeds like Momentis->memic, opaque Comeet uids) is accepted and
    filed with the derivation in docs/BACKLOG.md 61.
    """
    import sys
    import validate_empty as V
    import bd_rescue as B

    def page(company, slug):
        return ("<html><h1>" + company + " Careers</h1>"
                + ("<p>" + company + " is hiring in Tel Aviv.</p>") * 60
                + '<a href="https://boards.greenhouse.io/embed/job_board?for=' + slug
                + '">Open positions</a></html>')

    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    boards = {"Cogniteam": ("greenhouse", "riskified",
                            "https://boards-api.greenhouse.io/v1/boards/riskified/jobs"),
              "Kima": ("greenhouse", "kima",
                       "https://boards-api.greenhouse.io/v1/boards/kima/jobs")}
    pages = {"Cogniteam": page("Cogniteam", "riskified"), "Kima": page("Kima", "kima")}
    monkeypatch.setattr(V, "_get", lambda u, timeout=10:
                        pages["Cogniteam" if "cogniteam" in u else "Kima"])
    monkeypatch.setattr(V, "_verify", lambda name, plat, tok, api: (30, 9))
    monkeypatch.setattr(V, "extract_ats", lambda html, name: boards[name])

    # the attack: the page names Cogniteam AND ONLY Cogniteam, real predicates throughout
    kind, payload = V.check("Cogniteam", "https://www.cogniteam.com/careers")
    assert kind == "suspect", (
        "a page can never vouch for a board it merely embeds; Riskified's board was "
        "promoted under Cogniteam's name off Cogniteam's own page: %r %r" % (kind, payload))
    # positive control: the embedded board's own tenant token matches
    kind, payload = V.check("Kima", "https://www.kima.network/careers")
    assert kind == "promote" and payload[4] == "true", (
        "positive control regressed: %r %r" % (kind, payload))

    # the near-match must stay TIGHT: `lili` is a SUBSTRING of `elililly`, and Lili (the
    # Israeli fintech) onto Eli Lilly's board is a recorded incident. Plain containment
    # re-opens it.
    boards["Lili"] = ("greenhouse", "elililly",
                      "https://boards-api.greenhouse.io/v1/boards/elililly/jobs")
    pages["Lili"] = page("Lili", "elililly")
    monkeypatch.setattr(V, "_get", lambda u, timeout=10:
                        pages["Cogniteam" if "cogniteam" in u else
                              "Lili" if "lili" in u else "Kima"])
    kind, payload = V.check("Lili", "https://www.lili.co/careers")
    assert kind == "suspect", (
        "`lili` in `elililly` -- containment without tightness promotes Lili onto Eli "
        "Lilly's board: %r %r" % (kind, payload))

    # the OTHER clause independently: a page naming someone ELSE refuses even when the
    # embedded slug matches the name (a parked/hijacked domain serving copied markup).
    # This is the cell that keeps `activation_ok` load-bearing next to `embedded_board_ok`.
    boards["Voiceitt"] = ("greenhouse", "voiceitt",
                          "https://boards-api.greenhouse.io/v1/boards/voiceitt/jobs")
    pages["Voiceitt"] = page("Riskified", "voiceitt")
    monkeypatch.setattr(V, "_get", lambda u, timeout=10:
                        pages["Cogniteam" if "cogniteam" in u else
                              "Lili" if "lili" in u else
                              "Voiceitt" if "voiceitt" in u else "Kima"])
    kind, payload = V.check("Voiceitt", "https://www.voiceitt.com/careers")
    assert kind == "suspect", (
        "a page naming another company must refuse even a name-matching embed: %r %r"
        % (kind, payload))

    # the same shape at the 02:30 sibling: bd_rescue holds the unlocker page
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Cogniteam", "", "", "https://www.cogniteam.com/careers", "false",
         "unreachable; could not scan"],
        ["Kima", "", "", "https://www.kima.network/careers", "false",
         "unreachable; could not scan"],
        ["Voiceitt", "", "", "https://www.voiceitt.com/careers", "false",
         "unreachable; could not scan"],
    ])
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "x")
    monkeypatch.setattr(B, "_load_secrets", lambda *a, **k: None)
    monkeypatch.setattr(B, "alt_urls", lambda url: [url])
    monkeypatch.setattr(B, "unlock", lambda u, timeout=90:
                        pages["Cogniteam" if "cogniteam" in u else
                              "Voiceitt" if "voiceitt" in u else "Kima"])
    monkeypatch.setattr(B, "extract_ats", lambda html, name: boards[name])
    monkeypatch.setattr(B, "_verify", lambda name, plat, tok, api: (30, 9))
    monkeypatch.setattr(B.time, "sleep", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["bd_rescue.py"])
    B.main()
    out = _read(tmp_path)
    assert out["Cogniteam"][4] == "false", (
        "bd_rescue activated an embedded foreign board off a page naming this company: "
        "%r" % (out["Cogniteam"],))
    assert "riskified" not in out["Cogniteam"][3]
    assert out["Kima"][4] == "true", "positive control regressed: %r" % (out["Kima"],)
    assert out["Voiceitt"][4] == "false", (
        "a foreign page with a name-matching embed activated at bd_rescue: %r"
        % (out["Voiceitt"],))


def test_wayback_rescue_cannot_activate_another_companys_archived_board(
        tmp_path, monkeypatch):
    """`wayback_rescue` resurrects a board from archive.org. Sun 04:00.

    An archived snapshot is the oldest evidence in the pipeline, and this branch had no
    identity check at all -- a wrong resurrection is indistinguishable from a real one in
    every verdict that follows it.
    """
    import sys
    import wayback_rescue as W
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Bancor", "", "", "https://www.bancor.network/careers", "false",
         "unreachable; could not scan"],
        ["Fiverr", "", "", "https://www.fiverr.com/jobs", "false",
         "unreachable; could not scan"],
    ])
    res = {"Bancor": ("icims", "bancorpbank", _BANCORP, 30, 9),
           "Fiverr": ("greenhouse", "fiverr", _FIVERR, 40, 12)}
    monkeypatch.setattr(W, "rescue", lambda name, url: res[name])
    monkeypatch.setattr(W.time, "sleep", lambda *a: None)
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    monkeypatch.setattr(sys, "argv", ["wayback_rescue.py"])
    W.main()

    out = _read(tmp_path)
    assert out["Bancor"][4] == "false", (
        "activated Bancor onto The Bancorp Bank's archived board: %r" % (out["Bancor"],))
    assert out["Fiverr"][4] == "true", "positive control regressed: %r" % (out["Fiverr"],)


def test_retry_unreachable_row_builder_refuses_a_foreign_board(monkeypatch):
    """`retry_unreachable._row_for` is the seam every branch passes through. 02:30 daily.

    It returned an ACTIVE row straight from `resolve()`'s payload. This tool rewrites rows
    already marked `unreachable` -- exactly the population whose stored address is least
    trustworthy.
    """
    import retry_unreachable as R
    from pipeline import identity_gate as G
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)

    foreign = R._row_for("Bancor", "https://www.bancor.network/careers", "ats",
                         ("Bancor", "icims", "bancorpbank", _BANCORP, 30, 9), {})
    assert foreign[4] != "true", (
        "built an active row on The Bancorp Bank's board: %r" % (foreign,))
    assert _BANCORP not in foreign[3]

    ours = R._row_for("Fiverr", "https://www.fiverr.com/jobs", "ats",
                      ("Fiverr", "greenhouse", "fiverr", _FIVERR, 40, 12), {})
    assert ours[4] == "true" and ours[3] == _FIVERR, (
        "positive control regressed: %r" % (ours,))


def test_auto_expand_row_builder_refuses_a_foreign_board(monkeypatch):
    """`auto_expand` runs TWICE daily (08:00 and 20:00) and APPENDS new rows.

    Tested at the row builder, not through `main()`, on purpose: `main()` writes through
    `pipeline.companies.CSV_PATH`, an ABSOLUTE path fixed at import time from the repo root.
    A `chdir` fixture does not redirect it, so driving `main()` here would append to the real
    registry. `retry_unreachable._row_for` is the same shape for the same reason.
    """
    import auto_expand as E
    from pipeline import identity_gate as G
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)

    seed = "https://www.bancor.network/careers"
    foreign = E._row_for_ats(("Bancor", "icims", "bancorpbank", _BANCORP, 30, 9), seed)
    assert foreign[4] != "true", (
        "built an active row on The Bancorp Bank's board: %r" % (foreign,))
    # docs/BACKLOG.md 54, closed: the refusal must record the SEED url, never the refused
    # board -- `identity_gate.is_walled` derives crack_walled's pool membership from the
    # row's host, so persisting the refused board put a foreign Workday/iCIMS host into a
    # pool that exists to crack THIS company's board.
    assert foreign[2] == seed and foreign[3] == seed, (
        "the refused board leaked into the row's address: %r" % (foreign,))
    assert _BANCORP not in foreign[3]

    ours = E._row_for_ats(("Fiverr", "greenhouse", "fiverr", _FIVERR, 40, 12),
                          "https://www.fiverr.com/jobs")
    assert ours[4] == "true" and ours[3] == _FIVERR, (
        "positive control regressed: %r" % (ours,))


def test_an_acquired_subdomain_tenant_activates_without_a_readable_page(monkeypatch):
    """The Habana/Intel class. All 66 active Workday rows are `/wday/cxs/<tenant>/<site>/jobs`
    machine endpoints -- HTTP 400 on GET, so a page can NEVER decide them (measurement 4,
    module docstring of `pipeline/identity_gate.py`). The gate's order is: a page in hand
    decides; otherwise the tenant does; a page FETCH is the last resort. This pins the middle
    step: a matching subdomain tenant must activate with the page oracle answering None,
    or every one of those 66 rows is refused the day it passes through re-resolution.

    The stub table maps "Intel Israel" to None -- unreadable, not "does not name us". That
    distinction is the wave-1/wave-3 census result: None falls through to the tenant;
    only an actual False refuses.
    """
    import auto_expand as E
    from pipeline import identity_gate as G
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)   # Intel Israel -> None

    api = "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs"
    row = E._row_for_ats(("Intel Israel", "workday", "intel", api, 412, 38),
                         "https://intel.com/careers")
    assert row[4] == "true" and row[3] == api, (
        "a machine endpoint with a matching subdomain tenant must activate "
        "even though its page is unreadable: %r" % (row,))


# ---------------------------------------------------------------------------------------
# Guards written to kill a SURVIVING mutation.
#
# Each of these exists because `python tools/mutate.py --all` reported a mutation the suite
# did not notice. That is the harness working: a gate nobody tests is a gate that is not
# there, and until the mutation goes red the gate's presence in the source proves nothing.
# ---------------------------------------------------------------------------------------


def test_a_board_that_verifies_with_zero_jobs_is_not_a_recovery():
    """Kills `activation-njobs-drop`.

    A live-but-empty board and a dead token are indistinguishable from the caller's side, so
    a zero count is the `empty-board` shape, not a recovery -- activating on it re-creates
    the 0/0 rows the self-heal exists to clean up. Every one of the five schedule-driven
    writers passes its own count here, and nothing tested that the clause did anything.
    """
    from pipeline import identity_gate as G
    orig = G.page_names_company
    try:
        G.page_names_company = lambda n, u, html="": True     # perfect page evidence
        url = "https://boards-api.greenhouse.io/v1/boards/fiverr/jobs"
        assert G.activation_ok("Fiverr", url, 0) is False, (
            "a board verifying with zero jobs was accepted as a recovery")
        assert G.activation_ok("Fiverr", url, 12) is True, (
            "positive control: a board with jobs and page evidence must still activate")
    finally:
        G.page_names_company = orig


def test_activation_still_requires_the_url_to_claim_to_list_jobs():
    """Kills `activation-listing-drop`.

    Clause 3 of the activation rule (ARCHITECTURE.md section 2). `SCRAPE_ASSUME_IL` makes
    every card on a page an Israel role, so a nav menu scores like a board:
    `iai.co.il/solution/research-academy-space` once "verified 6 IL" whose titles were
    "Domain Operations" and "Press Releases".
    """
    from pipeline import identity_gate as G
    from pipeline.company_identity import looks_like_a_job_listing_page
    orig = G.page_names_company
    try:
        G.page_names_company = lambda n, u, html="": True
        nav = "https://www.acme-example.com/solution/research-academy-space"
        assert not looks_like_a_job_listing_page(nav), "fixture drift: pick a non-listing url"
        assert G.activation_ok("Acme", nav, 6) is False, (
            "activated on a page that does not claim to list jobs")
        board = "https://www.acme-example.com/careers/openings"
        assert looks_like_a_job_listing_page(board)
        assert G.activation_ok("Acme", board, 6) is True, (
            "positive control regressed")
    finally:
        G.page_names_company = orig


def test_the_search_ladder_actually_falls_through_when_serpapi_is_empty():
    """Kills `audit-ladder-serpapi-only`.

    `test_the_weekly_audit_search_has_a_fallback_below_serpapi` walks the AST of `serp` for
    the NAMES `_serpapi`, `ddg` and `google_via_unlocker`. The mutation
    `urls = _serpapi(...)` -> `return _serpapi(...)` leaves all three names in the function,
    now as dead code, and that guard stayed green -- a textbook source-shape defeat.

    SerpApi returns nothing until 2026-09-01, so a ladder that stops at rung one is a silent
    no-op that reports success: the Sunday audit would find zero boards and say so in a way
    indistinguishable from "there were none".
    """
    import audit_empty_rows as A
    calls = []

    def _serp(name, limit=5):
        calls.append("serpapi")
        return []

    def _ddg(q, limit=5):
        calls.append("ddg")
        return ["https://boards.greenhouse.io/fiverr"]

    # `serp` imports its fallback rungs lazily FROM `deep_validate`, inside the function, so
    # that is where they have to be patched -- patching `audit_empty_rows` would miss them.
    import deep_validate as D
    orig = (A._serpapi, D.ddg, D.google_via_unlocker)
    try:
        A._serpapi, D.ddg = _serp, _ddg
        D.google_via_unlocker = lambda q, limit=5: ["https://never.example"]
        urls = A.serp("Fiverr")
        assert "serpapi" in calls, "the first rung must still be tried"
        assert "ddg" in calls, (
            "SerpApi returned nothing and the ladder stopped there: %r" % (calls,))
        assert urls == ["https://boards.greenhouse.io/fiverr"], (
            "the fallback rung's result must be returned, got %r" % (urls,))
    finally:
        A._serpapi, D.ddg, D.google_via_unlocker = orig


def test_crack_walled_novrfy_does_not_persist_an_address_it_could_not_confirm(
        tmp_path, monkeypatch):
    """Kills `crack-oktowrite-callsite-invert`.

    `ok_to_write` returns a bool, so `if ok_to_write(...) is not None:` is ALWAYS true --
    a one-token edit that leaves the call in place and removes the gate entirely. The
    `novrfy` branch writes `fr[3]` without activating, which reads as harmless and is not:
    `listing_hunt`'s documented fast path reads that address the next night and activates
    on it, so persisting an unconfirmed URL only delays the wrong activation by 24 hours.

    The positive direction is asserted too, and it is not decoration: `crack-novrfy-narrow`
    (`if n_il < 0 and ok_to_write(...)`) makes the persist NEVER happen, which passed this
    fixture's negative assertions and survived a full sweep. A confirmed address on `novrfy`
    MUST be persisted -- that `host documented` stamp is what feeds the fast path its next
    candidate, and losing it silently is coverage loss, not safety.
    """
    import sys
    import crack_walled as C
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["OraCo", "", "", "https://oraco.example/careers", "false",
         "unsupported ATS icims.com"],
        ["GoodCo", "", "", "https://goodco.example/careers", "false",
         "unsupported ATS icims.com"],
    ])
    boards = {"OraCo": "https://someoneelse.icims.com/jobs/search?ss=1",
              "GoodCo": "https://goodco.icims.com/jobs/search?ss=1"}
    monkeypatch.setattr(C, "crack_one",
                        lambda name, seed, plat: ("novrfy", ("scrape", boards[name]),
                                                  0, "0 IL"))
    # per-company table, never a constant: OraCo's page is unreadable, GoodCo's names it
    monkeypatch.setattr(G, "page_names_company",
                        lambda n, u, html="": {"GoodCo": True}.get(n))
    monkeypatch.setattr(sys, "argv", ["crack_walled.py", "--apply"])
    C.main()

    out = _read(tmp_path)
    assert boards["OraCo"] not in out["OraCo"][3], (
        "persisted an address it could not confirm: %r" % (out["OraCo"],))
    assert out["OraCo"][4] == "false"
    assert out["GoodCo"][3] == boards["GoodCo"], (
        "positive control: a CONFIRMED novrfy address must be persisted -- it is the fast "
        "path's next candidate: %r" % (out["GoodCo"],))
    assert "host documented" in out["GoodCo"][5]
    assert out["GoodCo"][4] == "false", "novrfy documents, it must not activate"


def test_every_ownership_mirror_agrees_with_the_tool_it_mirrors():
    """`registry_health.pools()` must not RETYPE a tool's row filter.

    The matrix is the answer to "who re-checks a parked row", and section 2 tells a reader to
    trust it over any hand-written cell. It was only literally derived for `triage_dark`;
    four filters were retyped, and one of those was wrong: the crack mirror was
    `"unsupported ATS" in note`, which is half of `identity_gate.is_walled` -- it missed the
    host-derived half, under-counted that pool by 7 rows, and because `orphans()` subtracts
    pool membership it under-reported orphans by the same rows.

    `_EXTRACT_GAP` was LOOSER than `repair_extract_gap.MODE` (no date anchor), which is the
    direction that hides an orphan: a row the mirror matched but the tool did not was counted
    as owned when nothing owns it. Drift is 0 today; this test is what keeps it there.
    """
    import registry_health as R
    from pipeline import identity_gate as G
    from pipeline.recruiters import is_recruiter
    from repair_extract_gap import MODE

    rows = R.read_rows()
    labelled = R.pools(rows)

    crack_real = {r[0] for r in rows
                  if r[4] == "false" and G.is_walled(r)
                  and not R.is_terminal_note(r[5] or "") and not is_recruiter(r[0])}
    crack_matrix = {r[0] for r in labelled["crack_walled (19:00 daily + Sun)"]}
    assert crack_matrix == crack_real, (
        "the crack mirror disagrees with identity_gate.is_walled by %d row(s): %s"
        % (len(crack_matrix ^ crack_real), sorted(crack_matrix ^ crack_real)[:8]))

    gap_real = {r[0] for r in rows
                if r[4] == "false" and MODE.search(r[5] or "")
                and (r[3] or "").startswith("http")}
    gap_matrix = {r[0] for r in labelled["repair_extract_gap (19:00 daily)"]}
    assert gap_matrix == gap_real, (
        "the extract-gap mirror disagrees with repair_extract_gap.MODE by %d row(s): %s"
        % (len(gap_matrix ^ gap_real), sorted(gap_matrix ^ gap_real)[:8]))


# ---------------------------------------------------------------------------------------
# Three more mutation-killers. Each of these was reported by `tools/mutate.py` as
# "killed ONLY by a source-text guard" -- i.e. the hole was real and the only thing noticing
# it was a guard that reads the source, which is the kind this repo has watched break six
# times. A gate whose only witness is a string match is not guarded.
# ---------------------------------------------------------------------------------------


def test_the_hunt_does_not_persist_a_foreign_address_it_refused_to_activate(
        tmp_path, monkeypatch):
    """Kills `hunt-persist-remove`.

    The `nolisting` branch writes `fr[3]` WITHOUT activating, which reads as harmless and is
    not: the row keeps its fast-path token, and `listing_hunt`'s own documented fast path
    scrapes the stored address first the next night. Refusing to activate while still
    recording the address only moves the wrong activation 24 hours downstream, under a
    different tool's name.
    """
    import sys
    import listing_hunt as L
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["NanoLock Security", "", "", "https://nanolock.example/careers", "false",
         "dark-triage 2026-01-01: no ATS detected"],
        ["GoodCo", "", "", "https://www.goodco.example/careers", "false",
         "dark-triage 2026-01-01: no ATS detected"],
    ])
    foreign = "https://gen.wd1.myworkdayjobs.com/careers/"
    ours = "https://www.goodco.example/careers/openings"
    res = {"NanoLock Security": ("nolisting", foreign, 0, ""),
           "GoodCo": ("nolisting", ours, 0, "")}
    monkeypatch.setattr(L, "hunt_one",
                        lambda name, seed, documented=False, mode="": res[name])
    monkeypatch.setattr(G, "page_names_company", lambda n, u, html="": None)  # unreadable
    monkeypatch.setattr(sys, "argv", ["listing_hunt.py", "--apply"])
    L.main()

    out = _read(tmp_path)
    assert "myworkdayjobs" not in out["NanoLock Security"][3], (
        "persisted Gen Digital's Workday as the row's address: %r"
        % (out["NanoLock Security"],))
    # ordinary domain: the candidate is still recorded, which is the branch's whole purpose
    assert out["GoodCo"][3] == ours, (
        "positive control regressed — an ordinary-domain candidate must still be "
        "recorded: %r" % (out["GoodCo"],))


def test_repair_refuses_a_candidate_whose_page_it_could_not_read(tmp_path, monkeypatch):
    """Kills `repair-page-invert` (`is True` -> `is not False`).

    `page_names_company` is three-valued on purpose. `is not False` admits `None`, so a page
    nobody could read counts as ours -- which is how `SupPlant` reached
    `https://careers.workable.com/`, Workable's own front door. "We could not look" is not
    evidence, and this tool runs at 19:00 immediately before the hunt in the same job.
    """
    import sys
    import repair_dead_urls as R
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["SupPlant", "scrape", "", "https://careers.supplant-dead.com", "false",
         "monitored candidate 2026-01-01: host documented"],
        ["GoodCo", "scrape", "", "https://www.goodco-dead.com", "false",
         "monitored candidate 2026-01-01: host documented"],
    ])
    cand = {"SupPlant": ["https://careers.workable.com/"],
            "GoodCo": ["https://www.goodco.example/careers"]}
    # BOTH pages are unreadable to the page predicate; only GoodCo's whole name IS its domain
    monkeypatch.setattr(R, "resolves", lambda h, tries=3: not h.endswith("-dead.com"))
    monkeypatch.setattr(R, "candidates", lambda name, dead: cand.get(name, []))
    monkeypatch.setattr(R, "fetch", lambda u: (200, "<html>" + "z" * 40 + "</html>"))
    monkeypatch.setattr(R, "_unlock", lambda u: "")
    monkeypatch.setattr(G, "page_names_company", lambda n, u, html="": None)
    monkeypatch.setattr(sys, "argv", ["repair_dead_urls.py", "--apply"])
    R.main()

    out = _read(tmp_path)
    assert "workable.com" not in out["SupPlant"][3], (
        "repaired onto Workable's own front door off an unreadable page: %r"
        % (out["SupPlant"],))


def test_repair_still_needs_the_whole_name_to_be_the_domain(tmp_path, monkeypatch):
    """Kills `repair-narrow` (dropping the `whole_name` conjunct).

    `verdict() == "match"` also fires when the domain equals the company name with its
    generic words stripped, and that core can be an acronym: "DiA Imaging Analytics" strips
    to `dia`, and `registrable("www.dia.mil")` is `dia`. This tool once printed

        [OK] DiA Imaging Analytics  www.dia-analytics.com -> https://www.dia.mil/...

    for the US Defense Intelligence Agency. 125 of the 516 rows whose own URL scores `match`
    rest on a stripped core, so `match` alone is not evidence.
    """
    import sys
    import repair_dead_urls as R
    from pipeline import identity_gate as G
    from pipeline.company_identity import verdict, registrable, _norm
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["DiA Imaging Analytics", "scrape", "", "https://www.dia-analytics-dead.com", "false",
         "monitored candidate 2026-01-01: host documented"],
    ])
    impostor = "https://www.dia.mil/careers/"
    assert verdict("DiA Imaging Analytics", impostor) == "match", "fixture drift"
    assert registrable("www.dia.mil") != _norm("DiA Imaging Analytics"), (
        "fixture drift: the whole name must NOT be the domain here")

    monkeypatch.setattr(R, "resolves", lambda h, tries=3: not h.endswith("-dead.com"))
    monkeypatch.setattr(R, "candidates", lambda name, dead: [impostor])
    monkeypatch.setattr(R, "fetch", lambda u: (200, "<html>" + "z" * 40 + "</html>"))
    monkeypatch.setattr(R, "_unlock", lambda u: "")
    monkeypatch.setattr(G, "page_names_company", lambda n, u, html="": None)
    monkeypatch.setattr(sys, "argv", ["repair_dead_urls.py", "--apply"])
    R.main()

    out = _read(tmp_path)
    assert "dia.mil" not in out["DiA Imaging Analytics"][3], (
        "repaired DiA Imaging Analytics onto the Defense Intelligence Agency: %r"
        % (out["DiA Imaging Analytics"],))


# ---------------------------------------------------------------------------------------
# Wave-1 review findings. Each of these kills a mutation that left the suite green, or a
# case a reviewer drove end-to-end and the suite did not notice.
# ---------------------------------------------------------------------------------------


def test_the_page_test_wants_the_name_as_a_PHRASE_not_scattered_words():
    """Kills `page-strict-off`.

    `strict=True` is the entire Bancor/Bancorp lesson: it requires the company's words
    CONSECUTIVELY. Relaxed to plain containment, a page that happens to contain "Time" and
    "Know" anywhere becomes evidence for "Time To Know", and this predicate is the sole
    discriminator behind every column-3/4 write in the repo.

    Reviewer R2 flipped `strict=True` to `strict=False` and the suite stayed green: the two
    tests that mention `strict=True` call `page_mentions_company` DIRECTLY, so they kept
    asserting the primitive after the gate stopped using it.
    """
    from pipeline import identity_gate as G
    scattered = ("<html><p>It is time to learn what we know about hiring.</p>"
                 + "<p>We know a lot. Time flies.</p>" * 90 + "</html>")
    assert G.page_names_company("Time To Know", "", html=scattered) is False, (
        "the name's words appear scattered, not as a phrase; that is not evidence")
    phrase = "<html><h1>Time To Know</h1>" + "<p>Time To Know is hiring.</p>" * 90 + "</html>"
    assert G.page_names_company("Time To Know", "", html=phrase) is True, (
        "positive control: the name as a phrase must still count")


def test_identity_ok_still_refuses_a_foreign_ORDINARY_domain():
    """Kills `identity-foreign-drop`.

    `listing_hunt` hunts ordinary careers pages, so almost every candidate it produces takes
    `identity_ok`'s non-ATS path -- where `is_foreign` is the ONLY gate applied. Removing it
    re-opens the incident the module docstring is named after: FairFly activated off
    `fireflyspace.com`, 25 Firefly Aerospace roles published under FairFly's name.
    """
    from pipeline import identity_gate as G
    assert G.identity_ok("FairFly", "https://www.fireflyspace.com/careers/") is False, (
        "FairFly onto Firefly Aerospace's careers page")
    assert G.identity_ok("FairFly", "https://www.fairfly.com/careers/") is True, (
        "positive control: the company's own domain must still pass")


def test_ok_to_write_still_requires_the_url_to_claim_to_list_jobs():
    """Kills `oktowrite-listing-drop`.

    Clause 3 of the activation rule. `activation_ok`'s copy of it had a mutation; the twin in
    `ok_to_write` had none, so it could be dropped with the suite green -- and then
    `crack_walled` persists an About or nav page as the row's `api_url`, which
    `listing_hunt`'s fast path scrapes the next night.
    """
    from pipeline import identity_gate as G
    from pipeline.company_identity import looks_like_a_job_listing_page
    page = "<html><h1>Wiz</h1>" + "<p>Wiz is a cloud security company.</p>" * 90 + "</html>"
    about = "https://www.wiz.io/about"
    assert not looks_like_a_job_listing_page(about), "fixture drift"
    assert G.ok_to_write("Wiz", about, html=page) is False, (
        "an About page whose text names the company is still not a listings page")
    board = "https://boards.greenhouse.io/wizinc/jobs"
    assert looks_like_a_job_listing_page(board)
    assert G.ok_to_write("Wiz", board, html=page) is True, "positive control regressed"


def test_the_jobvite_taleo_branch_is_a_gate_and_not_a_pass_through():
    """Kills `identity-jobvite-open`.

    `company_identity.ATS_HOST` omits jobvite and taleo, so `verdict()` compares the company
    against the ATS VENDOR's domain and `is_foreign` refuses a correct board outright. The
    branch that works around it is the one place `identity_ok` skips `is_foreign` entirely
    and leans on the page test alone -- and no test in the repo named either platform, so the
    whole branch could be replaced by `return True`.

    `crack_walled.listing_urls()` builds exactly these URLs, so this is a live path.
    """
    from pipeline import identity_gate as G
    verint = "<html><h1>Verint Careers</h1>" + "<p>Verint is hiring.</p>" * 90 + "</html>"
    varonis = "<html><h1>Varonis Careers</h1>" + "<p>Varonis is hiring.</p>" * 90 + "</html>"
    assert G.identity_ok("Varonis", "https://jobs.jobvite.com/verint/jobs",
                         html=verint) is False, "Varonis onto Verint's Jobvite board"
    assert G.identity_ok("Varonis", "https://jobs.jobvite.com/varonis/jobs",
                         html=varonis) is True, "positive control: Varonis' own board"


def test_a_scoped_tenant_mismatch_still_refuses():
    """Kills `tenant-mismatch-drop`.

    Every existing test asserts a tenant mismatch must NOT block an ATS row -- that is
    `docs/BACKLOG.md` 21's 36-row measurement. None asserted the mismatch veto still fires
    where it IS scoped, so it could be deleted with the suite green. Reviewer R2 measured the
    effect on the real registry: refused rows 38 -> 35, and the three that flip are
    `Sight Sciences`, `Sight Diagnostics` and `Kubiya`.

    `Sight Sciences` and `Sight Diagnostics` are two different companies on the SAME
    `recruiting2.ultipro.com/SIG1008SIGH/` board, which is the mis-attribution shape itself.
    """
    from pipeline import identity_gate as G
    assert G.tenant_is_this_company(
        "Sight Diagnostics",
        "https://recruiting2.ultipro.com/SIG1008SIGH/JobBoard/x/") is False, (
        "Sight Diagnostics onto the board Sight Sciences is active on")
    assert G.tenant_is_this_company(
        "Riskified",
        "https://riskified.wd3.myworkdayjobs.com/wday/cxs/riskified/c/jobs") is True, (
        "positive control: a company's own subdomain tenant must still pass")


def test_the_name_stripping_retry_survives_because_46_rows_need_it():
    """Kills `namestop-neutered`.

    `page_mentions_company(strict=True)` wants the registry name's words consecutively, so
    any row whose name carries a suffix the page omits fails structurally -- 46 rows contain
    "Israel". The `_NAME_STOP` retry is the second chance. Neutering it is a real behaviour
    change that, before this test, was caught ONLY by an `inspect.getsource` assertion.
    """
    from pipeline import identity_gate as G
    page = ("<html><h1>Microsoft Careers</h1>"
            + "<p>Microsoft is hiring engineers.</p>" * 90 + "</html>")
    assert G.page_names_company("Microsoft Israel", "", html=page) is True, (
        "a page that says 'Microsoft' is still Microsoft Israel's page")
    other = "<html><h1>Novartis</h1>" + "<p>Novartis is hiring.</p>" * 90 + "</html>"
    assert G.page_names_company("Microsoft Israel", "", html=other) is False, (
        "positive control: the retry must not accept a page naming someone else")


def test_apply_resolved_will_not_re_point_an_active_row_at_a_foreign_board(
        tmp_path, monkeypatch):
    """`apply_resolved` was invisible to the derived enumeration until 2026-08-24.

    Its write is a TUPLE target -- `fields[1], fields[2], fields[3] = plat, tok, api` -- and
    the detector only unpacked bare `Subscript` targets. It writes col 3 and never col 4, so
    nothing else caught it either. It runs in `self-heal.yml` at 06:00, straight after the
    resolver and straight before `git commit`, and it had no identity check at all.

    It cannot ACTIVATE a row, but it can RE-POINT an already-active one, which publishes the
    other company's jobs under this company's name just the same.
    """
    import sys
    import json
    import apply_resolved as A
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Bancor", "greenhouse", "bancor", "https://boards-api.greenhouse.io/v1/boards/bancor/jobs",
         "true", "verified board"],
        ["Fiverr", "greenhouse", "old", "https://boards-api.greenhouse.io/v1/boards/old/jobs",
         "true", "verified board"],
    ])
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "resolved_configs.json").write_text(json.dumps({
        "Bancor": ["icims", "bancorpbank",
                   "https://careers-bancorpbank.icims.com/jobs/search?ss=1"],
        "Fiverr": ["greenhouse", "fiverr",
                   "https://boards-api.greenhouse.io/v1/boards/fiverr/jobs"],
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["apply_resolved.py"])
    A.main()

    out = _read(tmp_path)
    assert "bancorpbank" not in out["Bancor"][3], (
        "re-pointed an ACTIVE row at The Bancorp Bank's board: %r" % (out["Bancor"],))
    assert out["Fiverr"][3].endswith("/boards/fiverr/jobs"), (
        "positive control: a legitimate re-resolution must still apply: %r" % (out["Fiverr"],))


def test_validate_empty_a_readable_page_decides_and_a_refusal_is_visible(monkeypatch):
    """The census pin for `activation_ok`'s html ordering. This gate has flipped once; the
    three cells below are the record of why it must not flip again without a new predicate.

    * WAVE 1 (page-first, page-only): `Siemens Healthineers` on its own readable page that
      says only "Siemens" was refused -- and the refusal was SILENT (`("confirmed", None)`,
      indistinguishable from a genuine empty). The blocking part was the SILENCE.
    * WAVE 3 (tenant-first): `tenant_is_this_company` is True by VACUITY on every
      path-tenant platform, so the page in hand was never consulted and `Cogniteam` was
      PROMOTED onto Riskified's greenhouse board off a careers URL that no longer serves
      Cogniteam's page. A wrong write, on a schedule.
    * RESOLUTION (per the calibration-dispute rule -- both error cells non-empty, so do not
      tune, pick the bar-consistent direction): a READABLE page the caller holds decides,
      either way; only an UNREADABLE page (None) falls through to the tenant clause. These
      callers activate PARKED rows: a wrong refusal is parked, visible in the suspect list
      and recoverable; a wrong acceptance ships another company's jobs. The Siemens-class
      name-shape cost is accepted, VISIBLE, and filed with row names in docs/BACKLOG.md.
    """
    import validate_empty as V
    from pipeline import identity_gate as G

    # Cell 1 -- the wave-3 attack: readable page that names someone else => refuse, visibly.
    board = "https://boards-api.greenhouse.io/v1/boards/riskified/jobs"
    monkeypatch.setattr(V, "_get", lambda u, timeout=10:
                        "<html><h1>Riskified Careers</h1>"
                        + "<p>Riskified builds fraud prevention. Join Riskified.</p>" * 60
                        + "</html>")
    monkeypatch.setattr(V, "_verify", lambda name, plat, tok, api: (30, 9))
    monkeypatch.setattr(V, "extract_ats",
                        lambda html, name: ("greenhouse", "riskified", board))
    kind, payload = V.check("Cogniteam", "https://www.cogniteam.com/careers")
    assert kind == "suspect", (
        "a readable page naming another company must refuse the board it embeds, and the "
        "refusal must be visible: got %r" % (kind,))
    assert payload and "not this company's" in payload

    # Cell 2 -- the wave-1 name-shape case, now refused BUT VISIBLE, never silent-confirmed.
    board2 = "https://boards-api.greenhouse.io/v1/boards/siemens/jobs"
    monkeypatch.setattr(V, "_get", lambda u, timeout=10:
                        "<html><h1>Siemens Careers</h1>"
                        + "<p>Siemens is hiring in Tel Aviv.</p>" * 90 + "</html>")
    monkeypatch.setattr(V, "extract_ats",
                        lambda html, name: ("greenhouse", "siemens", board2))
    kind, payload = V.check("Siemens Healthineers", "https://www.siemens.com/careers")
    assert kind == "suspect", (
        "the accepted cost of the readable-page rule is a VISIBLE suspect, never a silent "
        "confirmed and never a promote on unconsulted evidence: got %r" % (kind,))

    # Cell 3 -- unreadable page + affirmative subdomain tenant => the tenant clause still
    # admits, so the machine-endpoint / filler-stripped-core population stays activatable.
    wd = "https://qualcomm.wd5.myworkdayjobs.com/wday/cxs/qualcomm/External/jobs"
    # 500 <= len < 2000: past check()'s own can't-re-check floor, below the page
    # predicate's readability floor -- a JS shell, the realistic walled shape.
    monkeypatch.setattr(V, "_get", lambda u, timeout=10: "<html>" + "x" * 900 + "</html>")
    monkeypatch.setattr(V, "extract_ats", lambda html, name: ("workday", "qualcomm", wd))
    kind, row = V.check("Qualcomm Israel", "https://www.qualcomm.com/careers")
    assert kind == "promote" and row and row[4] == "true", (
        "an UNREADABLE page is no evidence; the affirmative tenant must still admit: %r"
        % (kind,))


def test_no_note_write_costs_a_row_its_own_re_check_token():
    """`validate_empty`'s note must not evict the selector that put the row in its pool.

    `main()`'s `empty-but-suspect` write was the ONE note write in the repo that did not go
    through `pipeline.notes` -- a bare concatenation with no cap, so the 220-char limit never
    applied and the cell reached 324 chars. The next tool's stamp then evicted whole segments
    to make room, and on these rows the OLDEST segment is `no open Israel roles`, which is
    `validate_empty`'s entire selector. The row left its own Sunday pool permanently, and no
    scheduled tool ever rewrites that token.

    Measured on the real registry: 39 of 54 rows kept the token before this branch existed,
    26 with the first version of it, 52 now. Capping alone was not enough -- `replace_own`
    evicts oldest-first, which is exactly the wrong end -- so the write is skipped when it
    would take the token with it.
    """
    import csv as _csv
    import os as _os
    from pipeline.notes import replace_own
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    with open(_os.path.join(root, "companies.csv"), encoding="utf-8") as fh:
        rows = [r for r in _csv.reader(fh) if r and len(r) >= 6][1:]
    sel = [r for r in rows if "no open israel roles" in (r[5] or "").lower()]
    assert sel, "fixture drift: validate_empty's pool is empty"

    seg = "empty-but-suspect; 3 IL but the board is not this company's"
    kept = 0
    for r in sel:
        new = replace_own(r[5] or "", "empty-but-suspect", seg)
        # main() skips the write when it would cost the selector -- mirror that here
        final = new if "no open israel roles" in new.lower() else (r[5] or "")
        assert len(final) <= 220, (
            "%s: the note write must respect the 220-char cap (got %d)"
            % (r[0], len(final)))
        after = replace_own(final, "listing-hunt", "listing-hunt 2026-08-24: no listing found")
        if "no open israel roles" in after.lower():
            kept += 1
    assert kept >= len(sel) - 5, (
        "%d of %d rows lose their own re-check selector to this note; the write is supposed "
        "to be skipped rather than cost the row its pool" % (len(sel) - kept, len(sel)))


def test_the_scrape_branch_of_each_row_builder_is_gated_too(monkeypatch):
    """The `ats` and `scrape` branches are separate gates three lines apart.

    Both `retry_unreachable._row_for` and `auto_expand`'s loop call `activation_ok` twice --
    once for an `ats` payload, once for a `scrape` one. The mutation catalogue covered the
    `ats` call site in both files and NOTHING for the scrape call site, because coverage was
    counted per FILE. Deleting one `not` from the scrape guard inverted it in both
    directions -- activating `Voiceitt` (a bare domain) and parking `Pliops` (a real careers
    page) -- with 253 tests green.
    """
    import retry_unreachable as R
    from pipeline import identity_gate as G
    monkeypatch.setattr(G, "page_names_company", lambda n, u, html="": None)

    stored = "https://STORED.example/careers"
    bare_domain = R._row_for("Voiceitt", stored, "scrape",
                             (["a", "b", "c", "d", "e"], "https://www.voiceitt.com/"), {})
    assert bare_domain[4] == "false", (
        "a bare domain is not a listings page and must not activate: %r" % (bare_domain,))
    real = R._row_for("Pliops", stored, "scrape",
                      (["a", "b", "c", "d", "e"], "https://pliops.com/careers"), {})
    assert real[4] == "true" and real[3] == "https://pliops.com/careers", (
        "positive control: a real careers page must still activate: %r" % (real,))

    # auto_expand's scrape branch is the SAME gate in the sibling tool. It lived inline in
    # `main()` -- which writes through the absolute CSV_PATH, unreachable by any fixture --
    # so its three catalogue mutations survived a full sweep: a gate nothing could exercise.
    # Extracted to `_row_for_scrape` for exactly this reason.
    import auto_expand as E
    cache = {}
    seed2 = "https://SEED.example/careers"
    bare2 = E._row_for_scrape("Voiceitt", ["a", "b", "c"], "https://www.voiceitt.com/",
                              seed2, cache)
    assert bare2[4] == "false" and "Voiceitt" not in cache, (
        "auto_expand's scrape gate must refuse what retry's refuses: %r" % (bare2,))
    assert bare2[2] == seed2 and bare2[3] == seed2, (
        "the refused page leaked into the row's address -- the item-54 rule applies to "
        "the THIRD builder too: %r" % (bare2,))
    real2 = E._row_for_scrape("Pliops", ["a", "b", "c"], "https://pliops.com/careers",
                              seed2, cache)
    assert real2[4] == "true" and cache.get("Pliops") == ["a", "b", "c"], (
        "positive control: accept must activate AND populate the scrape cache: %r" % (real2,))
    agg = E._row_for_scrape("AnyCo", ["a"], "https://www.linkedin.com/jobs/x", seed2, cache)
    assert agg[4] == "false" and "aggregator" in agg[5], (
        "an aggregator page must park before the identity gate is even asked: %r" % (agg,))


def test_bd_rescue_gates_on_the_page_the_candidate_was_extracted_from(
        tmp_path, monkeypatch):
    """Wave-4 R2 (B3): `html=html` -> `html=best_html` survived the suite because the only
    bd fixture stubbed `alt_urls` to ONE url and `unlock` to a CONSTANT page -- in that
    population the html argument carries no information, so no binding of it can be wrong.
    Here: two alts, per-URL pages, and the LONGEST page is a parked-domain interstitial
    that is NOT the page the candidate was extracted from. `bd_rescue.py`'s own comment is
    the invariant: "gate on the page this candidate was extracted FROM". `extract_ats` is
    the real one.
    """
    import sys
    import bd_rescue as B
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Kima", "", "", "https://www.kima.network/careers", "false",
         "unreachable; could not scan"],
    ])
    kima_page = ("<html><h1>Kima Careers</h1>"
                 + "<p>Kima is hiring in Tel Aviv.</p>" * 60
                 + '<a href="https://boards.greenhouse.io/embed/job_board?for=kima&amp;t=1">'
                 + "Open positions</a></html>")
    junk = ("<html><h1>Parked Domain Services</h1>"
            + "<p>This domain is parked by Parked Domain Services.</p>" * 90 + "</html>")
    assert len(junk) > len(kima_page), "the junk page must be the LONGEST seen"
    pages = {"https://www.kima.network/careers?v=1": junk,
             "https://www.kima.network/careers": kima_page}
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "x")
    monkeypatch.setattr(B, "_load_secrets", lambda *a, **k: None)
    monkeypatch.setattr(B, "alt_urls", lambda url: [url + "?v=1", url])
    monkeypatch.setattr(B, "unlock", lambda u, timeout=90: pages[u])
    monkeypatch.setattr(B, "_verify", lambda name, plat, tok, api: (12, 4))
    monkeypatch.setattr(B.time, "sleep", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["bd_rescue.py"])
    B.main()
    out = _read(tmp_path)
    assert out["Kima"][4] == "true" and "kima" in out["Kima"][3], (
        "the gate judged the board against a DIFFERENT alt's page: %r" % (out["Kima"],))


def test_the_gate_reads_page_evidence_with_the_arguments_the_right_way_round(monkeypatch):
    """Wave-4 R2 (B3): every `activation_ok` fixture stubs `page_names_company` with a
    table keyed on its FIRST positional argument. Transpose `(name, api_url)` at either of
    the gate's internal page calls and the stub misses its key, returns None, and the
    tenant clause supplies the verdict the fixture expected -- suite green, while every
    readable-page acceptance from `bd_rescue` (9 rows) and `validate_empty` (59) silently
    dies; on the bd path a `x3` strike then parks the row for good. The per-company stub
    table measures the stub's KEY, not the gate's argument order, so these cells run the
    REAL predicate: html in hand for the held-page branch, `urlopen` stubbed at the
    network boundary for the fetch tail.
    """
    from pipeline import identity_gate as G
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)

    # held-page branch, accept direction: a real acquisition -- the machine endpoint's
    # tenant (memic) can never match, ONLY the page in hand admits. Transposed, the page
    # "names" a URL, answers False, and the acquisition is refused.
    page = "<h1>Momentis Surgical Careers</h1>" + "<p>Momentis Surgical is hiring.</p>" * 100
    api = "https://memic.wd1.myworkdayjobs.com/wday/cxs/memic/External/jobs"
    assert G.activation_ok("Momentis Surgical", api, 12, html=page) is True, (
        "a held page naming the company must admit the acquisition board")
    # refuse direction, same branch, real predicate: Bancorp's page never says `Bancor`
    ban = "<h1>The Bancorp Bank</h1>" + "<p>Bancorp Bank benefits.</p>" * 100
    assert G.activation_ok(
        "Bancor", "https://careers-bancorpbank.icims.com/jobs/search", 9, html=ban) is False

    # fetch tail (no html, tenant mismatch): the LAST page call in the gate.
    served = {"https://gen.wd1.myworkdayjobs.com/wday/cxs/gen/x/jobs":
              ("<h1>NanoLock Security Careers</h1>"
               + "<p>NanoLock Security is hiring in Israel.</p>" * 80).encode()}
    class _Resp:
        def __init__(self, data): self._d = data
        def read(self, n=-1): return self._d
    monkeypatch.setattr(G.urllib.request, "urlopen",
                        lambda req, timeout=25, context=None: _Resp(served[req.full_url]))
    assert G.activation_ok(
        "NanoLock Security", "https://gen.wd1.myworkdayjobs.com/wday/cxs/gen/x/jobs", 5
    ) is True, ("the fetch tail must admit when the fetched page names the company")


def test_a_zero_job_count_refuses_at_every_call_site_not_just_inside_the_gate(
        tmp_path, monkeypatch):
    """Wave-4 R2 (B3): `activation_ok`'s `if not n_jobs: return False` was pinned only by a
    DIRECT call -- `G.activation_ok("Fiverr", url, 0)` -- which tests the gate, not the
    seven arguments handed to it. Replacing the count with a truthy literal at any call
    site (`activation_ok(nm, api, 1)`) left the whole suite green, and the write it changes
    is `active=false -> true` on a board that verified with ZERO jobs -- the empty-board
    shape the self-heal exists to clean up.

    Page evidence is stubbed PERFECT (constant True) on purpose: the predicate under test
    is the COUNT ARGUMENT, and with every other clause admitting, only the count can
    refuse -- so a call site feeding the gate a constant instead of its count goes red
    here and nowhere else. The two call sites with redundant pre-guards
    (`validate_empty`'s `il > 0 and`, `bd_rescue`'s `v and v[0] and`) make that mutation
    an equivalent mutant there; their M8 records transpose `(name, api)` instead.
    """
    import sys
    import retry_unreachable as R
    import auto_expand as E
    import wayback_rescue as W
    from pipeline import identity_gate as G
    monkeypatch.setattr(G, "page_names_company", lambda n, u, html="": True)

    seed = "https://www.fiverr.com/jobs"
    z = R._row_for("Fiverr", seed, "ats", ("Fiverr", "greenhouse", "fiverr", _FIVERR, 0, 0), {})
    assert z[4] == "false", "retry ats: zero-job board activated: %r" % (z,)
    z = R._row_for("Pliops", seed, "scrape", ([], "https://pliops.com/careers"), {})
    assert z[4] == "false", "retry scrape: zero-job page activated: %r" % (z,)
    z = E._row_for_ats(("Fiverr", "greenhouse", "fiverr", _FIVERR, 0, 0), seed)
    assert z[4] == "false", "expand ats: zero-job board activated: %r" % (z,)
    z = E._row_for_scrape("Pliops", [], "https://pliops.com/careers",
                          "https://SEED.example/careers", {})
    assert z[4] == "false", "expand scrape: zero-job page activated: %r" % (z,)
    # positive control: with a real count every one of the four accepts
    ok = R._row_for("Fiverr", seed, "ats", ("Fiverr", "greenhouse", "fiverr", _FIVERR, 40, 12), {})
    assert ok[4] == "true", "positive control regressed: %r" % (ok,)

    # wayback passes r[3] straight from the archive payload -- drive main()
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["ZeroCo", "", "", "https://www.zeroco.example/careers", "false",
         "unreachable; could not scan"],
        ["Fiverr", "", "", "https://www.fiverr.com/jobs", "false",
         "unreachable; could not scan"],
    ])
    res = {"ZeroCo": ("greenhouse", "zeroco",
                      "https://boards-api.greenhouse.io/v1/boards/zeroco/jobs", 0, 0),
           "Fiverr": ("greenhouse", "fiverr", _FIVERR, 40, 12)}
    monkeypatch.setattr(W, "rescue", lambda name, url: res[name])
    monkeypatch.setattr(W.time, "sleep", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["wayback_rescue.py"])
    W.main()
    out = _read(tmp_path)
    assert out["ZeroCo"][4] == "false", (
        "wayback: a zero-job archived board activated: %r" % (out["ZeroCo"],))
    assert out["Fiverr"][4] == "true", "positive control regressed: %r" % (out["Fiverr"],)


def test_a_tenant_that_matches_only_the_FILLER_STRIPPED_core_is_still_admitted():
    """Kills `tenant-filler-neutered`.

    `tenant_is_this_company` builds two targets: the whole normalised name, and a `core` with
    generic and geographic words removed via `_NAME_FILLER`. For any company whose registry
    name carries such a word, the core is the ONLY target its own tenant matches --
    `Qualcomm Israel` on `qualcomm.wd5.myworkdayjobs.com`, `WINT Water Intelligence` on
    `wint.careers.hibob.com`. Neutering `_NAME_FILLER` flips 22 registry rows from admit to
    refuse, and because those endpoints are machine APIs that `page_names_company` answers
    `None` for, the refusal is FINAL: `activation_ok` and the Sunday audit both stamp
    "the board belongs to another company" onto a company's own board.

    It survived every existing fixture because every positive control in this file is either
    a path-tenant greenhouse board or an exact-name subdomain tenant (`Riskified` on
    `riskified.wd3`). Not one needed the filler-stripped core. That is the same shape as
    "a constant stub measures the constant".
    """
    from pipeline import identity_gate as G
    assert G.tenant_is_this_company(
        "Qualcomm Israel",
        "https://qualcomm.wd5.myworkdayjobs.com/External?locations=Israel") is True, (
        "Qualcomm's own Workday tenant, refused because the name carries 'Israel'")
    assert G.tenant_is_this_company(
        "WINT Water Intelligence", "https://wint.careers.hibob.com/jobs") is True, (
        "WINT's own hibob tenant, refused because the name carries 'Water Intelligence'")
    # the canonical refusal must be unmoved
    assert G.tenant_is_this_company(
        "Bancor", "https://careers-bancorpbank.icims.com/jobs/search?ss=1") is False


def test_host_platform_returns_a_name_the_cracker_actually_has_a_pattern_for():
    """Kills `hostplatform-alias-drop`.

    `crack_walled._platform_of` falls back to `host_platform` precisely when another tool has
    erased the `unsupported ATS <x>` note token -- measured at 24 of 25 pool rows. If
    `host_platform` returns the raw host fragment instead of the platform alias, the fallback
    resolves to a name `_HOST_PATTERNS` has no entry for, `crack_one` returns
    `("skip", "no pattern for ...")`, and the row quietly stops being cracked. No exception,
    no red build -- exactly the shape the durable-data fix existed to prevent.

    The pool guard covers membership; nothing covered the VALUE handed to `crack_one`.
    """
    from pipeline import identity_gate as G
    import crack_walled as C
    for url, expect in (("https://synopsys.avature.net/talentcommunity", "avature"),
                        ("https://x.icims.com/jobs", "icims"),
                        ("https://y.wd1.myworkdayjobs.com/careers", "workday")):
        plat = G.host_platform(url)
        assert plat == expect, "%s -> %r, expected %r" % (url, plat, expect)
    # and the fallback must name something the cracker can act on
    assert G.host_platform("https://synopsys.avature.net/x") in C._HOST_PATTERNS, (
        "the platform name host_platform returns has no _HOST_PATTERNS entry, so crack_one "
        "skips the row")


def test_the_unlocker_rung_inside_the_page_test_still_exists(monkeypatch):
    """Kills `page-unlocker-drop`.

    `page_names_company`'s own docstring records why this rung is gated on the KEY rather
    than on `SCRAPE_VIA_UNLOCKER`: `audit-coverage.yml` runs the cracker without that flag,
    and a missing flag must not silently downgrade the gate. Cause 1 in that docstring is a
    403 to a plain fetch -- `Bit`'s own careers page -- which renders under 2000 chars and
    would otherwise return `None`, which every caller reads as a refusal.

    Deleting the rung was green across the whole suite: nothing referenced
    `BRIGHTDATA_API_KEY` or `unlock` in either test file.
    """
    import bd_rescue
    from pipeline import identity_gate as G
    # ~520 chars: under the 2000 floor (so the rung fires) but well ABOVE a drifted one.
    # At the original 39 chars, `2000 -> 200` in the trigger still fired the rung and the
    # drift survived this test -- yet it silently drops the retry for every real bot wall
    # that renders a 200-2000 char challenge shell, which is most of them (the Bit page
    # this pins renders ~1.4k). The page must sit in that band to guard the band.
    walled = "<html><body>" + "Access denied. " * 33 + "</body></html>"
    full = "<html><h1>Bit Careers</h1>" + "<p>Bit is hiring.</p>" * 200 + "</html>"

    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    monkeypatch.setattr(bd_rescue, "unlock", lambda url, timeout=90: full)
    assert G.page_names_company("Bit", "https://careers.bit.example/", html=walled) is True, (
        "a bot-walled page must be retried through the unlocker, not read as no-evidence")

    # without the key the rung is inert and the answer is honestly `None`, not False
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    assert G.page_names_company("Bit", "https://careers.bit.example/", html=walled) is None, (
        "with no key we could not look, and that is not the same as looking and finding "
        "someone else")


def test_every_refusal_note_keeps_the_row_in_a_re_check_pool(monkeypatch):
    """A refusal must hand the row to SOME scheduled tool, never orphan it.

    Wave-3 R3 measured the first version of `retry_unreachable`'s two refusal notes: they
    carried no pool token and REPLACED the whole cell, so the 9 rows whose only token was
    `unreachable` (3M, Augwind Energy, Chakratec, Cyberbit, ElMindA, Panoply, Product
    Madness, Siemens Healthineers, Upsolver) left every pool at once -- including this
    tool's own selector, so they could never be retried -- became orphans, and at 11
    orphans `check_invariants` fires `bad()`, which blocks the digest commit itself.

    The convention pinned here: an identity refusal ends with `no listing found`, the
    hand-off token -- this tool could not find the RIGHT board, which is `listing_hunt`'s
    job. It is the same convention listing_hunt's own identity refusal already uses, and
    the token is in `check_invariants.POOL`, listing_hunt's selector, and
    `scan_dead_domains`' selector.
    """
    import re
    import check_invariants as ci
    import retry_unreachable as R
    import auto_expand as E
    from pipeline import identity_gate as G
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)

    seed = "https://www.bancor.network/careers"
    rows = [
        R._row_for("Bancor", seed, "ats",
                   ("Bancor", "icims", "bancorpbank", _BANCORP, 30, 9), {}),
        R._row_for("Bancor", seed, "scrape", (["a", "b"], _BANCORP), {}),
        E._row_for_ats(("Bancor", "icims", "bancorpbank", _BANCORP, 30, 9), seed),
        E._row_for_scrape("Bancor", ["a", "b"], _BANCORP, seed, {}),
    ]
    import listing_hunt as LH
    import registry_health as RH
    for row in rows:
        assert row[4] == "false", "fixture drift: these must all be refusals: %r" % (row,)
        assert re.search(ci.POOL, row[5], re.I), (
            "a refusal note that matches no re-check pool orphans the row and, at 11 "
            "orphans, blocks the digest commit: %r" % (row,))
        # ...and the RECEIVER's own selector, not just check_invariants' copy. Wave-4 R3:
        # dropping `no listing found` from listing_hunt's pool regex emptied the hunt of
        # 27 named rows while this test, check_invariants and registry_health all stayed
        # green -- because all three asserted a MIRROR, and the mirrors were retyped.
        assert LH.HUNT_POOL.search(row[5]), (
            "the hand-off token no longer lands in listing_hunt's own pool: %r" % (row,))
    # a retyped mirror is how the loss stayed silent; the mirror must BE the tool's
    assert RH._HUNT_SHAPE is LH.HUNT_POOL, (
        "registry_health's hunt mirror is no longer listing_hunt's own constant")
    # validate_empty's hand-off shape stays in the receiver's pool too
    assert LH.HUNT_POOL.search("empty-but-suspect; 3 IL but the board is not this company's")
