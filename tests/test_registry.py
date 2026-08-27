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
    import bd_rescue
    import retry_unreachable
    import wayback_rescue

    def _row_literal_with_a_literal_note(value):
        """`[name, plat, tok, api, "true", <not a call>]` -- the WHOLE-ROW shape. The
        2026-08-24 registry rebuild found this shape in 14 writers and gated every one;
        three of them (bd_rescue 02:30, retry_unreachable 02:30, wayback_rescue Sun)
        still rebuilt the notes cell from an f-string on their activation branch, and
        retry did it on EVERY branch -- which is how a night's `unreachable` erased
        listing-hunt's and Bright Data's verdicts (2026-08-25)."""
        return (isinstance(value, ast.List) and len(value.elts) >= 6
                and isinstance(value.elts[4], ast.Constant)
                and value.elts[4].value in ("true", "false")
                and not isinstance(value.elts[5], (ast.Call, ast.Name)))

    for mod in (audit_empty_rows, crack_walled, deep_validate,
                bd_rescue, retry_unreachable, wayback_rescue):
        offenders = []
        for node in ast.walk(ast.parse(inspect.getsource(mod))):
            if isinstance(node, ast.Return) and _row_literal_with_a_literal_note(node.value):
                offenders.append(ast.unparse(node)[:70])
            if not isinstance(node, ast.Assign):
                continue
            if _row_literal_with_a_literal_note(node.value):
                offenders.append(ast.unparse(node)[:70])
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
    """THREE spellings of the re-check pool exist -- `pipeline.verdicts.TOKENS` (claims to
    be the source of truth), `check_invariants.POOL` (the blocking gate's copy) and
    `listing_hunt.HUNT_POOL` (the hunt's own selector) -- and they differ on purpose in
    exactly the ways EXEMPT names. This pins every difference so a NEW one is red, and
    prints what each exemption costs on the live registry (derived, never typed).

    2026-08-25: TOKENS gained `url-cleared`/`url-flagged` (auto_expand's `--clear-agg-urls`
    writes the first, so the 9 rows carrying only that token are no longer invisible to
    audit_empty_rows/deep_validate). The remaining deliberate gap is HUNT_POOL lacking
    dark-triage (docs/BACKLOG.md "One re-check pool definition")."""
    import csv
    import os
    import re
    import check_invariants
    import listing_hunt
    from pipeline.verdicts import TOKENS, POOL_RX
    tokens = {t.lower() for t in TOKENS}
    ci = {t.lower() for t in check_invariants.POOL.split("|") if t and "(" not in t}
    hunt = {t.lower() for t in listing_hunt.HUNT_POOL.pattern.split("|") if t and "(" not in t}
    EXEMPT = {
        "no il listing": "TOKENS only: every live carrier also carries a POOL token",
        "roles-text present": "TOKENS only: every live carrier also carries a POOL token",
        "dark-triage": "TOKENS+POOL, not HUNT: triage_dark owns those rows; the hunt "
                       "must not re-hunt a row triage just verdicted",
    }
    assert (ci - tokens) == set(), sorted(ci - tokens)
    assert (tokens - ci) == {"no il listing", "roles-text present"}, sorted(tokens - ci)
    assert (ci - hunt) == {"dark-triage"}, sorted(ci - hunt)
    assert (hunt - ci) == set(), sorted(hunt - ci)
    assert set(EXEMPT) == (ci ^ tokens) | (ci ^ hunt), "an exemption is undocumented or stale"
    # the cost, derived from the live registry and printed with the assertion context
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "companies.csv"), encoding="utf-8") as fh:
        parked = [r for r in csv.reader(fh) if r and len(r) >= 6 and r[4] == "false"]
    cirx = re.compile(check_invariants.POOL, re.I)
    only_ci = [r[0] for r in parked if cirx.search(r[5] or "") and not POOL_RX.search(r[5] or "")]
    not_hunt = [r[0] for r in parked if POOL_RX.search(r[5] or "")
                and not listing_hunt.HUNT_POOL.search(r[5] or "")]
    assert only_ci == [], "a POOL token TOKENS does not know: %r" % (only_ci[:5],)
    print(f"\nexemption cost today: {len(not_hunt)} parked rows invisible to the hunt (dark-triage)")


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
    assert _slug_matches("Bancor", "bancorpbank") is False, (
        "since 2026-08-26 `bancorpbank` is a DECLARED not_tenant of Bancor: refused without a page")
    assert _slug_matches("Fiverr", "fiverr") and _slug_matches("Ibex Medical Analytics", "ib1"), (
        "near-equal vouches; a slug that merely fails near-equality is `cannot tell`, not refused")

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
    # `successfactors` and `jobvite` joined this list on 2026-08-26, when the operator lowered
    # the support bar to one row: both are HTML-only boards the repo could not read at all,
    # and both had rows producing nothing (Stratasys 0 -> 13 Israel roles, Varonis 0 -> 3).
    for plat in ("phenom", "eightfold.ai", "oraclecloud.com", "successfactors", "jobvite"):
        if plat in q:
            assert q[plat]["fetcher"], plat + " has a native fetcher and the queue must say so"
            assert q[plat]["fetcher"] in FETCHERS
    for plat in ("icims.com", "avature.net"):
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
    from probe_candidates import _wake_note
    note = "no ATS detected | listing-hunt 2026-08-20: no listing found | dark-triage 2026-08-24: extract-gap (2 role phrases)"
    woken = _wake_note(note)
    assert "dark-triage 2026-08-24: extract-gap" in woken, "the wake must keep triage's dated segment"
    assert not triage_dark._needs_triage(woken), "a kept, fresh triage stamp is what keeps triage off the woken row"
    src = inspect.getsource(triage_dark.main)
    assert '"probe-woken" not in' not in src, (
        "a `probe-woken` exclusion in main() is permanent (nothing cleared it): 6 rows left "
        "triage's schedule forever while in_triage_pool still counted them")

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
    # every statement that assigns fr[3] or fr[4] must sit under a test of the write gate's
    # verdict: `_wv = _gate.write_verdict(...)` (2026-08-25; `ok_to_write` is its boolean view)
    assigns = [ast.unparse(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign)
               and any(ast.unparse(t) == "_wv" for t in n.targets)]
    assert assigns and all("write_verdict" in a for a in assigns), assigns
    guarded, unguarded = 0, []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "_wv" not in ast.unparse(node.test):
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
    g = inspect.getsource(IG.write_verdict)
    assert 'return "unreadable"' in g and IG.ok_to_write("X", "https://x.example/careers") is False, (
        "an UNREADABLE page (None) must not pass: novrfy writes an address that "
        "listing_hunt's fast-path later activates on")

def test_a_tenant_mismatch_alone_must_not_block_an_ats_row():
    """THE reason `is_foreign` returns False for every ATS host, measured.

    Three independent reviewers recommended the same root-cause fix: stop
    `company_identity.is_foreign` early-returning False on ATS hosts, and move a near-equality
    tenant rule into shared plumbing. It was built, wired into `listing_hunt`'s fast path and
    `deep_validate`'s recovered branch, measured against the live registry - and REVERTED,
    because it rejects **24 ACTIVE rows** (measured 2026-08-24; an earlier version of this
    docstring said 36), and they are overwhelmingly legitimate acquisitions
    and parent-company boards that this repo names by name:

        Momentis Surgical -> greenhouse/memic          (ARCHITECTURE section 2 cites this one)
        Itamar Medical    -> zoll.wd5.myworkdayjobs
        Habana Labs (Intel) -> intel.wd1.myworkdayjobs
        VMware (Broadcom) -> broadcom.wd1.myworkdayjobs
        Splunk (Cisco)    -> cisco.wd5.myworkdayjobs
        HP Indigo         -> hp.wd5.myworkdayjobs

    Habana, VMware, Splunk and Itamar are DECLARED now (`pipeline/identity_facts.py`) and
    pass; the rest still stand as the measured cost of a string-only rule.

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
    # 24 at the rebuild's close; 22 once pipeline/identity_facts declared Citrix and Itamar
    # (re-measure: Census B in the plan). The floor guards against the rule being
    # WIDENED into an activation gate, not against declarations lowering the count.
    assert len(would_block) > 15, (
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


_ROWS3 = [["A", "scrape", "u", "https://a.example/careers", "false",
           "unreachable; could not scan"],
          ["B", "greenhouse", "b", "https://boards-api.greenhouse.io/v1/boards/b/jobs",
           "true", "re-audit 2026-08-21: deep-verified 3/1 IL"],
          ["C", "scrape", "u", "https://c.example/careers", "false",
           "deep-validated 2026-08-21: no ATS detected | monitored candidate"]]


def test_the_alarm_file_does_not_amplify_itself(tmp_path, monkeypatch):
    """`alarms_state` re-emits the ladder rungs it reads. The first version read them from
    the SAME file `--census` wrote `alarms()` into, so each run re-read its own output and
    prepended another "(ladder, as of ...)": 2 alarms, then 3, then 4, unbounded, into a
    git-tracked state file. A source-substring pin guarded a prefix test; now the ladder
    has its OWN file (`--ladder`, written by listing-hunt.yml, never by anything that reads
    it) and this test drives the loop instead of grepping for the guard."""
    import json
    import registry_health as R
    ladder = tmp_path / "ladder.json"
    ladder.write_text(json.dumps({"date": R.TODAY,
                                  "rungs": ["resolution rung DOWN: Playwright — missing"]}),
                      encoding="utf-8")
    monkeypatch.setattr(R, "LADDER", str(ladder))
    first = R.alarms_state(_ROWS3, prev={})
    second = R.alarms_state(_ROWS3, prev={})
    assert first == second
    assert sum(1 for x in first if x.startswith("(ladder)")) == 1
    assert not any("(ladder) (ladder)" in x for x in first)


def test_the_mailed_alarm_lines_do_not_change_on_a_day_nothing_changed(tmp_path, monkeypatch):
    """The inbox relay dedups the digest on a content hash: a line carrying "Nd old" or
    "as of <today>" would re-email the whole digest every day, forever. Every date in
    `alarms_state`'s output is the date something last HAPPENED. A stale ladder is
    reported by the file's date, not by an age."""
    import json
    import re
    import registry_health as R
    ladder = tmp_path / "ladder.json"
    ladder.write_text(json.dumps({"date": "2026-08-01", "rungs": []}), encoding="utf-8")
    monkeypatch.setattr(R, "LADDER", str(ladder))
    a = R.alarms_state(_ROWS3, prev={})
    b = R.alarms_state(_ROWS3, prev={})
    assert a == b
    dated = [x for x in a if re.search(r"\d{4}-\d{2}-\d{2}", x)]
    assert dated and all("last refreshed 2026-08-01" in x for x in dated), (
        "the only dated line may be the ladder's own file date: %r" % (dated,))
    assert not any(re.search(r"\d+d old", x) for x in a)


def test_the_digest_renders_registry_alarms_only_when_there_are_any():
    """The health block joins the Run-audit block in all three renderers, copying the
    `dead_sources` carrier. An empty list renders nothing -- the inbox relay dedups the
    digest on a content hash, so a healthy day must not change the body at all."""
    from pipeline import digest as D
    base = {"companies_scanned": 1, "companies_failed": 0, "jobs_fetched": 0,
            "israel_matched": 0, "accepted": 0, "after_merge": 0, "new": 0,
            "board_count": 0, "llm_calls": 0, "jd_filled_inline": 0, "email_overflow": 0,
            "first_scan": 0, "stages": "", "dead_sources": [], "paths": {},
            "failed_companies": []}
    quiet = dict(base, registry_alarms=[])
    loud = dict(base, registry_alarms=["re-check pool COLLAPSED to zero: crack_walled was 25"])
    md_q = D.build_markdown([], "2026-08-24", quiet)[1]      # (subject, body)
    md_l = D.build_markdown([], "2026-08-24", loud)[1]
    assert "Registry" not in md_q and "**Registry:** re-check pool COLLAPSED" in md_l
    assert "REGISTRY" not in D._text_audit(quiet)          # returns one string
    assert "REGISTRY: re-check pool COLLAPSED" in D._text_audit(loud)
    esc = lambda x: str(x)
    assert "Registry" not in D._html_audit(quiet, esc)
    assert "<b>Registry:</b> re-check pool COLLAPSED" in D._html_audit(loud, esc)


def test_the_census_refreshes_only_after_the_invariant_gate():
    """Text-parsed (no PyYAML in CI). The census step must sit AFTER the hard invariant
    guard -- a census before it blesses a corrupted registry as the new baseline -- and
    must be continue-on-error so it can never withhold the digest. The ladder file is
    written by the one job with Playwright, and that job must actually `git add` it."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dd = open(os.path.join(root, ".github", "workflows", "daily-digest.yml"),
              encoding="utf-8").read()
    i_gate = dd.index("python check_invariants.py")
    i_census = dd.index("registry_health.py --census")
    i_add = dd.index("persist_state.py commit")          # the one delivery path (infra, 2026-08-25)
    assert i_gate < i_census < i_add, "the census must run after the gate and before the commit"
    assert "--own cloud_state" in dd[i_add:i_add + 400], "the digest must persist cloud_state"
    block = dd[i_census:i_census + 300]
    assert "continue-on-error: true" in block, "the census step must never withhold the digest"
    lh = open(os.path.join(root, ".github", "workflows", "listing-hunt.yml"),
              encoding="utf-8").read()
    assert "registry_health.py --ladder" in lh
    # the ladder step must carry the Bright Data keys its sibling steps carry: the probe is
    # `resources(live=False)`, which reads the env, and a step without the keys records
    # "Bright Data DOWN" as a fact the mail repeats daily (confirmation-wave R3, B1)
    i_l = lh.index("registry_health.py --ladder")
    step = lh[lh.rfind("- name:", 0, i_l):i_l]
    assert "BRIGHTDATA_API_KEY" in step and "BRIGHTDATA_ZONE" in step, step
    commit = lh[lh.index("persist_state.py commit"):]
    assert "cloud_state/registry_ladder.json" in commit, (
        "listing-hunt lists explicit paths it owns; the ladder file must be one")
    # ...and a missing optional path must never abort the commit: the step that writes it
    # is continue-on-error, and `git add a b missing` under bash -e used to abort before
    # `git commit` -- the whole night's registry writes discarded (confirmation-wave R1,
    # B4). That tolerance is now persist_state.py's contract, pinned by
    # test_persist_stages_only_owned_paths_tolerates_a_missing_one_and_expands_a_directory.
    assert "git add" not in commit, "no inline git add beside the delivery path"


def test_the_digest_summary_is_wired_to_alarms_state():
    """The one seam between registry health and the mail: `summary["registry_alarms"]`
    must be bound to the `alarms_state()` result. Blanking it to `[]` left the suite green
    (confirmation-wave R1) -- the renderer was tested, the producer was not."""
    import ast
    import inspect
    import pipeline.run as R
    src = inspect.getsource(R)
    tree = ast.parse(src)
    keys = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)
            and any(isinstance(k, ast.Constant) and k.value == "registry_alarms" for k in n.keys)]
    assert keys, "summary no longer carries registry_alarms"
    d = keys[0]
    val = d.values[[isinstance(k, ast.Constant) and k.value == "registry_alarms" for k in d.keys].index(True)]
    assert getattr(val, "id", "") == "_registry_alarms_lines", ast.dump(val)
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
               and any(getattr(t, "id", "") == "_registry_alarms_lines" for t in n.targets)]
    callers = {getattr(getattr(a.value, "func", None), "id", "") for a in assigns}
    assert "_registry_alarms" in callers, "the alarms list is no longer produced by alarms_state"


def test_the_mail_hook_does_not_record_the_ladder():
    """`--census` must write `alarms_state` (registry facts) to the alarms file, never
    `alarms()` (which adds the resolution ladder): the digest job installs no Playwright,
    and recording the ladder from there is exactly BACKLOG 13's bug via a file."""
    import ast
    import inspect
    import registry_health as R
    tree = ast.parse(inspect.getsource(R.main).lstrip())
    writes = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and getattr(n.func, "id", "") == "write_json"
              and getattr(n.args[0], "id", "") == "ALARMS"]
    assert writes, "the --census branch no longer writes ALARMS"
    src = ast.get_source_segment(inspect.getsource(R.main).lstrip(), writes[0])
    assert "a_mail" in src, src
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
               and any(getattr(t, "id", "") == "a_mail" for t in n.targets)]
    assert assigns and getattr(assigns[0].value.func, "id", "") == "alarms_state", (
        "a_mail must come from alarms_state, not alarms")


def test_a_pool_that_falls_to_zero_is_an_alarm():
    """docs/BACKLOG.md 34: check_invariants has one aggregate floor and crack_walled went
    25 -> 2 -> 0 under it, green every night. `pool_floor` compares each tool to the size
    the last census recorded; the first census after deploy (no `//pools//`) never alarms."""
    import registry_health as R
    now = {label.split(" (")[0]: len(m) for label, m in R.pools(_ROWS3).items()}
    # the probe is a FACT pool since 2026-08-26: both parked http rows of _ROWS3 are its
    assert now["crack_walled"] == 0 and now["probe_candidates"] == 2, now
    prev = {"//pools//": {"crack_walled": 25, "probe_candidates": 2,
                          "listing_hunt": now["listing_hunt"] * 4 or 40}}
    out = R.pool_floor(_ROWS3, prev)
    assert any("COLLAPSED to zero: crack_walled was 25" in x for x in out), out
    assert not any("probe_candidates" in x for x in out), "a stable pool must be silent"
    assert any(x.startswith("re-check pool halved: listing_hunt") for x in out) == (
        now["listing_hunt"] * 4 >= 8), out
    assert R.pool_floor(_ROWS3, {}) == [] and R.pool_floor(_ROWS3, {"A": "false"}) == []
    # a 3 -> 1 pool is noise, not a collapse: below the >= 8 floor, and not zero
    assert R.pool_floor(_ROWS3, {"//pools//": {"probe_candidates": 3}}) == []


def test_the_pool_census_key_is_not_mistaken_for_a_company(tmp_path):
    """`save_census` stores per-tool pool sizes under a sentinel key; `census_diff` must
    exclude it like `//notes//`, or seven phantom companies appear in `added`/`gone` on
    the next run."""
    import json
    import registry_health as R
    path = tmp_path / "census.json"
    R.save_census(_ROWS3, path=str(path))
    prev = json.load(open(path, encoding="utf-8"))
    assert "//pools//" in prev and prev["//pools//"]["probe_candidates"] == 2
    d = R.census_diff(_ROWS3, prev)
    assert d["added"] == [] and d["gone"] == [] and d["prev_rows"] == 3
    assert not d["first_census"]


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
    # since 2026-08-25 the gate is `activation_verdict` (tenant vouch -> human page -> deferral);
    # `tenant_is_this_company` alone was vacuous on every path-tenant platform
    assert "activation_verdict" in calls or "activation_verdict(" in src, (
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
    monkeypatch.setattr(A, "_playwright_available", lambda: False)   # the deep rung never renders in a fixture
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
    src = inspect.getsource(D.apply_verdict)      # the write block moved here 2026-08-26 (BACKLOG 6)
    seg = re.search(r'f"deep-validated \{TODAY\}: ([^"]*)"', src)
    assert seg, "could not find the deep-validated refusal segment in apply_verdict()"
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
               "activation_verdict", "write_verdict", "board_vouches",
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
    Likewise `fr[3] = ""` CLEARS an address rather than proposing one (auto_expand's
    `--clear-agg-urls` un-buries rows parked on an aggregator shell that way, 2026-08-25).
    """
    # ONE rule, shared with tools/mutate.py (`_row_write`): the two detectors drifted once
    # (a bare-target-only check hid apply_resolved.py:61) and wave-1 F7 showed both blind
    # to `fr[3] += url`, `fr[3:4] = [url]`, `fr.__setitem__(3, url)` and `fr[4] = flag`.
    M = _mutate_module()
    out = []
    for n in ast.walk(tree):
        if M._row_write(n):
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
    """Derived the way docs/gen_modules.py derives it, so the two cannot disagree. Both
    `python x.py` and `python -m x` run-lines count (BACKLOG 63)."""
    import glob as _glob
    runs = set()
    for wf in _glob.glob(os.path.join(root, ".github", "workflows", "*.yml")):
        text = open(wf, encoding="utf-8").read()
        for m in re.finditer(r"python3?\s+(?:-u\s+)?([A-Za-z0-9_]+)\.py\b", text):
            runs.add(m.group(1) + ".py")
        for m in re.finditer(r"python3?\s+(?:-u\s+)?-m\s+([A-Za-z0-9_]+)\b", text):
            runs.add(m.group(1) + ".py")
    return runs


def _root_imports(root, module):
    """Root modules `module` imports anywhere in its body (function-local imports included)."""
    tree = ast.parse(open(os.path.join(root, module), encoding="utf-8").read())
    have = {os.path.basename(p) for p in __import__("glob").glob(os.path.join(root, "*.py"))}
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name + ".py" for a in n.names if a.name + ".py" in have}
        elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
            if n.module + ".py" in have:
                out.add(n.module + ".py")
    return out


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


# ---------------------------------------------------------------------------------------
# Declared identity: pipeline/identity_facts.py is the ONE table the gates consult before
# any heuristic. These pin the table's self-consistency against the real registry, its
# layering (it imports nothing from pipeline/), and the recorded incidents that must
# never become declarable.
# ---------------------------------------------------------------------------------------

_NEGATIVE_IDENTITY = [
    # (company, foreign tenant token, foreign board) -- every one a recorded wrong write
    ("Lili", "elililly", "https://boards-api.greenhouse.io/v1/boards/elililly/jobs"),
    ("Bancor", "bancorpbank", "https://careers-bancorpbank.icims.com/jobs/search?ss=1"),
    ("Cogniteam", "riskified", "https://boards-api.greenhouse.io/v1/boards/riskified/jobs"),
    ("Riskified", "novartis", "https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/riskified/jobs"),
    ("NanoLock Security", "gen", "https://gen.wd1.myworkdayjobs.com/wday/cxs/gen/x/jobs"),
    ("SimilarTech", "similarweb", "https://boards-api.greenhouse.io/v1/boards/similarweb/jobs"),
    ("Bit", "bitdefender", "https://boards-api.greenhouse.io/v1/boards/bitdefender/jobs"),
    ("Sight Diagnostics", "sightsciences", "https://recruiting2.ultipro.com/SIG1008SIGH/x"),
    ("Sight Diagnostics", "SIG1008SIGH", "https://recruiting2.ultipro.com/SIG1008SIGH/JobBoard/x/"),
    ("Dun & Bradstreet (Israel) Ltd.", "israeljobs", "https://boards-api.greenhouse.io/v1/boards/israeljobs/jobs"),
    ("Sckipio", "87.00C", "https://www.comeet.com/careers-api/2.0/company/87.00C/positions?token=x"),
    ("Sckipio", "", "https://www.comeet.com/careers-api/2.0/company/87.00C/positions?token=x"),
    ("Similarweb", "similartech", "https://boards-api.greenhouse.io/v1/boards/similartech/jobs"),
]


def test_every_declared_negative_is_in_the_incident_list():
    """The list above is the suite's memory of the incidents; the table is the code's. They
    must agree (confirmation wave R7: three declared tokens were missing here)."""
    from pipeline import identity_facts as F
    listed = {(F._key(n), F._norm(t)) for n, t, _ in _NEGATIVE_IDENTITY}
    for name, d in F.DECLARED.items():
        for t in d.get("not_tenants", ()):
            assert (F._key(name), F._norm(t)) in listed, (name, t)


def test_the_declared_identity_table_is_consistent_with_the_registry():
    """Every `tenants` entry names a real row and matches that row's board; every entry
    carries evidence. Run against the LIVE registry on purpose: a declaration that has
    drifted from the board it vouches for is a wrong accept waiting to happen."""
    import csv
    import os
    from pipeline import identity_facts as F
    from pipeline import identity_gate as G
    from pipeline.company_identity import ATS_HOST
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "companies.csv"), encoding="utf-8") as fh:
        rows = [r for r in csv.reader(fh) if r and len(r) >= 6][1:]
    problems = F.validate(rows, ATS_HOST, G._plumbing)
    assert not problems, "\n".join(problems)
    assert F.facts("merck (msd)") and F.tenants("MERCK (MSD)") == {"msd"}, "lookup is case-folded"
    assert F.facts("no such company") == {} and F.tenants("no such company") == frozenset()


def test_identity_facts_imports_nothing_from_the_package():
    """Layering: identity_facts < company_identity < identity_gate. The table must stay a
    leaf, or the next import cycle hides behind a lazy import the way the old gate did."""
    import ast
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tree = ast.parse(open(os.path.join(root, "pipeline", "identity_facts.py"), encoding="utf-8").read())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
    assert not any(m.startswith("pipeline") for m in mods), sorted(mods)


@pytest.mark.parametrize("name,tok,api", _NEGATIVE_IDENTITY)
def test_a_recorded_wrong_write_is_neither_declared_nor_admitted(name, tok, api):
    """The incidents this whole lane exists for. None may be declared (the table would then
    be the wrong write), none may be admitted by the gates, and since 2026-08-26 each is a
    NEGATIVE declaration (`identity_facts.not_tenants`) so `board_vouches` refuses it without
    a page -- the only durable form (docs/BACKLOG.md 198). Kills `facts-not-tenants-drop`,
    `vouch-neg-drop`, `tenant-neg-drop`, `embed-neg-drop`."""
    from pipeline import identity_facts as F
    from pipeline import identity_gate as G
    ctok = G.checkable_token(tok, api)
    assert F._norm(ctok) not in F.tenants(name), "a recorded incident was DECLARED"
    assert F._norm(ctok) in F.not_tenants(name), "a recorded incident is not a NEGATIVE declaration"
    assert not G.embedded_board_ok(name, tok, api)
    assert G.board_vouches(name, tok, api) is False
    assert not G.tenant_is_this_company(name, api) or "greenhouse" in api or "comeet" in api, (
        "a subdomain negative refuses in tenant_is_this_company too")


def test_a_declared_tenant_decides_the_subdomain_check_in_both_directions(monkeypatch):
    """Hook 2. A declared row's board must carry a declared tenant in its SUBDOMAIN
    labels: the declaration admits it (overriding the string `mismatch` verdict that
    refuses `Itamar Medical` -> zoll today) and refuses any other tenant. Undeclared rows
    are untouched (the census is byte-identical). And a declared tenant that appears only
    in the PATH of a foreign host is NOT a match -- that is the Riskified/Novartis incident
    walked back in through the table, and the M3 record `facts-tenant-scope-widen` is
    exactly that edit."""
    from pipeline import identity_facts as F
    from pipeline import identity_gate as G
    wd = "https://%s.wd1.myworkdayjobs.com/wday/cxs/%s/x/jobs"
    # a real declaration (G1): its own tenant admits, a foreign tenant refuses
    assert G.tenant_is_this_company("Habana Labs (Intel)", wd % ("intel", "intel"))
    assert not G.tenant_is_this_company("Habana Labs (Intel)", wd % ("gen", "gen"))
    # a declaration overrides the string verdict (Itamar-shape: verdict says mismatch)
    monkeypatch.setitem(F._INDEX, "itamar medical", {"tenants": ("zoll",), "why": "test"})
    assert G.tenant_is_this_company("Itamar Medical", wd % ("zoll", "zoll"))
    # path-tenant platforms are not this function's business: scope returns first
    assert G.tenant_is_this_company(
        "Merck (MSD)", "https://boards-api.greenhouse.io/v1/boards/anything/jobs")
    # the Riskified path-position attack: declared tenant in the PATH of a foreign host
    monkeypatch.setitem(F._INDEX, "riskified", {"tenants": ("riskified",), "why": "test"})
    assert not G.tenant_is_this_company(
        "Riskified", "https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/riskified/jobs"), (
        "a declared tenant matched against a PATH segment of another company's host")
    assert G.tenant_is_this_company(
        "Riskified", "https://riskified.wd3.myworkdayjobs.com/wday/cxs/riskified/x/jobs")


def test_a_declared_row_refuses_an_undeclared_token_on_a_path_platform(monkeypatch):
    """Hook 3, both directions: on a path-tenant platform a declared row's own token must
    be a declared tenant; any other token is refused even when the heuristics would have
    admitted it. Killing `facts-embed-token-drop` needs a case the heuristics ACCEPT but
    the declaration refuses -- so the fixture declares a row under a tenant that is NOT
    its own slug."""
    from pipeline import identity_facts as F
    from pipeline import identity_gate as G
    gh = "https://boards-api.greenhouse.io/v1/boards/%s/jobs"
    monkeypatch.setitem(F._INDEX, "armis", {"tenants": ("armisgroup",), "why": "test"})
    assert not G.embedded_board_ok("Armis", "armissecurity", gh % "armissecurity"), (
        "the heuristics admit armissecurity; the declaration says armisgroup -- declared wins")
    assert G.embedded_board_ok("Armis", "armisgroup", gh % "armisgroup")


def test_explain_answers_why_a_row_was_activated_or_refused_without_touching_the_network(
        monkeypatch):
    """`registry_health.py --explain` is the one entry point for "why this verdict?". It
    must print every section (an agent reads it top to bottom) and, without --fetch,
    make ZERO network calls -- `page_names_company` is a 25s GET plus a possible paid
    unlock, and every naive reproduction of a verdict used to spend it."""
    import urllib.request
    import registry_health as R
    import bd_rescue

    def boom(*a, **k):
        raise AssertionError("network call from --explain without --fetch")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(bd_rescue, "unlock", boom)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    rows = [["Habana Labs (Intel)", "workday", "intel/External",
             "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs", "true",
             "re-audit 2026-08-21: deep-verified 40/6 IL | listing-hunt 2026-08-23: found"],
            ["SeeTree", "scrape", "https://www.seetree.ai", "https://www.seetree.ai", "false",
             "chrome-verified 2026-08-22: no careers page (redirects home); discovery-net only"]]
    lines = []
    assert R.explain("habana labs (intel)", rows, out=lines.append) == 0
    text = "\n".join(lines)
    for header in ("== row ==", "== exclusions", "== declared identity", "== identity, offline ==",
                   "== platform ==", "== tenant", "== page test ==", "== pools", "== last stamp"):
        assert header in text, header
    assert "DECLARED tenants=['intel']" in text
    assert "tenant_is_this_company = True" in text
    assert "not fetched; pass --fetch" in text
    assert "stamped by: listing-hunt" in text and "identity_ok" in text
    lines.clear()
    assert R.explain("SeeTree", rows, out=lines.append) == 0
    text = "\n".join(lines)
    assert "none declared" in text and "terminal (no pool may re-open)" in text
    assert R.explain("no such row", rows, out=lines.append) == 1


def test_the_mutation_coverage_demand_is_pinned():
    """`tools/mutate.py --coverage` runs in CI but only through the sweep; its demand set
    lives in `_gate_call_sites`' default. Narrowing that default (dropping `identity_ok`)
    silently stopped demanding records at two writers with everything green
    (confirmation-wave R2). Pin the default and run the coverage check in the suite."""
    import importlib.util
    import inspect
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("mutate", os.path.join(root, "tools", "mutate.py"))
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    default = inspect.signature(M._gate_call_sites).parameters["gate_names"].default
    assert set(default) == {"activation_ok", "ok_to_write", "identity_ok"}, default
    assert M.coverage(M._load()) == [], "the derived coverage check reports a gap"


def test_the_gate_caller_map_is_derived_not_typed():
    """`identity_gate.GATE_CALLERS` is the one map from a tool to the gate it calls -- the
    artifact a fresh agent needs and nothing carried before. It is a literal so it can be
    read; this derives it with tools/mutate.py's call-site detector (alias-aware) and fails
    on drift, so a new caller or a changed gate cannot leave the map lying."""
    import ast
    import glob
    import importlib.util
    import os
    from pipeline import identity_gate as G
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("mutate", os.path.join(root, "tools", "mutate.py"))
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    gates = tuple(G.GATE_CALLERS)
    derived = {g: set() for g in gates}
    # over the registry WRITERS (the same derived set the mutation coverage uses), not every
    # root file: registry_health --explain CALLS the gates to report them and writes nothing
    for base in M._registry_writers():
        for _site, callee in M._gate_call_sites(os.path.join(root, base), gate_names=gates):
            derived[callee].add(base)
    literal = {g: set(v) for g, v in G.GATE_CALLERS.items()}
    assert derived == literal, (
        "GATE_CALLERS drifted from the source: %s"
        % {g: sorted(derived[g] ^ literal[g]) for g in gates if derived[g] != literal[g]})


def test_the_writer_allow_list_only_covers_tools_no_workflow_runs():
    """An allow-listed writer that becomes scheduled must turn this red.

    The allow-list is the one hand-maintained thing left in the enumeration, so it is the one
    thing that can rot. `_LEGACY_UNSCHEDULED` is only defensible while nothing runs those
    modules; `_RESTORE_ONLY` is defensible regardless, because those writes restore a value
    rather than propose one -- but it has to say so.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scheduled = _modules_a_workflow_runs(root)
    # BOTH buckets (BACKLOG 62): `restore_only` was exempted from this check while feeding
    # the same mutation-coverage exemption, so a name added there escaped both.
    leaked = sorted((set(_LEGACY_UNSCHEDULED) | set(_RESTORE_ONLY)) & scheduled
                    - {"merge_csv_rows.py"})       # the one restore_only a workflow runs, by design
    assert not leaked, (
        "these modules are allow-listed as one-shot/legacy but a workflow now runs them, so "
        "they write the registry on a schedule with no identity gate: %s" % leaked)
    for mod in _RESTORE_ONLY:
        # a restore_only writer restores a value; it must never ACTIVATE
        tree = ast.parse(open(os.path.join(root, mod), encoding="utf-8").read())
        acts = [n for n in _registry_writes(tree)
                if (isinstance(n, ast.List) and isinstance(n.elts[4], ast.Constant)
                    and n.elts[4].value == "true")
                or (isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                    and t.slice.value == 4 for t in n.targets))]
        assert not acts, "%s is restore_only but activates: %r" % (mod, [ast.unparse(a)[:60] for a in acts])
    # BACKLOG 63: a scheduled module may import a legacy writer -- the import must not be a
    # back door. Every col-3/4 write in an imported legacy module must sit inside its own
    # `main()` (never a helper the importer could call, never module level).
    for mod in sorted(scheduled):
        if not os.path.exists(os.path.join(root, mod)):
            continue
        for legacy in sorted(_root_imports(root, mod) & set(_LEGACY_UNSCHEDULED)):
            tree = ast.parse(open(os.path.join(root, legacy), encoding="utf-8").read())
            parents = {}
            for p in ast.walk(tree):
                for c in ast.iter_child_nodes(p):
                    parents[c] = p
            for w in _registry_writes(tree):
                fn = w
                while fn in parents and not isinstance(fn, ast.FunctionDef):
                    fn = parents[fn]
                assert isinstance(fn, ast.FunctionDef) and fn.name == "main", (
                    "%s imports %s, whose registry write at line %d is reachable outside "
                    "main(): %s" % (mod, legacy, w.lineno, ast.unparse(w)[:60]))
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


def test_wayback_cannot_resurrect_a_board_the_snapshot_merely_embeds(
        tmp_path, monkeypatch):
    """Wave-5 R1 (B1, reproduced end-to-end): `wayback_rescue` is the THIRD caller of the
    `extract_ats(html, name)` shape, on strictly older evidence than the other two -- and
    it was left on the pre-wave-4 gate, passing no `html=`, so `activation_ok` fell to the
    tenant clause, vacuously True on 6 of the 7 platforms `extract_ats` returns. A real
    pool row (`Panoply`) was activated onto Riskified's greenhouse board from an archived
    snapshot, on the Sunday cron, behind continue-on-error, while `validate_empty` refused
    the identical page two workflow lines later.

    `rescue()` now returns the snapshot html and the write is gated exactly like
    `bd_rescue`'s: the page can refuse, and the board must vouch for itself. The old
    guard test stubbed `rescue` wholesale, so it could never see any of this -- these
    stubs sit at `latest_snapshots`/`_get`/`_verify`, the named network boundaries, and
    `extract_ats` and the whole gate run for real.
    """
    import sys
    import wayback_rescue as W
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Panoply", "scrape", "https://panoply.io/careers/jobs",
         "https://panoply.io/careers/jobs", "false", "unreachable; could not scan"],
        ["Kima", "scrape", "https://www.kima.network/careers",
         "https://www.kima.network/careers", "false", "unreachable; could not scan"],
        ["Voiceitt", "scrape", "https://www.voiceitt.com/careers",
         "https://www.voiceitt.com/careers", "false", "unreachable; could not scan"],
    ])
    def page(company, slug):
        return ("<html><h1>" + company + " Careers</h1>"
                + ("<p>" + company + " is hiring in Tel Aviv.</p>") * 60
                + '<a href="https://boards.greenhouse.io/embed/job_board?for=' + slug
                + '&amp;t=1">Open positions</a></html>')
    # Panoply: own archived page, FOREIGN embed. Kima: own page, own board. Voiceitt: the
    # snapshot serves ANOTHER company's page carrying a name-matching embed (a hijacked
    # domain archived) -- the held-page clause must refuse it.
    snaps = {"https://panoply.io/careers/jobs": page("Panoply", "riskified"),
             "https://www.kima.network/careers": page("Kima", "kima"),
             "https://www.voiceitt.com/careers": page("Riskified", "voiceitt")}
    monkeypatch.setattr(W, "latest_snapshots", lambda url: ["snap://" + url])
    monkeypatch.setattr(W, "_get", lambda u, *a, **k: snaps.get(u[7:], ""))
    monkeypatch.setattr(W, "_verify", lambda name, plat, tok, api: (12, 3))
    monkeypatch.setattr(W.time, "sleep", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["wayback_rescue.py"])
    W.main()
    out = _read(tmp_path)
    assert out["Panoply"][4] == "false", (
        "an archived page cannot vouch for a board it merely embeds: %r" % (out["Panoply"],))
    assert "riskified" not in out["Panoply"][3]
    assert out["Kima"][4] == "true" and "kima" in out["Kima"][3], (
        "positive control regressed: %r" % (out["Kima"],))
    assert out["Voiceitt"][4] == "false", (
        "a snapshot naming another company activated a name-matching embed: %r"
        % (out["Voiceitt"],))


def test_the_embed_vouch_recognises_the_slug_shapes_production_actually_emits():
    """Wave-5 R1+R2: `_tenant_near` was calibrated on subdomain HOST LABELS and wave 4
    applied it to PATH TOKENS, which routinely carry a whole extra word -- so the embed
    vouch refused 44 real own-board slugs (`armissecurity`, `khealthcareers`,
    `bluevineisrael`) and ALL 83 Workday boards, because `wayback_rescue.extract_ats`
    returns the composite `tenant/site` as the token and `_norm` concatenates it into
    something no name can near-equal. The wave-4 Qualcomm census cell passed only by
    hand-writing a token shape production cannot emit.

    The calibration: (1) on a subdomain-tenant host with a checkable label,
    `tenant_is_this_company` already decided -- the token is not double-checked;
    (2) on path-tenant hosts, generic tail WORDS are stripped from the token before the
    near-match; (3) `_name_targets` also yields the parenthetical alias forms, so
    `VMware (Broadcom)` can match its own acquirer tenant. The tightness cells pin that
    none of this re-opens containment: `lili`/`elililly` and `bancor`/`bancorpbank` still
    refuse, and the +-1 length window stays +-1 -- at +-2 a digit-stripped Comeet uid
    (`A5.000` -> `a`) is CONTAINED in `zap` and another company's board is promoted
    (wave-5 R2, 8 wrong accepts measured at +-2 on the real pools).
    """
    from pipeline import identity_gate as G
    gh = "https://boards-api.greenhouse.io/v1/boards/%s/jobs"

    # the extra-word class: real slugs of real registry rows (wave-5 R1's sweep)
    assert G.embedded_board_ok("Armis", "armissecurity", gh % "armissecurity")
    assert G.embedded_board_ok("K Health", "khealthcareers", gh % "khealthcareers")
    assert G.embedded_board_ok("BlueVine", "bluevineisrael", gh % "bluevineisrael")
    # the Workday composite token, exactly as extract_ats returns it
    assert G.embedded_board_ok(
        "MSD", "msd/SearchJobs",
        "https://msd.wd5.myworkdayjobs.com/wday/cxs/msd/SearchJobs/jobs")
    # parenthetical alias: the acquirer tenant is IN the registry name
    assert G.embedded_board_ok(
        "VMware (Broadcom)", "broadcom/External_Career",
        "https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs")
    assert G.embedded_board_ok("Merck (MSD)", "msd",
                               "https://msd.wd5.myworkdayjobs.com/wday/cxs/msd/S/jobs")

    # tightness survives the calibration -- every recorded incident shape still refuses
    assert not G.embedded_board_ok("Lili", "elililly", gh % "elililly")
    assert not G.embedded_board_ok("Cogniteam", "riskified", gh % "riskified")
    assert not G.embedded_board_ok(
        "Bancor", "bancorpbank", "https://careers-bancorpbank.icims.com/jobs/search?ss=1")
    # DECLARED path-tenant rows: the embed vouch reads the declaration first (hook 3).
    # Momentis->memic was item 61's headline accepted refusal; it is admitted now because
    # the fact is declared with evidence, not because a matcher got looser.
    assert G.embedded_board_ok("Momentis Surgical", "memic", gh % "memic")
    assert G.embedded_board_ok("SentinelOne", "sentinellabs", gh % "sentinellabs")

    # the +-1 window pin (kills embed-near-window-drift)
    assert not G.embedded_board_ok(
        "zap group", "A5.000",
        "https://www.comeet.com/careers-api/2.0/company/A5.000/positions?token=x")

    # wave-6 R1 (B1): `Dun & Bradstreet (Israel) Ltd.` must not make bare `israel` a
    # target -- with the word-stripping layer, `israeljobs`/`israelcareers`/`israeltech`
    # all collapsed onto it and another company's board promoted on the Sunday path.
    # First closed by a pure-filler guard; now impossible by construction, because the
    # parenthetical is not split at all -- acquisitions are DECLARED, not parsed.
    assert not G.embedded_board_ok("Dun & Bradstreet (Israel) Ltd.", "israeljobs",
                                   gh % "israeljobs"), (
        "`israel` became an identity target via the parenthetical alias split")
    assert G.embedded_board_ok("Dun & Bradstreet (Israel) Ltd.", "dunbradstreet",
                               gh % "dunbradstreet"), (
        "positive control: the row's real identity must still vouch")

    # wave-6 R3's cross-accept inventory: under 3 chars the +-1-with-containment window
    # collapses, so short forms must match EXACTLY. `_TENANT_SUFFIX` digit-stripping
    # turns the Comeet uid `F2.004` into `f`, contained in `f5`; `hp` admitted `hpe`.
    # HP's own two-char tenant still matches by equality.
    assert not G.embedded_board_ok(
        "F5", "F2.004",
        "https://www.comeet.com/careers-api/2.0/company/F2.004/positions?token=x")
    assert not G.embedded_board_ok("HP", "hpe", gh % "hpe")
    assert G.embedded_board_ok("HP", "hp", gh % "hp"), (
        "positive control: a short OWN tenant must still match exactly")

    # the word-strip regex is TAIL-anchored: without the anchor, `techstars` strips its
    # 'tech' PREFIX to 'stars' and another company's board matches the name `Stars`.
    assert not G.embedded_board_ok("Stars", "techstars", gh % "techstars")

    # the short-form boundary in the TIGHTENING direction (wave-7 confirmation): at
    # `<= 3` the equality branch swallows Orbs' own 3-char ashby tenant `orb` against its
    # 4-char name -- the one real row on that boundary refuses its own board.
    assert G.embedded_board_ok(
        "Orbs", "orb", "https://api.ashbyhq.com/posting-api/job-board/orb"), (
        "the 3-vs-4-char own-board pair fell into the equality branch")


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
    page = "<html>" + "x" * 3000 + "</html>"
    res = {"Bancor": ("icims", "bancorpbank", _BANCORP, 30, 9, page),
           "Fiverr": ("greenhouse", "fiverr", _FIVERR, 40, 12, page)}
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
    from repair_extract_gap import in_extract_gap_pool

    rows = R.read_rows()
    labelled = R.pools(rows)

    crack_real = {r[0] for r in rows
                  if r[4] == "false" and G.is_walled(r)
                  and not R.is_terminal_note(r[5] or "") and not is_recruiter(r[0])}
    crack_matrix = {r[0] for r in labelled["crack_walled (19:00 daily + Sun)"]}
    assert crack_matrix == crack_real, (
        "the crack mirror disagrees with identity_gate.is_walled by %d row(s): %s"
        % (len(crack_matrix ^ crack_real), sorted(crack_matrix ^ crack_real)[:8]))

    gap_real = {r[0] for r in rows if in_extract_gap_pool(r)}
    gap_matrix = {r[0] for r in labelled["repair_extract_gap (19:00 daily)"]}
    assert gap_matrix == gap_real, (
        "the extract-gap mirror disagrees with repair_extract_gap.in_extract_gap_pool by %d row(s): %s"
        % (len(gap_matrix ^ gap_real), sorted(gap_matrix ^ gap_real)[:8]))

    # ...and the three pools whose tools export an `in_*_pool` callable: the matrix must
    # be THAT callable over the rows, member for member. The hunt was the one left as a
    # closure after wave 6; a closure is a retype with extra steps.
    import listing_hunt as LH
    import probe_candidates as PC
    import triage_dark as TD
    for label, pred in (("listing_hunt (19:00 daily)", LH.in_hunt_pool),
                        ("probe_candidates (05:00 daily)", PC.in_probe_pool),
                        ("triage_dark (18:00 daily)", TD.in_triage_pool)):
        real = {r[0] for r in rows if pred(r)}
        matrix = {r[0] for r in labelled[label]}
        assert matrix == real, (
            "%s mirror disagrees with the tool's own predicate by %d row(s): %s"
            % (label, len(matrix ^ real), sorted(matrix ^ real)[:8]))


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
    # the taleo half, previously untested with an empty registry set (docs/BACKLOG.md 55):
    # same rule, same both-directions pair, on the URL shape crack_walled builds
    radware = "<html><h1>Radware Careers</h1>" + "<p>Radware is hiring.</p>" * 90 + "</html>"
    assert G.identity_ok("Varonis", "https://radware.taleo.net/careersection/jobsearch.ftl",
                         html=radware) is False, "Varonis onto Radware's Taleo board"
    assert G.identity_ok("Radware", "https://radware.taleo.net/careersection/jobsearch.ftl",
                         html=radware) is True, "positive control: Radware's own board"


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
    # (was NanoLock Security -- since 2026-08-25 `gen` is its DECLARED not_tenant and refuses
    # without a page, by design; an undeclared near-miss is the shape this tail is for)
    served = {"https://gen.wd1.myworkdayjobs.com/wday/cxs/gen/x/jobs":
              ("<h1>Kaleidoo Careers</h1>"
               + "<p>Kaleidoo is hiring in Israel.</p>" * 80).encode()}
    class _Resp:
        def __init__(self, data): self._d = data
        def read(self, n=-1): return self._d
    monkeypatch.setattr(G.urllib.request, "urlopen",
                        lambda req, timeout=25, context=None: _Resp(served[req.full_url]))
    assert G.activation_ok(
        "Kaleidoo", "https://gen.wd1.myworkdayjobs.com/wday/cxs/gen/x/jobs", 5
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
                      "https://boards-api.greenhouse.io/v1/boards/zeroco/jobs", 0, 0, ""),
           "Fiverr": ("greenhouse", "fiverr", _FIVERR, 40, 12, "")}
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

    # ...and the rung is BUDGETED: the key on a Sunday cron made the uncapped rung
    # recurring paid spend (BACKLOG 36, armed by closing 59). Budget exhausted, the row
    # honestly reads None -- same as the key being absent, never a False.
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    monkeypatch.setattr(G, "_UNLOCK_BUDGET", 0)
    monkeypatch.setattr(G, "_UNLOCK_SPENT", 0)
    assert G.page_names_company("Bit", "https://careers.bit.example/", html=walled) is None, (
        "an exhausted unlocker budget must read as no-evidence, not spend anyway")

    # ...and the counter actually COUNTS (wave-7 confirmation: deleting the increment
    # left the suite green and the cap inert). Budget 1: the first call spends it, the
    # second is suppressed.
    monkeypatch.setattr(G, "_UNLOCK_BUDGET", 1)
    monkeypatch.setattr(G, "_UNLOCK_SPENT", 0)
    assert G.page_names_company("Bit", "https://careers.bit.example/", html=walled) is True
    assert G.page_names_company("Bit", "https://careers.bit.example/", html=walled) is None, (
        "the budget was spent by the first call; a second paid call went out anyway")


def test_the_merge_writes_the_registry_atomically(tmp_path, monkeypatch):
    """Wave-7 confirmation: reverting `merge_csv_rows` to its old truncating in-place
    write was suite-green -- the crash-window property has no direct observer, but the
    ROUTE does: the merge must go through `pipeline.atomic`'s replace, which is what
    makes a runner kill mid-merge leave the OLD file (a valid registry) instead of a
    400-line stump behind `|| true` on nine recovery paths.
    """
    import os as _os
    import merge_csv_rows as M
    import pipeline.atomic as A
    rows = [["company_name", "ats_platform", "token", "api_url", "active", "notes"],
            ["X", "scrape", "u", "https://x.example", "false", "unreachable; could not scan"]]
    base = tmp_path / "base.csv"; ours = tmp_path / "ours.csv"; target = tmp_path / "t.csv"
    import csv as _csv
    for f in (base, ours, target):
        with open(f, "w", newline="", encoding="utf-8") as fh:
            _csv.writer(fh).writerows(rows)
    hits = []
    real = _os.replace
    monkeypatch.setattr(A.os, "replace", lambda a, b: (hits.append(b), real(a, b))[1])
    M.merge(str(base), str(ours), str(target))
    assert any(str(target) in h for h in hits), (
        "the merged registry was not written through the atomic replace")


def test_each_pool_predicate_selects_and_excludes_on_real_note_shapes():
    """Wave-6 R2 (B3 x2): the pool constants were shared and identity-asserted, but no
    test drove the CONSUMERS -- `search` -> `match` at probe_candidates emptied the 05:00
    probe 130 -> 0 and the 18:00 triage 18 -> 0 with the suite green, and dropping
    `redundant` from the unified TERMINAL re-opened `Marvell Israel` (a deactivated
    scrape twin of a working ATS row) into crack_walled's ACTIVATING pool. These cells
    run each tool's own `in_*_pool` predicate -- the same callable `main()` selects with
    and `registry_health` imports -- over real note shapes with the pool token MID-NOTE,
    so an anchored match can never pass by accident.
    """
    import probe_candidates as PC
    import triage_dark as TD
    import crack_walled as CW

    # probe: token mid-note selects; a terminal token excludes; a non-http url excludes
    base = "deep-validated 2026-08-21: no ATS detected (rendered) | monitored candidate"
    row = lambda note, url="https://x.example/careers": ["X", "scrape", url, url, "false", note]
    assert PC.in_probe_pool(row(base))
    assert not PC.in_probe_pool(row(base + " | alias-of Y 2026-08-23: same board"))
    assert not PC.in_probe_pool(row(base, url="ftp://x"))
    assert not PC.in_probe_pool(["X", "s", "u", "https://x.example", "true", base])

    # triage: mid-note target token selects; the unified terminal set excludes
    t = "unreachable; could not scan | listing-hunt 2026-08-23: no listing found"
    assert TD.in_triage_pool(["X", "scrape", "u", "https://x.example", "false", t])
    assert not TD.in_triage_pool(["X", "scrape", "u", "https://x.example", "false",
                                  t + " | defunct (site gone)"])

    # hunt: a mid-note pool token selects; the shared terminal list excludes -- dropping
    # its terminal term re-admits a deactivated `redundant` twin to the hunt (and the
    # hunt activates). listing_hunt was the last tool spelling a private 3-token list.
    import listing_hunt as LH
    hunted = ["Marvell Israel", "scrape", "https://x.example/c", "https://x.example/c",
              "false", "deep-validated 2026-08-21: no ATS detected | unreachable; could not scan"]
    assert LH.in_hunt_pool(hunted)
    dup = list(hunted)
    dup[5] = "universal-scrape; 2 IL [deactivated: redundant scrape dup of working ATS twin] | unreachable"
    assert not LH.in_hunt_pool(dup), "a redundant twin re-entered the hunt pool"

    # crack: a walled host selects; the REDUNDANT twin must never re-enter (the row shape
    # is Marvell Israel's, verbatim class); a recruiter never enters
    wd = "https://marvell.wd1.myworkdayjobs.com/MarvellCareers"
    walled = ["Marvell Israel", "scrape", wd, wd, "false",
              "deep-validated 2026-08-21: unsupported ATS myworkdayjobs.com"]
    assert CW.in_crack_pool(walled)
    twin = list(walled)
    twin[5] = "universal-scrape; 2 Israel jobs [deactivated: redundant scrape dup of working ATS twin]"
    assert not CW.in_crack_pool(twin), (
        "a deactivated redundant twin re-entered the ACTIVATING crack pool -- dropping "
        "`redundant` from the shared TERMINAL was suite-green until this cell")
    rec = list(walled); rec[0] = "Experis Israel"
    assert not CW.in_crack_pool(rec)


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
    # the blocking gate's terminal set covers the WHOLE shared list -- reverting its
    # derivation to the old narrow literal was suite-green (wave-7 confirmation)
    from pipeline.verdicts import TERMINAL as _T
    for _tok in _T:
        assert re.search(ci.TERMINAL, _tok, re.I), (
            "check_invariants.TERMINAL no longer covers %r" % _tok)
    # a retyped mirror is how the loss stayed silent; the mirror must BE the tool's
    # the hunt mirror is the tool's own predicate now -- see
    # test_every_ownership_mirror_agrees_with_the_tool_it_mirrors, which pins all five
    # ...and check_invariants.POOL, the THIRD copy, is pinned set-equal to the receiver's
    # alternatives plus its one deliberate extra (`dark-triage` has its own pool). The old
    # guard checked only the narrowing direction; a token added to POOL alone WIDENS the
    # blocking gate's idea of "owned" and masks orphans (wave-5 R2 exhibited three).
    assert (set(ci.POOL.split("|")) ==
            set(LH.HUNT_POOL.pattern.split("|")) | {"dark-triage"}), (
        "check_invariants.POOL has drifted from listing_hunt.HUNT_POOL: %r vs %r"
        % (sorted(set(ci.POOL.split("|"))), sorted(set(LH.HUNT_POOL.pattern.split("|")))))
    # validate_empty's hand-off shape stays in the receiver's pool too
    assert LH.HUNT_POOL.search("empty-but-suspect; 3 IL but the board is not this company's")


# ---------------------------------------------------------------------------------------
# The 02:30 chain (bd_rescue -> retry_unreachable) and the Sunday rescues, 2026-08-25.
# Proof of the defect: `git show b3d1d49 -- companies.csv` -- nine rows lose
# `| listing-hunt 2026-08-24: no IL listing; monitored candidate` in one night, and the
# Bright Data verdict paid for 90 seconds earlier in the same job is gone with it.
# ---------------------------------------------------------------------------------------

_HUNTED = "unreachable; could not scan | listing-hunt 2026-08-24: no IL listing; monitored candidate"


def _chain_registry(tmp_path):
    return _registry(tmp_path, [
        ["Chakratec", "scrape", "https://www.chakratec.com/careers",
         "https://www.chakratec.com/careers", "false", _HUNTED],
        ["Cyberbit", "scrape", "https://www.cyberbit.com/careers",
         "https://www.cyberbit.com/careers", "false", _HUNTED],
        ["Fiverr", "", "", "https://www.fiverr.com/jobs", "false",
         "unreachable; could not scan"],
    ])


def test_retry_unreachable_keeps_other_tools_segments_when_still_unreachable(
        tmp_path, monkeypatch):
    """Kills `retry-note-base-drop`. A night that finds nothing must leave the row exactly
    as it found it plus one dated `retry` segment -- never rebuild the cell."""
    import sys
    import retry_unreachable as R
    import listing_hunt as LH
    import probe_candidates as PC
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    _chain_registry(tmp_path)
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    monkeypatch.setattr(R, "attempt", lambda name, url: (
        ("ats", ("Fiverr", "greenhouse", "fiverr", _FIVERR, 40, 12)) if name == "Fiverr"
        else ("unreachable", None)))
    monkeypatch.setattr(sys, "argv", ["retry_unreachable.py"])
    monkeypatch.delenv("RETRY_LIMIT", raising=False)
    R.main()

    out = _read(tmp_path)
    row = out["Chakratec"]
    assert "listing-hunt 2026-08-24: no IL listing; monitored candidate" in row[5], (
        "the hunt's segment was erased by a still-unreachable night: %r" % (row[5],))
    assert "unreachable" in row[5].lower(), "the selector token must survive: %r" % (row[5],)
    assert "retry 20" in row[5], "no dated retry stamp: %r" % (row[5],)
    assert row[4] == "false" and row[3] == "https://www.chakratec.com/careers"
    assert LH.in_hunt_pool(row) and PC.in_probe_pool(row), (
        "the row left the hunt or probe pool: %r" % (row,))
    # positive control: a real recovery activates, drops the disproved token, keeps its own
    ok = out["Fiverr"]
    assert ok[4] == "true" and ok[3] == _FIVERR and "retry-resolved" in ok[5], ok
    assert "unreachable" not in ok[5].lower(), "an activation keeps a disproved token: %r" % ok


def test_bd_validated_row_survives_the_retry_pass(tmp_path, monkeypatch):
    """Kills `bd-empt-keeps-unreachable`. The chain as the workflow runs it: bd_rescue
    reaches Chakratec's page (no board -> `scanned via brightdata`), cannot reach Cyberbit
    (`bd-tried`); retry_unreachable then runs 90 s later on the SAME csv. The reached row
    must not be re-attempted, and its paid verdict, its listing-hunt segment and BD's
    best_url must all be there in the morning."""
    import sys
    import bd_rescue as B
    import retry_unreachable as R
    import listing_hunt as LH
    import probe_candidates as PC
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    _chain_registry(tmp_path)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "x")
    monkeypatch.delenv("BD_LIMIT", raising=False)
    monkeypatch.setattr(B, "_load_secrets", lambda *a, **k: None)
    monkeypatch.setattr(B, "alt_urls", lambda url: [url.replace("/careers", "/jobs")])
    monkeypatch.setattr(B, "unlock", lambda u, timeout=90: (
        "" if "cyberbit" in u else "<html>" + "x" * 3000 + "</html>"))
    monkeypatch.setattr(B, "extract_ats", lambda html, name: None)
    monkeypatch.setattr(B.time, "sleep", lambda *a: None)
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    monkeypatch.setattr(sys, "argv", ["bd_rescue.py"])
    B.main()

    attempted = []

    def _attempt(name, url):
        attempted.append(name)
        return ("unreachable", None)
    monkeypatch.setattr(R, "attempt", _attempt)
    monkeypatch.setattr(sys, "argv", ["retry_unreachable.py"])
    monkeypatch.delenv("RETRY_LIMIT", raising=False)
    R.main()

    out = _read(tmp_path)
    reached = out["Chakratec"]
    assert "Chakratec" not in attempted, "retry re-attempted a row Bright Data had reached"
    assert "scanned via brightdata" in reached[5], "BD's paid verdict is gone: %r" % reached
    assert "listing-hunt 2026-08-24" in reached[5], "the hunt's segment is gone: %r" % reached
    assert "unreachable" not in reached[5].lower(), "a disproved token survived: %r" % reached
    assert reached[3] == "https://www.chakratec.com/jobs", "BD's best_url was reverted: %r" % reached
    assert LH.in_hunt_pool(reached) and PC.in_probe_pool(reached), reached
    # positive control: the row BD could NOT reach is still retry's to attempt
    unreached = out["Cyberbit"]
    assert attempted == ["Cyberbit"], "only the unreached row is retry's: %r" % (attempted,)
    assert "unreachable" in unreached[5].lower() and "bd-tried" in unreached[5], unreached
    assert "listing-hunt 2026-08-24" in unreached[5], unreached


def test_retry_unreachable_never_reopens_a_terminal_row(tmp_path, monkeypatch):
    """Kills `retry-pool-terminal-remove`. An `alias-of` row points at a board that WORKS -- a
    successful retry would publish every role twice under two names."""
    import sys
    import retry_unreachable as R
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Fiverr Israel", "", "", "https://www.fiverr.com/jobs", "false",
         "unreachable; could not scan | alias-of Fiverr"],
        ["Fiverr", "", "", "https://www.fiverr.com/jobs", "false",
         "unreachable; could not scan"],
    ])
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    seen = []

    def _attempt(name, url):
        seen.append(name)
        return ("ats", ("Fiverr", "greenhouse", "fiverr", _FIVERR, 40, 12))
    monkeypatch.setattr(R, "attempt", _attempt)
    monkeypatch.setattr(sys, "argv", ["retry_unreachable.py"])
    monkeypatch.delenv("RETRY_LIMIT", raising=False)
    R.main()
    out = _read(tmp_path)
    assert seen == ["Fiverr"], "a terminal row was attempted: %r" % (seen,)
    assert out["Fiverr Israel"][4] == "false" and "alias-of" in out["Fiverr Israel"][5]
    assert out["Fiverr"][4] == "true", "positive control regressed: %r" % (out["Fiverr"],)


def test_rescue_activations_keep_the_prior_note(tmp_path, monkeypatch):
    """Kills `bd-activate-cell-overwrite`, `wayback-activate-cell-overwrite` and
    `validate-empty-promote-overwrite`. An activation is when a row can least afford to
    lose its `dark-triage` mode or a terminal token (ARCHITECTURE section 2)."""
    import sys
    import bd_rescue as B
    import wayback_rescue as W
    import validate_empty as V
    from pipeline import identity_gate as G
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    page = "<html>" + "x" * 3000 + "</html>"
    prior = "dark-triage 2026-08-24: blocked | unreachable; could not scan | bd-tried 2026-08-01 x1"

    # bd_rescue
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [["Fiverr", "", "", "https://www.fiverr.com/jobs", "false", prior]])
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "x")
    monkeypatch.delenv("BD_LIMIT", raising=False)
    monkeypatch.setattr(B, "_load_secrets", lambda *a, **k: None)
    monkeypatch.setattr(B, "alt_urls", lambda url: [url])
    monkeypatch.setattr(B, "unlock", lambda u, timeout=90: page)
    monkeypatch.setattr(B, "extract_ats", lambda html, name: ("greenhouse", "fiverr", _FIVERR))
    monkeypatch.setattr(B, "_verify", lambda name, plat, tok, api: (12, 5))
    monkeypatch.setattr(B.time, "sleep", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["bd_rescue.py"])
    B.main()
    row = _read(tmp_path)["Fiverr"]
    assert row[4] == "true" and "brightdata-rescued" in row[5], row
    assert "dark-triage 2026-08-24: blocked" in row[5], "the triage mode was erased: %r" % row
    assert "unreachable" not in row[5].lower() and "bd-tried" not in row[5], row

    # wayback_rescue
    _registry(tmp_path, [["Fiverr", "", "", "https://www.fiverr.com/jobs", "false", prior]])
    monkeypatch.setattr(W, "rescue", lambda name, url: ("greenhouse", "fiverr", _FIVERR, 40, 12, page))
    monkeypatch.setattr(W.time, "sleep", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["wayback_rescue.py"])
    W.main()
    row = _read(tmp_path)["Fiverr"]
    assert row[4] == "true" and "wayback-rescued" in row[5], row
    assert "dark-triage 2026-08-24: blocked" in row[5], "the triage mode was erased: %r" % row
    assert "unreachable" not in row[5].lower(), row

    # validate_empty (Sun 04:00) -- its promote row is built from the page in check()
    _registry(tmp_path, [["Fiverr", "", "", "https://www.fiverr.com/jobs", "false",
                          "dark-triage 2026-08-24: page-empty | scanned; no open Israel roles now"]])
    monkeypatch.setattr(V, "_get", lambda u, timeout=10: page)
    monkeypatch.setattr(V, "_verify", lambda name, plat, tok, api: (30, 9))
    monkeypatch.setattr(V, "extract_ats", lambda html, name: ("greenhouse", "fiverr", _FIVERR))
    monkeypatch.setattr(sys, "argv", ["validate_empty.py"])
    V.main()
    row = _read(tmp_path)["Fiverr"]
    assert row[4] == "true" and "cross-validated" in row[5], row
    assert "dark-triage 2026-08-24: page-empty" in row[5], "the triage mode was erased: %r" % row


# ---------------------------------------------------------------------------------------
# auto_expand + resolve_llm, 2026-08-25 (docs/BACKLOG.md 177): the aggregator seed is
# never rendered, never parked; the LLM tier is asked only with a page in hand; the paid
# search rung is capped; the queue rotates. `main()` is driven through `CSV_PATH` and
# `load_companies` on the module (an absolute path fixed at import; a chdir does not
# redirect it -- the older row-builder tests explain why they stopped short of main()).
# ---------------------------------------------------------------------------------------

_LI = "https://il.linkedin.com/jobs/view/data-analyst-at-houzz-4281234567"
_SH = "https://secrethunter.io/jobz/98765"


def _expand_env(tmp_path, monkeypatch, queue, registry_rows=(), seen=None):
    import shutil
    import sys
    import auto_expand as E
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, list(registry_rows))
    monkeypatch.setattr(E, "CSV_PATH", str(tmp_path / "companies.csv"))
    monkeypatch.setattr(E, "DRY_RUN", False)
    (tmp_path / "research_companies.json").write_text(json.dumps(queue), encoding="utf-8")
    (tmp_path / "cloud_state").mkdir(exist_ok=True)
    key = tmp_path / "cloud_state" / "auto_expand_seen.json"
    if seen is not None:
        key.write_text(json.dumps(seen), encoding="utf-8")
    elif key.exists():
        key.unlink()
    monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/claude")
    # never the real resolver (Playwright + network): a test that wants one sets its own
    monkeypatch.setattr(E, "resolve", lambda name, url: (_ for _ in ()).throw(
        AssertionError("resolve_deep.resolve called on %s" % url)))
    monkeypatch.setattr(sys, "argv", ["auto_expand.py"])
    for k in ("AUTO_EXPAND_LIMIT", "LLM_RESOLVE_CAP", "AUTO_EXPAND_SEARCH_CAP"):
        monkeypatch.delenv(k, raising=False)
    return E


def _llm_stub(monkeypatch, answers):
    """answers: name -> (asked, result). Records the call order."""
    import resolve_llm as L
    calls = []

    def _fake(name, url):
        calls.append(name)
        asked, res = answers.get(name, (False, None))
        L.LAST.update(asked=asked, pages=1 if asked else 0, candidates=1 if asked else 0,
                      calls=1 if asked else 0)
        return res
    monkeypatch.setattr(L, "resolve_llm", _fake)
    return calls


def test_auto_expand_never_renders_or_parks_an_aggregator_seed(tmp_path, monkeypatch):
    """Kills `expand-agg-seed-resolves` and `expand-agg-parks-empty`. 338 of the 342
    queued names on 2026-08-25 were LinkedIn / secrethunter postings: each cost a 17-25 s
    render that could only end in a refusal, and the ten that got an LLM shot were parked
    as `scanned; no open Israel roles now` with the posting as their address."""
    from pipeline import identity_gate as G
    E = _expand_env(tmp_path, monkeypatch, [
        {"name": "Houzz", "careers_url": _LI},
        {"name": "yad2", "careers_url": _SH},
        {"name": "Fiverr", "careers_url": "https://www.fiverr.com/jobs"},
    ])
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    rendered = []

    def _resolve(name, url):
        rendered.append(name)
        return ("ats", ("Fiverr", "greenhouse", "fiverr", _FIVERR, 40, 12))
    monkeypatch.setattr(E, "resolve", _resolve)
    _llm_stub(monkeypatch, {})
    E.main()

    out = _read(tmp_path)
    assert rendered == ["Fiverr"], "an aggregator seed was rendered: %r" % (rendered,)
    assert "Houzz" not in out and "yad2" not in out, (
        "an aggregator seed was PARKED (buried under the posting's URL): %r" % (out,))
    assert out["Fiverr"][4] == "true" and out["Fiverr"][3] == _FIVERR, (
        "positive control regressed: %r" % (out["Fiverr"],))
    seen = json.loads((tmp_path / "cloud_state" / "auto_expand_seen.json").read_text())
    assert set(seen) == {"Houzz", "yad2"}, "the rotation key must stamp every LLM-tier entry: %r" % seen


def test_auto_expand_llm_shots_rotate_least_recently_tried_first(tmp_path, monkeypatch):
    """Kills `expand-rotation-drop`. Deferred names are never parked, so without the key
    the same file-order prefix would take every run's shots forever (the rule ARCHITECTURE
    section 2 states for scan_dead_domains and probe_candidates)."""
    import datetime as _dt
    queue = [{"name": n, "careers_url": _LI} for n in ("A Ltd", "B Ltd", "C Ltd")]
    E = _expand_env(tmp_path, monkeypatch, queue,
                    seen={"A Ltd": _dt.date.today().isoformat(), "B Ltd": "2026-08-01"})
    monkeypatch.setenv("LLM_RESOLVE_CAP", "1")
    monkeypatch.setenv("AUTO_EXPAND_SEARCH_CAP", "1")
    calls = _llm_stub(monkeypatch, {})
    E.main()
    assert calls == ["C Ltd"], "never tried must come first: %r" % (calls,)
    seen = json.loads((tmp_path / "cloud_state" / "auto_expand_seen.json").read_text())
    assert "C Ltd" in seen and seen["A Ltd"] == _dt.date.today().isoformat()

    # positive control: with no key, file order
    E = _expand_env(tmp_path, monkeypatch, queue)
    monkeypatch.setenv("LLM_RESOLVE_CAP", "1")
    monkeypatch.setenv("AUTO_EXPAND_SEARCH_CAP", "1")
    calls = _llm_stub(monkeypatch, {})
    E.main()
    assert calls == ["A Ltd"], calls


def test_auto_expand_llm_budget_counts_claude_calls_not_attempts(tmp_path, monkeypatch, capsys):
    """Kills `llm-calls-uncounted` (its predecessor `expand-budget-counts-attempts` was retired when the charge became LAST["calls"]). A name whose search ladder found no page
    costs no `claude -p` call, so it must not consume the call cap; the log says WHY each
    name was deferred so `cannot search` and `searched and failed` stay distinguishable
    (CLAUDE.md rule 2)."""
    queue = [{"name": n, "careers_url": _LI} for n in ("A Ltd", "B Ltd", "C Ltd")]
    E = _expand_env(tmp_path, monkeypatch, queue)
    monkeypatch.setenv("LLM_RESOLVE_CAP", "1")
    calls = _llm_stub(monkeypatch, {"A Ltd": (False, None), "B Ltd": (False, None),
                                    "C Ltd": (True, None)})
    E.main()
    log = capsys.readouterr().out
    assert calls == ["A Ltd", "B Ltd", "C Ltd"], (
        "an evidence-free attempt consumed the call cap: %r" % (calls,))
    assert "dfer A Ltd (no-candidates" in log and "dfer C Ltd (llm-none" in log, log
    assert "deferred 3 (llm-none 1, no-candidates 2)" in log, log
    # positive control: a call IS charged
    E = _expand_env(tmp_path, monkeypatch, queue)
    monkeypatch.setenv("LLM_RESOLVE_CAP", "1")
    calls = _llm_stub(monkeypatch, {n: (True, None) for n in ("A Ltd", "B Ltd", "C Ltd")})
    E.main()
    assert calls == ["A Ltd"], calls
    assert "dfer B Ltd (cap" in capsys.readouterr().out


def test_auto_expand_rereads_the_registry_before_every_append(tmp_path, monkeypatch):
    """Kills `expand-dupe-guard-drop`. `have` was computed once before a multi-minute
    loop; a concurrent writer that added the same name mid-run got a twin row."""
    from pipeline import identity_gate as G
    E = _expand_env(tmp_path, monkeypatch, [{"name": "Fiverr", "careers_url": "https://www.fiverr.com/jobs"}])
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)

    def _resolve(name, url):
        with open(tmp_path / "companies.csv", "a", encoding="utf-8", newline="") as fh:
            fh.write("Fiverr,greenhouse,fiverr,%s,true,added by another writer mid-run\n" % _FIVERR)
        return ("ats", ("Fiverr", "greenhouse", "fiverr", _FIVERR, 40, 12))
    monkeypatch.setattr(E, "resolve", _resolve)
    E.main()
    with open(tmp_path / "companies.csv", encoding="utf-8") as fh:
        names = [r.split(",")[0] for r in fh.read().splitlines()[1:]]
    assert names.count("Fiverr") == 1, "a twin row was appended: %r" % (names,)


def test_resolve_llm_does_not_ask_claude_without_a_reachable_page(monkeypatch):
    """Kills `llm-evidence-free-asks`. With an aggregator seed and SerpApi at 0 the
    evidence was the literal `(no pages reachable)` and the model was asked anyway --
    0 of 50 shots resolved over five runs."""
    import resolve_llm as L
    monkeypatch.setattr(L, "_fetch_html", lambda u, timeout=25, cap=300_000: (u, ""))
    monkeypatch.setattr(L, "_search_candidates", lambda name, limit=5: ["https://x.example/careers"])

    def _boom(prompt, timeout=120):
        raise AssertionError("claude was asked with no page in hand")
    monkeypatch.setattr(L, "_ask_claude", _boom)
    assert L.resolve_llm("X Ltd", _LI) is None
    assert L.LAST["asked"] is False and L.LAST["pages"] == 0, L.LAST
    # positive control: one readable page -> the model IS asked
    monkeypatch.setattr(L, "_fetch_html", lambda u, timeout=25, cap=300_000: (u, "<html><title>X careers</title></html>"))
    monkeypatch.setattr(L, "_ask_claude", lambda prompt, timeout=120: {"platform": "unknown"})
    assert L.resolve_llm("X Ltd", _LI) is None
    assert L.LAST["asked"] is True and L.LAST["pages"] == 1, L.LAST


def test_resolve_llm_search_ladder_uses_ddg_and_caps_the_unlocker(monkeypatch):
    """Kills `llm-ddg-rung-drop` and `llm-bd-cap-default`. The same ladder
    `audit_empty_rows.serp` got on 2026-08-23; the paid rung has its OWN counter (the
    `deep_validate` one is per process with a 150 default) and defaults to 5 per run."""
    import deep_validate as D
    import resolve_llm as L
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    monkeypatch.setattr(D, "ddg", lambda name, limit=4: ["https://www.x.example/careers", _LI])
    monkeypatch.setattr(D, "google_via_unlocker", lambda name, limit=4: (_ for _ in ()).throw(AssertionError("paid rung used while DDG answered")))
    assert L._search_candidates("X Ltd") == ["https://www.x.example/careers"], "DDG rung missing or aggregator leak"

    paid = []
    monkeypatch.setattr(D, "ddg", lambda name, limit=4: [])
    monkeypatch.setattr(D, "google_via_unlocker", lambda name, limit=4: paid.append(name) or ["https://g.example/careers"])
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    monkeypatch.delenv("LLM_BD_SEARCH_CAP", raising=False)
    L._BD_OWN["used"] = 0
    got = [L._search_candidates("X Ltd") for _ in range(7)]
    assert len(paid) == 5, "the paid rung is not capped at 5 by default: %d calls" % len(paid)
    assert got[0] == ["https://g.example/careers"] and got[6] == []
    monkeypatch.setenv("LLM_BD_SEARCH_CAP", "0")
    L._BD_OWN["used"] = 0
    paid.clear()
    assert L._search_candidates("X Ltd") == [] and paid == [], "cap 0 must spend nothing"
    L._BD_OWN["used"] = 0


def test_auto_expand_clear_agg_urls_keeps_the_row_hunt_owned(tmp_path, monkeypatch):
    """Kills `expand-clear-token-drop`. The 28 rows buried under an aggregator shell are
    un-buried by blanking the address and stamping `url-cleared` -- a token in
    listing_hunt.HUNT_POOL and (since 2026-08-25) verdicts.TOKENS, so every re-check
    still owns the row and none re-tests the shell."""
    import auto_expand as E
    import listing_hunt as LH
    from pipeline.verdicts import in_pool
    p = _registry(tmp_path, [
        ["Houzz", "scrape", _LI, _LI, "false", "scanned; no open Israel roles now"],
        ["Loris", "scrape", "https://loris.ai/careers", "https://loris.ai/careers", "false",
         "listing-hunt 2026-08-20: no listing found"],
        ["Fiverr", "greenhouse", "fiverr", _FIVERR, "true", ""],
    ])
    before = p.read_text(encoding="utf-8")
    assert E.clear_agg_urls(apply=False, path=str(p)) == ["Houzz"]
    assert p.read_text(encoding="utf-8") == before, "a dry run wrote"
    assert E.clear_agg_urls(apply=True, path=str(p)) == ["Houzz"]
    out = _read(tmp_path)
    row = out["Houzz"]
    assert row[2] == "" and row[3] == "" and row[4] == "false", row
    assert "url-cleared" in row[5] and "scanned; no open Israel roles now" in row[5], row
    assert LH.in_hunt_pool(row) and in_pool(row[5]), "the un-buried row left a pool: %r" % row
    assert out["Loris"][3] == "https://loris.ai/careers" and out["Fiverr"][4] == "true", out


# ---------------------------------------------------------------------------------------
# tools/mutate.py, 2026-08-25 (docs/BACKLOG.md 170): the gate ran the whole suite per
# record and was cancelled at 45 min on every push. Now a derived subset runs first and the
# full suite only when the subset does not settle the record; a baseline run excludes
# tests red at HEAD from every verdict. These guards pin the parts that could quietly turn
# a KILLED into a false green (or a red test into a false killer).
# ---------------------------------------------------------------------------------------

def _mutate_module():
    import importlib.util
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("mutate_under_test",
                                                  os.path.join(root, "tools", "mutate.py"))
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    return M


def test_the_mutation_selector_keeps_every_documented_killer():
    """Every `Kills \`<id>\`` docstring names a record that exists, and that test is in
    the record's subset; and every record that must die behaviourally has at least one
    behavioural/direct test in its subset (else it could never resolve without the
    full-suite fallback, and a selector that misses killers is a slow gate, not a wrong
    one -- but it should be visible here rather than in a 45-minute CI log)."""
    M = _mutate_module()
    muts = M._load()
    by_id = {m["id"]: m for m in muts}
    kills = M._kills_map()
    assert kills, "no `Kills` docstrings found -- the convention has gone"
    missing = sorted(set(kills) - set(by_id))
    assert not missing, "docstrings name records that do not exist: %r" % missing
    for mid, tests in kills.items():
        subset = set(M.select_tests(M.ROOT, by_id[mid]))
        assert tests <= subset, "%s: documented killer(s) not selected: %r" % (mid, tests - subset)
    starved = []
    for m in muts:
        if not m.get("must_be_killed_by_behavioural", True):
            continue
        subset = M.select_tests(M.ROOT, m)
        if not any(M._classify_killer(M.ROOT, t) in ("behavioural", "direct") for t in subset):
            starved.append(m["id"])
    assert not starved, "records with no behavioural test in their subset: %r" % starved


def test_the_mutation_selector_sees_through_aliases_helpers_and_strings(tmp_path):
    """The linkage in this suite is mostly function-local imports, module-level aliases
    and `importlib.import_module("<tool>")` strings; a selector blind to any of them
    silently degrades to full-suite fallbacks."""
    M = _mutate_module()
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pipeline" / "identity_gate.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "crack_walled.py").write_text(
        "def f():\n    from pipeline import identity_gate\n    return identity_gate.X\n",
        encoding="utf-8")
    (tmp_path / "auto_expand.py").write_text("Y = 2\n", encoding="utf-8")
    (tmp_path / "unrelated.py").write_text("Z = 3\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("""
import importlib
import pytest
from pipeline import identity_gate as IG


def _helper():
    import crack_walled
    return crack_walled.f()


def test_alias():
    assert IG.X == 1


def test_helper():
    assert _helper() == 1


@pytest.mark.parametrize("tool", ["auto_expand"])
def test_string(tool):
    assert importlib.import_module(tool)


def test_unrelated():
    import unrelated
    assert unrelated.Z == 3
""", encoding="utf-8")
    root = str(tmp_path)
    sel = M.select_tests(root, {"id": "r1", "file": "pipeline/identity_gate.py"})
    assert sel == ["tests/test_x.py::test_alias", "tests/test_x.py::test_helper"], sel
    sel = M.select_tests(root, {"id": "r2", "file": "auto_expand.py"})
    assert sel == ["tests/test_x.py::test_string"], sel
    sel = M.select_tests(root, {"id": "r3", "file": "unrelated.py"})
    assert sel == ["tests/test_x.py::test_unrelated"], sel
    # a helper class's test_-method and a non-test_ function are not ids pytest collects
    (tests / "test_y.py").write_text("""
import unrelated
class Helper:
    def test_ghost(self):
        assert unrelated.Z
class TestReal:
    def test_real(self):
        assert unrelated.Z
def helper_not_a_test():
    return unrelated.Z
""", encoding="utf-8")
    M._SELECTOR_CACHE.clear()          # derived once per process; the tree changed here
    sel = M.select_tests(root, {"id": "r5", "file": "unrelated.py"})
    assert sel == ["tests/test_x.py::test_unrelated", "tests/test_y.py::TestReal::test_real"], sel
    assert M._collectable_ids(root) >= {"tests/test_y.py::TestReal::test_real"}
    assert not any("Helper" in i or "helper_not" in i for i in M._collectable_ids(root))
    # the optional `killers` hint is unioned in, never required
    sel = M.select_tests(root, {"id": "r4", "file": "auto_expand.py",
                                "killers": ["tests/test_x.py::test_alias"]})
    assert sel == ["tests/test_x.py::test_alias", "tests/test_x.py::test_string"], sel


def test_a_baseline_red_test_is_never_reported_as_a_killer(tmp_path):
    """A test red at HEAD (a scraper date flake was red all of 2026-08-25) would make every
    mutation look KILLED. It is deselected from every run AND subtracted from the parsed
    failures, so a mutant that only that test catches reads as GREEN (= survived)."""
    M = _mutate_module()
    red = {"tests/test_units.py::test_red"}
    out = "FAILED tests/test_units.py::test_red - AssertionError\n1 failed in 1.0s\n"
    assert M._verdict(1, out, red, str(tmp_path), True) is None
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_units.py").write_text(
        "def test_red():\n    assert 0\n\ndef test_real(tmp_path):\n    assert 0\n",
        encoding="utf-8")
    out2 = out + "FAILED tests/test_units.py::test_real - AssertionError\n"
    v = M._verdict(1, out2, red, str(tmp_path), True)
    assert v[0] == "KILLED" and v[2] == "tests/test_units.py::test_real" and v[1] == "behavioural", v
    argv = M._pytest_argv(["tests/test_units.py::test_real"], ["tests/test_units.py::test_red[p]"])
    assert "--deselect" in argv and "tests/test_units.py::test_red[p]" in argv, argv
    # exclusion is by FULL id: one red `[caseA]` retires that case only (wave-1 F4), and a
    # param with a space survives parsing (F5)
    red = {"tests/test_units.py::test_p[case a]"}
    out3 = ("FAILED tests/test_units.py::test_p[case a] - AssertionError\n"
            "FAILED tests/test_units.py::test_p[case b] - AssertionError\n")
    assert M._parse_failures(out3) == ["tests/test_units.py::test_p[case a]",
                                       "tests/test_units.py::test_p[case b]"]
    (tmp_path / "tests" / "test_units.py").write_text(
        "def test_p(tmp_path):\n    assert 0\n", encoding="utf-8")
    v = M._verdict(1, out3, red, str(tmp_path), True)
    assert v and v[0] == "KILLED" and v[2] == "tests/test_units.py::test_p", v
    only_red = "FAILED tests/test_units.py::test_p[case a] - AssertionError\n"
    assert M._verdict(1, only_red, red, str(tmp_path), True) is None, (
        "the red case itself counted as a killer (bare-name exclusion)")
    # a ghost id (rc 4, `ERROR: not found`) is UNSETTLED, never a kill (wave-1 F1)
    assert M._verdict(4, "ERROR: not found: tests/test_a.py::test_ghost\nno tests ran\n",
                      set(), str(tmp_path), True) is M.UNSETTLED
    assert M._verdict(1, "some crash text with no FAILED line\n", set(), str(tmp_path), True) is M.UNSETTLED


def test_the_full_suite_runs_when_the_subset_does_not_settle_the_record(tmp_path, monkeypatch):
    """The subset may only END a record with a satisfying KILLED. Green, empty, or a
    static-only kill must fall back to the whole suite, exactly as the gate always ran --
    that is what keeps the verdict semantics identical to the single-run version."""
    M = _mutate_module()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_units.py").write_text(
        "def test_beh(tmp_path):\n    pass\n\ndef test_static():\n    import inspect\n"
        "    ast.parse('x')\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("GATE = True\n", encoding="utf-8")

    def _fake_archive(dest):
        import shutil as _sh
        _sh.copytree(str(tmp_path), dest, dirs_exist_ok=True)
    monkeypatch.setattr(M, "_archive", _fake_archive)
    monkeypatch.setattr(M, "select_tests", lambda root, mut, tests_dir=None: ["tests/test_units.py::test_beh"])
    calls = []

    def _runner(script):
        def _run(work, node_ids, deselect):
            calls.append(list(node_ids))
            return script[len(calls) - 1]
        return _run
    mut = {"id": "m", "file": "mod.py", "find": "GATE = True", "replace": "GATE = False"}
    beh = (1, "FAILED tests/test_units.py::test_beh - AssertionError\n")
    static = (1, "FAILED tests/test_units.py::test_static - AssertionError\n")
    green = (0, "1 passed\n")

    calls.clear(); monkeypatch.setattr(M, "_run", _runner([green, beh]))
    r = M.run_one(mut, str(tmp_path / "w1"))
    assert r["status"] == "KILLED" and r["mode"] == "fallback:green" and len(calls) == 2 and calls[1] == [], (r, calls)

    calls.clear(); monkeypatch.setattr(M, "_run", _runner([static, beh]))
    r = M.run_one(mut, str(tmp_path / "w2"))
    assert r["status"] == "KILLED" and r["mode"] == "fallback:static-only" and len(calls) == 2, (r, calls)

    calls.clear(); monkeypatch.setattr(M, "_run", _runner([beh]))
    r = M.run_one(mut, str(tmp_path / "w3"))
    assert r["status"] == "KILLED" and r["mode"] == "subset" and len(calls) == 1, (r, calls)

    calls.clear(); monkeypatch.setattr(M, "_run", _runner([green, green]))
    r = M.run_one(mut, str(tmp_path / "w4"))
    assert r["status"] == "FAIL" and "SURVIVED" in r["detail"] and len(calls) == 2, (r, calls)

    calls.clear(); monkeypatch.setattr(M, "_run", _runner([static, static]))
    r = M.run_one(mut, str(tmp_path / "w5"))
    assert r["status"] == "FAIL" and "ONLY by source-text" in r["detail"], r

    # wave-1 F1: a subset pytest could not run (rc 4) falls back; a full suite it could not
    # run is a harness FAIL, never a kill
    ghost = (4, "ERROR: not found: tests/test_units.py::test_beh\nno tests ran in 0.01s\n")
    calls.clear(); monkeypatch.setattr(M, "_run", _runner([ghost, beh]))
    r = M.run_one(mut, str(tmp_path / "w6"))
    assert r["status"] == "KILLED" and r["mode"] == "fallback:unsettled" and len(calls) == 2, r
    calls.clear(); monkeypatch.setattr(M, "_run", _runner([ghost, ghost]))
    r = M.run_one(mut, str(tmp_path / "w7"))
    assert r["status"] == "FAIL" and "did not judge" in r["detail"], r
    # a `killers` id the archive cannot collect is a loud catalogue error
    calls.clear(); monkeypatch.setattr(M, "_run", _runner([beh]))
    r = M.run_one({**mut, "killers": ["tests/test_units.py::test_nope"]}, str(tmp_path / "w8"))
    assert r["status"] == "FAIL" and "archive has not" in r["detail"] and calls == [], r
    # and a selected id that only the WORKING TREE has is dropped before pytest sees it
    calls.clear(); monkeypatch.setattr(M, "_run", _runner([beh]))
    monkeypatch.setattr(M, "select_tests", lambda root, mut, tests_dir=None: [
        "tests/test_units.py::test_beh", "tests/test_units.py::test_only_in_worktree"])
    r = M.run_one(mut, str(tmp_path / "w9"))
    assert r["status"] == "KILLED" and calls == [["tests/test_units.py::test_beh"]], (r, calls)


def test_mutation_ids_are_unique_and_every_subset_fits_a_windows_command_line():
    """Ids key the per-mutant work dirs (parallel sweep); a duplicate would share one.
    And a subset's argv must stay under CreateProcess's 32 KiB on the dev machine."""
    M = _mutate_module()
    muts = M._load()
    ids = [m["id"] for m in muts]
    assert len(set(ids)) == len(ids), sorted({i for i in ids if ids.count(i) > 1})
    for m in muts:
        argv = M._pytest_argv(M.select_tests(M.ROOT, m))
        assert len(" ".join(argv)) < 30_000, m["id"]
    # the collapse rule itself -- measured WITH the deselects (wave-1 F6)
    many = ["tests/test_units.py::test_%d" % i for i in range(2000)] + ["tests/test_registry.py::test_a"]
    argv = M._pytest_argv(many)
    assert "tests/test_units.py" in argv and "tests/test_registry.py::test_a" in argv
    assert len(" ".join(argv)) < 30_000
    red = ["tests/test_units.py::test_red_%d[param-%d]" % (i, i) for i in range(40)]
    argv = M._pytest_argv(many, red)
    assert len(" ".join(argv)) <= M._ARGV_CAP and argv.count("--deselect") == 40, len(" ".join(argv))
    # 300 ids that fit alone but not with 40 deselects: the collapse must count both
    some = ["tests/test_units.py::test_%d" % i for i in range(700)]
    assert len(" ".join(M._pytest_argv(some))) <= M._ARGV_CAP
    assert len(" ".join(M._pytest_argv(some, red))) <= M._ARGV_CAP
    for m in muts:
        assert len(" ".join(M._pytest_argv(M.select_tests(M.ROOT, m), red))) < 30_000, m["id"]


def test_the_census_step_never_probes_the_ladder_it_cannot_see(monkeypatch, capsys):
    """`registry_health.py --census` runs in the digest's census step -- no Bright Data
    env, no Playwright -- and printed two permanently false `rung DOWN` lines at the top
    of the operator's report every morning (run 32813499709, 2026-08-25). The ladder is
    `--ladder`'s (listing-hunt.yml, the one job with the keys); the census prints the
    registry facts and the MAIL alarms only."""
    import sys
    import registry_health as RH
    for k in ("BRIGHTDATA_API_KEY", "BRIGHTDATA_ZONE", "SERPAPI_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("bd_rescue._load_secrets", lambda *a, **k: None)
    # BACKLOG 44: no key must not read as "key present"
    detail = RH.resources(live=False)["SerpApi"]["detail"]
    assert "no SERPAPI_KEY" in detail, detail
    rows = RH.read_rows()
    probed = []
    monkeypatch.setattr(RH, "resources", lambda live=False: probed.append(live) or {})
    RH._report(rows, ladder=False)
    out = capsys.readouterr().out
    assert probed == [], "the census report probed the ladder"
    assert "rung DOWN" not in out and "resolution ladder" not in out, out[-400:]
    assert "re-check ownership" in out
    # positive control: the default report still prints the ladder
    RH._report(rows)
    assert probed == [False] and "resolution ladder" in capsys.readouterr().out
    # BACKLOG 44: an unknown flag says so and exits 2 instead of printing the report
    monkeypatch.setattr(sys, "argv", ["registry_health.py", "--pools"])
    assert RH.main() == 2
    assert "unknown flag" in capsys.readouterr().out


def test_repair_extract_gap_counts_a_refused_row_once(tmp_path, monkeypatch, capsys):
    """BACKLOG 45: a row refused by a gate fell through to the `else` and was counted
    twice -- "1 activated, 6 still dark" over four rows is the log a human reads to
    decide whether the gate is too tight."""
    import sys
    import repair_extract_gap as G
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["NanoLock Security", "", "", "https://gen.wd1.myworkdayjobs.com/en-US/careers/",
         "false", "dark-triage 2026-01-01: extract-gap (356 role phrases after render)"],
        ["GoodCo", "", "", "https://www.goodco.com/careers/openings", "false",
         "dark-triage 2026-01-01: extract-gap (12 role phrases after render)"],
        ["Dark Ltd", "", "", "https://www.dark.example/careers", "false",
         "dark-triage 2026-01-01: extract-gap (3 role phrases after render)"],
    ])
    monkeypatch.setattr("scrape_universal.scrape", lambda name, url: (
        [] if name == "Dark Ltd" else [{"title": "Engineer", "location": "Tel Aviv"}]))
    monkeypatch.setattr(IG, "page_names_company", lambda name, url, html="": False)
    monkeypatch.setattr(sys, "argv", ["repair_extract_gap.py", "--apply"])
    G.main()
    out = capsys.readouterr().out
    assert "=== repair: 1 activated, 2 still dark ===" in out, out[-300:]


def test_the_extract_gap_repair_never_selects_a_terminal_row(tmp_path, monkeypatch):
    """Kills `extract-gap-terminal-drop`. `repair_extract_gap` ACTIVATES (19:00, thirty
    minutes before the hunt) and its selector had no terminal exclusion: on 2026-08-25,
    the day ten same-board twins were parked `alias-of`, it selected `GenCell Energy` --
    whose board works -- off the row's own extract-gap stamp. Re-activating an alias
    publishes every role twice."""
    import sys
    import repair_extract_gap as G
    import registry_health as RH
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["GenCell Energy", "scrape", "", "https://www.gencellprojects.com/jobs", "false",
         "dark-triage 2026-08-20: extract-gap (5 role phrases after render) | "
         "alias-of GenCell 2026-08-25: identical board URL"],
        ["GoodCo", "", "", "https://www.goodco.com/careers/openings", "false",
         "dark-triage 2026-01-01: extract-gap (12 role phrases after render)"],
    ])
    monkeypatch.setattr("scrape_universal.scrape",
                        lambda name, url: [{"title": "Engineer", "location": "Tel Aviv"}])
    monkeypatch.setattr(IG, "page_names_company", lambda name, url, html="": True)
    monkeypatch.setattr(sys, "argv", ["repair_extract_gap.py", "--apply"])
    G.main()
    out = _read(tmp_path)
    assert out["GenCell Energy"][4] == "false", "an alias-of row was re-activated: %r" % (out["GenCell Energy"],)
    assert out["GoodCo"][4] == "true", "positive control regressed: %r" % (out["GoodCo"],)
    # the ownership mirror IS the tool's predicate
    rows = RH.read_rows(str(tmp_path / "companies.csv"))
    assert [r[0] for r in RH.pools(rows)["repair_extract_gap (19:00 daily)"]] == [], rows


def test_the_resolver_asks_through_the_shared_seam_tool_less_and_structured(monkeypatch, tmp_path):
    """Kills `llm-resolver-model-drift`. `resolve_llm._ask_claude` was the last bare
    `claude -p` (default model, every tool on, `shell=True` on Windows, the repo as cwd,
    the answer regex-extracted) -- the shape the classifier lane measured at ~10x the cost
    and retired. It now goes through `pipeline/llm.py`, whose argv is pinned here."""
    import subprocess
    import resolve_llm as L
    from pipeline import llm
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(
            {"structured_output": {"platform": "greenhouse", "token": "fiverr",
                                   "api_url": _FIVERR, "careers_url": "", "reason": "x"}}), stderr="")
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(llm.shutil, "which", lambda x: "/usr/bin/claude")
    monkeypatch.delenv("LLM_RESOLVE_MODEL", raising=False)
    out = L._ask_claude("Company: Fiverr\nEvidence:\n...")
    assert out["platform"] == "greenhouse" and out["api_url"] == _FIVERR, out
    cmd = seen["cmd"]
    assert cmd[cmd.index("--model") + 1] == "sonnet", cmd
    assert cmd[cmd.index("--tools") + 1] == "" and "--json-schema" in cmd and "--system-prompt" in cmd
    schema = json.loads(cmd[cmd.index("--json-schema") + 1])
    assert set(schema["properties"]) == {"platform", "token", "api_url", "careers_url", "reason"}
    assert "unknown" in schema["properties"]["platform"]["enum"]
    assert seen["kw"].get("shell") is None and seen["kw"]["input"].startswith("Company: Fiverr")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert os.path.abspath(seen["kw"]["cwd"]) != os.path.abspath(root), "the repo must not be the cwd"
    # infrastructure reads as None and is recorded, never raised into auto_expand
    monkeypatch.setattr(llm.shutil, "which", lambda x: None)
    assert L._ask_claude("x") is None and L.LAST["error"].startswith("missing")


def test_llm_call_json_returns_the_structured_object_and_call_is_unchanged(monkeypatch):
    """`call_json` is a second reading of the one invocation; `call`'s verdict contract
    (YES/NO/None, models, seconds) must be byte-for-byte what the classifier rehearsed."""
    import subprocess
    from pipeline import llm
    env = {"structured_output": {"verdict": "YES", "reason": "3+ yrs"},
           "modelUsage": {"claude-sonnet-5": {"inputTokens": 500}, "claude-haiku-4-5": {"inputTokens": 20}}}
    monkeypatch.setattr(llm.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=json.dumps(env), stderr=""))
    monkeypatch.setattr(llm.shutil, "which", lambda x: "/usr/bin/claude")
    kw = dict(system="s", schema="{}", model="sonnet", timeout=5)
    assert llm.call_json("p", **kw) == {"verdict": "YES", "reason": "3+ yrs"}
    v = llm.call("p", **kw)
    assert v["verdict"] == "YES" and v["reason"] == "3+ yrs" and v["models"] == ["claude-sonnet-5"]
    monkeypatch.setattr(llm.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout="not json at all", stderr=""))
    assert llm.call_json("p", **kw) is None
    assert llm.call("p", **kw)["verdict"] is None
    monkeypatch.setattr(llm.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, stdout=json.dumps({"is_error": True, "api_error_status": 401, "result": "Failed to authenticate"}), stderr=""))
    import pytest
    with pytest.raises(llm.LLMUnavailable) as ei:
        llm.call_json("p", **kw)
    assert ei.value.kind == "auth"


def test_both_writer_detectors_are_one_rule_and_see_the_evasive_shapes(tmp_path):
    """Wave-1 F7: `fr[3] = "" ; fr[3] += url`, `fr[3:4] = [url]`, `fr.__setitem__(3, url)`
    and `fr[4] = flag` were invisible to both detectors, so such a module was no "registry
    writer" and needed no gate and no mutations. One rule now, exercised here shape by
    shape, and the two enumerations must agree module for module."""
    import glob
    M = _mutate_module()
    cases = {
        'fr[3] = url': True, 'fr[3] = ""': False, 'fr[3] = "" or url': True,
        'fr[3] += url': True, 'fr[3:4] = [url]': True, 'fr.__setitem__(3, url)': True,
        'operator.setitem(fr, 4, "true")': True,
        'fr[4] = "true"': True, 'fr[4] = "false"': False, 'fr[4] = flag': True,
        'fr[4] = "tr" + "ue"': True, 'fr[4] += "true"': True,
        'fr[1], fr[2], fr[3] = plat, tok, api': True, 'fr[5] = note': False,
        'a[3] = 1': True,
    }
    for stmt, want in cases.items():
        tree = ast.parse(stmt)
        got = any(M._row_write(n) for n in ast.walk(tree))
        assert got == want, "%s -> %s" % (stmt, got)
    mine = {os.path.basename(p) for p in glob.glob(os.path.join(M.ROOT, "*.py"))
            if _registry_writes(ast.parse(open(p, encoding="utf-8").read()))}
    assert mine == set(M._registry_writers()), sorted(mine ^ set(M._registry_writers()))


def test_the_sunday_cross_validation_never_selects_a_terminal_or_active_row(tmp_path, monkeypatch):
    """Kills `validate-empty-terminal-drop`. `validate_empty` (Sun 04:00) ACTIVATES and
    selected on the bare substring `no open israel roles` over every row: on 2026-08-25
    it would have re-activated Primis Tech (`alias-of Primis`), kornit and `Tel Aviv`
    (`redundant`) with check_invariants green (wave-1 pools attacker)."""
    import sys
    import validate_empty as V
    import registry_health as RH
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Primis Tech", "scrape", "", "https://www.primis.tech/careers/", "false",
         "scanned; no open Israel roles now | alias-of Primis 2026-08-25: identical board URL"],
        ["Tel Aviv", "scrape", "", "https://jobs.secrettelaviv.com/", "false",
         "scanned; no open Israel roles now | redundant: not a company 2026-08-25"],
        ["Houzz", "scrape", "", "", "false", "scanned; no open Israel roles now | url-cleared 2026-08-25: x"],
        ["Fiverr", "greenhouse", "fiverr", _FIVERR, "true", "scanned; no open Israel roles now"],
        ["GoodCo", "scrape", "", "https://www.goodco.com/careers", "false",
         "scanned; no open Israel roles now"],
    ])
    checked = []

    def _check(name, url):
        checked.append(name)
        return ("promote", [name, "greenhouse", "fiverr", _FIVERR, "true", "cross-validated; 12/4 IL (was empty)"])
    monkeypatch.setattr(V, "check", _check)
    monkeypatch.setattr(G, "page_names_company", lambda name, url, html="": True)
    monkeypatch.setattr(sys, "argv", ["validate_empty.py"])
    rows = RH.read_rows(str(tmp_path / "companies.csv"))
    assert [r[0] for r in RH.pools(rows)["validate_empty (Sun 04:00)"]] == ["GoodCo"]
    V.main()
    out = _read(tmp_path)
    assert checked == ["GoodCo"], "selected a terminal, address-less or active row: %r" % (checked,)
    assert out["Primis Tech"][4] == "false" and out["Tel Aviv"][4] == "false", out
    assert out["GoodCo"][4] == "true", "positive control regressed: %r" % (out["GoodCo"],)


def test_bd_rescue_gives_up_after_three_tries_even_with_a_retry_segment_after_its_own(tmp_path, monkeypatch):
    """Kills `bd-tried-anchor`. The give-up counter was read with `x(\\d+)$`; since
    2026-08-25 `retry_unreachable` appends its segment after `bd-tried`, so the anchor
    read x1 forever: up to 5 paid unlocks x 9 rows every 8 days, permanently."""
    import sys
    import bd_rescue as B
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["A Ltd", "scrape", "", "https://a.example/careers", "false",
         "unreachable; could not scan | bd-tried 2026-08-01 x2 | retry 2026-08-20: still unreachable"],
        ["B Ltd", "scrape", "", "https://b.example/careers", "false",
         "unreachable; could not scan | bd-tried 2026-08-01 x3 | retry 2026-08-20: still unreachable"],
        ["C Ltd", "scrape", "", "https://c.example/careers", "false",
         "unreachable; could not scan | alias-of C 2026-08-25: identical board URL"],
    ])
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "x")
    monkeypatch.delenv("BD_LIMIT", raising=False)
    monkeypatch.setattr(B, "_load_secrets", lambda *a, **k: None)
    monkeypatch.setattr(B, "alt_urls", lambda url: [url])
    unlocked = []
    monkeypatch.setattr(B, "unlock", lambda u, timeout=90: unlocked.append(u) or "")
    monkeypatch.setattr(B.time, "sleep", lambda *a: None)
    monkeypatch.setattr(sys, "argv", ["bd_rescue.py"])
    B.main()
    out = _read(tmp_path)
    assert unlocked == ["https://a.example/careers"], (
        "x3 must be skipped and a terminal row never unlocked: %r" % (unlocked,))
    assert "bd-tried 20" in out["A Ltd"][5] and " x3" in out["A Ltd"][5], out["A Ltd"][5]
    assert "retry 2026-08-20: still unreachable" in out["A Ltd"][5]


def test_the_resolver_refuses_a_board_not_grounded_on_the_companys_own_page(monkeypatch):
    """Kills `llm-own-page-drop` and `llm-embed-vouch-drop`. The search ladder puts other
    companies' pages into the evidence and `_slug_matches` is a five-character prefix
    (any Comeet uid passes): `Similarweb` -> greenhouse `similartech` and `Sunflower
    Sustainable Investments` -> Claroty's Comeet `F2.004` both verified with real jobs
    (wave-1 write-path attacker). A proposal must be grounded on the company's OWN page."""
    import resolve_llm as L
    from pipeline import identity_gate as G
    monkeypatch.setattr(L, "fetch_company", lambda row: [{"title": "Analyst", "location": "Tel Aviv"}] * 3)
    monkeypatch.setattr(G, "page_names_company", lambda name, url, html="": True)
    st = "https://boards-api.greenhouse.io/v1/boards/similartech/jobs"
    # evidence from a search hit on the OTHER company's site / on the vendor's host only
    foreign = [("https://www.similartech.com/careers", "<html>similartech greenhouse</html>"),
               ("https://boards.greenhouse.io/similartech", "<html>similartech</html>")]
    import pytest
    with pytest.raises(ValueError):
        L._verify("Similarweb", "greenhouse", "similartech", st, pages=foreign)
    with pytest.raises(ValueError):
        L._verify("Sunflower Sustainable Investments", "comeet", "F2.004",
                  "https://www.comeet.com/careers-api/2.0/company/F2.004/positions?token=x",
                  pages=[("https://www.claroty.com/careers", "<html>comeet_uid F2.004</html>")])
    # positive controls: the token on the company's own page
    own = [("https://www.fiverr.com/jobs", "<html>boards.greenhouse.io/fiverr</html>")]
    assert L._verify("Fiverr", "greenhouse", "fiverr", _FIVERR, pages=own) == (3, 3)
    api49 = "https://www.comeet.com/careers-api/2.0/company/49.004/positions?token=x"
    assert L._verify("Upwind Security", "comeet", "49.004", api49,
                     pages=[("https://www.upwind.io/careers", "<html>comeet_uid: 49.004</html>")]) == (3, 3)
    # Comeet loads the uid at runtime: an own page whose static HTML lacks it is read in a
    # real browser (`_try_comeet_via_page`) and must yield the SAME uid -- and that read is
    # never attempted on a page that is not the company's own
    reads = []
    monkeypatch.setattr(L, "_try_comeet_via_page", lambda name, url: reads.append(url) or ("comeet", "49.004", api49))
    assert L._verify("Upwind Security", "comeet", "49.004", api49,
                     pages=[("https://www.upwind.io/careers", "<html>no uid in static html</html>"),
                            ("https://www.comeet.com/jobs/upwind/49.004", "<html>49.004</html>")]) == (3, 3)
    assert reads == ["https://www.upwind.io/careers"], reads
    reads.clear()
    with pytest.raises(ValueError):
        L._verify("Sunflower Sustainable Investments", "comeet", "49.004", api49,
                  pages=[("https://www.comeet.com/jobs/upwind/49.004", "<html>49.004</html>")])
    assert reads == [], "a vendor-host page must never be read as the company's own"
    # a held OWN page can still refuse a board it merely embeds (the Cogniteam/Riskified
    # shape): `similartech` passes the 5-char slug prefix AND sits on Similarweb's own page
    # as a stale embed -- only `embedded_board_ok` refuses it
    with pytest.raises(ValueError):
        L._verify("Similarweb", "greenhouse", "similartech", st,
                  pages=[("https://www.similarweb.com/careers", "<html>greenhouse.io/similartech</html>")])
    # and `_gather` feeds `_PAGES` so `resolve_llm` grounds without the caller threading it
    monkeypatch.setattr(L, "_search_candidates", lambda name, limit=5: [])
    monkeypatch.setattr(L, "_fetch_html", lambda u, timeout=25, cap=300_000: (u, "<html>boards.greenhouse.io/fiverr</html>"))
    L._gather("Fiverr", "https://www.fiverr.com/jobs")
    assert L._PAGES and L._PAGES[0][0] == "https://www.fiverr.com/jobs"


def test_auto_expand_charges_every_claude_call_and_pins_the_search_cap(tmp_path, monkeypatch, capsys):
    """Kills `expand-search-cap-drift` and `llm-calls-uncounted`. `resolve_llm` retries once
    with the verification error; the budget must count both calls (wave-1 F6)."""
    import resolve_llm as L
    queue = [{"name": "A%02d Ltd" % i, "careers_url": _LI} for i in range(45)]
    E = _expand_env(tmp_path, monkeypatch, queue)
    monkeypatch.delenv("AUTO_EXPAND_SEARCH_CAP", raising=False)
    monkeypatch.setenv("LLM_RESOLVE_CAP", "100")
    calls = []

    def _fake(name, url):
        calls.append(name)
        L.LAST.update(asked=False, pages=0, candidates=0, calls=0)
        return None
    monkeypatch.setattr(L, "resolve_llm", _fake)
    E.main()
    assert len(calls) == 40, "the default search cap is 40 per run: %d" % len(calls)
    # a two-call attempt costs two
    E = _expand_env(tmp_path, monkeypatch, queue[:3])
    monkeypatch.setenv("LLM_RESOLVE_CAP", "3")
    calls.clear()

    def _two(name, url):
        calls.append(name)
        L.LAST.update(asked=True, pages=1, candidates=1, calls=2)
        return None
    monkeypatch.setattr(L, "resolve_llm", _two)
    E.main()
    assert calls == ["A00 Ltd", "A01 Ltd"], "retries were not charged: %r" % (calls,)
    assert "dfer A02 Ltd (cap" in capsys.readouterr().out


def test_auto_expand_survives_a_malformed_rotation_key(tmp_path, monkeypatch):
    """Wave-1 F7: a non-string value in `cloud_state/auto_expand_seen.json` (a hand edit,
    a merge) raised TypeError inside the sort and killed the expand step."""
    queue = [{"name": n, "careers_url": _LI} for n in ("A Ltd", "B Ltd")]
    E = _expand_env(tmp_path, monkeypatch, queue, seen={"A Ltd": 20260825, "B Ltd": None})
    monkeypatch.setenv("LLM_RESOLVE_CAP", "1")
    monkeypatch.setenv("AUTO_EXPAND_SEARCH_CAP", "1")
    calls = _llm_stub(monkeypatch, {})
    E.main()
    assert calls == ["A Ltd"], calls


def test_clear_agg_urls_reads_every_segment_not_only_the_first(tmp_path):
    """Wave-1 filed note: `note.startswith` missed a buried row whose note led with a
    triage stamp (`Dun & Bradstreet (Israel) Ltd.`)."""
    import auto_expand as E
    p = _registry(tmp_path, [
        ["DnB", "scrape", _SH, _SH, "false",
         "dark-triage 2026-08-20: wrong-page | scanned; no open Israel roles now"],
    ])
    assert E.clear_agg_urls(apply=True, path=str(p)) == ["DnB"]
    assert _read(tmp_path)["DnB"][3] == ""


def test_the_hunts_link_picker_and_deep_validate_keep_their_own_schemas(monkeypatch):
    """Wave-2 I1 (INTRODUCED, fixed before push): `listing_hunt` and `deep_validate` import
    `resolve_llm._ask_claude` for their OWN prompts; hard-wiring the ATS schema into it
    made the hunt's `{"url"}` pick return "" every night with everything green."""
    import json as _json
    import listing_hunt as LH
    import deep_validate as DV
    import resolve_llm as L
    from pipeline import llm
    seen = []

    def fake(prompt, *, system, schema, model, timeout, cwd=None, effort="low"):
        seen.append(_json.loads(schema))
        return {"url": "https://x.example/jobs"} if "url" in _json.loads(schema)["properties"] \
            else {"platform": "unknown", "token": "", "api_url": "", "careers_url": "", "reason": "x"}
    monkeypatch.setattr(llm, "call_json", fake)
    assert L._ask_claude("p", system=LH._PICK_SYSTEM, schema=LH._PICK_SCHEMA)["url"].startswith("http")
    assert set(seen[-1]["properties"]) == {"url"}
    assert L._ask_claude("p")["platform"] == "unknown" and "platform" in seen[-1]["properties"]
    # the hunt's call site passes its own contract (source-level: the picker is inside a
    # Playwright loop no fixture drives)
    import inspect
    src = inspect.getsource(LH.hunt_one)
    assert "schema=_PICK_SCHEMA" in src and "system=_PICK_SYSTEM" in src
    src = inspect.getsource(DV)
    assert "schema=_SCHEMA" in src and "system=_SYSTEM" in src


# ---------------------------------------------------------------------------------------
# The Sunday chain, 2026-08-26 (BACKLOG 6, 38/164): one escalating pass, a committed key.
# ---------------------------------------------------------------------------------------

class _NoRenderer:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_sunday_audit_escalates_what_its_cheap_rung_left_dark(tmp_path, monkeypatch, capsys):
    """Kills `audit-deep-rung-drop`. The Saturday cron rendered the IDENTICAL 270 rows the
    Sunday audit had just read over plain HTTP. Now the render is the audit's second rung,
    over what the first left dark, through deep_validate's own validator and gates."""
    import sys
    import audit_empty_rows as A
    import deep_validate as DV
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Fiverr", "scrape", "", "https://www.fiverr.com/jobs", "false",
         "listing-hunt 2026-08-01: no listing found"],
        ["DarkCo", "scrape", "", "https://www.darkco.example/careers", "false",
         "listing-hunt 2026-08-01: no listing found"],
        ["Fresh Ltd", "scrape", "", "https://www.fresh.example/careers", "false",
         "listing-hunt 2026-08-01: no listing found | deep-validated 2026-08-20: no ATS detected (rendered)"],
    ])
    monkeypatch.setattr(A, "_load_secrets", lambda *a, **k: None)
    monkeypatch.setattr(A, "fetch", lambda u, timeout=20: "")          # the cheap rung finds nothing
    monkeypatch.setattr(A, "serp", lambda name, limit=5: [])
    monkeypatch.setattr(A.time, "sleep", lambda *a: None)
    monkeypatch.setattr(A, "_playwright_available", lambda: True)
    monkeypatch.setattr(DV, "Renderer", _NoRenderer)
    rendered = []

    def _validate(rend, name, seed):
        rendered.append(name)
        if name == "Fiverr":
            return ("recovered", "greenhouse", "fiverr", _FIVERR, 40, 12, "")
        return ("dark", None, None, None, 0, 0, "no ATS detected (rendered)")
    monkeypatch.setattr(DV, "validate_one", _validate)
    monkeypatch.setattr(DV.time, "sleep", lambda *a: None)
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    monkeypatch.setattr(sys, "argv", ["audit_empty_rows.py", "--apply"])
    monkeypatch.delenv("AUDIT_TIME_BUDGET_MIN", raising=False)
    monkeypatch.delenv("AUDIT_DEEP_BUDGET_MIN", raising=False)
    A.main()
    out = _read(tmp_path)
    assert rendered == ["Fiverr", "DarkCo"], (
        "the deep rung must render exactly the dark rows due a render (Fresh Ltd was "
        "deep-validated 6 days ago): %r" % (rendered,))
    assert out["Fiverr"][4] == "true" and "deep-verified 40/12 IL" in out["Fiverr"][5], out["Fiverr"]
    assert out["DarkCo"][4] == "false" and "deep-validated 20" in out["DarkCo"][5], out["DarkCo"]
    assert "deep-validated 2026-08-20" in out["Fresh Ltd"][5]
    # the rotation key is COMMITTED state now (BACKLOG 38/164), keyed by name
    seen = json.loads((tmp_path / "cloud_state" / "audit_seen.json").read_text(encoding="utf-8"))
    assert set(seen) >= {"Fiverr", "DarkCo", "Fresh Ltd"}
    assert not (tmp_path / "state").exists() or not (tmp_path / "state" / "audit_done.json").exists()
    log = capsys.readouterr().out
    assert "deep rung: 2 of 3 dark rows" in log, log[-500:]
    # no Playwright: the rung says so and renders nothing (no crash behind continue-on-error)
    monkeypatch.setattr(A, "_playwright_available", lambda: False)
    (tmp_path / "cloud_state" / "audit_seen.json").unlink()       # re-select the three rows
    rendered.clear()
    A.main()
    assert rendered == [] and "Playwright not importable" in capsys.readouterr().out


def test_the_audit_rotation_key_is_committed_state_and_persist_knows_it():
    """Kills `audit-seen-path-drift`. `state/` is gitignored, so in Actions the key was
    always {} and the 90-minute budget re-walked the same head of the list every Sunday."""
    import audit_empty_rows as A
    import persist_state as P
    assert A.AUDIT_SEEN.replace("\\", "/") == "cloud_state/audit_seen.json"
    assert "cloud_state/audit_seen.json" in P.STRATEGY
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wf = open(os.path.join(root, ".github", "workflows", "audit-coverage.yml"), encoding="utf-8").read()
    i = wf.index("--own")
    assert "cloud_state/audit_seen.json" in wf[i:i + 300], "audit-coverage.yml must --own the key"
    assert "AUDIT_DEEP_BUDGET_MIN" in wf and "BRIGHTDATA_API_KEY" in wf[wf.index("Re-audit parked rows"):]
    assert not os.path.exists(os.path.join(root, ".github", "workflows", "deep-validate.yml")), (
        "the Saturday cron is the audit's second rung now (BACKLOG 6)")


def test_a_dated_suspect_verdict_re_arms_the_hunt(monkeypatch):
    """Kills `hunt-suspect-drop`. BACKLOG 65: `empty-but-suspect` waited out the 14-day
    cooldown and no scheduled tool cleared it. A suspect newer than the hunt's last verdict
    is actionable; one the hunt already answered is not."""
    import listing_hunt as LH
    import validate_empty as V
    newer = "listing-hunt 2026-08-20: no listing found | empty-but-suspect 2026-08-24; 3 IL but the board is not this company's"
    older = "empty-but-suspect 2026-08-10; 3 IL | listing-hunt 2026-08-20: no listing found"
    assert LH.actionable_mode(newer), "a suspect newer than the hunt's verdict must re-arm the hunt"
    assert not LH.actionable_mode(older), "a suspect the hunt already answered must not"
    assert not LH.actionable_mode("listing-hunt 2026-08-20: no listing found")
    # the triage-mode rule it sits beside is untouched (positive controls)
    assert LH.actionable_mode("dark-triage 2026-08-24: url-dead | listing-hunt 2026-08-20: no listing found")
    assert not LH.actionable_mode("dark-triage 2026-08-24: page-empty")
    assert LH.HUNT_POOL.search(newer)                     # still the hunt's row
    assert "empty-but-suspect {TODAY}" in __import__("inspect").getsource(V.main)


def test_apply_resolved_vetoes_a_foreign_board_on_a_parked_row_too(tmp_path, monkeypatch):
    """Kills `apply-resolved-parked-scope`. BACKLOG 56: the veto was scoped to ACTIVE rows,
    so a parked row was re-pointed at a foreign address the hunt's fast path later
    activates on."""
    import sys
    import apply_resolved as AR
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    p = _registry(tmp_path, [
        ["Bancor", "scrape", "", "https://www.bancor.network/careers", "false", "no listing found"],
        ["Fiverr", "scrape", "", "https://www.fiverr.com/jobs", "false", "no listing found"],
    ])
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "resolved_configs.json").write_text(json.dumps({
        "Bancor": ["icims", "bancorpbank", _BANCORP],
        "Fiverr": ["greenhouse", "fiverr", _FIVERR]}), encoding="utf-8")
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    monkeypatch.setattr(sys, "argv", ["apply_resolved.py"])
    AR.main()
    out = _read(tmp_path)
    assert _BANCORP not in out["Bancor"][3], "a parked row was re-pointed at another company's board: %r" % (out["Bancor"],)
    assert out["Fiverr"][3] == _FIVERR, "positive control regressed: %r" % (out["Fiverr"],)


def test_bd_rescue_reads_the_unlockers_error_code_and_never_retries_a_policy_host(tmp_path, monkeypatch):
    """Kills `bd-policy-retry` and `bd-error-code-drop`. BACKLOG 110: a dead token (401), a
    host Bright Data's policy refuses (`policy_20140`, every myworkdayjobs page) and a walled
    page (`reject_block`) all read as "no HTML"."""
    import io
    import sys
    import urllib.error
    import urllib.request
    import bd_rescue as B

    class _Resp(io.BytesIO):
        def __init__(self, body, err):
            super().__init__(body)
            self.status = 200
            self.headers = {"x-brd-error-code": err} if err else {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "x")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "x")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=90: _Resp(b"<html>" + b"x" * 3000, ""))
    assert B.unlock("https://a.example") and B.LAST["error"] == ""
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=90: _Resp(b"wall", "reject_block"))
    assert B.unlock("https://a.example") == "" and B.LAST["error"] == "reject_block"
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=90: _Resp(b"", "policy_20140"))
    html, err = B.unlock_status("https://x.myworkdayjobs.com/y")
    assert html == "" and err == "policy_20140" and B._policy_closed(err)

    # main(): a policy refusal stamps `bd-policy` and the row is never unlocked again
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [["Wd Ltd", "scrape", "", "https://wd.myworkdayjobs.com/x", "false",
                          "unreachable; could not scan"]])
    monkeypatch.delenv("BD_LIMIT", raising=False)
    monkeypatch.setattr(B, "_load_secrets", lambda *a, **k: None)
    monkeypatch.setattr(B, "alt_urls", lambda url: [url, url + "/careers"])
    monkeypatch.setattr(B.time, "sleep", lambda *a: None)
    calls = []

    def _policy(u, timeout=90):
        calls.append(u)
        B.LAST.update(error="policy_20140", status=200)
        return ""
    monkeypatch.setattr(B, "unlock", _policy)
    monkeypatch.setattr(sys, "argv", ["bd_rescue.py"])
    B.main()
    row = _read(tmp_path)["Wd Ltd"]
    assert len(calls) == 1 and "bd-policy 20" in row[5] and "policy_20140" in row[5], (calls, row)
    calls.clear()
    B.main()
    assert calls == [], "a policy-closed host was unlocked again"
    # a dead token stops the whole pass without stamping anything
    _registry(tmp_path, [["A Ltd", "scrape", "", "https://a.example/careers", "false",
                          "unreachable; could not scan"]])
    def _dead(u, timeout=90):
        B.LAST.update(error="http-401", status=401)
        return ""
    monkeypatch.setattr(B, "unlock", _dead)
    import pytest
    with pytest.raises(SystemExit):
        B.main()
    assert _read(tmp_path)["A Ltd"][5] == "unreachable; could not scan"


def test_a_corrupt_scrape_cache_is_never_written_over(tmp_path, monkeypatch):
    """Kills `expand-corrupt-cache-write` and `retry-corrupt-cache-write`. BACKLOG 156: a
    momentarily unreadable scraped_cache.json became {} and was written back, deleting
    every company's cards."""
    import sys
    import auto_expand as E
    import retry_unreachable as R
    from pipeline import identity_gate as G
    E = _expand_env(tmp_path, monkeypatch, [{"name": "Fiverr", "careers_url": "https://www.fiverr.com/jobs"}])
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    monkeypatch.setattr(E, "resolve", lambda name, url: ("scrape", ([{"title": "x", "location": "Tel Aviv"}], url)))
    (tmp_path / "scraped_cache.json").write_text("{corrupt", encoding="utf-8")
    E.main()
    assert (tmp_path / "scraped_cache.json").read_text(encoding="utf-8") == "{corrupt"
    assert _read(tmp_path)["Fiverr"][4] == "true", "the registry row still lands"
    # positive control: a readable cache is written
    (tmp_path / "scraped_cache.json").write_text("{}", encoding="utf-8")
    E = _expand_env(tmp_path, monkeypatch, [{"name": "Fiverr2", "careers_url": "https://www.fiverr.com/jobs"}])
    monkeypatch.setattr(E, "resolve", lambda name, url: ("scrape", ([{"title": "x", "location": "Tel Aviv"}], url)))
    monkeypatch.setattr(G, "page_names_company", lambda n, u, html="": True)
    E.main()
    assert "Fiverr2" in json.loads((tmp_path / "scraped_cache.json").read_text(encoding="utf-8"))
    # retry_unreachable, same rule
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [["Fiverr", "", "", "https://www.fiverr.com/jobs", "false", "unreachable; could not scan"]])
    (tmp_path / "scraped_cache.json").write_text("[not an object", encoding="utf-8")
    monkeypatch.setattr(R, "attempt", lambda name, url: ("scrape", ([{"title": "x", "location": "Tel Aviv"}], url)))
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    monkeypatch.setattr(sys, "argv", ["retry_unreachable.py"])
    monkeypatch.delenv("RETRY_LIMIT", raising=False)
    R.main()
    assert (tmp_path / "scraped_cache.json").read_text(encoding="utf-8") == "[not an object"


def test_crack_walled_offers_the_native_api_for_a_cracked_eightfold_or_phenom_tenant():
    """Kills `crack-eightfold-api-drop`. The fetchers exist since 2026-08-24; a cracked
    tenant was still written as a nightly browser render (BACKLOG 77)."""
    import crack_walled as C
    m = C._HOST_PATTERNS["eightfold"].search("https://careers.qualcomm.com/api/pcsx/search?domain=qualcomm.com")
    urls = C.listing_urls("eightfold", m, "https://careers.qualcomm.com/careers")
    assert urls[0] == ("eightfold", "https://careers.qualcomm.com/api/pcsx/search?domain=qualcomm.com"), urls
    assert ("scrape", "https://careers.qualcomm.com/careers?location=Israel") in urls
    m = C._HOST_PATTERNS["eightfold"].search("https://paypal.eightfold.ai/careers")
    urls = C.listing_urls("eightfold", m, "https://www.paypal.com/careers")
    assert urls[0] == ("eightfold", "https://paypal.eightfold.ai/api/pcsx/search?domain=paypal.com"), urls
    m = C._HOST_PATTERNS["phenom"].search("https://careers.gehealthcare.com/widgets")
    urls = C.listing_urls("phenom", m, "https://careers.gehealthcare.com/")
    assert urls[0] == ("phenom", "https://careers.gehealthcare.com/widgets"), urls
    # the API candidate is verified through the production fetcher and returned as cracked-api
    import inspect
    src = inspect.getsource(C.crack_one)
    assert 'if kind in ("oraclehcm", "eightfold", "phenom"):' in src


def test_auto_expand_turns_a_linkedin_slug_into_the_companys_own_seed(tmp_path, monkeypatch):
    """Kills `expand-slug-seed-drop`. 399 of 1,544 queue entries carry the LinkedIn slug the
    bridge writes; it was never read (BACKLOG 178). A slug that resolves to the company's own
    site is a tier-1 seed; one that does not leaves the name an aggregator seed."""
    from pipeline import identity_gate as G
    E = _expand_env(tmp_path, monkeypatch, [
        {"name": "Fiverr", "careers_url": _LI, "slug": "fiverr"},
        {"name": "Nope Ltd", "careers_url": _LI, "slug": "nope-ltd"},
    ])
    monkeypatch.setattr(G, "page_names_company", _names_only_fiverr)
    asked = []
    monkeypatch.setattr(E, "_site_from_slug", lambda slug, timeout=8: asked.append(slug) or ("https://www.fiverr.com/" if slug == "fiverr" else ""))
    # OFF by default: the guest page carries no website link and the GET costs discovery's
    # LinkedIn budget -- nothing is asked unless the operator enables it
    monkeypatch.delenv("AUTO_EXPAND_SLUG_SEED", raising=False)
    calls0 = _llm_stub(monkeypatch, {})
    E.main()
    assert asked == [] and calls0 == ["Fiverr", "Nope Ltd"], (asked, calls0)
    E = _expand_env(tmp_path, monkeypatch, [
        {"name": "Fiverr", "careers_url": _LI, "slug": "fiverr"},
        {"name": "Nope Ltd", "careers_url": _LI, "slug": "nope-ltd"},
    ])
    monkeypatch.setenv("AUTO_EXPAND_SLUG_SEED", "1")
    monkeypatch.setattr(E, "_site_from_slug", lambda slug, timeout=8: "https://www.fiverr.com/" if slug == "fiverr" else "")
    rendered = []

    def _resolve(name, url):
        rendered.append((name, url))
        return ("ats", ("Fiverr", "greenhouse", "fiverr", _FIVERR, 40, 12))
    monkeypatch.setattr(E, "resolve", _resolve)
    calls = _llm_stub(monkeypatch, {})
    E.main()
    out = _read(tmp_path)
    assert rendered == [("Fiverr", "https://www.fiverr.com/")], rendered
    assert out["Fiverr"][4] == "true" and "Nope Ltd" not in out
    assert calls == ["Nope Ltd"], calls
    # the slug parser itself: a real about-page shape, and an aggregator link is refused
    html = '<a data-tracking-control-name="about_website" href="https://www.fiverr.com/?trk=x">'
    monkeypatch.setattr(E, "_LI_SITE", E._LI_SITE)
    assert E._LI_SITE.search(html).group(1) == "https://www.fiverr.com/"
    assert E._site_from_slug("has space") == ""


# ---------------------------------------------------------------------------------------
# Durable pools, 2026-08-26 (BACKLOG 53, 197, 27, 72, 190): a pool keys on row FACTS, not
# on a token inside another tool's segment; a terminal segment is never evicted.
# ---------------------------------------------------------------------------------------

def test_the_probe_pool_survives_the_hunts_own_verdict():
    """Kills `probe-pool-http-remove`, `probe-pool-aggregator-remove`,
    `probe-pool-terminal-remove`. The old selector stood on `monitored candidate` inside
    listing_hunt's own segment, which its next verdict deletes: 127 -> 20 in one simulated
    all-failing night."""
    import probe_candidates as PC
    from pipeline.notes import replace_own
    row = ["X Ltd", "scrape", "", "https://www.x.example/careers", "false",
           "listing-hunt 2026-08-20: no IL listing; monitored candidate"]
    assert PC.in_probe_pool(row)
    row[5] = replace_own(row[5], "listing-hunt", "listing-hunt 2026-08-26: no listing found")
    assert PC.in_probe_pool(row), "the hunt's own re-verdict must not evict the probe's row"
    assert not PC.in_probe_pool(["X Ltd", "scrape", "", "", "false", "url-cleared 2026-08-25: x"]), "nothing to probe"
    assert not PC.in_probe_pool(["X Ltd", "scrape", "", "https://il.linkedin.com/jobs/view/1", "false", "scanned; no open"]), "a posting is not a candidate page"
    assert not PC.in_probe_pool(["X Ltd", "scrape", "", "https://www.x.example/careers", "false", "alias-of X 2026-08-25: twin"]), "terminal"
    assert not PC.in_probe_pool(["Experis Israel", "scrape", "", "https://www.experis.example/careers", "false", "no listing found"]), "an agency by NAME"
    assert not PC.in_probe_pool(["X Ltd", "scrape", "", "https://www.x.example/careers", "true", ""]), "active rows are not candidates"
    assert not hasattr(PC, "PROBE_POOL"), "the token regex is gone; the row's address is the pool"


def test_the_terminal_test_asks_the_name_and_word_bounds_recruiter():
    """Kills `recruiter-boundary-remove` and `terminal-row-name-remove` (BACKLOG 72)."""
    from pipeline.verdicts import is_terminal, is_terminal_row
    assert not is_terminal("listing-hunt 2026-08-20: no IL listing via careers.smartrecruiters.com/Wix2"), (
        "`SmartRecruiters` in a note is not a recruiter verdict")
    assert is_terminal("recruiter (staffing agency)") and is_terminal("alias-of X 2026-08-25")
    assert is_terminal_row(["Experis Israel", "scrape", "", "https://x", "false", "no listing found"]), "an agency by name"
    assert not is_terminal_row(["Fiverr", "scrape", "", "https://x", "false", "no listing found"])
    assert is_terminal_row(["Fiverr", "scrape", "", "https://x", "false", "defunct: gone"])


def test_a_terminal_segment_is_never_evicted_by_append_or_by_the_merge():
    """Kills `terminal-keep-remove` and `merge-keep-remove`. 19 parked rows carried a
    terminal token that was not the newest segment on a note > 150 chars; one or two more
    routine stamps evicted the alias-of that kept them out of every activating pool."""
    from pipeline.notes import append
    import merge_csv_rows as M
    base = "alias-of Kornit Digital 2026-08-25: identical board URL (BACKLOG 133)"
    n = base
    for i in range(8):
        n = append(n, f"dark-triage 2026-09-0{i + 1}: wrong-page (a long reason that pushes the cell toward the cap, night {i})")
    assert "alias-of Kornit Digital" in n and len(n) <= 220, n
    assert n.startswith("alias-of"), "the protected segment keeps its place; the newest fits or is cut"
    # ...and so is the crack pool's membership fact (BACKLOG 27; the 14-night rehearsal
    # lost 6 crack rows on night one before this)
    n3 = "deep-validated 2026-08-21: unsupported ATS icims.com"
    for i in range(8):
        n3 = append(n3, f"listing-hunt 2026-09-0{i + 1}: no listing found (" + "r" * 60 + ")")
    assert "unsupported ATS icims.com" in n3 and len(n3) <= 220, n3
    # positive control: an unprotected old segment still goes first (`dark-triage <mode>`
    # is protected too since 2026-08-26 -- the extract-gap pool's fact -- so use two
    # unprotected ones)
    n2 = append("listing-hunt 2026-08-01: no listing found | crack-walled 2026-08-02: nocapture", "y" * 200)
    assert "listing-hunt 2026-08-01" not in n2 and n2.endswith("y" * 200)
    # the conflict merge trims from theirs' TAIL -- and the terminal segment is theirs'
    # tail here (ours never carried it): it must survive the trim all the same
    ours = "dark-triage 2026-09-01: wrong-page (" + "z" * 80 + ") | repair 2026-09-01: " + "q" * 80
    theirs = base
    merged = M._merge_notes(theirs, ours, cap=220)
    assert "alias-of Kornit Digital" in merged and len(merged) <= 220, merged
    assert "dark-triage 2026-09-01" in merged, "ours' newest verdict still wins its place"


def test_the_0230_chain_has_one_selector_that_the_mirror_imports(tmp_path, monkeypatch):
    """Kills `retry-pool-terminal-remove` and `retry-pool-narrow` (BACKLOG 190)."""
    import retry_unreachable as R
    import registry_health as RH
    p = R.in_retry_pool
    assert p(["A", "scrape", "", "https://a.example/careers", "false", "unreachable; could not scan"])
    assert p(["A", "scrape", "", "https://a.example/careers", "false",
              "listing-hunt 2026-08-20: no IL listing | bd-tried 2026-08-25 x1 | retry 2026-08-25: still unreachable"]), (
        "the token mid-note must select")
    assert not p(["A", "scrape", "", "https://a.example/careers", "false", "unreachable; could not scan | alias-of B 2026-08-25: twin"])
    assert not p(["A", "scrape", "", "", "false", "unreachable; could not scan"]), "nothing to retry without an address"
    assert not p(["A", "scrape", "", "https://a.example/careers", "false", "listing-hunt 2026-08-20: host unreachableXYZ"]), "a word, not a substring"
    rows = [["A", "scrape", "", "https://a.example/careers", "false", "unreachable; could not scan"],
            ["B", "scrape", "", "https://b.example/careers", "false", "no listing found"]]
    pools = RH.pools(rows)
    assert [r[0] for r in pools["retry_unreachable + bd_rescue (02:30 daily)"]] == ["A"]
    lines = []
    assert RH.explain("A", rows, out=lines.append) == 0
    assert any("retry_unreachable + bd_rescue" in ln and "True" in ln for ln in lines)


def test_the_sunday_cross_validation_is_a_fact_pool_staged_behind_the_probe_signals(tmp_path, monkeypatch):
    """Kills `validate-empty-walled-remove` (BACKLOG 197). Token arm today; the probe's
    own baseline is the durable arm, behind VALIDATE_EMPTY_SIGNALS=1 until one Sunday's
    log, because this pool activates."""
    import validate_empty as V
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cloud_state").mkdir()
    (tmp_path / "cloud_state" / "candidate_probe.json").write_text('{"Sig Ltd": {"sig": 3, "il": 1, "last": "2026-08-25"}}', encoding="utf-8")
    monkeypatch.delenv("VALIDATE_EMPTY_SIGNALS", raising=False)
    tok = ["Tok Ltd", "scrape", "", "https://www.tok.example/careers", "false", "scanned; no open Israel roles now"]
    sig = ["Sig Ltd", "scrape", "", "https://www.sig.example/careers", "false", "listing-hunt 2026-08-20: no listing found"]
    wd = ["Wd Ltd", "scrape", "", "https://x.wd1.myworkdayjobs.com/careers", "false", "scanned; no open Israel roles now"]
    assert V.in_validate_empty_pool(tok) and not V.in_validate_empty_pool(sig) and not V.in_validate_empty_pool(wd)
    monkeypatch.setenv("VALIDATE_EMPTY_SIGNALS", "1")
    assert V.in_validate_empty_pool(sig), "the probe saw signals on this page: durable membership"
    # `ever` survives a later probe that sees nothing (set once, never cleared)
    (tmp_path / "cloud_state" / "candidate_probe.json").write_text('{"Sig Ltd": {"sig": 0, "il": 0, "ever": true, "last": "2026-08-26"}}', encoding="utf-8")
    assert V.in_validate_empty_pool(sig), "a quiet night must not erase what the probe once saw"
    import probe_candidates as PC
    import sys
    _registry(tmp_path, [sig])
    monkeypatch.setattr(PC, "probe", lambda url: {"sig": 0, "il": 0})
    monkeypatch.setattr(sys, "argv", ["probe_candidates.py", "--apply"])
    monkeypatch.delenv("PROBE_TIME_BUDGET_MIN", raising=False)
    PC.main()
    st = json.loads((tmp_path / "cloud_state" / "candidate_probe.json").read_text(encoding="utf-8"))
    assert st["Sig Ltd"]["ever"] is True and st["Sig Ltd"]["sig"] == 0, st
    assert not V.in_validate_empty_pool(["Nope", "scrape", "", "https://www.nope.example/careers", "false", "no listing found"])
    assert not V.in_validate_empty_pool(wd), "walled hosts stay crack_walled's"


def test_two_rehearsed_nights_keep_every_pool():
    """The 14-night claim (BACKLOG 52) has a harness now: `tests/rehearse_registry.py`
    drives every scheduled tool's real `main()` and note writers over a copy of the
    registry with the network forbidden. Two `worst` nights over 200 parked rows run here
    (~15 s); the full 14 run in tests.yml. It runs as a SUBPROCESS: the harness patches
    modules and the clock process-wide."""
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, os.path.join(root, "tests", "rehearse_registry.py"),
                        "--nights", "2", "--rows", "200", "--policy", "worst"],
                       capture_output=True, text=True, cwd=root, timeout=600)
    assert r.returncode == 0 and "rehearsal OK" in r.stdout, r.stdout[-1200:] + r.stderr[-400:]


# ---------------------------------------------------------------------------------------
# Batch 3 wave 1 (2026-08-26): the wake keeps the protected facts, the wake is dated and
# consumed, append never slices, a pool that grows is reported, the census key is stable.
# ---------------------------------------------------------------------------------------

def test_append_never_slices_a_protected_segment_and_evicts_a_fact_before_cutting():
    """Kills `append-slice-restore` and `append-fact-evict`. Two protected segments
    filled the cell: the old code cut `dark-triage ...: <mode>` mid-word (silent) or left
    `crack-walled <date>: ` dangling (check F then BLOCKED the digest -- mixed seed 1,
    night 5)."""
    from pipeline.notes import append
    a = "deep-validated 2026-08-20: unsupported ATS icims.com (" + "x" * 60 + ")"
    b = "dark-triage 2026-08-23: blocked (" + "y" * 70 + ")"
    new = "crack-walled 2026-08-31: nocapture (ATS host not seen in render)"
    out = append(a + " | " + b, new)
    assert out == a + " | " + b, "two protected facts stay; the newcomer is dropped whole, nothing is cut"
    assert "crack-walled" not in out
    # terminal-only base: the newcomer is dropped whole, never a dangling `tool date: `
    t = "alias-of Kornit Digital 2026-08-25: identical board URL (BACKLOG 133) " + "z" * 130
    out2 = append(t, new)
    assert out2 == t[:220] and "crack-walled" not in out2
    import re
    assert not re.search(r"\d{4}-\d{2}-\d{2}:?\s*$", out2)


def test_the_wake_is_dated_keeps_the_triage_fact_and_the_hunt_consumes_it(monkeypatch):
    """Kills `wake-strips-triage`, `wake-undated`, `hunt-keeps-wake`,
    `page-empty-ignores-wake`. 39/39 extract-gap rows and 115/228 triage rows left their
    pool on the first wake; `probe-woken` then lived forever."""
    import re
    import probe_candidates as PC
    import listing_hunt as LH
    import triage_dark as TD
    import repair_extract_gap as RG
    note = ("listing-hunt 2026-08-20: no IL listing; monitored candidate | "
            "dark-triage 2026-08-24: extract-gap (2 role phrases after render)")
    woken = PC._wake_note(note)
    assert re.search(r"probe-woken \d{4}-\d{2}-\d{2}: re-hunt pending$", woken), woken
    row = ["X", "scrape", "", "https://www.x.example/careers", "false", woken]
    assert TD.in_triage_pool(row) and RG.in_extract_gap_pool(row) and LH.in_hunt_pool(row)
    assert "listing-hunt" not in woken
    # page-empty yields to a wake at least as new as the stamp; not to an older one
    pe = "dark-triage 2026-08-24: page-empty (live page, 0 roles)"
    assert LH._triaged_page_empty(pe)
    assert not LH._triaged_page_empty(pe + " | probe-woken 2026-08-25: re-hunt pending")
    assert not LH._triaged_page_empty(pe + " | probe-woken: re-hunt pending"), "legacy undated = fresh once"
    assert LH._triaged_page_empty("probe-woken 2026-08-01: re-hunt pending | " + pe)
    # the hunt's write consumes the wake; a second wake does not stack
    consumed = LH._consume_wake(woken)
    assert "probe-woken" not in consumed and "dark-triage 2026-08-24: extract-gap" in consumed
    assert PC._wake_note(woken).count("probe-woken") == 1
    src = open(LH.__file__, encoding="utf-8").read()
    assert src.count('_consume_wake(fr[5]), "listing-hunt"') == 5, "every hunt stamp consumes the wake"


def test_a_pool_that_grows_by_half_is_a_mail_line_and_the_deep_key_is_stable():
    """Kills `growth-line-drop` and `deep-key-rename`. 127 -> 228 re-baselined silently;
    `deep_validate` -> `deep_validate rung` skipped that floor until the next census."""
    import registry_health as RH
    rows = [["A%d" % i, "scrape", "", "https://a%d.example/careers" % i, "false", "no listing found"]
            for i in range(30)]
    prev = {RH._POOLS_KEY: {"probe_candidates": 12, "listing_hunt": 30, "deep_validate": 4}}
    lines = RH.pool_growth(rows, prev=prev)
    assert any("probe_candidates 12 -> 30" in x for x in lines), lines
    assert not any("listing_hunt" in x for x in lines)
    assert "deep_validate" in {k.split(" (")[0] for k in RH.pools(rows)}, "census key renamed"
    assert lines[0] in RH.alarms_state(rows, prev=prev)


def test_append_evicts_the_oldest_unprotected_first_and_a_dangling_mode_is_not_protected():
    """Kills `append-newest-first` and `protected-mode-empty`."""
    from pipeline.notes import append, _protected
    base = "listing-hunt 2026-08-01: no listing found | crack-walled 2026-08-02: nocapture (" + "q" * 60 + ")"
    out = append(base, "deep-validated 2026-08-03: x" + "w" * 60)
    assert "listing-hunt 2026-08-01" not in out and "crack-walled 2026-08-02" in out, out
    assert _protected("dark-triage 2026-08-22: page-empty") and not _protected("dark-triage 2026-08-22: "), (
        "a dangling mode must stay evictable")


def test_the_merge_trims_the_theirs_tail_then_a_fact_and_never_slices():
    """Kills `merge-trim-ours-head` and `merge-slice-restore`. The conflict path re-created
    `dark-triage <date>: page-empt` when only protected segments remained."""
    import re
    import merge_csv_rows as M
    ours = "deep-validated 2026-08-20: unsupported ATS phenom (" + "x" * 40 + ") | dark-triage 2026-09-01: page-empty (" + "y" * 60 + ")"
    theirs = "deep-validated 2026-08-20: unsupported ATS phenom (" + "x" * 40 + ") | listing-hunt 2026-09-02: no listing found (" + "z" * 60 + ")"
    merged = M._merge_notes(theirs, ours, cap=220)
    assert len(merged) <= 220 and merged.startswith("deep-validated 2026-08-20"), merged
    assert "dark-triage 2026-09-01: page-empty" in merged, "ours' protected fact stays; theirs' tail goes whole"
    assert not re.search(r"\d{4}-\d{2}-\d{2}:?\s*$", merged) and "page-empt" not in merged.replace("page-empty", "")
    # only PROTECTED segments left and still over the cap: theirs' tail goes WHOLE (the old
    # `[:cap]` would cut the `unsupported ATS` segment mid-word)
    t3 = ours + " | crack-walled 2026-09-03: unsupported ATS phenom (" + "u" * 40 + ")"
    m3 = M._merge_notes(t3, ours, cap=220)
    assert m3 == ours, m3
    # ours' own newest segment survives ahead of theirs' unique tail
    o2 = "alias-of X 2026-08-01: twin | listing-hunt 2026-09-01: own verdict (" + "a" * 100 + ")"
    t2 = "alias-of X 2026-08-01: twin | crack-walled 2026-09-01: theirs (" + "b" * 100 + ")"
    m2 = M._merge_notes(t2, o2, cap=220)
    assert "listing-hunt 2026-09-01" in m2 and "alias-of X" in m2, m2


def test_validate_empty_keys_on_each_of_its_own_facts_and_they_are_protected():
    """Kills `validate-empty-arm-and` and `protect-suspect-drop` (attacker 2, R4)."""
    import validate_empty as V
    from pipeline.notes import append
    row = lambda note: ["Enzymit", "scrape", "", "https://www.enzymit.example/careers", "false", note]
    assert V.in_validate_empty_pool(row("empty-but-suspect 2026-08-24; 2+ role-near-Israel mentions in HTML"))
    assert V.in_validate_empty_pool(row("cross-validated; 3/0 IL (was empty)"))
    n = "empty-but-suspect 2026-08-24; 2+ role-near-Israel mentions in HTML"
    for i in range(6):
        n = append(n, f"deep-validated 2026-09-0{i + 1}: no ATS detected (rendered; " + "r" * 80 + ")")
    assert "empty-but-suspect 2026-08-24" in n and V.in_validate_empty_pool(row(n)), n


def test_the_fact_pool_floor_blocks_at_fifty(tmp_path):
    """Kills `fact-floor-drift`: check E's fact floor is the probe pool's floor."""
    import csv
    import os
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    (tmp_path / "cloud_state").mkdir()
    def run(with_http):
        rows = [["company_name", "ats_platform", "token", "api_url", "active", "notes"]]
        rows += [[f"Live {i}", "greenhouse", f"live{i}", f"https://boards-api.greenhouse.io/v1/boards/live{i}/jobs", "true", ""] for i in range(60)]
        # 20 fact rows when `with_http` is off: under the floor of 50, above a drifted floor of 5
        rows += [[f"Parked {i}", "scrape", "", (f"https://www.p{i}.example/careers" if (with_http or i < 20) else ""), "false", "no listing found"] for i in range(60)]
        with open(tmp_path / "companies.csv", "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(rows)
        r = subprocess.run([sys.executable, os.path.join(root, "check_invariants.py")], cwd=tmp_path,
                           capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout + r.stderr
    rc_ok, out_ok = run(True)
    rc_bad, out_bad = run(False)
    assert "fact pool" not in out_ok, out_ok[-600:]
    assert rc_bad != 0 and "fact pool" in out_bad and "floor 50" in out_bad, out_bad[-600:]


def test_the_rehearsal_catches_a_cell_overwrite_and_bans_dns():
    """Kills `harness-retention-off` and `harness-dns-open`. The harness's own control: the
    classic overwrite (`fr[5] = seg`) must FAIL a worst night; DNS must not escape."""
    import os
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, REHEARSE_SELF_TEST="overwrite")
    r = subprocess.run([sys.executable, os.path.join(root, "tests", "rehearse_registry.py"),
                        "--nights", "1", "--rows", "120", "--policy", "worst"],
                       capture_output=True, text=True, cwd=root, timeout=600, env=env)
    assert r.returncode != 0 and "lost" in r.stdout, r.stdout[-800:] + r.stderr[-300:]
    code = ("import socket, sys; sys.path.insert(0, %r); import tests.rehearse_registry as R; R._forbid_sockets()\n"
            "try:\n    socket.gethostbyname('example.com'); print('ESCAPED')\nexcept Exception as e:\n    print('banned', type(e).__name__)") % root
    r2 = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root, timeout=120)
    assert "banned" in r2.stdout and "ESCAPED" not in r2.stdout, r2.stdout + r2.stderr


# ---------------------------------------------------------------------------------------
# Batch 4 (2026-08-26): the third state. "Cannot tell" is no longer spelled True.
# ---------------------------------------------------------------------------------------

def test_a_negative_declaration_forces_the_park():
    """Kills `facts-not-tenants-validate`: an ACTIVE row on a board it declares not its own
    is a validate() problem (declare, then park -- never both)."""
    from pipeline import identity_facts as F
    from pipeline import identity_gate as G
    from pipeline.company_identity import ATS_HOST
    rows = [["Bancor", "icims", "", "https://careers-bancorpbank.icims.com/jobs/search", "true", ""]]
    probs = F.validate(rows, ATS_HOST, G._plumbing)
    assert any("Bancor" in p and "ACTIVE" in p for p in probs), probs
    rows[0][4] = "false"
    assert not any("Bancor" in p for p in F.validate(rows, ATS_HOST, G._plumbing))
    # a token cannot be both
    import pytest as _pt
    orig = F.DECLARED["Bancor"]
    F.DECLARED["Bancor"] = {"tenants": ("bancorpbank",), "not_tenants": ("bancorpbank",), "why": "x http"}
    try:
        assert any("both" in p for p in F.validate(rows, ATS_HOST, G._plumbing))
    finally:
        F.DECLARED["Bancor"] = orig


def test_board_vouches_has_three_answers_and_never_spells_cannot_tell_as_true():
    """Kills `vouch-uid-true`, `vouch-none-false`, `vouch-near-drop` (BACKLOG 33/50)."""
    from pipeline import identity_gate as G
    gh = "https://boards-api.greenhouse.io/v1/boards/%s/jobs"
    assert G.board_vouches("Fiverr", "fiverr", gh % "fiverr") is True
    assert G.board_vouches("Momentis Surgical", "memic", gh % "memic") is True, "declared"
    assert G.board_vouches("Momentis Surgical", "other", gh % "other") is False, "declared row, other tenant"
    assert G.board_vouches("Ibex Medical Analytics", "ib1", "https://ib1.recruitee.com/api/offers/") is None
    assert G.board_vouches("Upwind Security", "49.004", "https://www.comeet.com/careers-api/2.0/company/49.004/positions?token=x") is None
    assert G.board_vouches("Cogniteam", "riskified", gh % "riskified") is False
    assert G.board_vouches("Riskified", "novartis/riskified", "https://novartis.wd3.myworkdayjobs.com/wday/cxs/novartis/riskified/jobs") is False
    assert G.board_vouches("Bancor", "", "https://careers-bancorpbank.icims.com/jobs/search") is False, "the negative reads the subdomain too"
    # a negative that would NEAR-MATCH the name is still refused by the two older gates
    # (kills `tenant-neg-drop`, `embed-neg-drop`: every recorded pair fails near-equality on
    # its own, so only a synthetic near-miss can tell the check from the string rule)
    from pipeline import identity_facts as F
    wd = "https://acmeinc.wd1.myworkdayjobs.com/wday/cxs/acmeinc/x/jobs"
    assert G.tenant_is_this_company("Acme", wd) and G.embedded_board_ok("Acme", "acmeinc", gh % "acmeinc")
    F._INDEX["acme"] = {"not_tenants": ("acmeinc",), "why": "test"}
    try:
        assert G.tenant_is_this_company("Acme", wd) is False
        assert G.embedded_board_ok("Acme", "acmeinc", gh % "acmeinc") is False
    finally:
        del F._INDEX["acme"]
    assert G.board_vouches("NVIDIA", "nvidia/NVIDIAExternalCareerSite", "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/x/jobs") is True
    assert G.board_vouches("Intelligems", "intelligems", "https://apply.workable.com/api/v1/widget/accounts/intelligems?details=true") is True
    assert G.board_vouches("SupPlant", "", "https://careers.workable.com/") is None, "all-plumbing host: cannot tell"
    assert G.board_vouches("Acme", "", "https://www.acme.example/careers") is True, "an ordinary host: is_foreign is the test there"
    assert G.board_vouches("FairFly", "", "https://fireflyspace.com/careers") is None, "a foreign domain cannot vouch"
    # scrape rows store the URL (or nothing) in column 2: the slug comes from the URL
    assert G.checkable_token("https:", "https://www.comeet.com/jobs/bridgewise/F9.009") == "bridgewise"
    assert G.checkable_token("", "https://api.lever.co/v0/postings/wiz?mode=json") == "wiz", "the tenant, not the platform"
    assert G.checkable_token("", "https://apply.workable.com/api/v3/widget/accounts/supplant?details=true") == "supplant"
    assert G.checkable_token("", "https://www.comeet.com/careers-api/2.0/company/87.00C/positions?token=x") == "87.00C"
    assert G.board_vouches("Sckipio", "", "https://www.comeet.com/careers-api/2.0/company/87.00C/positions?token=x") is False
    assert G.board_vouches("CyberArk", "paloaltonetworks", "") is None, "no address: nothing can vouch (was True)"
    assert G.board_vouches("Bridgewise", "https:", "https://www.comeet.com/jobs/bridgewise/F9.009") is True


def test_human_board_url_maps_every_registry_api_shape_and_never_an_endpoint(monkeypatch):
    """Kills `human-url-api-fallback` and `human-url-comeet-drop`."""
    from pipeline import identity_gate as G
    H = G.human_board_url
    assert H("https://boards-api.greenhouse.io/v1/boards/fiverr/jobs") == "https://job-boards.greenhouse.io/fiverr"
    assert H("https://api.ashbyhq.com/posting-api/job-board/deel") == "https://jobs.ashbyhq.com/deel"
    assert H("https://api.lever.co/v0/postings/logz?mode=json") == "https://jobs.lever.co/logz"
    assert H("https://api.eu.lever.co/v0/postings/x?mode=json") == "https://jobs.eu.lever.co/x"
    assert H("https://api.smartrecruiters.com/v1/companies/Wix2/postings") == "https://careers.smartrecruiters.com/Wix2"
    assert H("https://ib1.recruitee.com/api/offers/") == "https://ib1.recruitee.com/"
    assert H("https://mush.bamboohr.com/careers/list") == "https://mush.bamboohr.com/careers"
    assert H("https://any-do.breezy.hr/json") == "https://any-do.breezy.hr/"
    assert H("https://apply.workable.com/api/v1/widget/accounts/d-id?details=true") == "https://apply.workable.com/d-id/"
    assert H("https://www.comeet.com/jobs/upwind/49.004") == "https://www.comeet.com/jobs/upwind/49.004"
    assert H("https://www.acme.example/careers") == "https://www.acme.example/careers"
    assert H("https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/x/jobs") is None, "an unmapped endpoint is not a page"
    assert H("") is None
    # Comeet's API form: learned from the positions the endpoint returns, never guessed
    import pipeline.http as _http
    monkeypatch.setattr(_http, "get_json", lambda u, **k: [{"url_comeet_hosted_page": "https://www.comeet.com/jobs/upwind/49.004/Data-Analyst/AB.C12"}])
    assert G._comeet_human_url("https://www.comeet.com/careers-api/2.0/company/49.004/positions?token=x") == "https://www.comeet.com/jobs/upwind/49.004"
    assert H("https://www.comeet.com/careers-api/2.0/company/49.004/positions?token=x") == "https://www.comeet.com/jobs/upwind/49.004"
    monkeypatch.setattr(_http, "get_json", lambda u, **k: (_ for _ in ()).throw(OSError("down")))
    assert H("https://www.comeet.com/careers-api/2.0/company/49.004/positions?token=x") is None


def test_activation_verdict_names_its_refusals_and_defers_when_nothing_can_tell(monkeypatch):
    """Kills `activation-unverified-admit`, `activation-human-page-drop`,
    `activation-vouch-false-admit` (BACKLOG 33/37/50)."""
    from pipeline import identity_gate as G
    gh = "https://boards-api.greenhouse.io/v1/boards/%s/jobs"
    reads = []
    def fake_page(name, url, html=""):
        reads.append(url)
        if html:
            return ("Cogniteam" in html) if "cogniteam" in name.lower() else None
        return {"https://job-boards.greenhouse.io/ib1": None,
                "https://job-boards.greenhouse.io/panw": False,
                "https://job-boards.greenhouse.io/sevenai": True}.get(url)
    monkeypatch.setattr(G, "page_names_company", fake_page)
    V = G.activation_verdict
    assert V("Fiverr", gh % "fiverr", 0) == "empty"
    assert V("Fiverr", "https://www.fiverr.example/about-us/leadership", 3) == "not-listing"
    assert V("Fiverr", gh % "fiverr", 3, token="fiverr") == "ok" and not reads, "a vouching tenant needs no page"
    assert V("Cogniteam", gh % "riskified", 3, token="riskified") == "not-ours" and not reads, "a negative needs no page"
    assert V("CyberArk", gh % "panw", 5, token="panw") == "not-ours" and reads[-1] == "https://job-boards.greenhouse.io/panw", (
        "cannot tell -> the HUMAN board page decides, never the API endpoint")
    assert V("7AI", gh % "sevenai", 5, token="sevenai") == "ok"
    assert V("Ibex Medical Analytics", gh % "ib1", 5, token="ib1") == "unverified", "unreadable human page: deferred, not refused"
    monkeypatch.setattr(G, "_comeet_human_url", lambda u: None)
    assert V("Upwind Security", "https://www.comeet.com/careers-api/2.0/company/49.004/positions?token=x", 5, token="49.004") == "unverified"
    # a subdomain near-miss is "cannot tell" too (Oracle pod ids): the endpoint is the last resort
    reads.clear()
    assert V("onsemi", "https://hctz.fa.us2.oraclecloud.com/hcmRestApi/x", 5) == "unverified" and reads == ["https://hctz.fa.us2.oraclecloud.com/hcmRestApi/x"]
    # a held readable page decides both ways, before any of that
    assert V("Cogniteam", gh % "riskified", 3, html="<html>" + "Cogniteam careers " * 200 + "</html>", token="riskified") == "not-ours", (
        "a declared negative still refuses even when the held page names the company")
    assert V("Cogniteam", gh % "cogniteam", 3, html="<html>" + "Cogniteam careers " * 200 + "</html>", token="cogniteam") == "ok"
    assert G.activation_ok("Fiverr", gh % "fiverr", 3) is True and G.activation_ok("Ibex Medical Analytics", gh % "ib1", 5) is False
    assert G.write_verdict("Cogniteam", "https://job-boards.greenhouse.io/riskified", token="riskified") == "not-ours"
    assert G.write_verdict("Ibex Medical Analytics", "https://job-boards.greenhouse.io/ib1", token="ib1") == "unreadable"
    assert G.ok_to_write("7AI", "https://job-boards.greenhouse.io/sevenai") is True
    # the write gate reads the HUMAN page for an API endpoint it holds no html for
    # (kills `write-verdict-human-drop`, confirmation wave R4)
    reads.clear()
    assert G.write_verdict("7AI", gh % "sevenai", token="sevenai") == "ok" and reads[-1] == "https://job-boards.greenhouse.io/sevenai"
    # a malformed Comeet payload is "no page", never a crash (R5)
    import pipeline.http as _http
    monkeypatch.setattr(_http, "get_json", lambda u, **k: ["oops"])
    assert G._comeet_human_url("https://www.comeet.com/careers-api/2.0/company/49.004/positions?token=x") is None


def test_only_a_proven_refusal_is_stamped_not_this_companys_board(tmp_path, monkeypatch):
    """Kills `activation-unverified-stamp` (deep_validate), `crack-unreadable-stamp`
    (crack_walled), `validate-empty-unverified-stamp` (BACKLOG 37): an unreadable page
    writes no claim and the row's tokens survive."""
    import csv
    import deep_validate as D
    import crack_walled as C
    import validate_empty as V
    from pipeline import identity_gate as G
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(G, "page_names_company", lambda name, url, html="": None)
    monkeypatch.setattr(G, "_comeet_human_url", lambda u: None)
    # deep_validate: a recovered board nothing vouches for -> `unverified`, not `not this company's`
    rows = [["company_name", "ats_platform", "token", "api_url", "active", "notes"],
            ["Ibex Medical Analytics", "scrape", "", "https://www.ibex.example/careers", "false", "no listing found | dark-triage 2026-08-20: js-shell (x)"]]
    with open("companies.csv", "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    D._apply_verdict_to_file("Ibex Medical Analytics", "recovered", "recruitee", "ib1", "https://ib1.recruitee.com/api/offers/", 5, 2, "")
    out = [r for r in csv.reader(open("companies.csv", encoding="utf-8"))][1]
    assert out[4] == "false" and "not this company" not in out[5] and "unverified" in out[5] and "dark-triage 2026-08-20" in out[5], out
    # ...and a proven one still is
    monkeypatch.setitem(__import__("pipeline.identity_facts", fromlist=["x"])._INDEX, "ibex medical analytics", {"not_tenants": ("riskified",), "why": "test"})
    D._apply_verdict_to_file("Ibex Medical Analytics", "recovered", "greenhouse", "riskified", "https://boards-api.greenhouse.io/v1/boards/riskified/jobs", 5, 2, "")
    out = [r for r in csv.reader(open("companies.csv", encoding="utf-8"))][1]
    assert "not this company's board" in out[5], out
    # crack_walled: the write gate names its refusal
    assert G.write_verdict("Ibex Medical Analytics", "https://ib1.recruitee.com/") == "unreadable"
    src = open(C.__file__, encoding="utf-8").read()
    assert src.count('unverified (page unreadable)') == 2 and "write_verdict" in src
    # validate_empty: nothing vouches -> confirmed (no note), never suspect's false claim
    monkeypatch.setattr(V, "_get", lambda url: "<html>" + "x" * 3000 + "</html>")
    monkeypatch.setattr(V, "extract_ats", lambda html, name: ("recruitee", "ib1", "https://ib1.recruitee.com/api/offers/"))
    monkeypatch.setattr(V, "_verify", lambda name, plat, tok, api: (5, 2))
    v0 = V.check("Ibex Medical Analytics", "https://www.ibex.example/careers")
    assert v0[0] == "deferred" and "nothing vouches" in v0[1], "its own verdict, counted by main(); never `confirmed`"
    monkeypatch.setattr(V, "extract_ats", lambda html, name: ("greenhouse", "riskified", "https://boards-api.greenhouse.io/v1/boards/riskified/jobs"))
    v = V.check("Ibex Medical Analytics", "https://www.ibex.example/careers")
    assert v[0] == "suspect" and "not this company" in v[1]


def test_apply_resolved_vetoes_a_declared_negative_on_a_parked_row(tmp_path, monkeypatch):
    """Kills `apply-resolved-parked-scope` and `apply-resolved-vouch-drop` (BACKLOG 56)."""
    import csv
    import json
    import apply_resolved as A
    monkeypatch.chdir(tmp_path)
    rows = [["company_name", "ats_platform", "token", "api_url", "active", "notes"],
            ["Cogniteam", "scrape", "", "https://www.cogniteam.example/careers", "false", "no listing found"],
            ["Fiverr", "scrape", "", "https://www.fiverr.example/careers", "false", "no listing found"]]
    with open("companies.csv", "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    res = {"Cogniteam": ["greenhouse", "riskified", "https://boards-api.greenhouse.io/v1/boards/riskified/jobs"],
           "Fiverr": ["greenhouse", "fiverr", "https://boards-api.greenhouse.io/v1/boards/fiverr/jobs"]}
    (tmp_path / "resolved.json").write_text(json.dumps(res), encoding="utf-8")
    monkeypatch.setenv("RESOLVED_OUT", str(tmp_path / "resolved.json"))
    monkeypatch.setattr("sys.argv", ["apply_resolved.py", "--apply"])
    try:
        A.main()
    except SystemExit:
        pass
    out = {r[0]: r for r in csv.reader(open("companies.csv", encoding="utf-8"))}
    assert out["Cogniteam"][3] == "https://www.cogniteam.example/careers", "a parked row is vetoed too"
    assert out["Fiverr"][3].endswith("/fiverr/jobs"), "positive control: a vouching board is re-pointed"


def test_check_invariants_lists_the_active_rows_whose_tenant_cannot_vouch(tmp_path):
    """Kills `c3b-warn-drop`: the hand-check list is printed, as a warn, never a gate."""
    import csv
    import os
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    (tmp_path / "cloud_state").mkdir()
    rows = [["company_name", "ats_platform", "token", "api_url", "active", "notes"]]
    rows += [[f"Live {i}", "greenhouse", f"live{i}", f"https://boards-api.greenhouse.io/v1/boards/live{i}/jobs", "true", ""] for i in range(60)]
    rows += [["Findings", "lever", "findigs", "https://api.lever.co/v0/postings/findigs?mode=json", "true", ""]]
    rows += [[f"Parked {i}", "scrape", "", f"https://www.p{i}.example/careers", "false", "no listing found"] for i in range(60)]
    with open(tmp_path / "companies.csv", "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    r = subprocess.run([sys.executable, os.path.join(root, "check_invariants.py")], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-600:]
    assert "cannot vouch" in r.stdout and "Findings -> findigs" in r.stdout, r.stdout[-800:]


def test_triage_asks_the_page_judge_through_the_shared_seam_with_its_own_schema(monkeypatch):
    """Kills `triage-llm-schema-drop` and `triage-llm-unavailable-raise` (BACKLOG 117):
    the last bare `claude -p` in the lane goes through `pipeline.llm.call_json`, states its
    schema, and an unavailable CLI is `None` (the regex verdict stands), never a crash.

    2026-08-27: this test asserted `seen["schema"]["required"]` on the object it captured,
    i.e. it PINNED the schema as a dict -- and the seam puts `schema` into argv, so a dict
    made `subprocess.run` raise TypeError before the spawn and the judge returned None on
    every row for two days with this test green. It now parses the string, which is what
    the CLI is handed; the behavioural cover is
    `test_the_triage_page_judge_reaches_the_model_through_the_real_seam`, which drives the
    real seam with only `subprocess.run` replaced."""
    import triage_dark as T
    from pipeline import llm
    seen = {}
    def fake(prompt, *, system, schema, model, timeout, **kw):
        seen.update(schema=schema, system=system, model=model)
        return {"is_careers_page_for_this_company": True, "open_roles": ["Data Analyst"], "note": "ok"}
    monkeypatch.setattr(llm, "call_json", fake)
    monkeypatch.setenv("TRIAGE_LLM_CAP", "5")
    T._LLM_USED["n"] = 0
    v = T.llm_page_verdict("Acme", "https://acme.example/careers", "Data Analyst - Tel Aviv")
    assert v and v[0] == "has-roles" and "Data Analyst" in v[1]
    import json as _json
    assert isinstance(seen["schema"], str), "the seam puts this straight into argv"
    assert set(_json.loads(seen["schema"])["required"]) == {
        "is_careers_page_for_this_company", "open_roles", "note"}
    assert "open position" in seen["system"] and seen["model"]
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"is_careers_page_for_this_company": False, "open_roles": [], "note": "another firm"})
    assert T.llm_page_verdict("Acme", "https://x", "t")[0] == "wrong-page"
    monkeypatch.setattr(llm, "call_json", lambda *a, **k: {"is_careers_page_for_this_company": True, "open_roles": [], "note": "nothing"})
    assert T.llm_page_verdict("Acme", "https://x", "t")[0] == "confirmed-empty"
    def down(*a, **k):
        raise llm.LLMUnavailable("cli-missing", kind="missing")
    monkeypatch.setattr(llm, "call_json", down)
    assert T.llm_page_verdict("Acme", "https://x", "t") is None
    src = open(T.__file__, encoding="utf-8").read()
    assert 'subprocess.run(["claude"' not in src, "the bare claude -p is gone"
    T._LLM_USED["n"] = 0


def test_the_audit_write_is_the_named_verdict_and_a_serp_noise_slug_is_refused_by_the_page(monkeypatch):
    """Kills `audit-verdict-drop` (confirmation wave R1). `_slug_matches` cannot refuse an
    undeclared slug -- by design -- so the audit's WRITE must be the activation verdict, whose
    human-page read settles `CyberArk -> paloaltonetworks`."""
    import ast
    import inspect
    import audit_empty_rows as A
    from pipeline import identity_gate as G
    src = inspect.getsource(A.main)
    assert "activation_verdict(" in src and "_av != \"ok\"" in src
    assert 'tenant_is_this_company(name, api or "")' not in src, "the vacuous clause is gone from the write path"
    monkeypatch.setattr(G, "page_names_company",
                        lambda name, url, html="": {"https://job-boards.greenhouse.io/paloaltonetworks": False}.get(url))
    assert A._slug_matches("CyberArk", "paloaltonetworks", "https://boards-api.greenhouse.io/v1/boards/paloaltonetworks/jobs") is True, (
        "the string test defers (cannot tell)")
    assert G.activation_verdict("CyberArk", "https://boards-api.greenhouse.io/v1/boards/paloaltonetworks/jobs", 7,
                                token="paloaltonetworks") == "not-ours", "...and the page refuses"


def test_validate_empty_counts_its_deferrals_and_always_writes_its_suspect_note(tmp_path, monkeypatch, capsys):
    """Kills `validate-empty-deferred-drop` and `validate-empty-suspect-guard-restore`
    (BACKLOG 200, confirmation wave R2)."""
    import csv
    import validate_empty as V
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cloud_state").mkdir()
    long = "dark-triage 2026-08-20: extract-gap (" + "x" * 100 + ") | listing-hunt 2026-08-21: no listing found (" + "y" * 60 + ")"
    rows = [["company_name", "ats_platform", "token", "api_url", "active", "notes"],
            ["Defer Ltd", "scrape", "", "https://www.defer.example/careers", "false", "scanned; no open Israel roles now"],
            ["Full Ltd", "scrape", "", "https://www.full.example/careers", "false", long]]
    with open("companies.csv", "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    monkeypatch.setenv("VALIDATE_EMPTY_SIGNALS", "1")
    (tmp_path / "cloud_state" / "candidate_probe.json").write_text('{"Full Ltd": {"sig": 2, "il": 1}}', encoding="utf-8")
    monkeypatch.setattr(V, "check", lambda name, url: ("deferred", "3 IL but nothing vouches") if name == "Defer Ltd"
                        else ("suspect", "2+ role-near-Israel mentions in HTML"))
    monkeypatch.setattr("sys.argv", ["validate_empty.py"])
    V.main()
    out = capsys.readouterr().out
    assert "deferred (nothing vouches; no stamp): 1 -- Defer Ltd" in out, out[-600:]
    got = {r[0]: r for r in csv.reader(open("companies.csv", encoding="utf-8"))}
    assert "empty-but-suspect" in got["Full Ltd"][5] and "dark-triage 2026-08-20: extract-gap" in got["Full Ltd"][5], (
        "the suspect note is always written now; the protected facts survive it")
    assert "empty-but-suspect" not in got["Defer Ltd"][5] and "no open Israel roles" in got["Defer Ltd"][5]


def test_triage_never_writes_another_tools_pool_token_inside_its_own_segment():
    """Kills `triage-own-words-drop`. Bit's reason carried `unsupported ATS`, deep_validate's
    token and the crack pool's fact; every re-triage rewrote the segment and took Bit out of
    the crack pool with every guard green (rehearsed twice on 2026-08-26 -- the second time
    after a cron re-stamped the row with the old text)."""
    import inspect
    import triage_dark as T
    assert "unsupported ATS" not in T._own_words("ashby slug 404s; unsupported ATS")
    assert "walled ATS" in T._own_words("x; Unsupported ATS")
    assert "monitored candidate" not in T._own_words("looks like a monitored candidate")
    assert T._own_words("plain reason") == "plain reason"
    src = inspect.getsource(T.main)
    assert "_own_words(detail)" in src, "the stamp must go through the rewording"


# ---------------------------------------------------------------------------
# lane: registry, 2026-08-27 — the page judge, the mode set, the hunt's LLM cap.
# ---------------------------------------------------------------------------

def _argv_strict_run(reply):
    """A `subprocess.run` stand-in that enforces the SAME argv contract the real one does.

    The point of this helper is what it refuses. The obvious way to test an LLM caller here
    is to monkeypatch `pipeline.llm.call_json` and inspect what it was handed — and that is
    exactly the shape of the test that let `triage_dark._SCHEMA` ship as a dict and stay
    broken for two days (`tests/test_registry.py`, the 2026-08-25 batch-5 guard: it asserted
    `seen["schema"]["required"]`, i.e. it PINNED the dict). A fake that accepts anything
    proves nothing about the boundary, so this one rejects a non-str argv element with the
    real TypeError, and the test below drives the whole `pipeline/llm.py` seam.
    """
    import json as _json

    class _Proc:
        pass

    def run(cmd, **kw):
        for part in cmd:
            if not isinstance(part, (str, bytes)):
                raise TypeError("expected str, bytes or os.PathLike object, not "
                                + type(part).__name__)
        p = _Proc()
        p.returncode, p.stderr = 0, ""
        p.stdout = _json.dumps({"is_error": False, "structured_output": reply,
                                "modelUsage": {"claude-sonnet-5": {"outputTokens": 40}}})
        return p
    return run


def test_the_triage_page_judge_reaches_the_model_through_the_real_seam(monkeypatch):
    """`triage_dark.llm_page_verdict` must return a verdict, not None, when the CLI answers.

    Until 2026-08-27 it could not: `_SCHEMA` was a dict, `pipeline/llm.py` puts the schema
    into argv, and `subprocess.run` raised TypeError before spawning. `_invoke` turns any
    spawn failure into `LLMUnavailable(kind="missing")` and this function swallows that as
    "no CLI / no auth: the regex verdict stands" — so `wrong-page` became an unproduceable
    verdict and every `page-empty` row was an unconfirmed regex guess. Live effect on
    2026-08-26: 20 rows triaged, 0 LLM verdicts, cap counter reading as spend.
    """
    import shutil
    import triage_dark as T
    from pipeline import llm
    monkeypatch.setattr(shutil, "which", lambda _n: "claude")
    monkeypatch.setattr(llm.shutil, "which", lambda _n: "claude")
    monkeypatch.setattr(llm.subprocess, "run", _argv_strict_run(
        {"is_careers_page_for_this_company": True,
         "open_roles": ["Data Analyst", "BI Developer"], "note": "two roles"}))
    monkeypatch.setattr(T, "_LLM_USED", {"n": 0})
    got = T.llm_page_verdict("Wix", "https://www.wix.com/jobs", "PAGE TEXT")
    assert got is not None, "the judge is unreachable again — check the schema is a string"
    assert got[0] == "has-roles" and "Data Analyst" in got[1]


def test_the_triage_page_judge_can_still_say_wrong_page(monkeypatch):
    """The verdict `wrong-page` exists ONLY on this path — no regex produces it — so it is
    the one mode whose absence from a night's triage means the judge is dead rather than
    that no row deserved it."""
    import shutil
    import triage_dark as T
    from pipeline import llm
    monkeypatch.setattr(shutil, "which", lambda _n: "claude")
    monkeypatch.setattr(llm.shutil, "which", lambda _n: "claude")
    monkeypatch.setattr(llm.subprocess, "run", _argv_strict_run(
        {"is_careers_page_for_this_company": False, "open_roles": [], "note": "a blog"}))
    monkeypatch.setattr(T, "_LLM_USED", {"n": 0})
    got = T.llm_page_verdict("Wix", "https://www.wix.com/blog", "PAGE TEXT")
    assert got and got[0] == "wrong-page"


def test_the_triage_mode_set_is_every_mode_the_classifier_can_return():
    """`triage_dark.MODES` is this module's own object and must stay complete.

    A mode that no filter matches drops its rows out of every pool silently, and the
    detector for that (`check_invariants` check F2) compares against a HAND COPY of this
    set — which had 7 of the 8 and reported 24 rows carrying the real mode `no-url` as
    "truncated/unknown" every night. The set is derived here from the module's own AST so a
    ninth mode cannot be added without adding it to `MODES` too. ARCHITECTURE.md section 2:
    never retype a pool, import the tool's predicate.
    """
    import ast
    import triage_dark as T
    tree = ast.parse(open(T.__file__, encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "classify")
    returned = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple) \
                and node.value.elts and isinstance(node.value.elts[0], ast.Constant) \
                and isinstance(node.value.elts[0].value, str):
            returned.add(node.value.elts[0].value)
    assert returned, "classify's shape changed — re-point this guard"
    assert returned == set(T.MODES), (
        f"triage_dark.MODES disagrees with classify: "
        f"returned-not-declared={sorted(returned - set(T.MODES))} "
        f"declared-not-returned={sorted(set(T.MODES) - returned)}")


def test_the_hunt_actually_reads_the_llm_cap_its_docstring_promises(monkeypatch):
    """`listing_hunt`'s docstring has advertised `HUNT_LLM_CAP (default 200)` since the tool
    was written, and until 2026-08-27 nothing read it: no counter, no `os.environ.get`. The
    hunt is the lane's largest Claude consumer (a picker call per company plus scrape
    strategy 5, `SCRAPE_LLM: "1"` in the workflow) and its only bound was wall clock. A
    documented cap that does not exist is worse than no cap: the next reader budgets against
    it.
    """
    import listing_hunt as H
    monkeypatch.setenv("HUNT_LLM_CAP", "2")
    H._LLM_USED["n"] = 0
    assert H._llm_budget_left() is True
    H._LLM_USED["n"] = 2
    assert H._llm_budget_left() is False, "the cap is read but never enforced"
    src = open(H.__file__, encoding="utf-8").read()
    assert 'os.environ.get("HUNT_LLM_CAP"' in src,         "the docstring advertises HUNT_LLM_CAP; the code must actually read it"
    assert "_llm_budget_left()" in src.split("def _llm_budget_left")[-1],         "the budget helper exists but no caller consults it"


def test_the_resolver_counts_the_calls_that_could_not_have_verified():
    """`_verify` will not accept a board unless its token appears on a page on the company's
    OWN domain, so an attempt whose evidence holds no such page cannot succeed whatever the
    model answers — it spends up to two calls and returns None. `own_pages_in_evidence`
    names that condition, and `auto_expand` reports it as `hopeless N` rather than acting on
    it, because the measurement cannot be made off the runner: SerpApi is exhausted,
    DuckDuckGo is rate-limited from the dev machine and there are no Bright Data credentials
    there, so a local sample is all `candidates=0` and says nothing.

    This pins the PREDICATE, which is the part a gate would later stand on.
    """
    import resolve_llm as R
    pages = [("https://www.growthspace.com/careers", "<html>own page</html>"),
             ("https://boards.greenhouse.io/someoneelse", "<html>ats host</html>"),
             ("https://il.linkedin.com/jobs/view/1", "<html>aggregator</html>")]
    kept = R.own_pages_in_evidence("GrowthSpace", pages)
    assert kept == ["https://www.growthspace.com/careers"], kept
    assert R.own_pages_in_evidence("GrowthSpace", pages[1:]) == [], \
        "an ATS host and an aggregator are not the company's own page"
    assert "own_pages" in R.LAST


def test_auto_expand_reports_what_the_llm_tier_was_asked(monkeypatch, tmp_path):
    """The summary line is the only place the resolver queue is visible, and until
    2026-08-27 it said `resolved 0 … deferred 250` without saying how many of the tier's
    capped calls were even winnable. Two runs a day at `LLM_RESOLVE_CAP` 10 is the whole
    drain rate, so `asked N (hopeless M)` is the number that decides whether the cap is
    worth raising or the calls are worth refusing."""
    import auto_expand as A
    src = open(A.__file__, encoding="utf-8").read()
    assert 'f"asked {n_asked} (hopeless {n_hopeless}); "' in src
    assert 'n_hopeless += 1 if not _llm.LAST["own_pages"] else 0' in src
    assert "keeps shrinking the unresolved set every run until it reaches zero" not in src, \
        "the docstring's drain claim was measured false on 2026-08-26 (414 -> 411 -> 408)"


# The dated escape hatch for mutation records whose `find` no longer matches its file. It held
# 33 ids on 2026-08-27 and was emptied the same day, which is the only state it should ever be
# left in: `test_no_mutation_record_goes_stale_unnoticed` fails both when a record goes stale
# that is not listed here AND when a listed one is fixed without being removed, so the list can
# only shrink and cannot rot into an excuse. It stays (empty) rather than being deleted so the
# next refactor has somewhere honest to record a temporary red. docs/BACKLOG.md 273.
KNOWN_STALE_ANCHORS_2026_08_27 = frozenset()   # 33 on 2026-08-27, cleared the same day


def _stale_mutation_anchors():
    """Every record whose `find` does not occur EXACTLY once in the file it names.

    `tools/mutate.py` archives `git archive HEAD`, whose blobs are LF; the working copy here
    is CRLF (`core.autocrlf=true`), so normalise before counting or every multi-line anchor
    reads as stale on Windows and as fine in CI.
    """
    import json
    import os
    recs = json.load(open("tests/mutations.json", encoding="utf-8"))
    out = []
    for r in recs:
        path = r.get("file") or ""
        if not path or not os.path.exists(path):
            out.append((r.get("id"), "no such file: " + path))
            continue
        with open(path, encoding="utf-8", newline="") as f:
            src = f.read().replace("\r\n", "\n")
        n = src.count(r["find"])
        if n != 1:
            out.append((r.get("id"), f"{n} matches in {path}"))
    return out


def test_no_mutation_record_goes_stale_unnoticed():
    """A stale mutation record proves nothing, and today it is only DISCOVERABLE by a
    37-minute job that runs last in CI — so staleness accumulates until it is somebody
    else's push. On 2026-08-27 that had reached 33 of 200 records: the 2026-08-25 batch-4
    refactor replaced `ok_to_write` / `activation_ok` with `write_verdict` /
    `activation_verdict`, and every record anchored on the old spelling went quiet while
    `pytest` stayed green. This runs in under a second and names them.

    It is a ratchet, not a snapshot: a record that stops being stale must LEAVE the list, so
    the list can only shrink. That is the half that stops an allowlist becoming permission.
    """
    import os
    import pytest
    if os.environ.get("AJIL_MUTANT"):
        # Inside `tools/mutate.py`'s mutant copy the source is deliberately NOT HEAD's, so
        # the record whose text was just replaced always reads as stale. Without this the
        # test would "kill" every mutation in the catalogue and the gate would prove nothing
        # (measured 2026-08-27: it reported `audit-narrow  killed  test_no_mutation_record_
        # goes_s (direct)` -- a false kill, and it would have been the same for all 197).
        pytest.skip("the mutant's source is intentionally not HEAD's")
    stale = dict(_stale_mutation_anchors())
    known = KNOWN_STALE_ANCHORS_2026_08_27
    fresh = sorted(set(stale) - known)
    assert not fresh, (
        "mutation record(s) went stale — the code they guard moved, so they now guard "
        "nothing and `tools/mutate.py` will fail the push: "
        + "; ".join(f"{i} ({stale[i]})" for i in fresh)
        + ".  Re-anchor each onto the current code, keeping its `why`, and prove it with "
          "`python tools/mutate.py --id <id>` reporting `killed`.")
    fixed = sorted(known - set(stale))
    assert not fixed, (
        "these records are no longer stale — remove them from "
        "KNOWN_STALE_ANCHORS_2026_08_27 so the list keeps shrinking: " + ", ".join(fixed))


def test_no_two_active_rows_share_a_board():
    """Two ACTIVE rows on the same endpoint publish every role twice under two names, and
    `check_invariants` check B cannot see it: B counts `company_name`, and by construction
    the names differ. That is what `alias-of` exists to park.

    Found live on 2026-08-27 by an adversarial reviewer, hours old: `apply_resolved` had
    re-pointed `Anchor` onto uid 87.00D, which `Anchor Fintech` already held — byte-identical
    platform/token/api_url, both active, 14 colliding `seen_id`s, and `roles._winner` breaking
    the tie on `len(identity_key(name))`, so the shorter stub name `Anchor` would have won and
    Anchor Fintech's roles would have published under it. It was the only such pair in 1,244
    rows, and this session created it.
    """
    import csv
    from collections import Counter
    with open("companies.csv", encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r and len(r) >= 6][1:]
    live = [r for r in rows if r[4] == "true" and (r[3] or "").startswith("http")]
    dupes = Counter(r[3] for r in live)
    shared = {u: sorted(r[0] for r in live if r[3] == u) for u, n in dupes.items() if n > 1}
    assert not shared, (
        "active rows sharing one board — park all but one with `alias-of <the keeper>`: "
        + "; ".join(f"{names} -> {u[:70]}" for u, names in shared.items()))


def test_the_own_page_filter_is_called_not_re_typed():
    """`_own_page_names_token` must USE `own_pages_in_evidence`, not repeat its four lines.

    The first version of `own_pages_in_evidence` copied the filter and its docstring claimed
    the opposite — "ITS filter, not a copy" — which is the drift shape `registry_health.pools`
    calls this repo's commonest bug, asserted as its own absence. Behaviour is pinned in both
    directions as well as the wiring, because a shared helper that is wired but wrong is worse
    than a copy.
    """
    import ast
    import resolve_llm as R
    tree = ast.parse(open(R.__file__, encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_own_page_names_token")
    calls = {n.func.id for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "own_pages_in_evidence" in calls, "the filter is re-typed again"
    pages = [("https://www.growthspace.com/careers", "<html>tok-abc</html>"),
             ("https://boards.greenhouse.io/someoneelse", "<html>tok-abc</html>"),
             ("https://il.linkedin.com/jobs/view/1", "<html>tok-abc</html>")]
    assert R.own_pages_in_evidence("GrowthSpace", pages) == \
        ["https://www.growthspace.com/careers"]
    assert R._own_page_names_token("GrowthSpace", "tok-abc", "", pages) is True
    assert R._own_page_names_token("GrowthSpace", "tok-abc", "", pages[1:]) is False


def test_the_hunts_llm_budget_is_per_run_not_per_process():
    """`_LLM_USED` is a module global. Two `main()` calls in one process — the rehearsal, a
    test, an operator looping — would otherwise share one `HUNT_LLM_CAP`, so the second run
    silently makes no picker calls at all. The reset belongs at the top of `main`, next to
    the other per-run setup."""
    import ast
    import listing_hunt as H
    tree = ast.parse(open(H.__file__, encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    resets = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Subscript)
                      and isinstance(t.value, ast.Name) and t.value.id == "_LLM_USED"
                      for t in n.targets)]
    assert resets, "listing_hunt.main() does not reset its per-run LLM counter"


def test_the_weekly_audit_refuses_a_board_that_nothing_can_vouch_for(tmp_path, monkeypatch):
    """The audit's `if _av != "ok": ... continue` refusal had NO behavioural coverage, and
    only ONE of the five verdicts can actually reach it.

    Everything else is already refused by a rung above: `_slug_matches` (line 426) drops any
    tenant that does not near-match the name — of every declared negative in
    `identity_facts.DECLARED`, **0** still pass it, so `not-ours` cannot arrive — and
    `if not n_all` (line 454) drops the empty board before the verdict is even computed, so
    `empty` cannot either. I checked both by building those fixtures first; both left
    `audit-secondchance-remove` SURVIVING, which is what an unreachable branch looks like.

    What DOES reach it is `unverified`: an opaque token (a Comeet uid, a near-matching path
    tenant) makes `board_vouches` answer `None`, and when the human board page cannot be read
    there is nothing left to decide with. The audit must then leave the row dark and stamp no
    claim — that is the third identity state, and this refusal is the only thing enforcing it
    here. It is also the aspectiva shape: a uid nothing can falsify.

    Fiverr is the positive control: without it a gate that refuses everything passes.
    """
    import os
    import sys
    import audit_empty_rows as A
    monkeypatch.setattr(A, "_playwright_available", lambda: False)
    monkeypatch.chdir(tmp_path)
    _registry(tmp_path, [
        ["Voiceitt", "", "", "https://www.voiceitt.com/careers", "false",
         "no listing found 2026-01-01: dark"],
        ["Fiverr", "", "", "https://www.fiverr.com/jobs", "false",
         "no listing found 2026-01-01: dark"],
    ])
    os.makedirs(tmp_path / "state", exist_ok=True)
    (tmp_path / "state" / "audit_done.json").write_text("{}", encoding="utf-8")

    OPAQUE = "https://boards.greenhouse.io/voiceitt"    # slug matches, so every rung above
    FIVERR = "https://boards.greenhouse.io/fiverr"      # the verdict admits it
    pages = {
        OPAQUE: "<html>Voiceitt careers " + OPAQUE + " " + "y" * 3000 + "</html>",
        FIVERR: "<html>Fiverr careers " + FIVERR + " " + "w" * 3000 + "</html>",
    }
    monkeypatch.setattr(A, "fetch", lambda url, timeout=20: pages.get(url, ""))
    monkeypatch.setattr(A, "serp",
                        lambda name, limit=5: {"Voiceitt": [OPAQUE],
                                               "Fiverr": [FIVERR]}.get(name, []))
    monkeypatch.setattr(A, "verify", lambda name, plat, tok, api: (12, 5))
    # the ONLY difference between the two cells: nothing can vouch for Voiceitt's board and
    # its human page cannot be read, so the verdict is `unverified`.
    monkeypatch.setattr(IG, "board_vouches",
                        lambda name, tok, api: None if name == "Voiceitt" else True)
    # `page_names_company` answering None IS "the page could not be read" -- the state the
    # third verdict exists for. Fiverr's page reads fine.
    monkeypatch.setattr(IG, "page_names_company",
                        lambda name, url, html="": None if name == "Voiceitt" else True)
    monkeypatch.setattr(sys, "argv", ["audit_empty_rows.py", "--apply"])
    A.main()

    out = _read(tmp_path)
    assert out["Voiceitt"][4] == "false", (
        "the audit activated a board nothing could vouch for: %r" % (out["Voiceitt"],))
    assert out["Fiverr"][4] == "true", (
        "positive control regressed - the gate now refuses everything: %r" % (out["Fiverr"],))
