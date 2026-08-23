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
    calls = {n.func.id for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_page_names_company" in calls, (
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
    src = inspect.getsource(crack_walled._page_names_company)
    assert "_LENIENT" in src, "strict TLS re-introduces 6 known false positives"
    assert "unlock" in src, "a bot-walled page needs the residential fetch, not a refusal"
    assert "_NAME_STOP" in src, "`Microsoft Israel` on a page saying `Microsoft` is Microsoft"
    assert "return None" in src, "unreadable must be NO EVIDENCE, not disconfirmation"
    assert crack_walled._LENIENT.verify_mode.name == "CERT_NONE"
    page = "<h1>Careers at Microsoft</h1><p>Search jobs at Microsoft.</p>" * 40
    assert crack_walled._page_names_company("Microsoft Israel", "", html=page) is True
    bancorp = ("<h1>Careers at The Bancorp Bank</h1>" + "<p>Bancorp Bank benefits</p>" * 90)
    assert crack_walled._page_names_company("Bancor", "", html=bancorp) is False

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
    assert "strict=True" in src, "page evidence must be the phrase test, not word-soup"
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
    called = {n.func.id for n in ast.walk(tree)
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
                  and isinstance(n.func, ast.Name) and n.func.id == "_page_names_company"]
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
    assert hasattr(crack_walled, "_ok_to_write")
    src = inspect.getsource(crack_walled.main)
    tree = ast.parse(src.lstrip())
    # every statement that assigns fr[3] or fr[4] must sit under a test of _ok_to_write
    guarded, unguarded = 0, []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "_ok_to_write" not in ast.unparse(node.test):
            continue
        for st in ast.walk(node):
            if isinstance(st, ast.Assign):
                for t in st.targets:
                    u = ast.unparse(t)
                    if u.endswith("[3]") or u.endswith("[4]"):
                        guarded += 1
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                u = ast.unparse(t)
                if u.endswith("[3]") or u.endswith("[4]") or "fr[3]" in u:
                    unguarded.append(ast.unparse(node)[:60])
    assert guarded >= 1, "no fr[3]/fr[4] write sits under an _ok_to_write test"
    # the gate itself must demand a POSITIVE confirmation, not merely "not False"
    g = inspect.getsource(crack_walled._ok_to_write)
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
    carry a second signal. The predicate survives as `audit_empty_rows.tenant_is_this_company`
    and is used ONLY in `crack_walled._ok_to_write`, where `_page_names_company(...) is True`
    is already required and therefore no new false negative is possible.

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
