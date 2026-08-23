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


@pytest.mark.parametrize("company,url,ok", [
    ("General Motors", "https://search-careers.gm.com/", True),   # acronym w/ industry word
    ("Teva Pharmaceutical", "https://www.tevapharm.com/x", True),
    ("Sproutt", "https://sprout.careers/", True),
    ("Pliops", "https://pliops.com/careers", True),
    # each of these was ACCEPTED by the first version of the guard and is a real,
    # different company found while repairing dead URLs on 2026-08-23
    ("Tamar Robotics", "https://arberobotics.com/career/", False),   # Arbe Robotics
    ("RADLogics", "https://www.rad.com/career/", False),             # RAD Data Comms
    ("Noogata", "https://www.nooga.net/career", False),
])
def test_identity_rejects_industry_word_and_loose_substring_matches(company, url, ok):
    """Matching on a generic industry word ("robotics", "financial") or on a much shorter
    domain that merely prefixes the name ("rad" in "radlogics") is not identity."""
    from pipeline.company_identity import verdict
    assert (verdict(company, url) != "mismatch") is ok


def test_page_mentions_company_beats_domain_heuristics():
    from pipeline.company_identity import page_mentions_company
    assert page_mentions_company("Tamar Robotics", "<p>Tamar Robotics is hiring</p>")
    assert not page_mentions_company("Tamar Robotics", "<p>Arbe Robotics careers</p>")
    assert not page_mentions_company("RADLogics", "<h1>RAD Data Communications</h1>")


def test_registry_is_structurally_sound():
    """Cheap end-to-end guard: the real companies.csv must pass every invariant."""
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "check_invariants.py"], cwd=repo,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# --- a daily re-sighting used to overwrite a backfilled JD with "" -------------------
def test_a_re_sighting_without_a_description_never_erases_the_stored_one(tmp_path):
    """workday/smartrecruiters/bamboohr/microsoft list responses carry NO description, so
    every day's fetch of an already-matched role handed the store an empty string — and the
    store wrote it over the JD that `enrich_matched_jd` had paid Bright Data to fetch. The
    board then rendered no requirements, no skills and no tags for those roles."""
    from pipeline import store
    st = store.SeenStore(str(tmp_path / "t.db"))
    job = {"company": "ACME", "title": "Data Analyst", "location": "TLV", "url": "u",
           "posted_date": "2026-08-20", "seniority": "mid", "sources": ["workday"],
           "description": "R" * 900}
    st.upsert_matched(job, "2026-08-20")
    st.upsert_matched({**job, "description": ""}, "2026-08-21")     # next day, same role
    assert len(st.conn.execute("select description from matched").fetchone()[0]) == 900
    st.upsert_matched({**job, "description": "L" * 1500}, "2026-08-22")   # better text wins
    assert len(st.conn.execute("select description from matched").fetchone()[0]) == 1500
    # ...and the >3-day-gap path (re-opened role) must not erase it either
    st.upsert_matched({**job, "description": ""}, "2026-09-10")
    assert len(st.conn.execute("select description from matched").fetchone()[0]) == 1500
    st.close()


# --- the board is "still open", not "first seen in the last 14 days" -----------------
def test_the_jd_filler_only_spends_a_fetch_on_a_role_that_could_be_accepted():
    """The inline filler runs over hundreds of roles inside the digest's own timeout. A
    role the title gate already rejects must never cost an HTTP request — and a role that
    already has its JD must not be re-fetched every single morning."""
    from pipeline.jdfill import JDFiller
    f = JDFiller(budget_min=5)
    assert f.maybe_fill({"title": "Senior Backend Engineer", "url": "https://x/1",
                         "description": ""}) is False
    assert f.maybe_fill({"title": "Data Analyst", "url": "https://x/2",
                         "description": "D" * 400}) is False
    assert f.maybe_fill({"title": "Data Analyst", "url": "", "description": ""}) is False
    assert f.tried == 0


def test_stage_stamps_are_readable_by_the_next_stage(tmp_path, monkeypatch):
    """The cron order (repair 19:00 -> collect 00:00 -> publish 05:00) is real but implicit:
    when the repair job dies, the digest still runs on stale URLs and reports success. The
    stamp is what makes that visible instead of silent."""
    from pipeline import stages
    monkeypatch.setattr(stages, "PATH", str(tmp_path / "stages.json"))
    assert stages.age_days("repair") is None
    assert stages.require("repair") is False          # never run -> warn, never raise
    stages.stamp("repair", rows=7)
    assert stages.age_days("repair") == 0
    assert stages.require("repair") is True
    assert "repair: " in stages.summary() and "rows=7" in stages.summary()


# --- every path that flips a row to active must first check WHOSE page it verified ------
def test_every_activation_path_checks_company_identity():
    """`listing_hunt` learned on 2026-08-23 that "there are Israel jobs here" is not "these
    are THIS company's jobs" — FairFly activated off fireflyspace.com, COTI off
    jobs.citi.com. Four other tools flip `active` to true and only one had the gate:
    `repair_extract_gap` re-activated FairFly off the very same stored URL hours later.
    A wrong activation is worse than a dark row: the roles reach the board under a name
    that never posted them, and every later verdict honestly confirms the wrong page."""
    import ast
    import glob
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ungated = []
    for path in glob.glob(os.path.join(root, "*.py")):
        src = open(path, encoding="utf-8").read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        activates = any(
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                    and t.slice.value == 4 for t in n.targets)
            and isinstance(n.value, ast.Constant) and n.value.value == "true"
            for n in ast.walk(tree))
        if activates and "company_identity" not in src:
            ungated.append(os.path.basename(path))
    assert not ungated, (f"these tools activate a company row without an identity check: "
                         f"{ungated}")


# --- "time.com is Time To Know" — two ways the identity check said yes to a stranger ----
def test_a_common_word_that_is_the_whole_domain_is_not_the_company():
    """`verdict` scored time.com a clean MATCH for "Time To Know": the distinctive token
    "time" IS the entire registrable domain, so the "domain carries no extra content" test
    passed — and `repair_dead_urls` moved the row to TIME magazine's careers page. A name
    word missing from the domain makes the evidence suggestive, not conclusive."""
    from pipeline.company_identity import verdict
    assert verdict("Time To Know", "https://time.com/join-time/") == "weak"
    # the shapes this must NOT break
    assert verdict("SAP Israel", "https://jobs.sap.com/") == "match"
    assert verdict("Texas Instruments", "https://careers.ti.com/") == "match"
    assert verdict("Palo Alto Networks", "https://jobs.paloaltonetworks.com/") == "match"
    assert verdict("RADLogics", "https://rad.com/careers") == "mismatch"


def test_confirming_a_weak_domain_needs_the_NAME_not_its_words_scattered():
    """The loose page test — every distinctive word appears somewhere — is what let the
    weak verdict through: TIME's own careers page naturally contains "time" and "know".
    Matching is also per-token now; the old version normalized the page to one letter-run,
    where "…the time. To know more…" literally contains "timetoknow"."""
    from pipeline.company_identity import page_mentions_company
    scattered = "<p>It is time to apply. Get to know the team. We know time matters.</p>"
    assert page_mentions_company("Time To Know", scattered) is True      # loose: unchanged
    assert page_mentions_company("Time To Know", scattered, strict=True) is False
    assert page_mentions_company("Time To Know", "<h1>Time to Know Ltd</h1>", strict=True)
    assert page_mentions_company("Time To Know", "<h1>TimeToKnow</h1>", strict=True)
    assert not page_mentions_company("Wiz", "<p>the time. To know more</p>", strict=True)


# --- a source that quietly stops producing must be LOUD --------------------------------
def test_a_source_that_stops_returning_records_is_reported(tmp_path, monkeypatch):
    """The Bright Data Indeed dataset returned zero records on every run for five days —
    every snapshot came back `dataset_size: 0, error_codes: {"rate_limit": 15}`. The step
    printed "[indeed] 0 records", exited 0, and the workflow was green. Nothing anywhere
    said a source had died, which is why nobody noticed."""
    from pipeline import sources
    monkeypatch.setattr(sources, "PATH", str(tmp_path / "sources.json"))
    today = dt.date.today()
    sources.record({"indeed": 0, "linkedin": 12, "telegram": 40})
    s = sources.stale()
    assert any(x.startswith("indeed: has NEVER returned") for x in s), s
    assert not any(x.startswith("linkedin") for x in s), s

    # a source that produced, then went quiet for three days
    import json
    data = json.load(open(sources.PATH, encoding="utf-8"))
    data["linkedin"]["last_nonzero"] = (today - dt.timedelta(days=3)).isoformat()
    json.dump(data, open(sources.PATH, "w", encoding="utf-8"))
    sources.record({"linkedin": 0})
    assert any(x.startswith("linkedin: nothing for 3d") for x in sources.stale()), sources.stale()


# --- the conflict path was deleting other workflows' cache entries ---------------------
def test_cache_merge_keeps_what_the_other_workflow_cached(tmp_path):
    """`scraped_cache.json` is rewritten wholesale by eight tools across six workflows. The
    push-conflict recovery restored OUR copy — our copy as of CHECKOUT — so every company
    another workflow had cached in between was silently deleted. Same shape as the
    companies.csv incident `merge_csv_rows` exists to prevent, one file along."""
    import merge_json_cache as M
    base = {"A": [1], "B": [2], "C": [3]}
    ours = {"A": [1], "B": [99], "D": [4]}          # we changed B, added D, never had C
    theirs = {"A": [1], "B": [2], "C": [3], "E": [5]}   # another run added E, kept C
    out, _, _ = M.merge(base, ours, theirs)
    assert out["B"] == [99], "this run's own change must win"
    assert out["D"] == [4], "this run's new company must survive"
    assert out["C"] == [3], "a company we never touched must not be deleted"
    assert out["E"] == [5], "another workflow's new company must not be deleted"


def test_oraclehcm_asks_for_israel_instead_of_hoping_it_is_in_the_first_500():
    """`fetch_oraclehcm` walked the newest 500 requisitions and stopped. JPMorganChase
    posts 7,354, so its Israel roles were nowhere near that window and the fetcher reported
    a confident zero — the same shape as a dead source. The CE API takes `keyword=`, the way
    Workday takes `searchText`, so the fetcher runs that pass too (Dell went 2 -> 8 Israel
    roles). Structural check: the query must be built, not just intended."""
    import inspect
    from pipeline import fetchers
    src = inspect.getsource(fetchers.fetch_oraclehcm)
    assert "keyword=Israel" in src, "the Israel keyword pass is gone"
    assert "seen_ids" in src, "the two passes overlap; they must dedupe by requisition id"


def test_page_chrome_is_not_a_job_opening():
    """The universal scraper reads whatever card-shaped text a careers page offers, and on
    ten companies that included the consent banner: "Strictly necessary cookies",
    "Manage Consent Preferences", "Heading 4". One of them — "Analytics Cookies" — carries
    an analytics signal and reached the LLM tier as a candidate ROLE. Filtered on read, so
    it applies to everything already cached. A real title that merely starts with one of
    those words must survive."""
    from pipeline.fetchers import clean_scraped
    def one(t):
        out = clean_scraped([{"title": t}])
        return out[0]["title"] if out else None
    for junk in ("Strictly necessary cookies", "Analytics Cookies", "Performance cookies",
                 "Cookie List", "Cookie Settings", "Consent and Data Privacy",
                 "Manage Consent Preferences", "Heading 4", "Press Releases"):
        assert one(junk) is None, junk
    for real in ("Data Analyst", "Cookie Monster Engineer",
                 "Consent Management Product Manager",
                 "Cookies & Analytics Product Manager",
                 "Senior Analyst, Privacy Notice Automation"):
        assert one(real) == real, real
    # a card whose text ran together with its own call-to-action keeps the role
    assert one("Mumbai, IN Customer Success Specialist - APAC Read more") == \
        "Mumbai, IN Customer Success Specialist - APAC"


def test_no_two_active_rows_scan_the_same_board():
    """50 identity groups had more than one row, and 32 of those pairs pointed at the SAME
    url — "Intel"/"Intel Israel"/"Intel Corporation" all scanning one Workday tenant. Since
    `merge_key` normalizes only a trailing corporate suffix, the roles did not collapse:
    the board listed every Intel opening three times, and three fetches paid for it."""
    import csv
    import collections
    import os
    import urllib.parse
    from pipeline.firmographics import identity_key
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rows = [r for r in csv.DictReader(open(os.path.join(repo, "companies.csv"),
                                           encoding="utf-8")) if r["active"] == "true"]
    seen = collections.defaultdict(list)
    for r in rows:
        u = urllib.parse.urlsplit((r["api_url"] or "").strip().lower().rstrip("/"))
        seen[(identity_key(r["company_name"]), u.netloc, u.path, u.query)].append(
            r["company_name"])
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dupes, f"same company, same board, more than one active row: {list(dupes.values())[:6]}"


def test_the_hunt_never_stores_another_company_s_page_as_the_row_address():
    """The hunt persists its best candidate so a human can see where it looked. But when
    that candidate provably belongs to someone else — QuantLR's was quantlab.com, a US
    trading firm; FairFly's was fireflyspace.com — storing it in `api_url` turns a guess
    into data, and every later tool honestly re-tests the wrong company's careers page and
    records another confident verdict about it. HANDOFF §1c(b): never persist an unverified
    address. The note is text; the note is where it belongs."""
    import inspect
    import listing_hunt
    src = inspect.getsource(listing_hunt.main)
    body = src[src.index('elif verdict == "nolisting"'):]
    guard = body.index("is_foreign(name, url)")
    persist = body.index("fr[3] = url")
    assert guard < persist, "the identity check must gate the address write, not follow it"


def test_a_hyphenated_domain_that_lines_up_token_for_token_is_the_company():
    """ide-tech.com IS IDE Technologies, c2a-sec.com IS C2A Security, bren-energy.com IS
    Brenmiller Energy — all three scored `mismatch`, which blocks a legitimate recovery and
    made the identity report mostly false positives. Two independent tokens agreeing is what
    makes this safe: the ONE-token version of the same rule is precisely the
    rad.com/RADLogics and nooga.net/Noogata false match, so a single-part domain stays out."""
    from pipeline.company_identity import verdict
    assert verdict("IDE Technologies", "https://www.ide-tech.com/en/careers/") == "match"
    assert verdict("C2A Security", "https://c2a-sec.com/careers/") == "match"
    assert verdict("Brenmiller Energy", "https://bren-energy.com/careers/") == "match"
    assert verdict("RADLogics", "https://rad.com/careers") == "mismatch"
    assert verdict("Noogata", "https://nooga.net/careers") == "mismatch"
    assert verdict("Tamar Robotics", "https://arbe-robotics.com/careers") == "mismatch"


def test_making_room_in_the_note_drops_old_segments_whole():
    """Every writer made room the same way — slice the base — and the newest segment lives
    at the END of the base. That is how 87 rows came to say `dark-triage 2026-08-22:
    page-emp` (also `page-e`, and on one row `pa`), and how Somatix ended up with
    `dark-triage 2026-08-22:` and no mode at all. A mode no filter matches drops the row
    out of whichever pool keys on it — the documented #1 bug class here."""
    from pipeline.notes import append, replace_own
    base = ("aggregator URL (builtin.com-class global listing) auto-parked 2026-08-22 — "
            "would attribute third-party jobs; needs real careers page | "
            "dark-triage 2026-08-22: page-empty")
    seg = "listing-hunt 2026-08-23: no IL listing; monitored candidate"
    out = append(base, seg)
    assert len(out) <= 220
    assert "dark-triage 2026-08-22: page-empty" in out, "the newest prior verdict was cut"
    assert out.endswith(seg)
    # a re-stamp replaces only this tool's own segment, never another tool's
    again = replace_own(out, "listing-hunt", "listing-hunt 2026-08-24: no listing found")
    assert "dark-triage 2026-08-22: page-empty" in again
    assert "2026-08-23" not in again and again.endswith("no listing found")
    # a single oversized segment keeps its head rather than emitting a different verdict
    assert len(append("", "x" * 300)) == 220


def test_every_note_writer_uses_the_append_log_helper():
    """Structural: a new tool that hand-rolls `(base + seg)[:220]` re-introduces the bug
    above, silently, on rows nobody is looking at."""
    import glob
    import os
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for path in glob.glob(os.path.join(root, "*.py")) + glob.glob(
            os.path.join(root, "pipeline", "*.py")):
        name = os.path.basename(path)
        if name in ("notes.py", "check_invariants.py", "merge_csv_rows.py"):
            continue
        src = open(path, encoding="utf-8").read()
        # every shape of "slice the base to make room": [:220], 220 - len(x), cap - len(x)
        if re.search(r"\)\[:220\]|(220|cap|NOTE_CAP) *- *len\(", src):
            offenders.append(name)
    assert not offenders, (f"these still slice a note by hand instead of using "
                           f"pipeline.notes.append: {offenders}")


@pytest.mark.parametrize("company,url,flagged", [
    # the five false positives that failed the gate and withheld a day's digest: only the
    # COMPANY side was normalized, so "G-STAT" -> "gstat" never matched the slug "g-stat"
    ("G-STAT", "https://www.linkedin.com/jobs/view/data-analyst-at-g-stat-4452928552", False),
    ("Port.io", "https://www.linkedin.com/jobs/view/senior-bi-analyst-at-port-io-4448277590", False),
    ("Checkout.com", "https://www.linkedin.com/jobs/view/fraud-data-analyst-at-checkout-com-4411198404", False),
    # a requisition number inside the TITLE ended a non-greedy match before the employer
    ("Experis Israel", "https://www.linkedin.com/jobs/view/business-data-analyst-241239-at-experis-israel-4411198404", False),
    # two letters cannot carry identity, and a percent-encoded Hebrew slug is not evidence
    ("EY", "https://www.linkedin.com/jobs/view/%D7%9E%D7%A0%D7%AA%D7%97-4411198404", False),
    # ...and the real thing it exists to catch
    ("Menora Mivtachim Group", "https://il.linkedin.com/jobs/view/data-analyst-25455-at-yael-group-4449299472", True),
    ("IEC", "https://il.linkedin.com/jobs/view/bi-developer-at-central-bottling-company-israel-ltd-4451515278", True),
    ("Riskified", "https://www.riskified.com/careers/1", False),
])
def test_linkedin_slug_attribution(company, url, flagged):
    """LinkedIn's URL is the only place a scraped card states who is actually hiring — 147
    board rows were once published under the wrong employer. But the check compared a
    normalized company against an un-normalized slug, so on 2026-08-23 it flagged five good
    rows, and ONE of them failed the blocking invariant gate and withheld the whole day's
    digest, board and email."""
    from pipeline.company_identity import url_names_other_company
    assert url_names_other_company(company, url) is flagged


def test_a_page_that_does_not_claim_to_list_jobs_cannot_activate_a_row():
    """`SCRAPE_ASSUME_IL=1` makes the hunt treat every card on a page as an Israel role, so
    a navigation menu scores exactly like a board: `iai.co.il/solution/research-academy-space`
    "verified 6 IL" whose titles were "Design and Integration", "Domain Operations" and
    "Press Releases", and it was activated twice — once by the hunt, once by the extract-gap
    repair. Adcore's row was a BLOG post whose three "jobs" were article titles."""
    from pipeline.company_identity import looks_like_a_job_listing_page as ok
    for bad in ("https://www.iai.co.il/solution/research-academy-space/",
                "https://www.adcore.com/blog/chatgpt-search-engine-optimization/",
                "https://www.cognifit.com/research",
                "https://www.ginasoftware.com/solutions/search-and-rescue-software/",
                "https://www.ey.com/en_us/israel"):
        assert not ok(bad), bad
    for good in ("https://www.tevapharm.com/your-career/",
                 "https://www.comeet.com/jobs/hub-technologies/07.00F",
                 "https://careers.amd.com/careers-home/jobs?location=Israel",
                 "https://jobs.apple.com/en-us/search?location=israel-ISR",
                 "https://www.xtend.me/working-at-xtend",
                 "https://orbia-orbia-precision-agriculture-netafim.teamtailor.com",
                 "https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX",
                 "https://servicenow.willhire.co/"):
        assert ok(good), good


def test_every_active_scrape_row_points_at_something_that_claims_to_list_jobs():
    import csv
    import os
    from pipeline.company_identity import looks_like_a_job_listing_page as ok
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = [r["company_name"] for r in csv.DictReader(
        open(os.path.join(repo, "companies.csv"), encoding="utf-8"))
        if r["active"] == "true" and r["ats_platform"] == "scrape"
        and not ok(r["api_url"] or "")]
    assert not bad, f"active scrape rows on a page that is not a listings page: {bad}"


def test_a_first_scan_company_is_shown_honestly_rather_than_withheld():
    """`_posted_in` refuses to call a first-scan company's back catalogue "posted in the
    last 48h" — 336 companies were activated in one night and their whole history would
    otherwise have buried the actual news. But withholding them entirely produced a
    zero-role email on a day the pipeline had just gained 336 employers. They go in the
    email under their own heading, with "date not published" rather than a bare dash next
    to a line that claims 48h freshness."""
    from pipeline import digest as D
    jobs = [{"company": "Acme", "title": "Senior Data Analyst", "location": "Tel Aviv",
             "url": "https://a/1", "posted_date": "2026-08-23", "description": "x"},
            {"company": "Newco", "title": "BI Developer", "location": "Haifa",
             "url": "https://b/2", "posted_date": "", "description": "y",
             "_new_company": True}]
    title, body = D.build_markdown(jobs, "2026-08-23", {"first_scan": 1, "new": 1})
    assert title.startswith("🎯 1 new senior analytics role")   # counts only the 48h ones
    assert "Newly covered companies (1)" in body
    assert "date not published" in body
    assert body.index("Senior Data Analyst") < body.index("Newly covered companies")

    # ...and when there is nothing 48h-fresh, the subject says what the email IS
    only_new = [j for j in jobs if j.get("_new_company")]
    title2, body2 = D.build_markdown(only_new, "2026-08-23", {"first_scan": 1, "new": 0})
    assert "newly covered companies" in title2
    # ...and it must not say "no new openings" directly above a section listing some
    assert "_No new matching openings today._" not in body2
    assert "Nothing posted in the last 48h at a company we already track" in body2


def test_the_blocking_gate_blocks_on_corruption_not_on_one_bad_row():
    """The gate runs without continue-on-error immediately before the digest commits, so
    anything it calls a violation costs the whole day: no digest, no board, no email. On
    2026-08-23 ONE false-positive attribution row did exactly that. Shape and identity
    corruption still block (they make the registry unreadable or make the merge drop edits
    silently); a handful of unowned or unscannable rows warn. A FLOOD of orphans is a pool
    collapse and still blocks — that is check D's actual purpose."""
    import check_invariants as C
    src = open(C.__file__, encoding="utf-8").read()
    def section(letter, nxt):
        return src[src.index(f"# {letter}. "):src.index(f"# {nxt}. ")]
    assert "bad(" in section("A", "B"), "a malformed row must still block"
    assert "bad(" in section("B", "C"), "a duplicate company_name must still block"
    assert "bad(" not in section("C", "D"), "one unscannable row must not withhold the digest"
    assert "ORPHAN_BLOCK_AT" in section("D", "E"), "check D must have a flood threshold"
    assert "bad(" in section("E", "F"), "a collapsed re-check pool must still block"
    assert C.ORPHAN_BLOCK_AT >= 1


def test_a_native_ats_row_points_at_that_ats():
    """Imperva's row said `ats_platform=workday` with its own careers HTML as the endpoint,
    so every run POSTed to it, got HTML, and logged "Expecting value: line 1 column 1" —
    one of the four permanent `companies_failed` in every digest, for as long as anyone had
    looked. A 100%-failing row is invisible precisely because it fails every time."""
    import csv
    import os
    import re
    import check_invariants as C
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = [f"{r['company_name']} ({r['ats_platform']}): {r['api_url'][:50]}"
           for r in csv.DictReader(open(os.path.join(repo, "companies.csv"), encoding="utf-8"))
           if r["active"] == "true" and C.PLATFORM_HOST.get(r["ats_platform"])
           and not re.search(C.PLATFORM_HOST[r["ats_platform"]], r["api_url"] or "", re.I)]
    assert not bad, f"rows whose every fetch will fail: {bad}"


@pytest.mark.parametrize("loc,expected", [
    ("תל אביב", True), ("ירושלים", True), ("מחוז המרכז", True),
    ("באר יעקב, מחוז המרכז", True), ("שפלת יהודה, מחוז הדרום", True), ("ישראל", True),
    ("Tel Aviv, Israel", True), ("Ra'anana, Center District, Israel", True),
    ("New York, NY", False), ("Kyiv, Ukraine", False), ("Berlin, Germany", False),
    ("EMEA", False),
])
def test_a_hebrew_location_is_an_israeli_location(loc, expected):
    """`scrape_universal` recognised "תל אביב" when deciding a card was Israeli and stamped
    it as the role's location — and `pipeline.israel` had no Hebrew names at all, so it then
    dropped the role the scraper had just found. An Israeli careers page writes its own
    locations in Hebrew, and Indeed writes them as districts ("מחוז המרכז")."""
    from pipeline.israel import is_israel_job
    assert is_israel_job({"location": loc}) is expected


def test_the_scrapers_location_regex_is_derived_from_both_place_lists():
    """The Hebrew names were a short hard-coded list inside scrape_universal while
    pipeline.israel had none — which is exactly how the two drifted into contradicting
    each other. Check G in check_invariants guards this; so does this."""
    from scrape_universal import ISRAEL_LOC
    from pipeline.israel import _IL_PLACES, _IL_PLACES_HE
    missing = [p for p in _IL_PLACES + _IL_PLACES_HE if not ISRAEL_LOC.search(p)]
    assert not missing, missing
    assert len(_IL_PLACES_HE) > 20, "the Hebrew list should not shrink back to a stub"


def test_discovery_validates_the_company_name_before_queueing_it():
    """The employer field arrives verbatim from the aggregator, and sometimes it is the
    whole posting headline ("Data researcher - Navina") or a staffing agency. Five such rows
    were ACTIVE and fetched daily, every downstream layer grew its own guard against them,
    and the nightly hunt spent a search looking for "AppSec"'s careers page (it came back
    with remoterocketship.com/company/guildmortgage). HANDOFF §4d item 9: validate at the
    source. Structural, because the bridge is a loop with no seam to call."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("discovery_daily.py", "discovery_telegram.py"):
        src = open(os.path.join(root, name), encoding="utf-8").read()
        bridge = src[src.index("auto-expand"):]
        assert "looks_like_junk" in bridge, f"{name} queues job-title-shaped names"
        assert "is_recruiter" in bridge, f"{name} queues agencies"


def test_company_facts_are_not_backslash_escaped_inside_a_code_span():
    """`_md_esc` exists so a scraped company name cannot inject a link or an @mention. But
    inside a code span markdown already takes the text literally, so escaping there only
    PRINTS the backslashes — the first email carrying company facts read
    `\~16,068 employees` · `founded 2005`."""
    from pipeline import digest as D
    jobs = [{"company": "PANW", "title": "Product Analyst", "location": "Tel Aviv",
             "url": "https://x/1", "posted_date": "2026-08-04", "description": "d"}]
    _, body = D.build_markdown(jobs, "2026-08-23", {}, {}, firmographics={
        "PANW": {"sector": "cybersecurity", "stage": "public", "employees_global": 16068,
                 "founded": 2005, "il_center": "Tel Aviv (R&D)"}})
    assert "`~16,068 employees`" in body
    assert "\~" not in body and "\(" not in body


def test_a_role_is_never_listed_in_both_email_sections(tmp_path):
    """`_posted_in` returns on the ISO branch before it reaches the first-scan gate, so a
    role at a brand-new company that DOES state a date inside the 48h window qualifies for
    the main list — and for the "newly covered" list, which selects on the company. It would
    have appeared twice in the same email."""
    from pipeline import store
    st = store.SeenStore(str(tmp_path / "t.db"))
    run = "2026-08-23"
    base = {"location": "TLV", "seniority": "mid", "sources": ["greenhouse"],
            "description": "D" * 500}
    st.upsert_matched({**base, "company": "NewCo", "title": "Data Analyst",
                       "url": "u1", "posted_date": "2026-08-23"}, run)
    st.upsert_matched({**base, "company": "NewCo", "title": "BI Developer",
                       "url": "u2", "posted_date": ""}, run)
    seen_before = {c for (c,) in st.conn.execute(
        "SELECT DISTINCT company FROM matched WHERE first_seen < ?", (run,))}
    assert seen_before == set(), "NewCo must look brand new"
    rows = st.get_matched_since(run)
    dated = [j for j in rows if (j.get("posted_date") or "") >= "2026-08-22"]
    already = {(j["company"], j["title"]) for j in dated}
    first_scan = [j for j in rows if j["company"] not in seen_before
                  and (j["company"], j["title"]) not in already]
    assert [j["title"] for j in dated] == ["Data Analyst"]
    assert [j["title"] for j in first_scan] == ["BI Developer"]
    st.close()


@pytest.mark.parametrize("card,loc", [
    ("Data Analyst  Apply       Tel Aviv", "Tel Aviv"),
    ("Applied Scientist Haifa", "Haifa"),
    ("Analyst Kiryat Gat full-time", "Kiryat Gat"),
    ("IL, Netanya (On-site)", "Netanya"),
    ("Senior BI Developer, Ra'anana", "Ra'anana"),
    ("Tel Aviv, Israel", "Tel Aviv, Israel"),
    ("nothing here", "Israel"),
])
def test_a_scraped_location_is_a_place_not_the_card_around_it(card, loc):
    """The scraper took a fixed 12-character window either side of the place name, which
    starts and ends MID-WORD and drags in whatever the card put next to the location: real
    board rows read "Apply       Tel Av" and "d Scientist Haifa". The location is what the
    reader uses to decide whether to apply, so it has to be a place."""
    from scrape_universal import _loc_from_ctx
    assert _loc_from_ctx(card) == loc


# --- docs: a confident document that is no longer true (SCHEDULING.md said the email was
# --- unbuilt for three days after it shipped; HANDOFF listed two load-bearing modules as
# --- "safe to delete" while retry_unreachable imports one of them nightly) -------------
def test_docs_are_consistent_with_the_code():
    """The docs are a build artifact and this is their test.

    `docs/check_docs.py` fails when a doc names a file that no longer exists, when the
    schedule table disagrees with the workflow crons, when a root module is unclassified in
    `docs/MODULES.md`, when a module called legacy is imported by live code, or when
    HANDOFF.md grows back into a 753-line archive. Run it directly for the report:
    `python docs/check_docs.py`."""
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run([sys.executable, os.path.join(root, "docs", "check_docs.py")],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=root)
    assert proc.returncode == 0, "docs/check_docs.py failed:\n" + (proc.stdout or "") + (proc.stderr or "")
