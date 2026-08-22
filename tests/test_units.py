"""Unit guards for the pure decision functions. stdlib + pytest only, no network, no I/O.

Every assertion here corresponds to a bug that actually shipped in this repo. The value is
not coverage — it is that these specific failures are silent: they do not raise, they just
quietly stop covering companies or start reporting the wrong ones.

    python -m pytest            # ~1s
"""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import aggregators, israel, seniority, verdicts  # noqa: E402


# --- module surface: a same-named file overwrote this module and deleted the function ---
def test_aggregator_public_surface():
    assert callable(getattr(aggregators, "fetch_serpapi_google_jobs", None))
    import pipeline.run  # noqa: F401  — import-time smoke, catches a broken module pre-cron


# --- aggregator blocklist: builtin.com incident + t.me anchoring + scheme-less URLs ---
@pytest.mark.parametrize("url,expected", [
    ("https://www.linkedin.com/jobs/view/1", True),
    ("https://builtin.com/jobs?allLocations=true", True),
    ("https://t.me/s/israeljobs", True),
    ("www.getclera.com/co/x", True),
    ("https://supplant.me/careers/", False),      # must NOT match "t.me/"
    ("https://www.supersmart.me/careers", False),
    ("https://boards-api.greenhouse.io/v1/boards/wix/jobs", False),
    ("https://careers.wix.com/", False),
    ("", False),
])
def test_is_aggregator(url, expected):
    assert aggregators.is_aggregator(url) is expected


# --- Israel gate ---
def test_country_code_israel_only():
    assert israel.country_is_israel(" il ") and israel.country_is_israel("ISR")
    assert not israel.country_is_israel("IS") and not israel.country_is_israel("ISL")


def test_is_israel_job_text_fallback():
    assert israel.is_israel_job({"location": "Nes Ziona"}) is True
    assert israel.is_israel_job({"location": "New York"}) is False


def test_scraper_city_regex_stays_derived():
    """The scraper kept its own city list and silently dropped Sderot/Yoqneam/Nes Ziona
    + 23 spellings — roles were extracted correctly and then filtered away."""
    from scrape_universal import ISRAEL_LOC
    from pipeline.israel import _IL_PLACES
    missing = [p for p in _IL_PLACES if not ISRAEL_LOC.search(p)]
    assert missing == [], f"scraper location regex dropped: {missing}"
    assert not ISRAEL_LOC.search("New York")


# --- classifier ---
@pytest.mark.parametrize("title,decision", [
    ("Senior Data Analyst", "accept"),
    ("Analytics Team Lead", "accept"),
    ("Data Scientist, Product Analytics", "accept"),
    ("Junior Data Analyst", "reject"),
    ("Senior Software Engineer", "reject"),
    ("Senior Machine Learning Engineer", "reject"),
    ("Senior Security Analyst", "reject"),
    ("Senior Financial Analyst", "reject"),
])
def test_classify_no_llm(title, decision):
    assert seniority.classify({"title": title}, use_llm=False)["decision"] == decision


@pytest.mark.parametrize("word", ["analytics", "dashboards", "stakeholders",
                                  "experiments", "analyze"])
def test_analytics_regex_matches_derived_forms(word):
    """A trailing \\b after a PREFIX alternative made every derived form fail. This regex is
    both the ML counter-signal and the only positive evidence in _sig_accept_nollm, so the
    bug hurt precision and recall at once."""
    assert seniority._DESC_ANALYTICS.search(word)


def test_bare_senior_data_scientist_needs_analytics_evidence():
    ml = {"title": "Senior Data Scientist",
          "description": "Requirements: train deep learning models in PyTorch, deploy "
                         "neural networks, feature engineering."}
    an = {"title": "Senior Data Scientist",
          "description": "Requirements: A/B tests, dashboards, SQL, stakeholders, "
                         "business metrics, analytics."}
    assert seniority.classify(ml, use_llm=False)["decision"] == "reject"
    assert seniority.classify(an, use_llm=False)["decision"] == "accept"


def test_hebrew_seniority_markers():
    """'ראש צות' was a typo (one vav) and matched nothing real."""
    assert seniority._HEBREW_SENIOR.search("ראש צוות אנליטיקה")


# --- verdict pools: the silent-exclusion bug class ---
@pytest.mark.parametrize("note,want", [
    ("deep-validated 2026-01-01: no ATS detected", True),
    ("deep-validated 2026-01-01: unsupported ATS eightfold.ai", True),
    ("scanned; no open Israel roles now", True),
    ("aggregator URL; resolve real careers page", True),
    ("host documented, 0 IL now", True),
    ("scanned via brightdata; no open Israel roles now", True),
    ("no listing found", True),
    ("defunct: acquired by NVIDIA", False),
    ("x | domain-dead 2026-01-01 (dns-dead)", False),
])
def test_verdict_pool_membership(note, want):
    assert verdicts.in_pool(note) is want


def test_every_pool_token_is_registered():
    """Any new verdict string must be added to verdicts.TOKENS or rows carrying it leave
    every re-check pool silently (this stranded 52 rows, then another 64)."""
    for token in verdicts.TOKENS:
        assert verdicts.in_pool(f"something | {token} 2026-01-01: detail")


def test_staleness_escapes_are_not_terminal():
    """A `"marker" not in note` filter freezes coverage forever — introduced and removed
    three times in this repo."""
    old = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    new = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    assert verdicts.stale("", "listing-hunt", 14)
    assert verdicts.stale(f"listing-hunt {old}: no listing found", "listing-hunt", 14)
    assert not verdicts.stale(f"listing-hunt {new}: no listing found", "listing-hunt", 14)


# --- git-layer merge: the lost-update fix that once reintroduced the lost update ---
def test_merge_applies_only_this_runs_changes(tmp_path):
    from merge_csv_rows import merge

    def w(name, rows):
        p = tmp_path / name
        p.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")
        return str(p)

    base = w("base.csv", [["A", "old"], ["B", "old"]])
    ours = w("ours.csv", [["A", "MINE"], ["B", "old"]])      # we changed only A
    target = w("target.csv", [["A", "old"], ["B", "THEIRS"]])  # someone else changed B
    merge(base, ours, target)
    out = [l.split(",") for l in
           (tmp_path / "target.csv").read_text(encoding="utf-8").splitlines()]
    assert out == [["A", "MINE"], ["B", "THEIRS"]]           # B must survive


def test_merge_unions_note_segments_from_both_writers(tmp_path):
    """The notes column is an append-log of per-tool segments. Row-granular replacement made
    a 7-hour hunt overwrite 351 freshly-written triage modes with its own stale row version —
    a lost update the row-level merge was supposed to prevent, one layer down."""
    from merge_csv_rows import merge

    def w(name, rows):
        p = tmp_path / name
        p.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")
        return str(p)

    cols = ["A", "scrape", "", "http://x", "false"]
    base = w("base.csv", [cols + ["no ATS detected"]])
    ours = w("ours.csv", [cols + ["no ATS detected | listing-hunt 2026-08-22: no IL listing"]])
    target = w("target.csv", [cols + ["no ATS detected | dark-triage 2026-08-22: url-dead"]])
    merge(base, ours, target)
    note = (tmp_path / "target.csv").read_text(encoding="utf-8").strip().split(",")[-1]
    assert "listing-hunt" in note, "the run's own verdict was dropped"
    assert "dark-triage" in note, "the other writer's segment was clobbered"


def test_merge_notes_never_truncates_the_newest_segment():
    """Capping with note[:220] cut the verdict off the END, so the row kept its old prose and
    silently lost the decision that was just made."""
    from merge_csv_rows import _merge_notes
    fresh = "dark-triage 2026-08-22: url-dead (http 404 on careers page)"
    out = _merge_notes("x " * 130, fresh)
    assert len(out) <= 220 and fresh in out


def test_triage_does_not_restamp_every_night():
    """`f"dark-triage {TODAY}" not in note` re-triaged all 352 dark rows nightly, and since
    listing_hunt treats a triage date >= its own stamp as "hunt now", that silently cancelled
    the hunt's 14-day cooldown and pinned its time budget to the same prefix of the pool."""
    import triage_dark
    today = dt.date.today().isoformat()
    old = (dt.date.today() - dt.timedelta(days=triage_dark.TRIAGE_TTL_DAYS + 1)).isoformat()
    assert triage_dark._needs_triage("") is True
    assert triage_dark._needs_triage(f"dark-triage {today}: url-dead") is False
    assert triage_dark._needs_triage(f"dark-triage {old}: url-dead") is True


def test_probe_wake_actually_reaches_the_hunt():
    """probe_candidates stripped only listing-hunt/crack-walled, so a woken row kept its
    `dark-triage … page-empty` stamp and listing_hunt._triaged_page_empty still excluded it:
    105/105 wakes were swallowed. The probe's whole purpose is to re-open the hunt."""
    import listing_hunt
    from probe_candidates import WAKE_STAMP, _wake_note
    note = ("no ATS detected | listing-hunt 2026-08-22: no IL listing "
            "| dark-triage 2026-08-22: page-empty (live page, 0 roles)")
    woken = _wake_note(note)
    assert not listing_hunt._triaged_page_empty(woken), "wake left the row hunt-excluded"
    # every stale segment must go, not just the first: after removing one, the separator
    # loses its leading space and a `\s\|` pattern silently stops matching
    assert "listing-hunt" not in woken and "dark-triage" not in woken
    assert "no ATS detected" in woken, "the base verdict was destroyed"
    assert woken.endswith(WAKE_STAMP), "the wake stamp was truncated off the end"


def test_triage_pool_survives_note_erosion():
    """Triage rewrites the note it matched on and the 220-char cap trims the base a little
    more each time, so rows whose original verdict eroded matched nothing and left EVERY
    recurring pool (17 companies were owned by no scheduled tool)."""
    import triage_dark
    eroded = "scanned via brightdata; no  | dark-triage 2026-08-22: page-empty (0 roles)"
    assert triage_dark.TARGET_NOTES.search(eroded)
    assert not triage_dark.SKIP_NOTES.search(eroded)


@pytest.mark.parametrize("company,url,ok", [
    # legitimate: acronym domains, ATS hosts, brand/parent pairs
    ("Texas Instruments", "https://careers.ti.com/", True),
    ("General Motors", "https://search-careers.gm.com/", True),
    ("Central Bottling Company Israel", "https://www.cbccom.com/", True),
    ("Quantum Source", "https://www.qs-labs.com/", True),
    ("AWS", "https://www.amazon.jobs/", True),
    ("Nebius", "https://careers.nebius.com/", True),
    ("Wix", "https://boards.greenhouse.io/wix", True),
    # impostors: each of these ACTIVATED a company off another employer's board
    ("FairFly", "https://fireflyspace.com/careers", False),
    ("Ironblocks", "https://www.fireblocks.com/careers", False),
    ("COTI", "https://jobs.citi.com/", False),
    ("1MRobotics", "https://careers.micron.com/", False),
    ("L7 Defense", "https://search-careers.gm.com/", False),
    ("factify", "https://duckduckgo.com/?q=x", False),
])
def test_company_identity_guard(company, url, ok):
    """Verifying "there are real Israel jobs here" never asked "are they THIS company's?",
    so any page with Israel roles activated the row. 135 roles landed under the wrong
    employer before this guard existed."""
    from pipeline.company_identity import is_foreign
    assert is_foreign(company, url) is not ok


def test_empty_scrape_rows_are_never_parked():
    """A company in this market can have zero openings for a month and still be a healthy
    source. Parking an active scrape row after a 3-day EMPTY streak retired good companies
    and made the next role posted there invisible. Only ERRORS park a row now; a long empty
    streak just asks triage to re-read the page, and the row stays active and scanned."""
    import ast
    import refresh_scrape_cache as R
    src = open(R.__file__, encoding="utf-8").read()
    assert "EMPTY_REVALIDATE_DAYS" in src, "the empty-streak path was removed entirely"
    tree = ast.parse(src)
    # locate the `if jobs is None:` (error) branch; parked.append must occur only inside it
    park_lines = [n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Attribute) and n.attr == "append"
                  and isinstance(n.value, ast.Name) and n.value.id == "parked"]
    err = [n for n in ast.walk(tree) if isinstance(n, ast.If)
           and isinstance(n.test, ast.Compare) and getattr(n.test.left, "id", "") == "jobs"]
    assert err, "error branch not found"
    lo = err[0].lineno
    hi = max(getattr(x, "lineno", 0) for x in ast.walk(err[0]))   # operators carry no lineno
    assert park_lines, "nothing parks at all — error rot detection lost"
    for ln in park_lines:
        assert lo <= ln <= hi, f"parked.append at line {ln} is outside the ERROR branch"


def test_no_script_references_an_undefined_name():
    """Two shipped bugs of this exact shape, both invisible behind `continue-on-error`:

      refresh_scrape_cache._write_csv_rows  -> rot parking raised NameError AFTER writing
                                               the cache, so it never parked anything
      crack_walled._budget / _t0            -> NameError on the first target, so the
                                               walled-ATS crack never ran at all

    compileall does not catch these (they are runtime lookups) and the daily workflows
    swallow the traceback, so the tool looks like it ran and quietly did nothing.
    """
    import ast
    import builtins
    import glob

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = {}
    for path in sorted(glob.glob(os.path.join(repo, "*.py"))
                       + glob.glob(os.path.join(repo, "pipeline", "*.py"))):
        tree = ast.parse(open(path, encoding="utf-8").read())
        defined = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "self", "cls"}
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                defined.update((a.asname or a.name).split(".")[0] for a in n.names)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(n.name)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                defined.add(n.id)
            elif isinstance(n, ast.arg):
                defined.add(n.arg)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                defined.add(n.name)
            elif isinstance(n, ast.Global):
                defined.update(n.names)
        used = {n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        missing = sorted(used - defined)
        if missing:
            offenders[os.path.basename(path)] = missing
    assert not offenders, f"undefined names (runtime NameError waiting to happen): {offenders}"


def test_merge_never_reverts_a_repaired_url_to_a_dead_one(tmp_path):
    """A multi-hour run commits the address the row had at CHECKOUT. If another writer has
    since replaced an NXDOMAIN hostname with a verified one, applying the run's row hands
    the company back a URL that does not resolve — and every later tool then honestly
    reports it as unreachable again."""
    import csv as _csv
    from merge_csv_rows import merge

    def w(name, rows):
        p = tmp_path / name
        with open(p, "w", newline="", encoding="utf-8") as f:
            _csv.writer(f).writerows(rows)
        return str(p)

    dead = "https://careers.pliops.com/careers?location=Israel"
    good = "https://pliops.com/careers"
    cols = ["Pliops", "scrape", ""]
    base = w("base.csv", [cols + [dead, "false", "no ATS detected"]])
    ours = w("ours.csv", [cols + [dead, "false",
                                  "no ATS detected | listing-hunt 2026-08-23: no IL listing"]])
    tgt = w("t.csv", [cols + [good, "false",
                              "no ATS detected | url-repaired 2026-08-23: dead host replaced"]])
    merge(base, ours, tgt)
    row = next(_csv.reader(open(tgt, encoding="utf-8")))
    assert row[3] == good, "merge reverted a verified URL to an NXDOMAIN one"
    assert "listing-hunt" in row[5] and "url-repaired" in row[5]


def test_every_registry_platform_has_a_fetcher():
    """`fetch_company` RAISES on an unknown ats_platform, so a platform written into
    companies.csv without a matching entry in FETCHERS kills that company's fetch every
    run. Checks the real registry against the real dispatch table."""
    import csv as _csv
    from pipeline.fetchers import FETCHERS

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    used = set()
    with open(os.path.join(repo, "companies.csv"), encoding="utf-8") as f:
        for r in _csv.reader(f):
            if r and len(r) >= 6 and r[4] == "true":
                used.add((r[1] or "").strip().lower())
    used.discard("")
    used.discard("ats_platform")           # header row
    missing = sorted(used - set(FETCHERS))
    assert not missing, f"active rows use platforms with no fetcher: {missing}"


def test_registry_is_structurally_sound():
    """Cheap end-to-end guard: the real companies.csv must pass every invariant."""
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "check_invariants.py"], cwd=repo,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
