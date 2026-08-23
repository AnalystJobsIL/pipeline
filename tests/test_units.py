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


# --- discovery lane, 2026-08-23: four silent-exclusion bugs in the intake layer ---------
def test_telegram_records_source_health_before_its_early_return():
    """`discovery_telegram.main()` returned as soon as a scan produced nothing — and the
    `sources.record` call sat AFTER that return. So the one mechanism built to notice a dead
    source (written because the Bright Data Indeed dataset returned zero for five days
    unseen) could never see Telegram: on 2026-08-23 `cloud_state/source_health.json` had
    keys for indeed/linkedin/linkedin-targeted and no `telegram` key at all, while
    `discovered_cache.json` held 104 telegram-sourced jobs. A source that cannot report a
    zero cannot be reported dead."""
    import ast
    import inspect
    import discovery_telegram
    tree = ast.parse(inspect.getsource(discovery_telegram.main))
    body = tree.body[0].body
    first_return = next((i for i, n in enumerate(body) if isinstance(n, ast.Return)), len(body))
    called_before = {
        n.func.id for i, stmt in enumerate(body) if i < first_return
        for n in ast.walk(stmt) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_health" in called_before, (
        "source-liveness must be recorded before main()'s first return, or a zero-yield "
        "run leaves Telegram invisible to pipeline/sources.stale()")


def test_telegram_health_counts_posts_parsed_not_posts_merged():
    """It recorded `len(added)` — jobs left after deduping against discovered_cache.json.
    A channel producing normally but repeating roles we already hold would have recorded 0
    and been reported as a dead source."""
    import ast
    import inspect
    import discovery_telegram
    call = [n for n in ast.walk(ast.parse(inspect.getsource(discovery_telegram.main)))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_health"]
    assert len(call) == 1 and ast.unparse(call[0].args[0]) == "len(new_jobs)"


def test_targeted_discovery_window_rotates_over_every_stale_company():
    """`stale.json` is rebuilt every digest in companies.csv row order, so `unresolved[:20]`
    was a stable prefix: the same 20 companies went to Bright Data every day and the other
    90 (of 110, measured 2026-08-23) were never searched once. Same records per run, whole
    list covered."""
    import discovery_daily
    stale = {f"Co{i}": {"reason": "empty-board"} for i in range(100)}
    real = discovery_daily._load_json
    discovery_daily._load_json = lambda path: stale if "stale" in path else {}
    try:
        seen, sizes = set(), set()
        for day in range(1, 61):
            window = discovery_daily._targeted_inputs(cap=20, day=day)
            sizes.add(len(window))
            seen.update(q["company"] for q in window)
        assert sizes == {20}, f"per-run Bright Data spend must not change: {sizes}"
        assert seen == set(stale), f"{len(set(stale) - seen)} companies never targeted"
    finally:
        discovery_daily._load_json = real


def test_the_targeted_sweep_scopes_by_company_not_by_keyword_text():
    """The dataset takes a dedicated `company` input. This built
    `keyword: "<name> data analyst"` instead, so LinkedIn ranked on "data analyst" and
    treated the employer name as spare tokens. A/B tested live 2026-08-23 over the same 20
    stale companies: keyword-text form billed 160 records and returned 0 for any of them;
    the `company` form billed 25 and returned 22 on-target. Scoping is also ~6x cheaper,
    because an unscoped query always fills `limit_per_input` while a scoped one returns only
    what that employer has."""
    import discovery_daily
    stale = {"Outbrain": {"reason": "empty-board"}, "Deel": {"reason": "regressed-to-zero"}}
    real = discovery_daily._load_json
    discovery_daily._load_json = lambda path: stale if "stale" in path else {}
    try:
        got = discovery_daily._targeted_inputs(day=1)
    finally:
        discovery_daily._load_json = real
    assert {q["company"] for q in got} == set(stale), "the employer must be its own field"
    for q in got:
        assert q["keyword"] == "data analyst",             "the company name must NOT be concatenated into the keyword — that is the bug"


def test_the_targeted_window_never_asks_about_the_same_company_twice():
    """`cap` is 100 and the targetable list is 88 long, so the wrap-around
    `(unresolved + unresolved)[start:start + cap]` handed back 12 duplicate names — and a
    duplicate input is a second bill for rows we already have. Found by running it."""
    import discovery_daily
    stale = {f"Co{i}": {"reason": "empty-board"} for i in range(88)}
    real = discovery_daily._load_json
    discovery_daily._load_json = lambda path: stale if "stale" in path else {}
    try:
        for day in (1, 7, 200, 366):
            names = [q["company"] for q in discovery_daily._targeted_inputs(cap=100, day=day)]
            assert len(names) == len(set(names)) == 88, (day, len(names), len(set(names)))
    finally:
        discovery_daily._load_json = real


def test_targeted_discovery_skips_rows_whose_board_is_not_actually_broken():
    """`misconfig-scrape-on-ats` is a warning about the ROW SHAPE, not a broken board — the
    digest reads those companies fine every morning. 22 of the 110 stale entries on
    2026-08-23 were that reason, i.e. a fifth of the sweep's inputs bought nothing."""
    import discovery_daily
    assert "misconfig-scrape-on-ats" not in discovery_daily._TARGETABLE
    assert set(discovery_daily._TARGETABLE) == {"empty-board", "regressed-to-zero", "fetch-error"}


def test_indeed_source_health_counts_raw_records_like_every_other_source():
    """`per_source["indeed"]` held post-filter, post-dedup jobs while the dataset sources
    held raw records, so one number meant two things — and an Indeed page whose cards were
    all rejected (junior/stale) would have scored as a DEAD SOURCE. pipeline/sources.py
    answers 'did this source return anything', which is a property of the source."""
    import ast
    import inspect
    import discovery_daily
    src = inspect.getsource(discovery_daily.main)
    assigns = [ast.unparse(n) for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.Assign) and ast.unparse(n).startswith("per_source['indeed']")]
    assert assigns == ["per_source['indeed'] = n_indeed_raw"], assigns


@pytest.mark.parametrize("name,expected", [
    # Both were live employer names in ONE Indeed query on 2026-08-23 and both passed
    # is_recruiter() AND looks_like_junk() — one auto-expand run from a registry row.
    ('קומבלק איי.טי. בע"מ', True),      # Comblack IT — `comblack` was already in _CONFIRMED
    ("חברה דיסקרטית", True),            # "discreet company" = the Hebrew `confidential`
    # ...and two more of the same shape, from the 99 companies one live intake pass queued
    ("קבוצת יעל", True),                # Yael Group — `yael group` was already in _CONFIRMED
    ("לוג-און תוכנה", True),            # Log-On Software — `log-on software` likewise
    # researched, not guessed: its own posting advertises a role at an unnamed client
    ('עידור מחשבים בע"מ', True),
    # ...and researched-and-KEPT: Matrix is 16k staff and we already scan two of its boards
    ("מטריקס", False),
    ("Matrix IT", False),
    ("Software AG-SPL", False),
    # ...and the real Hebrew-named employers next to them in the same registry must not move
    ("IBI בית השקעות", False),
    ("בנק דיסקונט", False),
    ("מנורה מבטחים החזקות", False),
    ("IEC - Israel Electric Corporation חברת החשמל לישראל בע\"מ", False),
])
def test_a_hebrew_spelling_does_not_walk_past_a_latin_recruiter_entry(name, expected):
    from pipeline.recruiters import is_recruiter
    assert is_recruiter(name) is expected


# --- discovery lane, round 2: the breadth sweep was discovering nothing -----------------
def test_the_breadth_sweep_is_deep_and_recency_filtered():
    """It returned 0 new companies — 29 jobs, 27 employers, 25 already registry rows and 11
    staffing agencies. `limit_per_input` was 15, and LinkedIn ranks by relevance, so the
    sweep re-read a saturated head every day. Unknown companies live in the TAIL and the
    yield accelerates with depth (1 new at 15 records, 15 at 100), while `time_range` makes
    depth self-limiting: "Past week" billed 61 against a limit of 100 and overlapped the
    unfiltered run by only 14/61. Measured together: 391 records -> 147 employers ->
    58 NEW companies, against 0."""
    import discovery_daily
    _ds, _by, inputs, limit = discovery_daily.QUERIES["linkedin"]
    assert limit >= 50, "a shallow breadth sweep only ever re-reads the saturated head"
    assert inputs and all(q.get("time_range") for q in inputs),         "without a recency window every run re-ranks the same employers"
    assert all("company" not in q for q in inputs),         "the breadth sweep must stay UNSCOPED — scoping it to known companies is what made "         "the targeted sweep incapable of returning an unknown employer"


def test_discovery_reports_new_companies_per_source():
    """New companies per source is what this layer exists to produce, and nothing printed
    it — only the aggregate. That is how the breadth sweep came to yield 0 while its record
    count looked healthy. A source can be alive, on-budget and useless at once."""
    import ast
    import inspect
    import discovery_daily
    src = inspect.getsource(discovery_daily.main)
    assert "yield_by_src" in src
    fmts = [ast.unparse(n) for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.JoinedStr) and "NEW companies" in ast.unparse(n)]
    assert fmts, "the per-source yield line must be printed, not just computed"


def test_indeed_search_retries_and_names_its_failure_mode():
    """An unlocker exception, a bot wall with no mosaic blob, and a genuinely empty result
    set all collapsed to a bare `[]`, and the caller printed "0 cards" for all three —
    ARCHITECTURE.md section 8 item 2, a mass zero read as a measurement. Observed
    2026-08-23: "business intelligence" returned 0 on two consecutive runs and 15 on the
    retry, so it was never empty. Roughly 2 of 5 queries were failing silently."""
    import discovery_daily
    import bd_rescue
    calls = {"n": 0}
    blob = ('window.mosaic.providerData["mosaic-provider-jobcards"] = '
            '{"metaData":{"mosaicProviderJobCardsModel":{"results":[{"jobkey":"a"}]}}};')
    def flaky(url, timeout=90):
        calls["n"] += 1
        return "" if calls["n"] == 1 else blob        # fail once, then succeed
    real = bd_rescue.unlock
    bd_rescue.unlock = flaky
    try:
        got = discovery_daily.indeed_search("x")
    finally:
        bd_rescue.unlock = real
    assert calls["n"] == 2, "a transient unlocker failure must be retried, not reported as 0"
    assert [r["jobkey"] for r in got] == ["a"]


def test_discovery_spend_is_pro_rated_so_a_source_never_goes_dark_mid_month():
    """Depth is what makes the breadth sweep discover anything (0 -> 58 new companies/day),
    but a sweep that spends the month's quota by the 24th returns ZERO for the last week of
    every month — and a silent zero from a source that used to produce is the worst failure
    mode in this repo. Measured 2026-08-23: the ledger said 2,989 records spent of an assumed
    5,000 with 9 days left, i.e. 223/day sustainable against the ~455/day just shipped."""
    import datetime as dt
    import discovery_daily as dd
    real_ledger, real_budget = dd.bd_spend_this_month, dd.BD_MONTHLY_BUDGET
    try:
        # a generous plan changes nothing: both sweeps run flat out
        dd.bd_spend_this_month = lambda today=None: (0, 0)
        dd.BD_MONTHLY_BUDGET = 50_000
        assert dd.plan_spend(today=dt.date(2026, 9, 1))[:2] == (dd.LINKEDIN_LIMIT_MAX, 100)
        # a tight one throttles depth but never to zero, and never below the old shipped 15
        dd.BD_MONTHLY_BUDGET = 5_000
        breadth, targeted, _ = dd.plan_spend(today=dt.date(2026, 9, 1))
        assert dd.LINKEDIN_LIMIT_MIN <= breadth < dd.LINKEDIN_LIMIT_MAX
        assert breadth >= 15, "must never throttle below the depth that yielded 1 new company"
        # ...and BREADTH is served before the targeted backfill, because breadth is the
        # discovery source and the backfill only ever asks about companies we already have
        assert targeted < breadth
        # an unreadable ledger must NOT throttle — that would be a silent failure of its own
        dd.bd_spend_this_month = lambda today=None: (None, None)
        assert dd.plan_spend()[:2] == (dd.LINKEDIN_LIMIT_MAX, 100)
    finally:
        dd.bd_spend_this_month, dd.BD_MONTHLY_BUDGET = real_ledger, real_budget


def test_bd_spend_ledger_never_raises():
    """Spend reporting runs inside the daily discovery step; if it can throw, it can kill a
    run that has already done its useful work. `/customer/balance` is 403 for this token, so
    the snapshot ledger is the only spend number this repo can produce — but it is still a
    network call in the middle of a cron job."""
    import discovery_daily as dd
    real = dd.urllib.request.urlopen
    def boom(*a, **k):
        raise OSError("network down")
    dd.urllib.request.urlopen = boom
    try:
        assert dd.bd_spend_this_month() == (None, None)
        dd.report_bd_spend()          # must print, not raise
    finally:
        dd.urllib.request.urlopen = real


# --- registry lane, 2026-08-24: five bugs in the re-check pools and the search ladder -----
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
