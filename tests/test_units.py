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
    ("UserWay", "https://www.levelaccess.com/careers/", True),   # only identity_facts can pass this
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
    address. The note is text; the note is where it belongs.

    2026-08-24: the gate here was `is_foreign(name, url)`, which returns False for every ATS
    host by design — so on a walled ATS this branch had no gate at all and persisted the
    candidate anyway. It is now `_identity_ok`, which falls through to
    `IG.ok_to_write` (page must name the company) on ATS hosts and keeps
    `is_foreign` everywhere else. Strictly stronger; the assertion follows it."""
    import inspect
    import listing_hunt
    src = inspect.getsource(listing_hunt.main)
    body = src[src.index('elif verdict == "nolisting"'):]
    guard = body.index("_gate.identity_ok(name, url)")
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
    import inspect

    import discovery_daily
    # depth: it walks pages rather than taking a fixed shallow slice
    assert discovery_daily.LINKEDIN_PAGES >= 2,         "a shallow breadth sweep only ever re-reads the saturated head"
    src = inspect.getsource(discovery_daily.linkedin_search)
    # recency: f_TPR is LinkedIn's time-posted filter, in seconds
    assert "f_TPR" in src, "without a recency window every run re-ranks the same employers"
    # unscoped: scoping the breadth sweep to known companies is exactly what made the
    # targeted sweep incapable of ever returning an unknown employer
    assert "company" not in src.split("urlencode", 1)[1].split(")", 1)[0]
    assert discovery_daily._LI_KEYWORDS, "the breadth sweep needs keywords to sweep on"


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
        # A tight budget must NOT throttle breadth: it is billed per REQUEST (at most
        # LINKEDIN_PAGES x keywords, ~18, and usually 0 because the guest endpoint is free),
        # so throttling it saves nothing and starves the discovery source. The per-RECORD
        # targeted backfill is what absorbs a tight month.
        # NOTE this assertion used to read `targeted < breadth`, which is why it passed for
        # hours while the backfill was starved to zero at every budget under ~31,000/month:
        # 0 < 15 is true. Assert what must be TRUE, not what happens to hold.
        dd.BD_MONTHLY_BUDGET = 5_000
        breadth, targeted, _ = dd.plan_spend(today=dt.date(2026, 9, 1))
        assert breadth == dd.LINKEDIN_LIMIT_MAX, "breadth is per-request; never throttle it"
        assert targeted > 0, "the backfill is the only cover for 15 zero-reporting rows"
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


def test_the_shared_bd_search_cap_is_per_process_not_per_day():
    """`DEEP_BD_SEARCH_CAP` reads like a daily ceiling of 150 and is not one: `_BD` is a
    module-level dict, so the count resets in every process, and SIX scripts import
    `google_via_unlocker` in processes of their own (resolve_broken 06:00, listing_hunt
    19:00, crack_walled 19:00, repair_dead_urls, deep_validate Sat, audit_empty_rows Sun).
    Effective ceiling ~450 credits on a weekday and ~750 at the weekend against a shared
    5,000/month pool; observed peak 272 in a day. This guard exists so the next reader of
    that constant is not misled — it asserts the SHAPE that makes it per-process."""
    import deep_validate
    assert isinstance(deep_validate._BD, dict) and "used" in deep_validate._BD
    importers = set()
    import ast
    import glob
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in glob.glob(os.path.join(root, "*.py")):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module == "deep_validate":
                if any(a.name == "google_via_unlocker" for a in n.names):
                    importers.add(os.path.basename(path))
    assert len(importers) >= 4, (
        "if this shrank, the per-process cap may finally be safe — re-check "
        "docs/BACKLOG.md item 6 before relaxing it: " + str(sorted(importers)))


def test_linkedin_cards_are_parsed_per_card_not_by_zipping_field_lists():
    """The public search is read for ~60 cards per Unlocker credit, so the parser matters:
    running one regex per field over the whole page and zipping the lists shifts every
    pairing after a card that is missing a location, and a job attributed to the wrong
    employer is the failure this repo guards hardest against (147 board rows were published
    under the wrong company once). Cards are split on `data-entity-urn` and each field is
    read INSIDE its own block; a card that cannot be attributed is skipped, never guessed."""
    from discovery_daily import _li_cards
    page = (
        '<li><div class="base-card" data-entity-urn="urn:li:jobPosting:111">'
        '<a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/a-111">'
        '<span class="sr-only"> Senior Data Analyst </span></a>'
        '<h4 class="base-search-card__subtitle"><a href="#">Alpha Ltd</a></h4>'
        '<span class="job-search-card__location">Tel Aviv, Israel</span>'
        '<time datetime="2026-08-20"></time></div></li>'
        # NO location on this one — the shift that a zip-based parser gets wrong
        '<li><div class="base-card" data-entity-urn="urn:li:jobPosting:222">'
        '<a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/b-222">'
        '<span class="sr-only"> BI Developer </span></a>'
        '<h4 class="base-search-card__subtitle"><a href="#">Beta Inc</a></h4>'
        '<time datetime="2026-08-21"></time></div></li>'
        # no title/company at all: must be dropped, not paired with the next card's fields
        '<li><div class="base-card" data-entity-urn="urn:li:jobPosting:333"></div></li>')
    got = _li_cards(page)
    assert [c["job_id"] for c in got] == ["111", "222"]
    assert got[0]["company"] == "Alpha Ltd" and got[0]["title"] == "Senior Data Analyst"
    assert got[0]["location"] == "Tel Aviv, Israel"
    assert got[1]["company"] == "Beta Inc" and got[1]["title"] == "BI Developer"
    assert got[1]["location"] == "Israel", "a missing location must default, never borrow"
    assert got[1]["posted_date"] == "2026-08-21"


def test_the_breadth_sweep_is_billed_per_request_not_per_record():
    """The two Bright Data products bill differently and the gap is ~39x: the dataset charges
    1 credit per RECORD (391 jobs = 391 credits from ONE trigger), the Unlocker charges 1
    credit per REQUEST and a public-search page carries ~60 cards. Measured 2026-08-23: the
    full 4-keyword sweep costs 10 Unlocker credits against 391 dataset records. If the
    breadth sweep ever goes back to run_query_raw, the bill goes up ~39x silently."""
    import inspect

    import discovery_daily
    main = inspect.getsource(discovery_daily.main)
    breadth = main.split("TARGETED backfill", 1)[0]
    assert "linkedin_search" in breadth
    assert "run_query_raw" not in breadth,         "the breadth sweep must not use the per-record dataset path"
    # and the per-source credit count must stay visible — it IS the bill
    assert "UNLOCKER_CALLS" in main


def test_breadth_uses_many_plain_keywords_not_one_clever_boolean_query():
    """LinkedIn's public search caps at ~80 distinct jobs PER QUERY, not per keyword, so a
    combined `("data analyst" OR "data scientist" OR ...)` search buys ONE window instead of
    nine. Measured 2026-08-23, same baseline: the OR query returned 50 employers and 10 new
    companies for 2 credits; nine separate queries returned 184 employers and 76 new for 18.
    Sixteen credits for sixty-six companies. The keyword list is long and flat on purpose."""
    import discovery_daily as dd
    assert len(dd._LI_KEYWORDS) >= 6, "width is the only dial that works against the cap"
    for kw in dd._LI_KEYWORDS:
        assert " OR " not in kw.upper(), (
            f"{kw!r}: combining terms into one query collapses nine result windows into one")
    # two requests reach all 80; a third is pure waste
    assert dd.LINKEDIN_PAGES == 2, (
        "the cap is 80 distinct jobs and two pages reach it — more pages bill for nothing, "
        "fewer leave ~25% of the window unread")


# --- adversarial review, 2026-08-23: defects the rewrite introduced the same day --------
def test_a_cards_block_cannot_run_past_the_end_of_its_own_li():
    """The LAST card on a page had an unbounded block, so it absorbed anything later in the
    document carrying the same class names — and LinkedIn's right-rail "people also viewed"
    is built from the same `base-search-card` component with NO jobPosting urn, so it is not
    a boundary. A last card missing its own subtitle emitted a LONDON "Senior Manager" at
    "Acme Corp" as a Tel Aviv job dated today, carrying the previous card's id.
    `url_names_other_company` passes it because company and url are wrong together."""
    from discovery_daily import _li_cards, _li_urn_ids
    page = (
        '<li><div class="base-card" data-entity-urn="urn:li:jobPosting:111">'
        '<a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/a-111">'
        '<span class="sr-only"> Data Analyst </span></a>'
        '<h4 class="base-search-card__subtitle">'
        '<a href="https://www.linkedin.com/company/alpha">Alpha</a></h4>'
        '<span class="job-search-card__location">Tel Aviv, Israel</span>'
        '<time datetime="2026-08-20"></time></div></li>'
        '<li><div class="base-card" data-entity-urn="urn:li:jobPosting:222">'
        '<span class="sr-only"> Senior Manager </span></div></li>'
        '<section><a class="base-card__full-link" href="https://uk.linkedin.com/jobs/view/z-9">'
        '<h4 class="base-search-card__subtitle">'
        '<a href="https://www.linkedin.com/company/acme-uk">Acme Corp</a></h4>'
        '<span class="job-search-card__location">London, United Kingdom</span>'
        '<time datetime="2026-08-23"></time></a></section>')
    got = _li_cards(page)
    assert [c["job_id"] for c in got] == ["111"], "the tail card must be dropped, not merged"
    assert all("London" not in c["location"] for c in got)
    assert len(_li_urn_ids(page)) == 2, "and the drop must still be COUNTED"


def test_discovery_never_asserts_israel_just_because_the_query_asked_for_it():
    """Every normalizer stamped `country_code: "IL"` because the QUERY said Israel, and
    `israel.is_israel_job` short-circuits on country_code before it reads any text — so the
    pipeline's only geo gate was a no-op for the entire discovery layer. Anything that leaked
    past a request-level location filter published as an Israeli role."""
    import inspect

    import discovery_daily
    from pipeline.israel import is_israel_job
    for fn in (discovery_daily.linkedin_normalize, discovery_daily.indeed_normalize,
               discovery_daily.workable_normalize, discovery_daily.normalize):
        src = inspect.getsource(fn)
        assert '"country_code": "IL"' not in src, f"{fn.__name__} still asserts IL"
    assert is_israel_job({"location": "London, United Kingdom", "country_code": "",
                          "url": "https://uk.linkedin.com/jobs/view/z"}) is False
    assert is_israel_job({"location": "Tel Aviv, Israel", "country_code": "", "url": ""}) is True


def test_the_budget_split_charges_breadth_what_it_actually_costs():
    """`left = per_day - breadth_limit * n_kw` reserved 15x9=135 credits/day for a sweep
    billed per REQUEST at 18 — and because `breadth` was itself derived from `per_day`, the
    remainder was always `per_day mod n_kw`, i.e. 0-8 NO MATTER HOW BIG THE BUDGET. The
    targeted backfill — the only cover for 15 active rows whose own board reports zero — was
    starved at every budget under ~31,000/month, while printing "budget reserved for the
    breadth sweep", which reserved nothing."""
    import datetime as dt

    import discovery_daily as dd
    real_l, real_b = dd.bd_spend_this_month, dd.BD_MONTHLY_BUDGET
    dd.bd_spend_this_month = lambda today=None: (0, {})
    try:
        for budget in (5_000, 15_000, 31_000):
            dd.BD_MONTHLY_BUDGET = budget
            _breadth, targeted, _how = dd.plan_spend(today=dt.date(2026, 9, 1))
            assert targeted > 0, f"targeted starved at budget {budget}"
    finally:
        dd.bd_spend_this_month, dd.BD_MONTHLY_BUDGET = real_l, real_b


def test_an_exhausted_guest_pool_is_not_a_block_and_costs_nothing():
    """Two opposite bugs in the same branch. Treating an HTTP-200-empty guest reply as a
    SUCCESS killed the keyword with no message and no fallback (a mass zero read as a
    measurement). Treating it as a BLOCK paid the Unlocker to re-read a pool already
    drained — 2 credits per keyword for nothing. It is a block only when we have no cards
    yet."""
    import discovery_daily as dd
    import bd_rescue
    calls = {"paid": 0}
    def never_paid(url, timeout=120):
        calls["paid"] += 1
        return ""
    real_guest, real_unlock = dd._li_guest, bd_rescue.unlock
    card = ('<li><div class="base-card" data-entity-urn="urn:li:jobPosting:%d">'
            '<a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/a-%d">'
            '<span class="sr-only"> Data Analyst </span></a>'
            '<h4 class="base-search-card__subtitle">A Co</h4></div></li>')
    try:
        bd_rescue.unlock = never_paid
        # page 0 yields cards, page 1 is empty -> pool exhausted, must NOT pay
        seq = [dd._li_cards(card % (1, 1)), []]
        dd._li_guest = lambda kw, loc, d, st: (seq.pop(0) if seq else [], True)
        got = dd.linkedin_search("x", pages=2)
        assert len(got) == 1 and calls["paid"] == 0, (len(got), calls)
        # nothing at all on page 0 -> that IS a block, the paid path must run
        calls["paid"] = 0
        had = os.environ.get("BRIGHTDATA_API_KEY")
        os.environ["BRIGHTDATA_API_KEY"] = "test"
        try:
            dd._li_guest = lambda kw, loc, d, st: ([], True)
            dd.linkedin_search("x", pages=1)
            assert calls["paid"] == 1, "a first-page zero must fall through to the Unlocker"
        finally:
            if had is None:
                os.environ.pop("BRIGHTDATA_API_KEY", None)
            else:
                os.environ["BRIGHTDATA_API_KEY"] = had
    finally:
        dd._li_guest, bd_rescue.unlock = real_guest, real_unlock


def test_a_partial_bright_data_ledger_reads_as_unknown_not_as_truth():
    """When zone/cost failed it still returned the dataset-only sum — 2,989 instead of 4,106
    on 2026-08-23, 60% instead of 82% — which lets budget_per_day over-spend AND stops the
    80% warning ever firing. budget_per_day already handles None correctly."""
    import discovery_daily as dd
    real = dd._bd_get
    def only_snapshots(url):
        if "snapshots" in url:
            return [{"created": "2026-08-10T05:00:00Z", "dataset_size": 100}]
        raise OSError("zone/cost down")
    dd._bd_get = only_snapshots
    try:
        import datetime as dt
        mtd, parts = dd.bd_spend_this_month(today=dt.date(2026, 8, 23))
        assert mtd is None, f"a partial ledger must be None, got {mtd}"
        assert dd.budget_per_day(today=dt.date(2026, 8, 23)) is None
    finally:
        dd._bd_get = real


def test_an_undated_card_does_not_become_immortal():
    """Both the write-side prune (`if d and d < cut`) and the read-side TTL
    (`not posted_date or ...`) skip undated jobs, and `_alive()` refreshes `last_seen` every
    day the entry sits in the cache — so a card with no <time datetime> never leaves the
    board. Worse, this run's copy wins the (company,title) merge, so one undated card turns
    a normal job permanent."""
    import datetime as dt

    from discovery_daily import linkedin_normalize
    j = linkedin_normalize({"job_id": "1", "title": "Data Analyst", "company": "A Co",
                            "location": "Tel Aviv, Israel", "posted_date": "", "url": "u",
                            "company_slug": "a-co"})
    assert j["posted_date"] == dt.date.today().isoformat()


def test_a_junior_posting_still_contributes_its_employer():
    """The junior cut ran inside normalize(), so the job never entered `jobs` and its
    EMPLOYER never reached the names harvest. ARCHITECTURE 1a states the opposite intent —
    the breadth sweep's product is employer names — so an unknown Israeli company whose only
    past-week analyst ad says "Junior" was invisible to discovery forever."""
    from discovery_daily import linkedin_normalize
    j = linkedin_normalize({"job_id": "1", "title": "Junior Data Analyst", "company": "New Co",
                            "location": "Haifa, Israel", "posted_date": "2026-08-20",
                            "url": "u", "company_slug": "new-co"})
    assert j is not None and j["_junior"] is True and j["company"] == "New Co"


def test_a_corrupt_job_cache_aborts_the_telegram_merge_instead_of_wiping_it():
    """`_load_json(path, [])` collapsed ABSENT and CORRUPT into an empty list, and the merge
    writes that list back — so one half-written file deletes every cached job. The watermark
    advances in the SAME run, which is what makes it unrecoverable: the exact mechanism that
    cost 79 verified roles on 2026-08-21."""
    import os
    import tempfile

    import discovery_telegram as dt
    d = tempfile.mkdtemp()
    good, bad = os.path.join(d, "g.json"), os.path.join(d, "b.json")
    with open(good, "w", encoding="utf-8") as f:
        f.write('[{"company":"A","title":"B"}]')
    with open(bad, "w", encoding="utf-8") as f:
        f.write('[{"company":"A","title":"B"')      # truncated mid-write
    assert dt._load_cache(good) == [{"company": "A", "title": "B"}]
    assert dt._load_cache(os.path.join(d, "absent.json")) == []   # absent is legitimately []
    with pytest.raises(dt.CacheUnreadable):
        dt._load_cache(bad)


def test_a_decorated_telegram_post_does_not_shift_every_field_by_one():
    """The secrethunter format is POSITIONAL — lines[0..2] are title/company/city — so one
    decoration-only header line makes the JOB TITLE the company name, and that fabricated
    employer passes both is_recruiter and looks_like_junk into the auto-expand queue."""
    from discovery_telegram import parse_post
    body = ["Senior Data Analyst", "Riskified", "Tel Aviv", "01/01/26",
            "SQL, Python", "Senior", "https://x.co/1"]
    plain = parse_post(list(body), "2026-08-23")
    decorated = parse_post(["\U0001F525\U0001F525\U0001F525"] + body, "2026-08-23")
    assert plain["company"] == decorated["company"] == "Riskified"
    assert plain["title"] == decorated["title"] == "Senior Data Analyst"


def test_indeed_search_with_zero_tries_does_not_raise():
    """`why` was only bound inside the loop, so tries=0 hit UnboundLocalError on the final
    print instead of returning an empty list."""
    from discovery_daily import indeed_search
    assert indeed_search("x", tries=0) == []


# --- third-wave verdict, 2026-08-23: what the first round of fixes still got wrong -----
def test_a_hard_blocked_guest_endpoint_still_gets_every_paid_page():
    """The first fix moved the bug rather than removing it: `if i and out` became
    `elif out:`, which still does not test `ok` — so once any cards existed, a HARD BLOCK
    broke the loop before reaching the paid fallback and only `start=0` was ever fetched.
    That is the documented GitHub-runner case, ~20 of 80 cards lost per keyword, while the
    credits-per-card line reported a flattering 60/credit."""
    import discovery_daily as dd
    import bd_rescue
    paid = []
    card = ('<li><div class="base-card" data-entity-urn="urn:li:jobPosting:%d">'
            '<a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/a-%d">'
            '<span class="sr-only"> Data Analyst </span></a>'
            '<h4 class="base-search-card__subtitle">A Co</h4></div></li>')
    def fake_unlock(url, timeout=120):
        paid.append(url)
        return card % (100 + len(paid), 100 + len(paid))
    real_guest, real_unlock = dd._li_guest, bd_rescue.unlock
    had = os.environ.get("BRIGHTDATA_API_KEY")
    os.environ["BRIGHTDATA_API_KEY"] = "test"      # the paid path is gated on a key existing
    try:
        bd_rescue.unlock = fake_unlock
        dd._li_guest = lambda kw, loc, d, st: ([], False)      # blocked from the first page
        got = dd.linkedin_search("x", pages=2)
        assert len(paid) == 2, f"a blocked guest must use the whole paid budget, got {paid}"
        assert "start=0" in paid[0] and "start=25" in paid[1], paid
        assert len(got) == 2
    finally:
        dd._li_guest, bd_rescue.unlock = real_guest, real_unlock
        if had is None:
            os.environ.pop("BRIGHTDATA_API_KEY", None)
        else:
            os.environ["BRIGHTDATA_API_KEY"] = had


def test_one_blank_guest_page_is_not_proof_the_pool_is_finished():
    """The guest endpoint emits intermittent 200-empty pages INSIDE the result pool. Stopping
    at the first one saw 55 of 71 reachable jobs on a measured live walk — a 23% silent loss
    per keyword, every run, with no message and no fallback. Free requests, so probing past a
    blank is nearly free."""
    import discovery_daily as dd
    card = ('<li><div class="base-card" data-entity-urn="urn:li:jobPosting:%d">'
            '<a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/a-%d">'
            '<span class="sr-only"> Data Analyst </span></a>'
            '<h4 class="base-search-card__subtitle">A Co</h4></div></li>')
    pages = [dd._li_cards(card % (1, 1)), [], dd._li_cards(card % (2, 2)), [], [], []]
    real = dd._li_guest
    try:
        dd._li_guest = lambda kw, loc, d, st: ((pages.pop(0), True) if pages else ([], True))
        got = dd.linkedin_search("x", pages=1)
        assert {c["job_id"] for c in got} == {"1", "2"}, \
            "a card AFTER a blank page must still be collected"
    finally:
        dd._li_guest = real


@pytest.mark.parametrize("shape", [{}, [], {"c": {"custom": {"renamed": 1}}}])
def test_an_unrecognised_zone_cost_shape_reads_as_unknown_not_as_zero(shape):
    """Only an EXCEPTION was treated as unreadable. An HTTP 200 in an unrecognised shape —
    empty dict, a list, renamed keys, or a wrong/empty BRIGHTDATA_ZONE — produced a confident
    0 + 0, so the ledger reported 2,989 instead of 4,106 (60% instead of 82%): the exact
    under-count this function exists to prevent, silently, with the 80% warning unable to
    fire and budget_per_day over-permitting."""
    import datetime as dt

    import discovery_daily as dd
    real = dd._bd_get
    dd._bd_get = lambda u: ([{"created": "2026-08-10T05:00:00Z", "dataset_size": 2989}]
                            if "snapshots" in u else shape)
    try:
        mtd, _parts = dd.bd_spend_this_month(today=dt.date(2026, 8, 23))
        assert mtd is None, f"unrecognised zone/cost must be unknown, got {mtd}"
    finally:
        dd._bd_get = real


@pytest.mark.parametrize("fn,rec", [
    ("workable_normalize", {"id": "1", "title": "Data Analyst",
                            "company": {"title": "A Co"}, "location": {"city": "Haifa"},
                            "url": "u"}),
    ("indeed_normalize", {"displayTitle": "Data Analyst", "company": "A Co", "jobkey": "k"}),
    ("normalize", None),
])
def test_no_normalizer_emits_an_undated_job(fn, rec):
    """An undated job is skipped by BOTH the write-side prune (`if d and d < cut`) and the
    read-side TTL (`not posted_date or ...`) while `_alive()` refreshes last_seen every day —
    so it never leaves the board. The fix had been applied to linkedin_normalize only, and
    then the brand-new Workable source re-introduced it on EVERY record by reading
    `published`/`created_at`, neither of which that API sends (the field is `created`)."""
    import datetime as dt

    import discovery_daily as dd
    j = (dd.normalize("linkedin", {"job_title": "Data Analyst", "company_name": "A Co"})
         if rec is None else getattr(dd, fn)(rec))
    assert j["posted_date"] == dt.date.today().isoformat()


def test_workable_reads_the_field_names_the_api_actually_sends():
    """`published` and `created_at` are not keys in the payload — the date is `created`, and
    the location sub-key is `subregion`, not `region`. Live keys 2026-08-23: benefitsSection
    company created department description employmentType id isFeatured language location
    locations requirementsSection socialSharingDescription state title updated url workplace;
    location: city countryName subregion."""
    from discovery_daily import workable_normalize
    j = workable_normalize({"id": "7", "title": "BI Developer", "created": "2026-08-19T09:00:00Z",
                            "company": {"title": "A Co", "website": "https://a.co"},
                            "location": {"subregion": "Northern District"}, "url": "https://u"})
    assert j["posted_date"] == "2026-08-19"
    assert j["location"] == "Northern District, Israel"
    assert j["careers_hint"] == "https://a.co", "the employer's own site is why this source exists"


@pytest.mark.parametrize("fn,rec", [
    ("indeed_normalize", {"displayTitle": "Junior Data Analyst", "company": "NewCo",
                          "jobkey": "k"}),
    ("workable_normalize", {"id": "1", "title": "Junior Data Analyst",
                            "company": {"title": "NewCo"}, "location": {"city": "Haifa"},
                            "url": "u"}),
])
def test_every_source_keeps_a_junior_postings_employer(fn, rec):
    """The flag-do-not-drop reasoning was applied to one of four normalizers, so an unknown
    Israeli employer whose only past-week analyst ad says "Junior" stayed invisible to three
    of the four sources."""
    import discovery_daily as dd
    j = getattr(dd, fn)(rec)
    assert j is not None and j["_junior"] is True and j["company"] == "NewCo"


def test_the_keyless_sources_survive_a_missing_bright_data_key():
    """The key gate was an early `return` sitting above Workable, the LinkedIn guest endpoint
    AND `sources.record()` — so a rotated secret took the whole intake layer dark, including
    the half that needs no key, and silenced the mechanism built to notice that."""
    import ast
    import inspect

    import discovery_daily
    # Walk EVERY Return in main(), at any nesting depth. The first version of this test
    # looked only at TOP-LEVEL returns, found none (main's only `return` is nested inside
    # `if cacheable:`), and passed through its own `or first_return == len(body)` escape
    # without asserting anything — it would have passed with the bug reinstated.
    tree = ast.parse(inspect.getsource(discovery_daily.main)).body[0]
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    assert not returns, (
        "main() must have NO return: every early exit sat above the keyless sources "
        "(Workable, the LinkedIn guest endpoint) and above sources.record(), so a missing "
        "key or a corrupt cache took the free half of the layer dark AND silenced the "
        f"detector built to notice. Found {len(returns)} at lines "
        f"{[n.lineno for n in returns]}")
    src = inspect.getsource(discovery_daily.main)
    for required in ("workable_search", "linkedin_search", "sources.record"):
        assert required in src, f"{required} must run"


def test_telegram_does_not_assert_israel_either():
    """`is_israel_job` short-circuits on country_code, so stamping "IL" here made the geo gate
    a no-op for 104 of the 205 cached jobs. The location always ends ", Israel", so the text
    scan reaches the same answer honestly."""
    from discovery_telegram import parse_post
    from pipeline.israel import is_israel_job
    j = parse_post(["Data Analyst", "Explorium", "Tel Aviv", "01/01/26", "SQL", "Senior",
                    "https://x/1"], "2026-08-23")
    assert j["country_code"] == ""
    assert is_israel_job(j) is True




# --- fourth-wave re-verdict, 2026-08-23 -------------------------------------------------
def test_the_free_walk_is_not_bounded_by_the_paid_dial():
    """`for i in range(pages * 6)` tied the FREE guest walk to `LINKEDIN_PAGES`, the PAID
    budget dial that every docstring here invites tuning. It capped the walk at 12 pages and
    `LINKEDIN_PAGES=0` returned [] for every keyword in silence. Worse, the "~80 jobs per
    query" cap that justified it was measured on the PAID /jobs/search page and is wrong for
    the guest endpoint: measured 2026-08-23, `analytics` has 201 jobs / 148 employers and
    `data scientist` 162 / 106, against which linkedin_search was shipping TEN."""
    import inspect

    import discovery_daily as dd
    src = inspect.getsource(dd.linkedin_search)
    assert "range(LINKEDIN_GUEST_PAGES)" in src, "the free walk needs its own bound"
    assert "range(pages * 6)" not in src
    # 40 is a floor, not the dial: the 2026-08-24 run ended four keywords on the 30-page cap
    # with 206-269 jobs collected and the pool not exhausted, so 30 is measured-insufficient.
    assert dd.LINKEDIN_GUEST_PAGES >= 40


def test_one_repeated_page_does_not_end_a_keyword():
    """The guest endpoint's paging is unstable and re-serves a window it has already given.
    `if not fresh: break` killed the keyword on the first repeat, making the yield
    nondeterministic across runs minutes apart (16 jobs vs 100) — and the low run reads as
    keyword saturation, which sends the next reader to the wrong dial entirely."""
    import discovery_daily as dd
    card = ('<li><div class="base-card" data-entity-urn="urn:li:jobPosting:%d">'
            '<a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/a-%d">'
            '<span class="sr-only"> Data Analyst </span></a>'
            '<h4 class="base-search-card__subtitle">A Co</h4></div></li>')
    p1, p2 = dd._li_cards(card % (1, 1)), dd._li_cards(card % (2, 2))
    pages = [p1, p1, p2, p1, p1, p1]          # a repeat, then MORE jobs, then a dead tail
    real = dd._li_guest
    try:
        dd._li_guest = lambda kw, loc, d, st: ((pages.pop(0), True) if pages else ([], True))
        got = dd.linkedin_search("x", pages=1)
        assert {c["job_id"] for c in got} == {"1", "2"}, \
            "a repeated page must be stepped over, not treated as the end of the pool"
    finally:
        dd._li_guest = real


def test_a_blank_page_does_not_disarm_the_everything_is_billed_alarm():
    """The blank branch incremented `linkedin_free`, so under a soft block the end-of-sweep
    warning `paid and not free` could never fire — the precise case the blank tolerance was
    written for. A blank is a request MADE, not a request that PRODUCED."""
    import inspect

    import discovery_daily as dd
    src = inspect.getsource(dd.linkedin_search)
    blank_branch = src.split("elif ok:", 1)[1].split("if not ok or", 1)[0]
    assert 'SOURCE_PATH["linkedin_blank"]' in blank_branch
    assert 'SOURCE_PATH["linkedin_free"]' not in blank_branch


def test_the_targeted_sweep_records_a_zero_when_it_does_not_run():
    """`elif not targeted_cap:` covered the no-budget case and missed the one its own comment
    named — a HEALTHY stale.json with nothing to target. The key then stopped being written,
    `sources.stale()` kept reading the frozen last_run, and the digest printed
    `linkedin-targeted: nothing for Nd` every morning forever: a death report for a source
    that was working perfectly and had nothing to do."""
    import ast
    import inspect

    import discovery_daily as dd
    # Structural, not textual: the first version of this test grepped the source and matched
    # the phrase inside the COMMENT that explains the fix, so it failed on correct code.
    tree = ast.parse(inspect.getsource(dd.main)).body[0]
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.If) and ast.unparse(n.test) == "targeted")
    assert node.orelse, "`if targeted:` needs an else branch"
    assert not (len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)), (
        "an `elif` here covers only the no-budget case and misses the HEALTHY one — "
        "a stale.json with nothing to target")
    assert any(ast.unparse(n) == "per_source['linkedin-targeted'] = 0"
               for n in node.orelse), ast.unparse(node.orelse)


def test_a_null_valued_zone_cost_is_unknown_not_zero():
    """The guard was key-PRESENCE. A JSON `null` passes `"reqs_unblocker" in cost` and
    `int(None or 0)` then yields a confident, silent 0 — the same under-count, narrower."""
    import datetime as dt

    import discovery_daily as dd
    real = dd._bd_get
    shape = {"myzone": {"custom": {"reqs_unblocker": None, "reqs_serp": None}}}
    dd._bd_get = lambda u: ([{"created": "2026-08-10T05:00:00Z", "dataset_size": 150}]
                            if "snapshots" in u else shape)
    try:
        mtd, _ = dd.bd_spend_this_month(today=dt.date(2026, 8, 23))
        assert mtd is None, f"null-valued counters must read as unknown, got {mtd}"
    finally:
        dd._bd_get = real


def test_a_valid_list_of_non_dicts_does_not_destroy_the_cache():
    """`[1, 2, 3]` passes the isinstance-list check and is then silently emptied by the
    `isinstance(p, dict)` filter in the merge — the one corrupt shape that still overwrote
    the cache with this run's jobs alone."""
    import inspect

    import discovery_daily as dd
    src = inspect.getsource(dd.main)
    assert "not any(isinstance(x, dict) for x in prev)" in src


def test_the_better_careers_lead_wins_when_two_sources_find_one_company():
    """Sources run Indeed-first, so a company found by BOTH Indeed and Workable kept Indeed's
    POSTING url and discarded Workable's `company.website` — degrading the single thing that
    source exists to provide (docs/BACKLOG.md item 2)."""
    import inspect

    import discovery_daily as dd
    src = inspect.getsource(dd.main)
    assert "_real_lead" in src and 'j.get("careers_hint")' in src
    assert '_v.pop("_real_lead", None)' in src, "the internal flag must not reach the queue"


# --- discovery lane, 2026-08-24: the city windows and the free walk's depth ---


def test_city_queries_never_pay_even_when_the_guest_endpoint_is_blocked():
    """The city windows are free-only BY CONSTRUCTION: they pass pages=0, which the paid
    fallback gate reads as 'no paid budget'. Bright Data at 97% of pool taught why this must
    be structural — a blocked runner multiplying the paid worst case by the city product
    would triple the breadth bill in silence."""
    import discovery_daily as dd
    import bd_rescue
    calls = {"paid": 0}
    def never_paid(url, timeout=120):
        calls["paid"] += 1
        return ""
    real_guest, real_unlock = dd._li_guest, bd_rescue.unlock
    had = os.environ.get("BRIGHTDATA_API_KEY")
    os.environ["BRIGHTDATA_API_KEY"] = "test"
    try:
        bd_rescue.unlock = never_paid
        dd._li_guest = lambda kw, loc, d, st: ([], False)   # hard block on every page
        got = dd.linkedin_search("data analyst", pages=0, location="Haifa, Israel")
        assert got == [] and calls["paid"] == 0, (got, calls)
    finally:
        dd._li_guest, bd_rescue.unlock = real_guest, real_unlock
        if had is None:
            os.environ.pop("BRIGHTDATA_API_KEY", None)
        else:
            os.environ["BRIGHTDATA_API_KEY"] = had


def test_the_drift_denominator_is_keyed_per_query_not_per_keyword():
    """LI_CARDS_PRESENT was keyed by keyword. The city windows re-run the same keywords, so
    two queries would merge into one entry and main()'s pop-after-first would charge the
    second query's cards to nobody — under-counting the parser-drift denominator."""
    import discovery_daily as dd
    real_guest = dd._li_guest
    def one_urn_page(kw, loc, d, st):
        if st > 0:
            return [], True
        dd._li_last_present[0] = {f"{kw}|{loc}"}
        card = ('<li><div class="base-card" data-entity-urn="urn:li:jobPosting:1">'
                '<a class="base-card__full-link" href="https://il.linkedin.com/jobs/view/a-1">'
                '<span class="sr-only"> T </span></a>'
                '<h4 class="base-search-card__subtitle">A Co</h4></div></li>')
        return dd._li_cards(card), True
    try:
        dd._li_guest = one_urn_page
        dd.LI_CARDS_PRESENT.clear()
        dd.linkedin_search("x", pages=0, location="Israel")
        dd.linkedin_search("x", pages=0, location="Haifa, Israel")
        assert ("x", "Israel") in dd.LI_CARDS_PRESENT
        assert ("x", "Haifa, Israel") in dd.LI_CARDS_PRESENT
    finally:
        dd._li_guest = real_guest
        dd.LI_CARDS_PRESENT.clear()


def test_the_query_plan_is_national_paid_city_free():
    """National queries keep the paid fallback (pages=None -> LINKEDIN_PAGES); city queries
    carry pages=0. The split is what keeps plan_spend's '~N paid worst case' line truthful
    without plan_spend knowing the cities exist."""
    import discovery_daily as dd
    qs = dd._li_queries()
    national = [(kw, loc, pg) for kw, loc, pg in qs if loc == "Israel"]
    city = [(kw, loc, pg) for kw, loc, pg in qs if loc != "Israel"]
    assert [kw for kw, _, _ in national] == dd._LI_KEYWORDS
    assert all(pg is None for _, _, pg in national)
    assert all(pg == 0 for _, _, pg in city), "a city query with a paid budget can bill"
    assert len(city) == len(dd._LI_CITIES) * len(dd._LI_KEYWORDS), \
        "every keyword gets every city window — the pool is per QUERY"


def test_the_city_list_is_peripheral_only():
    """Measured 2026-08-23: Herzliya added 0 of 20 jobs over the national window and
    Jerusalem 3 of 31 — Tel Aviv metro is already inside the Tel Aviv-weighted national
    search. A metro city added 'for coverage' spends pages on a window we already have."""
    import discovery_daily as dd
    for city in dd._LI_CITIES:
        for metro in ("herzliya", "jerusalem", "tel aviv", "ramat gan", "givatayim"):
            assert metro not in city.lower(), f"{city} is inside the national window already"


def test_a_starved_targeted_cap_skips_the_trigger_loudly(capsys):
    """A cap of 4 (Bright Data pool at 97%, 2026-08-24) still triggered a dataset snapshot,
    polled it for up to 15 minutes, burned a slot in the 22-day targeting rotation and
    returned ZERO records. Below TARGETED_MIN_CAP the trigger is skipped and SAYS so; a cap
    of 0 stays silent because plan_spend's own line already covers it."""
    import discovery_daily as dd
    assert dd._targeted_cap_or_zero(4) == 0
    out = capsys.readouterr().out
    assert "dataset trigger skipped" in out and "cap 4" in out
    assert dd._targeted_cap_or_zero(dd.TARGETED_MIN_CAP) == dd.TARGETED_MIN_CAP
    assert dd._targeted_cap_or_zero(0) == 0
    assert "skipped" not in capsys.readouterr().out, "0 is plan_spend's message, not ours"
    src_main = __import__("inspect").getsource(dd.main)
    assert "_targeted_cap_or_zero" in src_main, "the gate must actually be wired in main()"


# --------------------------------------------------------------------------- #
# ats-fetch lane, 2026-08-24 — see docs/sessions/2026-08-24-ats-fetch.md
# --------------------------------------------------------------------------- #
def _pcsx_position(i, jid, display, locs, std):
    return {"id": jid, "displayJobId": display, "name": f"Role {i}", "locations": locs,
            "standardizedLocations": std, "postedTs": 1786106796, "creationTs": 1786011493,
            "positionUrl": f"/careers/job/{jid}"}


# --- scraper lane, 2026-08-24: render/parse split, error vs empty, the pooled refresh ---
# Every test here is offline: the parse is a pure function of a `Rendered` bundle, the refresh
# is driven by a fake `scrape_result`, and the process pool by a module-level fake worker.

import csv as _csv
import datetime as _dtm
import html as _html
import json as _json
import re as _re
import time as _time
from types import SimpleNamespace as _NS


def _rendered(**kw):
    import scrape_universal as N
    kw.setdefault("url", "https://co.example/careers")
    kw.setdefault("http_status", 200)
    return N.Rendered(**kw)


def _no_fetch(u, t):
    return None, None


def _cards_html(n=4, loc="Tel Aviv, Israel", cls="job-title", footer=""):
    cards = "".join(
        f'<div class="card"><h3 class="{cls}">Senior Data Analyst {i}</h3>'
        f'<span class="loc">{loc}</span><a href="/jobs/{i}">Apply</a></div>' for i in range(n))
    return f"<html><body><h1>Careers</h1>{cards}<footer>{footer}</footer></body></html>"


def test_scrape_extracts_from_next_data_blob():
    """Strategy 1: a Next.js state blob with an array of titled objects becomes jobs, carrying
    the posting's own id and ISO date."""
    import scrape_universal as N
    blob = _json.dumps({"props": {"pageProps": {"jobs": [
        {"title": "Senior Data Analyst", "location": "Tel Aviv, Israel",
         "url": "https://co.example/jobs/1", "id": "1", "datePosted": "2026-08-20T10:00:00Z"},
        {"title": "BI Developer", "location": "Haifa", "url": "/jobs/2", "id": "2"}]}}})
    jobs, strategy = N._extract("Co", "https://co.example/careers", _rendered(blobs=[blob]),
                                fetch=_no_fetch)
    assert strategy == "structured" and [j["title"] for j in jobs] == ["Senior Data Analyst", "BI Developer"]
    assert jobs[0]["posted_date"] == "2026-08-20" and jobs[0]["job_id"] == "1"
    assert jobs[1]["url"] == "https://co.example/jobs/2"       # relative urls are joined
    assert jobs[0]["country_code"] == "" and jobs[0]["ats_platform"] == "scrape"


def test_scrape_recovers_a_job_object_from_a_body_that_is_not_valid_json():
    """The last-ditch brace scan: an XHR body that fails json.loads still yields the flat
    objects inside it."""
    import scrape_universal as N
    body = 'callback({"title":"Data Analyst","location":"Herzliya","id":"7"}); junk'
    jobs, strategy = N._extract("Co", "https://co.example/careers", _rendered(bodies=[body]),
                                fetch=_no_fetch)
    assert strategy == "structured" and [j["title"] for j in jobs] == ["Data Analyst"]
    # Playwright marshals a function-valued window global as None; a body can be a dict
    jobs, _ = N._extract("Co", "https://co.example/careers", _rendered(blobs=[None, body], bodies=[{"x": 1}]),
                         fetch=_no_fetch)
    assert [j["title"] for j in jobs] == ["Data Analyst"]


def test_scrape_dom_links_need_israel_context_near_the_title():
    """Strategy 2 accepts a link only when it looks like a posting AND an Israel token sits
    within 220 characters of the title — a footer address 300 characters away is not a
    location, and an /about-us link is not a posting."""
    import scrape_universal as N
    far = "x" * 300
    dom = [{"title": "Senior Data Analyst", "url": "https://co.example/jobs/1",
            "ctx": "Senior Data Analyst Herzliya Full-time"},
           {"title": "Data Engineer", "url": "https://co.example/jobs/2",
            "ctx": "Data Engineer " + far + " Tel Aviv"},
           {"title": "Product Analyst", "url": "https://co.example/about-us",
            "ctx": "Product Analyst Tel Aviv"}]
    jobs, strategy = N._extract("Co", "https://co.example/careers", _rendered(dom=dom),
                                fetch=_no_fetch)
    assert strategy == "dom" and [(j["title"], j["location"]) for j in jobs] == [("Senior Data Analyst", "Herzliya")]


def test_scrape_card_headings_need_three_siblings_and_role_titles():
    """Strategy 3 wants at least three same-class headings that read like roles; two cards, or
    a group of department labels, is not a board."""
    import scrape_universal as N
    url = "https://co.example/careers"
    jobs, strategy = N._extract("Co", url, _rendered(page_html=_cards_html(4)), fetch=_no_fetch)
    assert strategy == "cards" and len(jobs) == 4
    # (`_loc_from_ctx` keeps up to 28 characters before "Israel" when the card carries no
    # punctuation between title and place — pre-existing, filed in docs/BACKLOG.md)
    assert jobs[0]["location"].endswith("Tel Aviv, Israel")
    assert jobs[0]["url"] == "https://co.example/jobs/0"
    jobs, _ = N._extract("Co", url, _rendered(page_html=_cards_html(2)), fetch=_no_fetch)
    assert jobs == []
    labels = "".join(f"<h3>{t}</h3><span>Tel Aviv</span>" for t in ("Sales", "Marketing", "Product", "Legal"))
    jobs, _ = N._extract("Co", url, _rendered(page_html=f"<body>{labels}</body>"), fetch=_no_fetch)
    assert jobs == []


def test_scrape_cards_without_locations_need_an_il_url_or_assume_il(monkeypatch):
    """A card with no location is kept only when the listing itself is Israel-scoped: the URL
    says so, or `SCRAPE_ASSUME_IL=1` AND the page carries an Israel token. The flag must
    never widen beyond that — with no token on the page it accepts nothing."""
    import scrape_universal as N
    monkeypatch.delenv("SCRAPE_ASSUME_IL", raising=False)
    plain = _cards_html(4, loc="")
    assert N._extract("Co", "https://co.example/careers", _rendered(page_html=plain), fetch=_no_fetch)[0] == []
    jobs, _ = N._extract("Co", "https://co.example/careers?location=Israel", _rendered(page_html=plain), fetch=_no_fetch)
    assert len(jobs) == 4 and {j["location"] for j in jobs} == {"Israel"}
    monkeypatch.setenv("SCRAPE_ASSUME_IL", "1")
    assert N._extract("Co", "https://co.example/careers", _rendered(page_html=plain), fetch=_no_fetch)[0] == []
    with_footer = _cards_html(4, loc="", footer="HQ: 3 Aba Eban, Herzliya")
    jobs, _ = N._extract("Co", "https://co.example/careers", _rendered(page_html=with_footer), fetch=_no_fetch)
    assert len(jobs) == 4


def test_scrape_position_links_use_the_injected_fetcher_and_stop_at_the_deadline():
    """Strategy 4 fetches each same-prefix position page through `fetch` and reads its <h1>;
    an expired company deadline fetches nothing at all."""
    import scrape_universal as N
    url = "https://co.example/careers"
    links = "".join(f'<a href="/careers-position/role-{i}/">Role {i}</a>' for i in range(4))
    page = f"<body><p>We are hiring</p>{links}</body>"
    calls = []

    def fetch(u, t):
        calls.append(u)
        if "/careers-position/" in u:
            n = u.rstrip("/").split("-")[-1]
            return f"<html><h1>Data Analyst {n}</h1><p>Location: Ra'anana</p></html>", 200
        return None, None
    jobs, strategy = N._extract("Co", url, _rendered(page_html=page), fetch=fetch)
    assert strategy == "links" and len(jobs) == 4 and jobs[0]["location"] == "Ra'anana"
    assert sum("/careers-position/" in u for u in calls) == 4
    calls.clear()
    expired = N.Deadline(t_end=_time.monotonic() - 1)
    jobs, _ = N._extract("Co", url, _rendered(page_html=page), fetch=fetch, deadline=expired)
    assert jobs == [] and calls == []


def test_scrape_llm_strategy_is_off_without_the_env_and_uses_the_runner(monkeypatch):
    import scrape_universal as N
    url = "https://co.example/careers?location=Israel"
    page = "<body><h2>Open positions</h2><div>Senior Data Analyst</div><div>BI Developer</div></body>"
    ran = []

    def runner(prompt, timeout_s):
        ran.append(prompt)
        return 'Sure: [{"title": "Senior Data Analyst", "location": ""}]'
    monkeypatch.delenv("SCRAPE_LLM", raising=False)
    jobs, _ = N._extract("Co", url, _rendered(page_html=page), fetch=_no_fetch, llm=runner)
    assert jobs == [] and ran == []
    monkeypatch.setenv("SCRAPE_LLM", "1")
    jobs, strategy = N._extract("Co", url, _rendered(page_html=page), fetch=_no_fetch, llm=runner)
    assert strategy == "llm" and [(j["title"], j["location"]) for j in jobs] == [("Senior Data Analyst", "Israel")]
    assert "Senior Data Analyst" in ran[0]


def test_scrape_strategies_stop_at_the_first_one_that_finds_jobs():
    """Until 2026-08-24 the DOM pass ran even after structured JSON had succeeded, adding
    run-together card blobs beside the clean records: on the captured Port.io page it added
    16 entries with location "Editor Tel Aviv - Israel" — 14 of them Palo Alto roles — to
    the 10 real ones. The first strategy that yields wins; the rest do not run."""
    import scrape_universal as N
    blob = _json.dumps({"jobs": [{"title": "Senior Data Analyst", "location": "Tel Aviv", "id": "1"},
                                 {"title": "BI Developer", "location": "Tel Aviv", "id": "2"},
                                 {"title": "Product Analyst", "location": "Haifa", "id": "3"}]})
    dom = [{"title": "Marketing Analyst Palo Alto Apply now", "url": "https://co.example/jobs/9",
            "ctx": "Marketing Analyst Palo Alto Apply now Editor Tel Aviv - Israel"}]
    jobs, strategy = N._extract("Co", "https://co.example/careers",
                                _rendered(blobs=[blob], dom=dom, page_html=_cards_html(4)), fetch=_no_fetch)
    assert strategy == "structured" and [j["title"] for j in jobs] == ["Senior Data Analyst", "BI Developer", "Product Analyst"]
    # wave 2 (2026-08-24): one or two structured hits can be a "featured posting" widget
    # beside a DOM-rendered board — the DOM pass still runs and adds to them
    featured = _json.dumps({"jobs": [{"title": "Office Manager", "location": "Tel Aviv", "id": "0"},
                                     {"title": "Finance Manager", "location": "Tel Aviv", "id": "0b"}]})
    board = [{"title": t, "url": f"https://co.example/jobs/{i}", "ctx": f"{t} Tel Aviv, Israel"}
             for i, t in enumerate(("Senior Data Analyst", "BI Developer", "Analytics Engineer"), 1)]
    jobs, strategy = N._extract("Co", "https://co.example/careers", _rendered(blobs=[featured], dom=board),
                                fetch=_no_fetch)
    assert strategy == "structured+dom" and len(jobs) == 5


def test_scrape_never_raises_and_scrape_result_reports_the_failure(monkeypatch):
    """`scrape()` is called bare by resolve_deep; it must return [] on any failure. The
    lane's own callers read `scrape_result().status` to tell that failure from an empty board."""
    import scrape_universal as N

    def boom(url, timeout_ms, deadline):
        raise RuntimeError("driver died")
    monkeypatch.setattr(N, "_render", boom)
    assert N.scrape("Co", "https://co.example/careers") == []
    res = N.scrape_result("Co", "https://co.example/careers")
    assert res.status == "error" and res.error == "internal:RuntimeError" and res.jobs == []
    import inspect
    assert str(inspect.signature(N.scrape)) == "(company, url, timeout_ms=45000)"
    for name in ("ISRAEL_LOC", "ROLE", "BAD_TITLE", "_find", "_loc_from_ctx"):
        assert hasattr(N, name), name


@pytest.mark.parametrize("fields,jobs,expected", [
    (dict(http_status=200, page_html="<html><body><h1>Careers</h1><p>No open positions.</p></body></html>"), [], "empty"),
    (dict(http_status=200, page_html="<html></html>"), [], "empty"),   # a JS shell is EMPTY
    (dict(http_status=None, error="goto:TimeoutError"), [], "error"),
    (dict(http_status=None, error="launch:Error"), [], "error"),
    (dict(http_status=403), [], "error"),                       # a block is not "no roles"
    (dict(http_status=404), [], "error"),
    (dict(http_status=503), [], "error"),
    (dict(http_status=200, error="render:TargetClosedError"), [], "error"),
    (dict(http_status=403), [{"title": "x"}], "ok"),            # rescued via plain/unlocker HTML
    (dict(http_status=None, error="goto:TimeoutError", plain_status=200, plain_html="x" * 2500), [], "empty"),
    (dict(http_status=None, error="goto:TimeoutError", plain_status=200, plain_html="x" * 500), [], "error"),
    (dict(http_status=None, error="goto:TimeoutError", plain_status=403, plain_html=""), [], "error"),
    # walls that answer 200: Akamai "Access Denied" (Nokia's and Akamai's own careers pages,
    # captured 2026-08-24), a Cloudflare challenge — unless plain HTTP got a readable page
    (dict(http_status=200, page_html="<html><head><title>Access Denied</title></head><h1>Access Denied</h1></html>"), [], "error"),
    (dict(http_status=200, page_html='<title>Just a moment...</title><div class="cf-browser-verification">'), [], "error"),
    (dict(http_status=200, page_html="<h1>Access Denied</h1>", plain_status=200, plain_html="<html>" + "x" * 3000), [], "empty"),
    (dict(http_status=None, error="goto:TimeoutError", plain_status=200, plain_html="<h1>Access Denied</h1>" + "x" * 3000), [], "error"),
    # a 200 with nothing captured at all is not a page we read
    (dict(http_status=200, page_html="", blobs=[], bodies=[], dom=[]), [], "error"),
    (dict(http_status=200, error="render:TargetClosedError", plain_status=200, plain_html="x" * 2500), [], "empty"),
])
def test_scrape_result_tells_a_broken_page_from_an_empty_board(fields, jobs, expected):
    """Until 2026-08-24 every navigation failure came back as [] — the nightly refresh logged
    0 errors across 433 sites, so a 403 night deleted a company's jobs from the cache and the
    product read it as "no openings". The table in ARCHITECTURE.md §5a, as assertions."""
    import scrape_universal as N
    status, _ = N._classify(_rendered(**fields), jobs)
    assert status == expected


@pytest.mark.parametrize("fixture", ["arm", "xtend"])
def test_new_parse_matches_the_pre_refactor_extractor_on_captured_pages(fixture):
    """Render payloads captured on 2026-08-24 with the extractor as it was BEFORE the
    render/parse split, and the jobs it produced. The split must reproduce them exactly.
    (Only the two DOM-strategy pages were small enough to commit; the other strategies were
    diffed the same way on 23 captured pages in the session record, not in the repo.)"""
    import scrape_universal as N
    here = os.path.dirname(os.path.abspath(__file__))
    fx = _json.load(open(os.path.join(here, "fixtures", "scrape", f"{fixture}.json"), encoding="utf-8"))
    jobs, strategy = N._extract(fx["company"], fx["url"], _rendered(url=fx["url"], dom=fx["dom"]),
                                fetch=_no_fetch)
    assert strategy == "dom" and jobs == fx["expected"]


def test_assume_il_cannot_turn_a_navigation_menu_into_a_board(monkeypatch):
    """`SCRAPE_ASSUME_IL=1` makes every location-less card on an Israel-token page an Israel
    role. The activation gate (`looks_like_a_job_listing_page`) is what catches a nav menu
    with an Israeli footer; the parse itself must at least refuse the obvious shapes — a menu
    of one-word labels, a blog index of sentences, an offices page."""
    import scrape_universal as N
    monkeypatch.setenv("SCRAPE_ASSUME_IL", "1")
    footer = "<footer>Head office: HaMenofim 8, Herzliya, Israel</footer>"
    menu = "".join(f"<h3>{t}</h3>" for t in ("About", "Products", "Solutions", "Press Releases",
                                             "Domain Operations", "Contact", "Blog", "Partners"))
    blog = "".join(f'<h2 class="post-title">{t}</h2>' for t in (
        "Why we moved our data platform to Iceberg", "How our analysts think about churn",
        "What we learned shipping the product analytics suite", "Our engineering values"))
    offices = "".join(f"<h3>{t}</h3>" for t in ("Tel Aviv", "Haifa", "Herzliya", "New York"))
    for page in (menu, blog, offices):
        jobs, _ = N._extract("Co", "https://co.example/solutions/research", _rendered(page_html=page + footer),
                             fetch=_no_fetch)
        assert jobs == [], page[:60]
    assert N._page_is_il("https://co.example/careers", "<html>nothing local here</html>") is False


# ---- the refresh -----------------------------------------------------------------------------
_TODAY = _dtm.date.today().isoformat()


def _il_job(name, n=1):
    return {"company": name, "title": f"Senior Data Analyst {n}", "location": "Tel Aviv",
            "country_code": "", "url": f"https://{name.lower()}.example/jobs/{n}", "posted_date": "",
            "ats_platform": "scrape", "job_id": str(n), "description": ""}


def _refresh_sandbox(tmp_path, monkeypatch, rows, old_cache=None, rot=None, outcomes=None):
    """A registry, cache, rot file and stage file under tmp_path; `outcomes` maps a company
    name to ("ok"|"empty"|"error", detail) and drives a fake `scrape_result`."""
    import refresh_scrape_cache as R
    from pipeline import stages
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = _NS(csv=tmp_path / "companies.csv", cache=tmp_path / "cache.json",
                rot=tmp_path / "rot.json", stages=tmp_path / "stages.json")
    with open(paths.csv, "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(["company_name", "ats_platform", "token", "api_url", "active", "notes"])
        for r in rows:
            w.writerow(r if len(r) == 6 else
                       [r[0], "scrape", "", f"https://{r[0].lower()}.example/careers", "true",
                        r[1] if len(r) > 1 else ""])
    paths.cache.write_text(_json.dumps(old_cache or {}), encoding="utf-8")
    paths.rot.write_text(_json.dumps(rot or {}), encoding="utf-8")
    monkeypatch.setattr(R, "CSV_PATH", str(paths.csv))
    monkeypatch.setattr(R, "CACHE_PATH", str(paths.cache))
    monkeypatch.setattr(R, "ROT_PATH", str(paths.rot))
    monkeypatch.setattr(stages, "PATH", str(paths.stages))
    monkeypatch.delenv("SCRAPE_REFRESH_TIME_BUDGET_MIN", raising=False)
    monkeypatch.delenv("SCRAPE_WORKERS", raising=False)
    outcomes = outcomes or {}

    def fake(name, url, timeout_ms=45000, **kw):
        kind, detail = outcomes.get(name, ("ok", 1))
        if kind == "error":
            return _NS(jobs=[], status="error", error=detail, http_status=403, strategy="",
                       elapsed_s=0.1, rescued=False)
        if kind == "empty":
            return _NS(jobs=[], status="empty", error="", http_status=200, strategy="",
                       elapsed_s=0.1, rescued=False)
        return _NS(jobs=[_il_job(name, i + 1) for i in range(detail)], status="ok", error="",
                   http_status=200, strategy="dom", elapsed_s=0.1, rescued=False)
    monkeypatch.setattr(R, "scrape_result", fake)
    paths.R = R
    paths.stages_mod = stages
    return paths


def _snapshot(*ps):
    return [p.read_bytes() for p in ps]


def _days_ago(n):
    return (_dtm.date.today() - _dtm.timedelta(days=n)).isoformat()


def _rows_by_name(p):
    return {r["company_name"]: r for r in _csv.DictReader(open(p, encoding="utf-8"))}


def test_refresh_carries_jobs_forward_on_error_but_never_on_empty(tmp_path, monkeypatch):
    """A company in this market can have zero openings for a month and still be a healthy
    source. Parking an active scrape row after a 3-day EMPTY streak retired good companies
    and made the next role posted there invisible. Only ERRORS park a row (after
    ROT_PARK_DAYS) and only ERRORS carry yesterday's jobs; a long empty streak just asks
    triage to re-read the page, and the row stays active and scanned."""
    stable = [f"Ok{i}" for i in range(12)]         # keeps the run under the 20% shrink guard
    old = {"Acme": [_il_job("Acme")], "Beta": [_il_job("Beta")], "Delta": [_il_job("Delta")],
           **{n: [_il_job(n)] for n in stable}}
    rot = {"Acme": {"since": _days_ago(7), "why": "error", "last": _days_ago(1), "n": 6},
           "Beta": {"since": _days_ago(60), "why": "empty", "last": _days_ago(1), "n": 59},
           "Delta": {"since": _days_ago(14), "why": "error", "last": _days_ago(1), "n": 13}}
    P = _refresh_sandbox(tmp_path, monkeypatch,
                         [("Acme",), ("Beta",), ("Gamma",), ("Delta",)] + [(n,) for n in stable],
                         old, rot, {"Acme": ("error", "http:403"), "Beta": ("empty", ""),
                                    "Delta": ("error", "goto:TimeoutError")})
    assert P.R.run(["--workers", "1"]) == 0
    cache = _json.loads(P.cache.read_text(encoding="utf-8"))
    assert cache["Acme"] == old["Acme"], "an error carries yesterday's jobs"
    assert "Beta" not in cache, "an empty result carries nothing"
    assert "Delta" not in cache, "the carry expires after CARRY_MAX_DAYS"
    assert len(cache["Gamma"]) == 1
    rot = _json.loads(P.rot.read_text(encoding="utf-8"))
    assert "Acme" not in rot, "a parked row starts with a clean streak when something re-activates it"
    assert rot["Beta"]["why"] == "empty" and rot["Beta"]["n"] == 60 and "Gamma" not in rot
    rows = _rows_by_name(P.csv)
    assert rows["Acme"]["active"] == "false" and rows["Acme"]["notes"].count("scrape rotted (error 7d)") == 1
    assert rows["Delta"]["active"] == "false"
    assert rows["Beta"]["active"] == "true" and rows["Beta"]["notes"].count("empty-but-suspect") == 1
    assert rows["Gamma"]["active"] == "true" and rows["Gamma"]["notes"] == ""
    # a second night: the flag is not appended twice; the parked row is no longer active, so
    # it is not scanned and its segment is not touched
    assert P.R.run(["--workers", "1"]) == 0
    rows = _rows_by_name(P.csv)
    assert rows["Beta"]["notes"].count("empty-but-suspect") == 1
    assert rows["Acme"]["notes"].count("scrape rotted") == 1 and rows["Acme"]["active"] == "false"


def test_refresh_rereads_the_registry_before_parking_and_keeps_other_writers_notes(tmp_path, monkeypatch):
    """Single-writer rule: the registry is re-read immediately before the write, rows are
    matched by name, and another tool's segment written during the run survives."""
    rot = {"Acme": {"since": _days_ago(9), "why": "error", "last": _days_ago(1), "n": 8}}
    P = _refresh_sandbox(tmp_path, monkeypatch, [("Acme", "listing-hunt 2026-08-01: verified 3 IL"), ("Zed",)],
                         {"Acme": [_il_job("Acme")]}, rot, {"Acme": ("error", "http:403")})
    real = P.R.scrape_result

    def racing(name, url, **kw):          # another writer touches the registry mid-run
        rows = list(_csv.reader(open(P.csv, encoding="utf-8")))
        for r in rows:
            if r and r[0] == "Zed":
                r[5] = "dark-triage 2026-08-24: page-empty"
        with open(P.csv, "w", newline="", encoding="utf-8") as f:
            _csv.writer(f).writerows(rows)
        return real(name, url, **kw)
    monkeypatch.setattr(P.R, "scrape_result", racing)
    assert P.R.run(["--workers", "1"]) == 0
    rows = _rows_by_name(P.csv)
    assert rows["Zed"]["notes"] == "dark-triage 2026-08-24: page-empty"
    assert rows["Acme"]["active"] == "false"
    assert "listing-hunt 2026-08-01" in rows["Acme"]["notes"] and "scrape rotted (error 9d)" in rows["Acme"]["notes"]


def test_refresh_mass_failure_guard_refuses_to_rot_park_or_drop(tmp_path, monkeypatch):
    """The night the runner breaks looks like 100 sites erroring at once. Above
    MASS_FAILURE_PCT the run is not a measurement: rot streaks do not advance, nothing is
    parked, the cache keeps every old entry, and the stamp says why. Below the row floor it
    is only an alarm."""
    names = [f"Co{i:02d}" for i in range(25)]
    old = {n: [_il_job(n)] for n in names}
    rot = {n: {"since": _days_ago(8), "why": "error", "last": _days_ago(1), "n": 7} for n in names[:5]}
    outcomes = {n: ("error", "goto:TimeoutError") for n in names[:24]}
    outcomes[names[24]] = ("ok", 2)
    P = _refresh_sandbox(tmp_path / "big", monkeypatch, [(n,) for n in names], old, rot, outcomes)
    before = _snapshot(P.csv, P.rot)
    assert P.R.run(["--workers", "1"]) == 0
    assert _snapshot(P.csv, P.rot) == before, "rot and registry untouched under mass failure"
    cache = _json.loads(P.cache.read_text(encoding="utf-8"))
    assert set(cache) == set(names) and len(cache[names[24]]) == 2
    stamp = _json.loads(P.stages.read_text(encoding="utf-8"))["collect"]
    assert stamp["alarm"].startswith("mass-failure-errors-96%") and stamp["errors"] == 24
    assert stamp["parked"] == 0, "five rows were parkable; a mass-failure night parks none and says so"
    # the floor: 3 of 3 erroring is a bad night for 3 sites, not a broken runner
    P = _refresh_sandbox(tmp_path / "small", monkeypatch, [("A",), ("B",), ("C",)], {"A": [_il_job("A")]},
                         {"A": {"since": _days_ago(8), "why": "error", "last": _days_ago(1), "n": 7}},
                         {n: ("error", "http:503") for n in "ABC"})
    assert P.R.run(["--workers", "1"]) == 0
    assert _json.loads(P.rot.read_text(encoding="utf-8"))["B"]["why"] == "error", "rot advanced"
    assert _rows_by_name(P.csv)["A"]["active"] == "false"
    assert _json.loads(P.stages.read_text(encoding="utf-8"))["collect"]["alarm"] == "errors-100%+no-jobs"


def test_refresh_time_budget_carries_the_unprocessed_and_stamps_the_count(tmp_path, monkeypatch):
    """~850 rows against a 330-minute job: a timeout used to discard the entire run. The
    budget stops cleanly, untouched companies carry over from last night's cache, and the
    stamp says how many."""
    names = ["A", "B", "C", "D", "E"]
    old = {n: [_il_job(n)] for n in names}
    P = _refresh_sandbox(tmp_path, monkeypatch, [(n,) for n in names], old, {}, {"B": ("empty", "")})
    real = P.R.scrape_result

    def slow(name, url, **kw):
        _time.sleep(0.05)
        return real(name, url, **kw)
    monkeypatch.setattr(P.R, "scrape_result", slow)
    monkeypatch.setenv("SCRAPE_REFRESH_TIME_BUDGET_MIN", "0.0005")     # 30 ms
    assert P.R.run(["--workers", "1"]) == 0
    cache = _json.loads(P.cache.read_text(encoding="utf-8"))
    stamp = _json.loads(P.stages.read_text(encoding="utf-8"))["collect"]
    assert stamp["scraped"] == 1 and stamp["unprocessed"] == 4
    assert set(cache) == set(names), "unprocessed companies keep last night's entry"
    assert "unprocessed-4" in stamp["alarm"]


def test_refresh_scoped_and_dry_runs_write_nothing(tmp_path, monkeypatch):
    """`--only`, `--limit`, `--only-missing`, `--shard` and `--dry-run` never touch the
    registry, the rot file, the stamp or the cache; `--apply` on a scoped run MERGES its hits
    into the cache and nothing else."""
    old = {"Acme": [_il_job("Acme")], "Beta": [_il_job("Beta")]}
    rot = {"Acme": {"since": _days_ago(9), "why": "error", "last": _days_ago(1)}}
    P = _refresh_sandbox(tmp_path, monkeypatch, [("Acme",), ("Beta",), ("Gamma",)], old, rot,
                         {"Acme": ("error", "http:403"), "Beta": ("empty", "")})
    P.stages.write_text("{}", encoding="utf-8")
    before = _snapshot(P.csv, P.cache, P.rot, P.stages)
    for argv in (["--only", "Acme,Beta", "--workers", "1"], ["--limit", "2", "--workers", "1"],
                 ["--only-missing", "--workers", "1"], ["--shard", "0", "2", "--workers", "1"],
                 ["--dry-run", "--workers", "1"]):
        assert P.R.run(argv) == 0, argv
        assert _snapshot(P.csv, P.cache, P.rot, P.stages) == before, argv
    assert P.R.run(["--only-missing", "--apply", "--workers", "1"]) == 0
    cache = _json.loads(P.cache.read_text(encoding="utf-8"))
    assert set(cache) == {"Acme", "Beta", "Gamma"}, "additive merge: nothing dropped"
    assert _snapshot(P.csv, P.rot, P.stages) == [before[0], before[2], before[3]]


def test_refresh_stamps_collect_with_counts_the_digest_renders(tmp_path, monkeypatch):
    """Nothing about the scrape reached the email: the workflow stamped `collect` bare. The
    script stamps it with counts; every value is a space-free token so `stages.summary()`
    (k=v joined by spaces, stages by ' | ') renders it in all three digest renderers."""
    P = _refresh_sandbox(tmp_path, monkeypatch, [("Acme",), ("Beta",), ("Gamma",), ("D",), ("E",), ("F",)],
                         {}, {}, {"Beta": ("empty", ""), "Gamma": ("error", "http:403")})
    assert P.R.run(["--workers", "1"]) == 0
    stamp = _json.loads(P.stages.read_text(encoding="utf-8"))["collect"]
    assert {"rows", "scraped", "with_jobs", "empty", "errors", "carried", "unprocessed",
            "parked", "workers", "minutes"} <= set(stamp) and "alarm" not in stamp   # 1/6 errors: no alarm
    for k, v in stamp.items():
        assert _re.fullmatch(r"[A-Za-z0-9_.%+:-]+", str(v)), (k, v)
    line = P.stages_mod.summary()
    assert f"collect: {_TODAY} (TODAY)" in line          # keys render alphabetically (stamp sorts)
    for tok in ("scraped=6", "with_jobs=4", "empty=1", "errors=1", "unprocessed=0"):
        assert f" {tok}" in line.split(" | ")[1], tok
    from pipeline import digest as D
    stats = {"stages": line, "paths": {}}
    _, md = D.build_markdown([], _TODAY, stats)
    assert "with_jobs=4" in md and "with_jobs=4" in D._text_audit(stats)
    assert "with_jobs=4" in D._html_audit(stats, lambda v: _html.escape(str(v)))


def test_refresh_shrink_abort_keeps_the_cache_and_stamps_its_reason(tmp_path, monkeypatch):
    """A run whose rebuilt cache would lose more than 20% of its companies keeps the old
    file (mass-empty is as suspicious as mass-error) — and now says so in the stamp instead
    of returning silently."""
    names = [f"C{i:02d}" for i in range(25)]
    old = {n: [_il_job(n)] for n in names}
    P = _refresh_sandbox(tmp_path / "full", monkeypatch, [(n,) for n in names], old, {},
                         {n: ("empty", "") for n in names[:9]})
    before = _snapshot(P.cache, P.rot, P.csv)
    assert P.R.run(["--workers", "1"]) == 0
    assert _snapshot(P.cache, P.rot, P.csv) == before
    stamp = _json.loads(P.stages.read_text(encoding="utf-8"))["collect"]
    assert stamp["alarm"] == "shrink-abort-25-to-16" and stamp["parked"] == 0
    # wave 1 (2026-08-24): the guard used to compare the whole rebuilt cache, so a night the
    # budget cut short (carried entries padding the count) could drop every processed
    # company's jobs unnoticed. It is measured over what was processed.
    P = _refresh_sandbox(tmp_path / "starved", monkeypatch, [(n,) for n in names], old, {},
                         {n: ("empty", "") for n in names[:19]})
    real = P.R.scrape_result

    def slow(name, url, **kw):
        _time.sleep(0.02)
        return real(name, url, **kw)
    monkeypatch.setattr(P.R, "scrape_result", slow)
    monkeypatch.setenv("SCRAPE_REFRESH_TIME_BUDGET_MIN", "0.0075")     # ~20 rows
    assert P.R.run(["--workers", "1"]) == 0
    stamp = _json.loads(P.stages.read_text(encoding="utf-8"))["collect"]
    assert stamp["alarm"].startswith("shrink-abort-") and stamp["unprocessed"] > 0
    assert _json.loads(P.cache.read_text(encoding="utf-8")) == old
    # ...and it is measured over what was PROCESSED, not the whole cache: 10 of 25 processed,
    # 5 of those lost = 50% (the whole-cache view would say 5 of 25 = 20%, no abort)
    P = _refresh_sandbox(tmp_path / "half", monkeypatch, [(n,) for n in names], old, {},
                         {n: ("empty", "") for n in names[:5]})
    monkeypatch.setattr(P.R, "scrape_result", slow)
    monkeypatch.setenv("SCRAPE_REFRESH_TIME_BUDGET_MIN", "0.0035")     # ~10 rows
    assert P.R.run(["--workers", "1"]) == 0
    stamp = _json.loads(P.stages.read_text(encoding="utf-8"))["collect"]
    assert 8 <= stamp["scraped"] <= 12 and stamp["alarm"].startswith("shrink-abort-")


def test_refresh_pool_and_inline_paths_build_the_same_cache(tmp_path, monkeypatch):
    """Bookkeeping happens in the parent, in registry order: a 3-worker pool and the inline
    loop produce byte-identical cache, rot and counts."""
    import concurrent.futures as cf
    names = [f"Co{i:02d}" for i in range(12)]
    outcomes = {names[1]: ("empty", ""), names[4]: ("error", "http:403"), names[7]: ("ok", 3)}
    old = {names[4]: [_il_job(names[4])]}
    outs = []
    for argv, pool in ((["--workers", "1"], None), (["--workers", "3"], cf.ThreadPoolExecutor)):
        P = _refresh_sandbox(tmp_path / argv[1], monkeypatch, [(n,) for n in names], old, {}, outcomes)
        real = P.R.scrape_result

        def jitter(name, url, **kw):
            _time.sleep(0.01 * (hash(name) % 5))
            return real(name, url, **kw)
        monkeypatch.setattr(P.R, "scrape_result", jitter)
        assert P.R.run(argv, pool_cls=pool) == 0
        stamp = _json.loads(P.stages.read_text(encoding="utf-8"))["collect"]
        for k in ("minutes", "workers", "finished_at"):
            stamp.pop(k)
        outs.append((P.cache.read_bytes(), P.rot.read_bytes(), stamp))
    assert outs[0] == outs[1]


def test_refresh_pool_runs_a_module_level_worker_under_spawn():
    """The Linux/Windows proof: the real ProcessPoolExecutor with the `spawn` context and a
    picklable module-level worker; a worker that raises costs its company, not the run."""
    import refresh_scrape_cache as R
    from fake_scrape_worker import fake_worker
    rows = [{"company_name": n, "api_url": f"https://{n}.example"} for n in
            ("ok-1", "err-1", "empty-1", "boom-1", "slow-0.2", "ok-2")]
    t0 = _time.time()
    got = {r["name"]: r for r in R._scrape_all(rows, workers=2, worker=fake_worker)}
    assert set(got) == {r["company_name"] for r in rows}
    # recycling: more rows than one chunk of workers * tasks_per_worker — every row still
    # comes back (CPython's max_tasks_per_child hung the first full rehearsal at 4 x 25)
    many = [{"company_name": f"ok-{i}", "api_url": "https://x.example"} for i in range(11)]
    assert len(list(R._scrape_all(many, workers=2, worker=fake_worker, tasks_per_worker=2))) == 11
    assert got["ok-1"]["status"] == "ok" and got["err-1"]["error"] == "http:403"
    assert got["empty-1"]["status"] == "empty" and got["boom-1"]["error"] == "pool:RuntimeError"
    assert _time.time() - t0 < 60


def test_refresh_worker_never_raises(monkeypatch):
    import refresh_scrape_cache as R

    def boom(name, url, **kw):
        raise RuntimeError("driver died")
    monkeypatch.setattr(R, "scrape_result", boom)
    out = R._worker(("Acme", "https://acme.example"))
    assert out["status"] == "error" and out["error"] == "worker:RuntimeError" and out["jobs"] == []


def test_atomic_write_json_leaves_no_partial_file(tmp_path):
    """The cache and rot files used to be written with a plain open(): a kill mid-write
    left a truncated file for the commit step to add. The helper writes a temp file and
    swaps; on failure the previous bytes stay and no temp file remains."""
    from pipeline.atomic import write_json
    p = tmp_path / "cache.json"
    write_json(str(p), {"a": 1})
    with pytest.raises(TypeError):
        write_json(str(p), {"a": object()})
    assert _json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert [f for f in os.listdir(tmp_path) if f.startswith(".tmp_")] == []


def test_scrape_rotted_segment_survives_a_conflict_merge_without_duplicating():
    """`scrape rotted (error 7d) <date>` was not in merge_csv_rows._TOOL, so the segment was
    keyed by its first 28 characters — which include the day count — and two nights'
    segments both survived a conflict merge, evicting another tool's verdict at the cap."""
    from merge_csv_rows import _merge_notes
    theirs = "listing-hunt 2026-08-01: verified 3 IL | scrape rotted (error 7d) 2026-08-20: extraction yields 0"
    ours = "listing-hunt 2026-08-01: verified 3 IL | scrape rotted (error 8d) 2026-08-21: extraction yields 0"
    merged = _merge_notes(theirs, ours)
    assert merged.count("scrape rotted") == 1 and "8d" in merged and merged.count("listing-hunt") == 1


def test_no_workflow_step_restamps_collect_after_the_refresh():
    """`refresh_scrape_cache.py` stamps `collect` with its counts and alarm. A later bare
    `python -m pipeline.stages stamp collect` step replaced them with {} — and reported the
    stage done even when the script had crashed."""
    import glob
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for wf in glob.glob(os.path.join(repo, ".github", "workflows", "*.yml")):
        for line in open(wf, encoding="utf-8").read().splitlines():
            if line.strip().startswith("run:") and "stages stamp collect" in line:
                pytest.fail(f"{os.path.basename(wf)} re-stamps collect: {line.strip()}")


def test_refresh_a_streak_restarts_when_its_kind_changes_and_counts_observed_nights(tmp_path, monkeypatch):
    """Wave 1 (2026-08-24): the first version kept `since` when a streak flipped from empty to
    error, so a company that had been honestly empty for 60 days was parked on its first
    transient timeout — 184 real rows would have been one error away from deactivation a week
    after shipping. A flip starts a new streak, and a park needs ROT_PARK_DAYS OBSERVED error
    nights (a budget-skipped night does not advance the clock)."""
    old = {"Beta": [_il_job("Beta")], "Old": [_il_job("Old")], "Ok1": [_il_job("Ok1")],
           "Ok2": [_il_job("Ok2")], "Ok3": [_il_job("Ok3")], "Ok4": [_il_job("Ok4")]}
    rot = {"Beta": {"since": _days_ago(60), "why": "empty", "last": _days_ago(1), "n": 60},
           "Old": {"since": _days_ago(30), "why": "error", "last": _days_ago(20), "n": 2}}
    P = _refresh_sandbox(tmp_path, monkeypatch, [(n,) for n in old], old, rot,
                         {"Beta": ("error", "goto:TimeoutError"), "Old": ("error", "http:503")})
    assert P.R.run(["--workers", "1"]) == 0
    rot = _json.loads(P.rot.read_text(encoding="utf-8"))
    rows = _rows_by_name(P.csv)
    assert rot["Beta"] == {**rot["Beta"], "since": _TODAY, "why": "error", "n": 1}
    assert rows["Beta"]["active"] == "true" and "scrape rotted" not in rows["Beta"]["notes"]
    assert rot["Old"]["n"] == 3 and rows["Old"]["active"] == "true", "30 wall-clock days, 3 observed nights: no park"
    # a same-day re-dispatch (workflow_dispatch is enabled) must not count a second night
    assert P.R.run(["--workers", "1"]) == 0
    rot = _json.loads(P.rot.read_text(encoding="utf-8"))
    assert rot["Old"]["n"] == 3 and rot["Beta"]["n"] == 1 and rot["Beta"]["since"] == _TODAY
    cache = _json.loads(P.cache.read_text(encoding="utf-8"))
    assert cache["Beta"] == old["Beta"], "the error night carries yesterday's jobs"


def test_refresh_a_partial_rescue_keeps_yesterdays_fuller_list(tmp_path, monkeypatch):
    """Wave 1 (2026-08-24): a goto timeout AFTER the first XHR page landed produced 2 jobs
    with `rescued=True`, and that partial read replaced a 30-role cache entry with no error,
    no rot, no alarm. A rescued result smaller than yesterday's is an error night."""
    old = {"Acme": [_il_job("Acme", i) for i in range(30)], "Ok": [_il_job("Ok")]}
    P = _refresh_sandbox(tmp_path, monkeypatch, [("Acme",), ("Ok",)], old, {})
    real = P.R.scrape_result

    def partial(name, url, **kw):
        res = real(name, url, **kw)
        if name == "Acme":
            res.jobs, res.rescued, res.error = res.jobs[:2], True, "goto:TimeoutError"
        return res
    monkeypatch.setattr(P.R, "scrape_result", partial)
    assert P.R.run(["--workers", "1"]) == 0
    cache = _json.loads(P.cache.read_text(encoding="utf-8"))
    rot = _json.loads(P.rot.read_text(encoding="utf-8"))
    assert len(cache["Acme"]) == 30 and rot["Acme"]["why"] == "error"
    assert rot["Acme"]["error"] == "partial:goto:TimeoutError"


def test_refresh_records_roles_found_but_none_in_israel(tmp_path, monkeypatch):
    """Wave 1 (2026-08-24): "37 roles found, 0 in Israel" was byte-identical to "nothing on
    the page". The stamp carries `no_il`, and the rot entry carries `found`."""
    P = _refresh_sandbox(tmp_path, monkeypatch, [("Acme",), ("Ok",)], {}, {})
    real = P.R.scrape_result

    def abroad(name, url, **kw):
        res = real(name, url, **kw)
        if name == "Acme":
            for j in res.jobs:
                j["location"] = "Austin, TX"
        return res
    monkeypatch.setattr(P.R, "scrape_result", abroad)
    assert P.R.run(["--workers", "1"]) == 0
    stamp = _json.loads(P.stages.read_text(encoding="utf-8"))["collect"]
    rot = _json.loads(P.rot.read_text(encoding="utf-8"))
    assert stamp["empty"] == 1 and stamp["no_il"] == 1 and rot["Acme"]["found"] == 1
    assert rot["Acme"]["why"] == "empty"


def test_refresh_a_stuck_worker_costs_its_rows_not_the_night():
    """Wave 1 (2026-08-24): a worker that never returned blocked the executor's exit and the
    interpreter's atexit join, so one hung Chromium turned a finished 41-minute night into a
    330-minute killed job with nothing committed. When nothing completes for `stall_s` the
    chunk's children are terminated, the rows in flight are `hang` errors, and the next
    chunk runs on a fresh pool — under the real spawn pool."""
    import refresh_scrape_cache as R
    from fake_scrape_worker import fake_worker
    rows = [{"company_name": n, "api_url": "https://x.example"} for n in
            ("ok-1", "slow-60", "ok-2", "ok-3", "ok-4", "ok-5")]
    t0 = _time.time()
    got = {r["name"]: r for r in R._scrape_all(rows, workers=2, worker=fake_worker,
                                                tasks_per_worker=2, stall_s=2)}
    assert _time.time() - t0 < 40, "the generator must not wait for the stuck worker"
    assert got["slow-60"]["error"].startswith("hang:")
    assert all(got[n]["status"] == "ok" for n in ("ok-1", "ok-2", "ok-3", "ok-4", "ok-5"))


@pytest.mark.parametrize("card,expected_days", [
    ("Senior Data Analyst Tel Aviv, Israel Posted 3 days ago Apply", 3),
    ("Data Analyst Herzliya · Published: 2026-08-20", None),          # ISO, checked below
    ("BI Developer Haifa Full-time", ""),
    ("Data Analyst | Updated 2024-01-01 | Copyright 2024", ""),        # 'Updated' is not 'date'
    ("Our office opened 3 months ago. Data Analyst Tel Aviv", ""),     # unannounced age: not ours
    ("Senior Data Analyst Tel Aviv Apply Junior QA Engineer Tel Aviv Posted 45 days ago Apply", ""),
])
def test_posted_date_is_read_from_the_card_and_never_from_its_neighbour(card, expected_days):
    """Wave 2 (2026-08-24): the word boundary in `_CARD_DATE` had been written through a
    non-raw string and was a literal backspace, so only the unanchored "N days ago" branch
    was live — and it stamped the NEXT card's age onto a role, which `pipeline/run.py`
    then treated as too old for the 48-hour email, permanently. A date must be announced
    ("Posted …") and must sit before this card's Apply button."""
    import datetime as dt
    import scrape_universal as N
    got = N._date_from_card(card)
    if expected_days is None:
        assert got == "2026-08-20"
    elif expected_days == "":
        assert got == ""
    else:
        assert got == (dt.date.today() - dt.timedelta(days=expected_days)).isoformat()


def test_scrape_a_leadership_array_is_not_a_board():
    """Wave 2 (2026-08-24, synthetic): a team list in page state — `{"name": "Dana Levi",
    "role": "VP Marketing", "location": "Tel Aviv"}` — passed the title test through `role`,
    won as "structured", and suppressed the page's real job links."""
    import scrape_universal as N
    team = _json.dumps({"props": {"team": [
        {"name": "Dana Levi", "role": "VP Marketing", "location": "Tel Aviv", "id": "t1"},
        {"name": "Omer Cohen", "role": "Head of Product", "location": "Tel Aviv", "id": "t2"},
        {"name": "Noa Bar", "role": "Director of Sales", "location": "Herzliya", "id": "t3"}]}})
    dom = [{"title": t, "url": f"https://co.example/jobs/{i}", "ctx": f"{t} Tel Aviv, Israel"}
           for i, t in enumerate(("Senior Data Analyst", "BI Developer"), 501)]
    jobs, strategy = N._extract("Co", "https://co.example/careers", _rendered(blobs=[team], dom=dom),
                                fetch=_no_fetch)
    assert strategy == "dom" and [j["title"] for j in jobs] == ["Senior Data Analyst", "BI Developer"]
    # ...while a posting that happens to carry a `name` key still counts
    posting = _json.dumps({"jobs": [{"name": "Senior Data Analyst", "location": "Tel Aviv", "id": "1"},
                                    {"name": "BI Developer", "location": "Haifa", "id": "2"}]})
    jobs, strategy = N._extract("Co", "https://co.example/careers", _rendered(blobs=[posting]), fetch=_no_fetch)
    assert strategy == "structured" and len(jobs) == 2


def test_refresh_a_rescued_full_read_is_believed_and_a_partial_one_converges(tmp_path, monkeypatch):
    """Wave 2 (2026-08-24): the partial-rescue rule compared tonight's read with the list it
    had carried forward itself, so it latched — a 403-walled company rescued every night
    whose board lost ONE role served the stale list for six nights and was deactivated on
    the seventh. A rescue with no browser error is a complete read; a browser-failed partial
    is held back for PARTIAL_MAX_NIGHTS and then believed."""
    import datetime as dt
    old = {"Walled": [_il_job("Walled", i) for i in range(10)],
           "Partial": [_il_job("Partial", i) for i in range(30)],
           **{f"Ok{i}": [_il_job(f"Ok{i}")] for i in range(6)}}
    rows = [("Walled",), ("Partial",)] + [(f"Ok{i}",) for i in range(6)]
    P = _refresh_sandbox(tmp_path, monkeypatch, rows, old, {})
    real = P.R.scrape_result

    def scraper(name, url, **kw):
        res = real(name, url, **kw)
        if name == "Walled":            # render 403, plain page rescued in full: 9 real roles
            res.jobs = [_il_job("Walled", i) for i in range(9)]
            res.rescued, res.error, res.http_status = True, "", 403
        if name == "Partial":           # goto timed out after the first XHR page: 2 of 30
            res.jobs = [_il_job("Partial", i) for i in range(2)]
            res.rescued, res.error = True, "goto:TimeoutError"
        return res
    monkeypatch.setattr(P.R, "scrape_result", scraper)
    day0 = dt.date.today()
    for night in range(1, 5):
        monkeypatch.setattr(P.R._dt, "date",
                            type("D", (), {"today": staticmethod(lambda n=night: day0 + dt.timedelta(days=n)),
                                           "fromisoformat": staticmethod(dt.date.fromisoformat)}))
        assert P.R.run(["--workers", "1"]) == 0
        cache = _json.loads(P.cache.read_text(encoding="utf-8"))
        rows_now = _rows_by_name(P.csv)
        assert len(cache["Walled"]) == 9 and rows_now["Walled"]["active"] == "true", night
        assert len(cache["Partial"]) == (30 if night <= P.R.PARTIAL_MAX_NIGHTS else 2), night
    rot = _json.loads(P.rot.read_text(encoding="utf-8"))
    assert "Walled" not in rot and "Partial" not in rot


def test_scrape_a_cloudflare_protected_page_is_not_a_wall():
    """Wave 2 (2026-08-24): Cloudflare injects `/cdn-cgi/challenge-platform/scripts/jsd/main.js`
    into ordinary 200 pages when JS detections are on, and Incapsula injects
    `_Incapsula_Resource`; neither is a challenge page. Only a challenge/denial PAGE is."""
    import scrape_universal as N
    page = ("<html><head><title>Careers | Acme</title></head><body><h1>Open positions</h1>"
            "<p>No open positions right now.</p>" + "filler " * 400 +
            '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
            '<script src="/_Incapsula_Resource?SWJIYLWA=1"></script></body></html>')
    assert N._blocked_by(page) == ""
    assert N._classify(N.Rendered(url="u", http_status=200, page_html=page), []) == ("empty", "")
    assert N._blocked_by("<html><body>Request unsuccessful. Incapsula incident ID: 1</body></html>") == "incapsula"
    assert N._blocked_by("<title>Attention Required! | Cloudflare</title>") == "cloudflare"
    assert N._blocked_by("<p>We monitor Access Denied events and Attention Required alerts.</p>") == ""


def test_refresh_the_stall_watchdog_really_terminates_the_stuck_child():
    """Wave 2 (2026-08-24): `_kill_children` ran after `shutdown()`, which clears the
    executor's process table, so it terminated nothing and stuck Chromiums accumulated
    chunk after chunk. The children are taken before the shutdown."""
    import refresh_scrape_cache as R
    from fake_scrape_worker import fake_worker
    seen = []
    orig = R._children_of

    def spy(ex):
        procs = orig(ex)
        seen.extend(procs)
        return procs
    R._children_of = spy
    try:
        rows = [{"company_name": n, "api_url": "https://x.example"} for n in ("ok-1", "slow-60", "ok-2")]
        got = list(R._scrape_all(rows, workers=2, worker=fake_worker, tasks_per_worker=2, stall_s=2))
    finally:
        R._children_of = orig
    assert any(r["error"].startswith("hang:") for r in got)
    assert seen, "the watchdog saw no children"
    _time.sleep(1.0)
    assert not any(p.is_alive() for p in seen), "a stuck child survived the watchdog"


def test_refresh_survives_a_rot_entry_written_before_nights_were_counted(tmp_path, monkeypatch):
    """Rehearsal (2026-08-24): the real `scrape_rot.json` holds 207 entries written before `n`
    existed, all stamped `last=today` by that morning's run; the same-day path returned
    `e["n"]` and crashed the whole refresh with KeyError. A legacy entry gets n=1."""
    rot = {"Beta": {"since": _days_ago(1), "why": "empty", "last": _TODAY},
           "Gamma": {"since": _days_ago(3), "why": "empty", "last": _days_ago(1)}}
    P = _refresh_sandbox(tmp_path, monkeypatch, [("Beta",), ("Gamma",), ("Ok",)], {}, rot,
                         {"Beta": ("empty", ""), "Gamma": ("empty", "")})
    assert P.R.run(["--workers", "1"]) == 0
    rot = _json.loads(P.rot.read_text(encoding="utf-8"))
    assert rot["Beta"]["n"] == 1 and rot["Gamma"]["n"] == 1


def test_scrape_a_deadline_inside_the_position_pages_is_a_partial_read():
    """Wave 3 (2026-08-24): the company budget expiring while strategy 4 was fetching position
    pages returned the 4 it had as a complete `ok` list, and the refresh wrote them over
    yesterday's 20 with no error and no alarm. A truncated pass is flagged like a failed
    render, so the refresh holds yesterday's fuller list."""
    import scrape_universal as N
    url = "https://co.example/careers"
    links = "".join(f'<a href="/careers-position/role-{i:02d}/">Role {i}</a>' for i in range(20))
    page = f"<body>{links}</body>"
    calls = []

    class Budget(N.Deadline):
        def remaining(self):
            return 0.0 if len(calls) >= 5 else 60.0

        def expired(self):
            return self.remaining() <= 0

    def fetch(u, t):
        calls.append(u)
        n = u.rstrip("/").split("-")[-1]
        return f"<html><h1>Data Analyst {n}</h1><p>Ra'anana</p></html>", 200
    r = _rendered(page_html=page)
    jobs, strategy = N._extract("Co", url, r, deadline=Budget(t_end=0), fetch=fetch)
    assert strategy == "links" and 0 < len(jobs) < 20 and r.truncated and r.error == "deadline:links"
    status, _ = N._classify(r, jobs)
    assert status == "ok"
    res = N.scrape_result("Co", url, render=lambda u, t, d: _rendered(page_html=page), fetch=fetch, budget_s=1)
    assert res.rescued or res.error == "" or res.error.startswith("deadline:")


def test_refresh_a_failed_registry_write_keeps_the_streak_that_justified_it(tmp_path, monkeypatch):
    """Wave 3 (2026-08-24): the rot entries of parked rows were popped and written BEFORE the
    registry write; if that write failed, seven nights of evidence were gone while the row
    stayed active. The registry is written first."""
    rot = {"Acme": {"since": _days_ago(8), "why": "error", "last": _days_ago(1), "n": 7}}
    P = _refresh_sandbox(tmp_path, monkeypatch, [("Acme",)] + [(f"Ok{i}",) for i in range(6)],
                         {"Acme": [_il_job("Acme")], **{f"Ok{i}": [_il_job(f"Ok{i}")] for i in range(6)}},
                         rot, {"Acme": ("error", "http:403")})

    def broken(parked, today):
        raise OSError("busy")
    monkeypatch.setattr(P.R, "_park", broken)
    with pytest.raises(OSError):
        P.R.run(["--workers", "1"])
    assert _json.loads(P.rot.read_text(encoding="utf-8"))["Acme"]["n"] == 7
    assert _rows_by_name(P.csv)["Acme"]["active"] == "true"


def test_refresh_rotates_the_processing_order_by_day(tmp_path, monkeypatch):
    """Wave 3 (2026-08-24): rows were submitted in registry order, so a budget cut stranded
    the same tail (carried, never re-scraped) every night. The order rotates by the day;
    the bookkeeping is unaffected."""
    import datetime as dt
    names = [f"Co{i:02d}" for i in range(10)]
    seen = []
    for day in (0, 1):
        P = _refresh_sandbox(tmp_path / str(day), monkeypatch, [(n,) for n in names], {}, {})
        real = P.R.scrape_result
        order = []

        def spy(name, url, **kw):
            order.append(name)
            return real(name, url, **kw)
        monkeypatch.setattr(P.R, "scrape_result", spy)
        base = dt.date.today() + dt.timedelta(days=day)
        monkeypatch.setattr(P.R._dt, "date", type("D", (), {
            "today": staticmethod(lambda b=base: b), "fromisoformat": staticmethod(dt.date.fromisoformat)}))
        assert P.R.run(["--workers", "1"]) == 0
        seen.append(order)
        assert set(_json.loads(P.cache.read_text(encoding="utf-8"))) == set(names)
    assert seen[0] != seen[1] and sorted(seen[0]) == sorted(seen[1]) == names


# --------------------------------------------------------------------------- #
# ats-fetch lane, 2026-08-24 — see docs/sessions/2026-08-24-ats-fetch.md
# --------------------------------------------------------------------------- #


def _pcsx_position(i, jid, display, locs, std):
    return {"id": jid, "displayJobId": display, "name": f"Role {i}", "locations": locs,
            "standardizedLocations": std, "postedTs": 1786106796, "creationTs": 1786011493,
            "positionUrl": f"/careers/job/{jid}"}


def test_eightfold_pcsx_pages_by_what_the_server_returned_and_keeps_microsoft_keys(monkeypatch):
    """Eightfold's pcsx search serves at most 10 positions per call whatever `num` asks
    (Qualcomm 2026-08-24: count=36 came back 10+10+10+6). The Microsoft fetcher advanced
    `start` by its requested 20, so positions 10-19 of every page were skipped — Microsoft
    had count=14 on 2026-08-24 and the fetcher returned 10. Paging must advance by the page length.
    And the Microsoft row must keep producing the same store keys ("microsoft:<displayJobId>")
    and public URLs, or every Microsoft role is emailed again as new."""
    from pipeline import fetchers
    count = 4
    pages = {0: [_pcsx_position(1, 111, "A1", ["Israel, Haifa"], ["IL"]),
                 _pcsx_position(2, 222, "A2", ["Herzliya, Israel"], ["Herzliya, Tel Aviv District, IL"])],
             2: [_pcsx_position(3, 333, "A3", ["Dublin, Ireland"], ["Dublin, IE"]),
                 _pcsx_position(4, 444, "A4", ["Tel Aviv, Israel"], ["Tel Aviv, IL"])]}
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        start = int(url.split("start=")[1].split("&")[0])
        assert "num=20" in url and "location=Israel" in url and "query=" in url
        return {"data": {"count": count, "positions": pages.get(start, [])}}
    monkeypatch.setattr(fetchers.http, "get_json", fake_get)

    ms = fetchers.fetch_company({"company_name": "Microsoft", "ats_platform": "microsoft", "token": "",
                                 "api_url": "https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com"})
    assert [j["job_id"] for j in ms] == ["A1", "A2", "A3", "A4"], "advance by page length, not by num"
    assert all(j["ats_platform"] == "microsoft" for j in ms), "the row's platform is the store key"
    assert ms[0]["url"] == "https://jobs.careers.microsoft.com/global/en/job/A1"
    assert calls[0].startswith("https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query=&location=Israel&start=0&num=20")
    assert len(calls) == 2, "count=4 reached after two pages of 2 — no third request"
    # explicit country from standardizedLocations; a foreign one stays "" (text fallback)
    assert [j["country_code"] for j in ms] == ["IL", "IL", "", "IL"]
    assert ms[0]["posted_date"] == "2026-08-07"

    q = fetchers.fetch_company({"company_name": "Qualcomm", "ats_platform": "eightfold", "token": "qualcomm.com",
                                "api_url": "https://careers.qualcomm.com/api/pcsx/search"})
    assert q[0]["url"] == "https://careers.qualcomm.com/careers/job/111", "relative positionUrl → tenant host"
    assert q[0]["ats_platform"] == "eightfold"
    assert "domain=qualcomm.com" in calls[-1], "the token supplies ?domain= when the URL lacks it"


def test_a_phenom_host_answering_the_eightfold_path_is_a_failure_not_a_zero(monkeypatch):
    """FETCHERS["phenom"] used to alias fetch_eightfold. Phenom hosts answer that path with
    HTTP 200 and {"status":"failure","errorMsg":"Tenant not identified","data":null} — a
    confident, permanent zero for every phenom row. It must raise instead."""
    from pipeline import fetchers
    monkeypatch.setattr(fetchers.http, "get_json", lambda url, **kw: {
        "status": "failure", "errorCode": None, "errorMsg": "Tenant not identified", "data": None})
    with pytest.raises(ValueError, match="Tenant not identified"):
        fetchers.fetch_eightfold({"company_name": "GE", "ats_platform": "eightfold", "token": "ge.com",
                                  "api_url": "https://careers.gehealthcare.com/api/pcsx/search"})
    assert fetchers.FETCHERS["phenom"] is fetchers.fetch_phenom
    assert fetchers.FETCHERS["microsoft"] is fetchers.fetch_eightfold


def test_phenom_widgets_normalises_pages_and_refuses_other_shapes(monkeypatch):
    """Phenom's /widgets search (GE HealthCare: totalHits=20 of 985, exactly the 20 with an
    Israel location). Pages by what the server RETURNED until totalHits (a tenant capping
    pages below `size` must not lose the rest — the Eightfold bug, pre-empted); the
    country facet is the Israel filter, so `country: Israel` becomes an explicit IL code;
    the ~350-char `descriptionTeaser` is NOT stored as the description (it would clear
    jdfill's 300-char bar and the classifier would judge on a blurb). Anything without
    `refineSearch` (Dolby's 401 body, a non-Phenom host) raises."""
    from pipeline import fetchers
    seen_bodies = []

    def job(i):
        return {"title": f"Analyst {i}", "jobSeqNo": f"SEQ{i}", "reqId": f"R{i}",
                "applyUrl": f"https://x.example/apply/{i}", "postedDate": "2026-07-28T00:00:00.000+0000",
                "cityStateCountry": "Haifa, Haifa District, Israel", "country": "Israel",
                "descriptionTeaser": "Lead the <b>verification</b> team."}

    def fake_post(url, body, **kw):
        seen_bodies.append(body)
        assert body["ddoKey"] == "refineSearch" and body["selected_fields"] == {"country": ["Israel"]}
        frm = body["from"]
        jobs = [job(i) for i in range(frm, min(frm + body["size"], 130))]
        return {"refineSearch": {"totalHits": 130, "data": {"jobs": jobs}}}
    monkeypatch.setattr(fetchers.http, "post_json", fake_post)
    out = fetchers.fetch_company({"company_name": "GE HealthCare", "ats_platform": "phenom", "token": "",
                                  "api_url": "https://careers.gehealthcare.com/widgets"})
    assert len(out) == 130 and len(seen_bodies) == 2, "100 + 30, then stop at totalHits"
    assert out[0] == {"company": "GE HealthCare", "title": "Analyst 0",
                      "location": "Haifa, Haifa District, Israel", "country_code": "IL",
                      "url": "https://x.example/apply/0", "posted_date": "2026-07-28",
                      "ats_platform": "phenom", "job_id": "SEQ0", "description": ""}
    assert fetchers.fetch_phenom.israel_scoped is True

    def capped_post(url, body, **kw):        # server serves 20 a page whatever `size` says
        frm = body["from"]
        return {"refineSearch": {"totalHits": 130, "data": {"jobs": [job(i) for i in range(frm, min(frm + 20, 130))]}}}
    monkeypatch.setattr(fetchers.http, "post_json", capped_post)
    assert len(fetchers.fetch_phenom({"company_name": "X", "ats_platform": "phenom", "token": "",
                                      "api_url": "https://x/widgets"})) == 130

    def no_total_post(url, body, **kw):      # a tenant that omits totalHits: page until dry
        frm = body["from"]
        return {"refineSearch": {"data": {"jobs": [job(i) for i in range(frm, min(frm + 100, 250))]}}}
    monkeypatch.setattr(fetchers.http, "post_json", no_total_post)
    assert len(fetchers.fetch_phenom({"company_name": "X", "ats_platform": "phenom", "token": "",
                                      "api_url": "https://x/widgets"})) == 250

    monkeypatch.setattr(fetchers.http, "post_json", lambda url, body, **kw: {"message": "Please try again later"})
    with pytest.raises(ValueError, match="not a Phenom widgets response"):
        fetchers.fetch_phenom({"company_name": "Dolby", "ats_platform": "phenom", "token": "",
                               "api_url": "https://jobs.dolby.com/widgets"})


def test_workday_zero_israel_is_a_measurement_and_zero_worldwide_is_a_failure(monkeypatch):
    """25 of the 26 Workday rows in the self-heal queue on 2026-08-24 were live tenants with
    2 to ~2,726 postings and none in Israel; one (Dell) had none at all. The first must return
    [] quietly; the second must raise BoardEmpty (→ fetch-error, named in the mail); and a
    probe that itself fails (Workday answers 500 to bursts) must leave the answer unknown —
    an empty list, never an error."""
    from pipeline import fetchers
    row = {"company_name": "Adobe", "ats_platform": "workday", "token": "",
           "api_url": "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/external_experienced/jobs"}

    def make(whole_total, probe_raises=False):
        calls = []

        def fake_post(url, body, **kw):
            calls.append((body, kw))
            if body["searchText"] == "Israel":
                return {"total": 0, "jobPostings": []}
            if probe_raises:
                raise fetchers.http.HttpError("HTTP 500")
            return {"total": whole_total, "jobPostings": [{"title": "x"}]}
        monkeypatch.setattr(fetchers.http, "post_json", fake_post)
        return calls

    calls = make(741)
    assert fetchers.fetch_workday(row) == []
    assert len(calls) == 2 and calls[1][0] == {"searchText": "", "limit": 1, "offset": 0}
    assert calls[1][1].get("retries") == 1, "the probe is single-shot"

    make(0)
    with pytest.raises(fetchers.BoardEmpty, match="0 postings worldwide"):
        fetchers.fetch_workday(row)

    make(0, probe_raises=True)
    assert fetchers.fetch_workday(row) == [], "could not tell is not broken"
    assert fetchers.fetch_workday.israel_scoped is True


def test_health_does_not_flag_israel_scoped_fetchers_as_empty_boards(tmp_path):
    """`empty-board` was raised for any platform outside a hand-typed tuple in health.py,
    which named custom_json and jazzhr but not workday or microsoft — so 26 healthy Workday
    tenants sat in stale.json and the 06:00 self-heal re-resolved them weekly. The rule is
    now derived from the fetcher (`israel_scoped`), and platform_check tests the behaviour
    rather than grepping the source."""
    from pipeline import fetchers, health
    scoped = sorted(k for k, f in fetchers.FETCHERS.items() if getattr(f, "israel_scoped", False))
    assert scoped == ["custom_json", "eightfold", "microsoft", "phenom", "workday"]
    for plat in scoped + ["scrape", "discovery", "jazzhr"]:
        assert health.stale_reason(plat, "", 0, "empty", 0) is None, plat
    for plat in ("greenhouse", "comeet", "lever", "ashby", "workable"):
        assert health.stale_reason(plat, "", 0, "empty", 0) == "empty-board", plat
    # a scoped fetcher's baseline is a search-hit count: "had 40, now 0" is not a verdict
    # either (the fetcher raises BoardEmpty when the board is really empty)...
    assert health.stale_reason("workday", "", 0, "empty", 40) is None
    assert health.stale_reason("greenhouse", "", 0, "empty", 40) == "regressed-to-zero"
    # ...but a SCRAPE row that had postings and now has none is still a regression: the
    # self-heal pool and the targeted discovery sweep read that flag (25 rows on
    # 2026-08-24), and the first cut of this rule silently dropped all of them (wave 3)
    assert health.stale_reason("scrape", "https://x.example/careers", 0, "empty", 12) == "regressed-to-zero"
    assert health.stale_reason("scrape", "https://x.example/careers", 0, "empty", 0) is None
    # ...and an error is an error, whatever the platform
    assert health.stale_reason("workday", "", 0, "error", 0) == "fetch-error"
    # write=False judges without touching the files (scoped runs)
    b, s = tmp_path / "b.json", tmp_path / "s.json"
    stale = health.record({"Decart": {"platform": "ashby", "n": 0, "status": "error", "api": "u",
                                      "error": "HttpError: HTTP 404"},
                           "Adobe": {"platform": "workday", "n": 0, "status": "empty", "api": "u"}},
                          baseline_path=str(b), stale_path=str(s), write=False)
    assert list(stale) == ["Decart"] and stale["Decart"]["error"] == "HttpError: HTTP 404"
    assert not b.exists() and not s.exists()


def test_board_health_reaches_the_mail_with_the_reason():
    """Until 2026-08-24 the audit said `Failed companies: Decart (HttpError)` — the class
    name — and the empty/regressed counts that stale.json carries reached nobody:
    `stats["stale_boards"]` was computed and never put into the summary. One line, grouped
    by reason, names capped, silent when everything is healthy."""
    import inspect
    from pipeline import digest, health, run as run_mod
    line = health.mail_lines({
        "Decart": {"reason": "fetch-error", "error": "HttpError: HTTP 404 for https://api.ashbyhq.com/..."},
        "Dell Technologies": {"reason": "fetch-error", "error": "BoardEmpty: dell.wd1: 0 postings worldwide"},
        "Leadspace": {"reason": "empty-board"}, "Any.do": {"reason": "empty-board"},
        "Salesforce": {"reason": "regressed-to-zero"},
        **{f"S{i}": {"reason": "misconfig-scrape-on-ats"} for i in range(25)}})
    assert line == ["2 fetch errors (Decart: HttpError: HTTP 404 for https://api.ashbyhq.com/...; "
                    "Dell Technologies: BoardEmpty: dell.wd1: 0 postings worldwide) · "
                    "1 regressed to zero (Salesforce) · 2 empty (Any.do; Leadspace) · "
                    "25 scrape rows on an ATS host"]
    assert health.mail_lines({}) == [], "nothing to say when every board is healthy"
    many = health.mail_lines({f"C{i:02d}": {"reason": "empty-board"} for i in range(9)})
    assert many == ["9 empty (C00; C01; C02; C03; C04; C05; +3 more)"]
    # the run puts it in the summary, and every renderer prints it
    src = inspect.getsource(run_mod.run)
    assert '"fetch_health": _fetch_health_lines' in src and "health.mail_lines(stale, _previous, scanned=health_results)" in src
    assert "str(e))[:70]" in src, "the failed-companies line must carry the exception text"
    assert r"\?\S*" in src, "query strings (Comeet ?token=) are stripped BEFORE the 70-char cut"
    assert "scanned=health_results" in src, "cleared must be judged only over rows this run scanned"
    many_failed = {"companies_scanned": 1, "failed_companies": [f"C{i} (HttpError: x)" for i in range(30)]}
    _, md2 = digest.build_markdown([], "2026-08-24", many_failed, {})
    assert "C7 (HttpError: x), +22 more" in md2 and "C8 (" not in md2, "an outage morning is eight names and a count"
    _, html2, text2 = digest.build_digest([], "2026-08-24", many_failed)
    assert "+22 more" in html2 and "C8 (" not in html2 and "+22 more" in text2, "the HTML mail is capped too"
    summary = {"companies_scanned": 1, "fetch_health": line}
    _, md = digest.build_markdown([], "2026-08-24", summary, {})
    assert "- **Boards:** 2 fetch errors (Decart: HttpError: HTTP 404" in md
    _, html, text = digest.build_digest([], "2026-08-24", summary)
    assert "BOARDS: 2 fetch errors" in text and "<b>Boards:</b> 2 fetch errors" in html


def test_discovery_drops_are_counted_and_printed(monkeypatch, capsys):
    """docs/BACKLOG.md 9: three filters in one silent comprehension — 109 of 1,097 cached
    jobs were dropped as recruiters on 2026-08-24 and nothing said so. Every drop class is
    printed once. The second half of item 9, narrowly: a card whose slug names a DECLARED
    identity of the company (identity_facts: "AWS" -> domain `amazon`; exact whole-word, 3+ chars) is
    the company's own posting and is kept; an undeclared foreign slug is still dropped."""
    import json as _json
    from pipeline import fetchers
    today = dt.date.today().isoformat()
    cache = [{"company": "Wix", "title": "a", "url": "https://il.linkedin.com/jobs/view/a-at-wix-4454120001", "posted_date": today},
             {"company": "Wix", "title": "b", "url": "https://il.linkedin.com/jobs/view/b-at-wix-4454120002", "posted_date": "2020-01-01"},
             {"company": "Manpower", "title": "c", "url": "https://il.linkedin.com/jobs/view/c-at-manpower-4454120003", "posted_date": today},
             {"company": "Wix", "title": "d", "url": "https://il.linkedin.com/jobs/view/d-at-monday-com-4454120004", "posted_date": today},
             {"company": "AWS", "title": "e", "url": "https://il.linkedin.com/jobs/view/e-at-amazon-web-services-4454120005", "posted_date": today},
             {"company": "Siemens EDA", "title": "f", "url": "https://il.linkedin.com/jobs/view/f-at-swissquote-4454120006", "posted_date": today},
             {"company": "Itamar Medical", "title": "g", "url": "https://il.linkedin.com/jobs/view/g-at-zollinger-corp-4454120007", "posted_date": today},
             {"company": "AWS", "title": "h", "url": "https://il.linkedin.com/jobs/view/amazon-consultant-at-acme-consulting-4454120008", "posted_date": today},
             {"company": "SentinelOne", "title": "i", "url": "https://il.linkedin.com/jobs/view/i-at-sentinel-labs-4454120009", "posted_date": today},
             {"company": "Merck (MSD)", "title": "j", "url": "https://il.linkedin.com/jobs/view/j-at-msd-4454120010", "posted_date": today},
             {"company": "Merck (MSD)", "title": "k", "url": "https://il.linkedin.com/jobs/view/k-at-msdelivery-4454120011", "posted_date": today}]
    monkeypatch.setattr(_json, "load", lambda f: cache)
    from pipeline.company_identity import url_names_other_company as _u
    assert _u("AWS", cache[4]["url"]), "the raw guard would drop the declared identity"
    kept = fetchers.fetch_discovery({"company_name": "Discovery"})
    assert [j["title"] for j in kept] == ["a", "e", "i", "j"], ("declared `amazon`/`sentinellabs`/`msd` kept as a whole "
        "leading run of the employer's words (exact, so 3-char `msd` is safe); `sw` (2 chars), `zoll` inside `zollinger`, "
        "`msd` inside `msdelivery`, and `amazon` in the TITLE half do not vouch")
    out = capsys.readouterr().out
    assert "[discovery] kept 4 of 11 cached jobs (dropped: expired 1, recruiter 1, slug-mismatch 5)" in out


def test_every_list_description_and_date_goes_through_the_same_normaliser(monkeypatch):
    """workable/breezy stored the raw stripped HTML (no junk filter, no cap) while every
    other fetcher used `_snippet`; workable/breezy/bamboohr sliced dates `[:10]` while the
    others parsed them. One path each: a CSS-soup description is blanked, an unparseable
    date is "" rather than ten raw characters."""
    from pipeline import fetchers
    junk = '<div class="x">var(--token) pointer-events</div>' + "x" * 7000
    monkeypatch.setattr(fetchers.http, "get_json", lambda url, **kw: {
        "jobs": [{"title": "Analyst", "city": "Tel Aviv", "country": "Israel", "url": "https://w/1",
                  "shortcode": "S1", "created_at": "2026-08-01T10:00:00Z", "description": junk}]})
    w = fetchers.fetch_workable({"company_name": "W", "ats_platform": "workable", "token": "w", "api_url": "https://apply.workable.com/api/v1/widget/accounts/w"})
    assert w[0]["description"] == "" and w[0]["posted_date"] == "2026-08-01"
    monkeypatch.setattr(fetchers.http, "get_json", lambda url, **kw: [
        {"name": "Analyst", "friendly_id": "f1", "published_date": "August 1, 2026", "description": "<p>Real</p>" + "y" * 7000}])
    b = fetchers.fetch_breezy({"company_name": "B", "ats_platform": "breezy", "token": "b", "api_url": "https://b.breezy.hr/json"})
    assert b[0]["posted_date"] == "2026-08-01" and len(b[0]["description"]) == fetchers._DESC_MAX
    monkeypatch.setattr(fetchers.http, "get_json", lambda url, **kw: {
        "result": [{"id": 7, "jobOpeningName": "Analyst", "datePosted": "not a date"}]})
    bh = fetchers.fetch_bamboohr({"company_name": "H", "ats_platform": "bamboohr", "token": "h", "api_url": "https://h.bamboohr.com/careers/list"})
    assert bh[0]["posted_date"] == ""


# --- scraper lane, 2026-08-24: render/parse split, error vs empty, the pooled refresh ---
# Every test here is offline: the parse is a pure function of a `Rendered` bundle, the refresh
# is driven by a fake `scrape_result`, and the process pool by a module-level fake worker.

import csv as _csv
import datetime as _dtm
import html as _html
import json as _json
import re as _re
import time as _time
from types import SimpleNamespace as _NS


def test_the_empty_board_probe_fails_closed_on_a_dead_endpoint_and_open_on_a_burst(monkeypatch):
    """Wave-1 finding: the first probe swallowed EVERY error, so it failed open on exactly
    the condition it existed to detect — a moved tenant whose probe 4xxs went 'healthy'.
    And `and not total` skipped the probe when a moved `site` kept its facet count with no
    postings. Now: an empty first page always earns the probe; a 4xx from the probe is
    re-raised (the endpoint is dead — that is the finding); 5xx/network/malformed is
    'could not tell' → []; a count of 0 → BoardEmpty; a missing count with no postings → 0.
    The same helper serves Workday, Eightfold and Phenom."""
    from pipeline import fetchers
    H = fetchers.http.HttpError
    wd = {"company_name": "X", "ats_platform": "workday", "token": "",
          "api_url": "https://x.wd5.myworkdayjobs.com/wday/cxs/x/ext/jobs"}

    def workday(first, probe):
        def fake_post(url, body, **kw):
            if body["searchText"] == "Israel":
                return first
            if isinstance(probe, Exception):
                raise probe
            return probe
        monkeypatch.setattr(fetchers.http, "post_json", fake_post)
    workday({"total": 7, "jobPostings": []}, {"total": 0, "jobPostings": []})
    with pytest.raises(fetchers.BoardEmpty):          # facet total survives, postings gone
        fetchers.fetch_workday(wd)
    workday({"total": 0, "jobPostings": []}, H("HTTP 404 for u: Not Found"))
    with pytest.raises(H):                             # probe 4xx → the endpoint is dead
        fetchers.fetch_workday(wd)
    for code in (401, 403, 408, 429):                  # ...but "not now" is not "dead"
        workday({"total": 0, "jobPostings": []}, H(f"HTTP {code} for u: x"))
        assert fetchers.fetch_workday(wd) == [], code
    workday({"total": 0, "jobPostings": []}, H("HTTP 500 for u: Server Error"))
    assert fetchers.fetch_workday(wd) == []           # burst → unknown → []
    workday({"total": 0, "jobPostings": []}, H("network error for u: timed out"))
    assert fetchers.fetch_workday(wd) == []
    workday({"total": 0, "jobPostings": []}, {"jobPostings": []})
    assert fetchers.fetch_workday(wd) == []           # no `total` at all → could not tell
    workday({"total": 0, "jobPostings": []}, {"total": "741"})
    assert fetchers.fetch_workday(wd) == []           # a string count still counts
    workday({"total": 7, "jobPostings": []}, {"total": 741})
    with pytest.raises(ValueError, match="reports 7 Israel hits but served none"):
        fetchers.fetch_workday(wd)                    # a healthy board that serves nothing

    # Eightfold: 0 Israel positions → one unscoped GET; 0 worldwide → BoardEmpty
    def pcsx(worldwide):
        def fake_get(url, **kw):
            if "location=Israel" in url:
                return {"data": {"count": 0, "positions": []}}
            assert "location=&" in url and kw.get("retries") == 1
            return {"data": {"count": worldwide, "positions": []}}
        monkeypatch.setattr(fetchers.http, "get_json", fake_get)
    ef = {"company_name": "PayPal", "ats_platform": "eightfold", "token": "paypal.com",
          "api_url": "https://paypal.eightfold.ai/api/pcsx/search"}
    pcsx(75)
    assert fetchers.fetch_eightfold(ef) == []
    pcsx(0)
    with pytest.raises(fetchers.BoardEmpty):
        fetchers.fetch_eightfold(ef)

    # Phenom: 0 Israel hits → one unfiltered POST; 0 hits at all → BoardEmpty
    def phenom(worldwide):
        def fake_post(url, body, **kw):
            hits = 0 if body["selected_fields"] else worldwide
            return {"refineSearch": {"totalHits": hits, "data": {"jobs": []}}}
        monkeypatch.setattr(fetchers.http, "post_json", fake_post)
    ph = {"company_name": "eBay", "ats_platform": "phenom", "token": "",
          "api_url": "https://jobs.ebayinc.com/widgets"}
    phenom(472)
    assert fetchers.fetch_phenom(ph) == []
    phenom(0)
    with pytest.raises(fetchers.BoardEmpty):
        fetchers.fetch_phenom(ph)


def test_the_boards_line_leads_with_what_changed_since_yesterday():
    """88 of the 91 entries in a simulated stale.json are standing state (empty boards,
    scrape rows on an ATS host) that reads the same every morning; a new fetch error inside
    that line is invisible by day three. The line now opens with the delta. `run.py` reads
    yesterday's file BEFORE `record()` rewrites it."""
    import inspect
    from pipeline import health, run as run_mod
    prev = {"Guardz": {"reason": "fetch-error"}, "Any.do": {"reason": "empty-board"},
            "Adobe": {"reason": "empty-board"}}
    now = {"Decart": {"reason": "fetch-error", "error": "HttpError: HTTP 404"},
           "Any.do": {"reason": "empty-board"},
           "Adobe": {"reason": "fetch-error", "error": "BoardEmpty: 0 postings worldwide"}}
    assert health.mail_lines(now, prev) == [
        "new today: Adobe: fetch-error; Decart: fetch-error · cleared: Guardz · "
        "2 fetch errors (Adobe: BoardEmpty: 0 postings worldwide; Decart: HttpError: HTTP 404) · "
        "1 empty (Any.do)"]
    assert health.mail_lines(now, now)[0].startswith("2 fetch errors"), "no delta, no prefix"
    # "cleared" means recovered: not a row nobody scanned (deactivated overnight), and not an
    # empty-board on a platform whose zero is a measurement (never broken; 26 Workday rows
    # would have read as "cleared" the first morning the rule landed)
    prev2 = {"Adobe": {"reason": "empty-board", "platform": "workday"},
             "Leadspace": {"reason": "empty-board", "platform": "lever"},
             "Gone Co": {"reason": "fetch-error", "platform": "ashby"}}
    assert health.mail_lines({}, prev2, scanned={"Adobe", "Leadspace"}) == ["cleared: Leadspace"]
    assert health.mail_lines({}, prev2) == ["cleared: Gone Co; Leadspace"]
    src = inspect.getsource(run_mod.run)
    assert src.index("health.previous()") < src.index("health.record(")
    assert "stale_boards" not in src, "a summary key nothing renders is a lie waiting to happen"


def test_platform_check_catches_a_scoped_fetcher_that_forgot_to_declare_it(monkeypatch):
    """Wave-1 finding: the first `empty->flag(health)` column read the same attribute health
    reads — a tautology. The check is now: a fetcher whose source narrows to Israel must
    DECLARE `israel_scoped` (True, or False for oraclehcm's hybrid pass), and health's
    verdict must match the declaration. Deleting `fetch_workday.israel_scoped` must show."""
    from pipeline import fetchers, platform_check
    import contextlib, io
    def grid():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            platform_check.check()
        return {l.split()[0]: l.split() for l in buf.getvalue().splitlines() if l and l.split()[0] in fetchers.FETCHERS}
    base = grid()
    assert base["workday"][-2:] == ["ok", "ok"] and base["oraclehcm"][-2:] == ["ok", "ok"]
    monkeypatch.delattr(fetchers.fetch_workday, "israel_scoped")
    broken = grid()
    assert broken["workday"][-2:] == ["MISSING", "ok"], "narrows to Israel, undeclared"
    monkeypatch.setattr(fetchers.fetch_greenhouse, "israel_scoped", True, raising=False)
    assert grid()["greenhouse"][-2:] == ["MISSING", "ok"], \
        "claims to narrow to Israel but does not — would switch off empty-board for 104 rows"
