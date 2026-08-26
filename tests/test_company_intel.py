"""Guards for the `company-intel` lane (ARCHITECTURE.md §7): the digest's blurbs + facts
hook (`pipeline/company_intel.py`), the record / identity / export (`pipeline/firmographics.py`)
and the local chain.

Every assertion is a bug that shipped or a claim §7 makes. No test spawns `claude`, touches
`cloud_state/`, or reads `state/`: the store is a tmp sqlite, the export a tmp file, and
the one CLI seam (`firmographics._claude`) is monkeypatched.

    python -m pytest tests/test_company_intel.py -q
"""
import datetime as dt
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import company_info, company_intel as CI, digest, firmographics as F, store  # noqa: E402

TODAY = "2026-08-24"
REC = {"sector": "fintech", "sub_sector": "B2B payments", "stage": "growth-private",
       "stage_note": "Series B", "size_band": "S", "employees_global": 42, "founded": 2015,
       "business_model": "SaaS subscriptions", "customer_type": "SMBs",
       "il_center": "Tel Aviv (HQ)", "as_of": TODAY}


def _job(company, **kw):
    return {"company": company, "title": "Data Analyst", "location": "Tel Aviv", "url": "u",
            "posted_date": TODAY, "description": "About " + company, **kw}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A scratch store + scratch export; every `claude` call is a recorded fake."""
    st = store.SeenStore(str(tmp_path / "t.db"))
    export = tmp_path / "firmographics.json"
    export.write_text("{}", encoding="utf-8")   # present and empty; tests that want it absent delete it
    monkeypatch.setattr(F, "SHARED_EXPORT", str(export))
    calls = []

    def fake_claude(prompt, *, system="", schema="", model="", effort="", tools=(),
                    timeout=240, meta=None):
        """The seam is `F.ask` since 2026-08-26 (BACKLOG 117). The `script(prompt, tools)`
        contract every test below writes against is UNCHANGED — it still returns the CLI's
        text — and this wraps that text in the envelope shape `F.result_object` reads, so a
        JSON answer travels as `structured_output` and prose travels as the blurb schema's
        one field. Research is still `tools` truthy; the tests never had to learn a flag."""
        calls.append({"prompt": prompt, "tools": tuple(tools), "timeout": timeout,
                      "model": model, "effort": effort, "system": system, "schema": schema})
        script = getattr(fake_claude, "script", None) or (lambda p, t: json.dumps(REC) if t else "Co does X. It earns Y.")
        out = script(prompt, tools)
        if isinstance(out, Exception):
            raise out
        try:
            data = json.loads(out)
            if not isinstance(data, dict):
                raise ValueError
        except Exception:                       # noqa: BLE001 — prose: the blurb shape
            data = {"known": True, "blurb": out}
        res = {"data": data, "envelope": {"result": out}, "models": [model or "fake"],
               "searches": 1 if tools else 0, "seconds": 0.0}
        if meta is not None:
            F.record_call(meta, res, model)
        return res
    monkeypatch.setattr(F, "ask", fake_claude)
    return st, export, calls, fake_claude


def _run(st, jobs, **kw):
    kw.setdefault("run_date", TODAY)
    return CI.enrich_for_run(st, board_jobs=jobs, **kw)


# --- 1. the duplicate-spend bug: the chain read sqlite alone, never the export -----------
def test_chain_targets_exclude_companies_the_export_already_holds(env, monkeypatch):
    st, export, calls, _ = env
    export.write_text(json.dumps({"Phoenix Financial": REC}), encoding="utf-8")
    have = F.union_store(st)
    assert "Phoenix Financial" in have, "the union must see what the cloud researched"
    _, _, rep = _run(st, [_job("Phoenix Financial")])
    assert rep["candidates"] == 0 and not [c for c in calls if c["tools"]], "a profiled company is never re-researched"


# --- 2. the export is the union, not the local table ----------------------------------
def test_export_writes_the_union_not_the_local_table(env):
    st, export, _, _ = env
    export.write_text(json.dumps({"CloudOnly": REC}), encoding="utf-8")
    st.save_firmographics({"LocalOnly": REC}, TODAY)
    F.save_shared(F.union_store(st))
    assert set(json.load(open(export, encoding="utf-8"))) == {"CloudOnly", "LocalOnly"}


def test_sync_seeds_sqlite_from_the_export_and_is_idempotent(env):
    st, export, _, _ = env
    export.write_text(json.dumps({"CloudOnly": REC}), encoding="utf-8")
    assert F.sync_store(st, TODAY) == 1
    assert F.sync_store(st, TODAY) == 0
    assert st.load_firmographics()["CloudOnly"] == REC


# --- 3. a scoped local run must leave the committed file alone --------------------------
def test_scoped_run_never_writes_the_shared_export(env):
    st, export, _, _ = env
    export.write_text("{}", encoding="utf-8")
    st.save_firmographics({"Wix": REC}, TODAY)
    _, _, rep = _run(st, [_job("Wix")], use_llm=False, scoped=True)
    assert export.read_text(encoding="utf-8") == "{}" and rep["published"] is False


def test_unscoped_run_publishes_the_union(env):
    st, export, _, _ = env
    st.save_firmographics({"Wix": REC}, TODAY)
    _, _, rep = _run(st, [_job("Wix")], use_llm=False)
    assert rep["published"] and "Wix" in json.load(open(export, encoding="utf-8"))


# --- 4. an outage stops the loop, records no strike, and the mail says so -------------
def test_research_stops_on_outage_records_no_strike_and_the_mail_says_so(env):
    st, _, calls, fake = env
    n = {"i": 0}

    def script(p, tools):
        if not tools:
            return "Co does X. It earns Y."
        n["i"] += 1
        return json.dumps(REC) if n["i"] == 1 else F.ResearchUnavailable("API Error: 529 Overloaded")
    fake.script = script
    _, _, rep = _run(st, [_job("A"), _job("B"), _job("C")])
    assert rep["researched"] == 1 and rep["unavailable_after"] == 1
    assert st.load_firmo_failures() == {}, "an outage is not evidence about a name"
    lines, warn = CI.audit_lines(rep)
    assert "claude unavailable after 1 research call" in lines[0]
    assert len(warn) == 1 and "529" in warn[0]
    assert n["i"] == 2, "the loop stopped at the first infrastructure failure"


def test_a_blurb_outage_does_not_cache_an_empty_blurb(env):
    st, _, _, fake = env
    fake.script = lambda p, t: F.ResearchUnavailable("Not logged in")
    _, _, rep = _run(st, [_job("A")])
    assert st.load_company_info() == {}, "'' must not be cached for an outage"
    assert rep["unavailable_after"] == 0 and rep["researched"] == 0


# --- 5. the time budget ----------------------------------------------------------------
def test_research_respects_the_time_budget(env, monkeypatch):
    st, _, calls, _ = env
    rep = CI._report()
    rep["budget_min"] = 0
    CI._research(st, ["A", "B"], [_job("A"), _job("B")], TODAY, rep)
    assert rep["skipped_budget"] == 2 and not [c for c in calls if c["tools"]]
    assert "skipped (budget 0m spent)" in CI.audit_lines({**CI._report(), **rep, "candidates": 2, "board_companies": 2, "published": True})[0][0]


def test_each_research_call_is_clamped_to_the_remaining_budget(env):
    st, _, calls, _ = env
    rep = CI._report()
    rep["budget_min"] = 2  # 120 s left: the first call may not ask for 240 s
    CI._research(st, ["A"], [_job("A")], TODAY, rep)
    assert calls[-1]["timeout"] <= 120


# --- 6. the email's companies are researched first -------------------------------------
def test_email_companies_are_researched_before_board_only_companies():
    board = [_job("Zed"), _job("Zed"), _job("Alpha"), _job("Mailed")]
    assert CI._research_order(board, [_job("Mailed")]) == ["Mailed", "Zed", "Alpha"]


# --- 7. every report shape renders a reconcilable line ---------------------------------
@pytest.mark.parametrize("patch,needle,warnings", [
    ({"research_off": True, "candidates": 3}, "research off (--no-llm); 3 of 10", 0),
    ({}, "all 10 board companies profiled", 0),
    ({"candidates": 3, "researched": 2, "failed": 1}, "3 of 10 board companies unprofiled (cap 5/run, budget 10m): 2 researched, 1 failed", 0),
    ({"candidates": 7, "researched": 5}, "2 over the cap wait for the next run", 0),
    ({"candidates": 3, "failed": 3, "soft_outage": True}, "soft outage suspected", 1),
    ({"candidates": 2, "failed": 2}, "2 of 10 board companies unprofiled", 1),
    ({"candidates": 2, "unavailable_after": 1, "unavailable_in": "blurbs", "unavailable_reason": "timed out"}, "claude unavailable after 1 blurbs call (timed out)", 1),
    ({"blurbs_asked": 30, "blurbs_written": 1, "blurbs_empty": 29}, "blurbs: 30 asked, 1 written, 29 empty", 0),
    ({"export_status": "missing"}, "export MISSING", 1),
    ({"export_status": "corrupt"}, "file left untouched", 1),
    ({"synced": 19}, "19 newer than the store", 0),
    ({"publish_error": "PermissionError: denied"}, "export NOT written (PermissionError: denied)", 1),
])
def test_audit_lines_cover_every_report_shape(patch, needle, warnings):
    rep = {**CI._report(), "board_companies": 10, "cap": 5, "budget_min": 10.0, "published": True,
           "export_records": 940, "export_newest": TODAY, "store_records": 921, **patch}
    lines, warn = CI.audit_lines(rep)
    assert len(lines) == 1 and needle in lines[0], lines
    assert len(warn) == warnings, warn


# --- 8/15. a missing or corrupt export is reported, never silently replaced -------------
def test_missing_export_is_reported_and_recreated(env):
    st, export, _, _ = env
    export.unlink()
    st.save_firmographics({"Wix": REC}, TODAY)
    ci, disp, rep = _run(st, [_job("Wix")], use_llm=False)
    assert rep["export_status"] == "missing" and disp["Wix"] == REC
    assert export.exists() and CI.audit_lines(rep)[1]


def test_corrupt_export_is_never_overwritten_by_the_union(env):
    st, export, _, _ = env
    export.write_text('{"a": ', encoding="utf-8")
    st.save_firmographics({"Wix": REC}, TODAY)
    _, disp, rep = _run(st, [_job("Wix")], use_llm=False)
    assert rep["export_status"] == "corrupt" and disp["Wix"] == REC
    assert export.read_text(encoding="utf-8") == '{"a": ', "a corrupt export must not become a smaller valid one"
    assert F.load_shared() == {}


# --- 9/10. blurbs: derived from facts for free; '' retried monthly ---------------------
def test_a_blurb_is_derived_from_facts_without_an_llm_call(env):
    st, _, calls, _ = env
    st.save_firmographics({"Wix": REC}, TODAY)
    ci, _, rep = _run(st, [_job("Wix")], use_llm=False)
    assert "SaaS subscriptions" in ci["Wix"] and rep["blurbs_derived"] == 1 and calls == []
    assert st.load_company_info() == {}, "a derived blurb is never cached"


def test_empty_blurbs_retry_monthly_not_daily(env):
    st, _, calls, _ = env
    st.save_company_info({"Trivago": ""}, TODAY)
    _, _, rep = _run(st, [_job("Trivago")])
    assert not [c for c in calls if not c["tools"]] and rep["blurbs_waiting"] == 1
    st.save_company_info({"Trivago": ""}, "2026-07-01")
    _run(st, [_job("Trivago")])
    assert len([c for c in calls if not c["tools"]]) == 1


def test_derive_blurb_reads_the_facts_as_prose():
    assert company_info.derive_blurb("Wix", REC) == (
        "Wix is a growth-stage private company in fintech: B2B payments. "
        "It makes money through SaaS subscriptions. Customers: SMBs.")
    assert company_info.derive_blurb("X", {"sector": "fintech"}) == ""
    assert company_info.derive_blurb("X", None) == ""


def test_the_seam_pins_model_effort_search_and_never_a_shell_or_the_repo(monkeypatch):
    """The 2026-08-24 version of this test asserted only `shell is False` off Windows and
    `["claude", "-p", "--allowedTools", "WebSearch"]`. Every other property of that argv was
    unpinned, and all of them were wrong: no --model (so the CLI default ran — opus[1m] from
    ~/.claude/settings.json on the laptop, the account default on the runner, and nothing
    recorded which), no schema, no system prompt, no --output-format json (so no modelUsage,
    no cost, and no evidence the web search ever ran), and cwd inherited = the repo root,
    which read CLAUDE.md and the gitignored CLAUDE.local.md into every call. BACKLOG 117."""
    import shutil as _sh
    from pipeline import llm
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = list(cmd), kw
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(
            {"type": "result", "is_error": False,
             "structured_output": {"known": True, "sector": "fintech", "sub_sector": "",
                                   "stage": "public", "stage_note": "", "size_band": "",
                                   "employees_global": None, "founded": None,
                                   "business_model": "", "customer_type": "",
                                   "il_center": ""},
             "modelUsage": {"claude-sonnet-5": {"inputTokens": 5, "outputTokens": 9,
                                                "canonicalModel": "claude-sonnet-5",
                                                "webSearchRequests": 2}}}), stderr="")
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(_sh, "which", lambda n, *a, **k: "/usr/bin/claude")

    rec = F.research_company("Wix")
    assert rec and rec["sector"] == "fintech"
    cmd, kw = seen["cmd"], seen["kw"]
    assert kw.get("shell", False) is False, "no shell on ANY OS (it ran a bare `claude` on Linux)"
    assert "israeli-jobs-pipeline" not in str(kw.get("cwd", "")).lower(), \
        "cwd must never be the repo: from there every call read CLAUDE.md + CLAUDE.local.md"
    assert cmd[cmd.index("--model") + 1] == F.RESEARCH_MODEL, "the model must be pinned"
    assert cmd[cmd.index("--effort") + 1] == F.RESEARCH_EFFORT
    assert cmd[cmd.index("--tools") + 1] == "WebSearch", "availability"
    assert cmd[cmd.index("--allowedTools") + 1] == "WebSearch", "and permission — both axes"
    assert cmd[cmd.index("--output-format") + 1] == "json", "no envelope = no audit"
    assert "--no-session-persistence" in cmd
    assert cmd[cmd.index("--json-schema") + 1] == F._RESEARCH_SCHEMA
    assert cmd[cmd.index("--system-prompt") + 1] == F._RESEARCH_SYSTEM


def test_the_research_prompt_mandates_a_web_search():
    """Measured 2026-08-26 over four companies with a checkable recent fact: a prompt that
    merely SUGGESTED search searched on 1 of 4, and every searchless answer was staler than
    the record it would have replaced (Aidoc missed its 2026-04 Series E and $534M; Aleph
    Farms missed the 2025 down-round). Mandating it: 4 of 4 searched, 4 of 4 current.
    This sentence is load-bearing — soften it and re-run that measurement, or don't."""
    import fill_employees_llm
    for text, who in ((F._RESEARCH_SYSTEM, "researcher"),
                      (fill_employees_llm._SYSTEM, "employee fill")):
        assert "ALWAYS search the web" in text, f"the {who} stopped mandating a search"
        assert "never answer from memory" in text.lower() or "even for a company" in text, who
    # ONE line: cmd.exe truncates an argv element at a newline (the classifier lane shipped
    # 116 of 1,336 characters of rules that way)
    for text in (F._RESEARCH_SYSTEM, company_info._SYSTEM, fill_employees_llm._SYSTEM):
        assert "\n" not in text


def test_the_schema_cannot_drift_from_the_validator():
    """The schema is DERIVED from STAGES/SIZE_BANDS, and `minLength` on `sector` is what
    stops a model satisfying the whole schema with empty strings — `_coerce` insists on
    exactly one field, so an all-empty record would otherwise be ACCEPTED, cached until
    2027-02, and rendered as a one-chip card while the mail said `1 researched`."""
    sc = json.loads(F._RESEARCH_SCHEMA)
    assert set(sc["properties"]["stage"]["enum"]) - {""} == F.STAGES
    assert set(sc["properties"]["size_band"]["enum"]) - {""} == F.SIZE_BANDS
    assert sc["properties"]["sector"].get("minLength") == 1
    assert "known" in sc["required"], "without it _coerce cannot tell 'no sector' from 'not a company'"
    assert sc["additionalProperties"] is False


def test_the_three_callers_share_the_seam():
    import fill_employees_llm
    import inspect
    for mod in (company_info, fill_employees_llm):
        src = inspect.getsource(mod)
        assert "subprocess.run(" not in src, f"{mod.__name__} spawns claude itself"


def test_cli_failure_raises_with_a_kind_and_prose_returns_none(monkeypatch):
    """Infrastructure RAISES (and now carries `.kind`, so an auth failure is an outage on the
    FIRST hit instead of after SOFT_OUTAGE_MIN_FAILS); a bad ANSWER returns None and costs
    the name a strike. The exit-0-with-an-error-envelope shape is the one that used to be
    scored as the name failing — a real company struck for a keychain problem."""
    import shutil as _sh
    from pipeline import llm
    monkeypatch.setattr(_sh, "which", lambda n, *a, **k: "/usr/bin/claude")

    def stdout(text, code=0):
        monkeypatch.setattr(llm.subprocess, "run",
                            lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, stdout=text, stderr=""))

    # (a) non-zero exit -> infrastructure
    monkeypatch.setattr(llm.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Not logged in"))
    with pytest.raises(F.ResearchUnavailable) as e:
        F.research_company("X")
    assert e.value.kind == "auth", "an auth failure must be nameable as one, not 'transient'"

    # (b) THE SHIPPED BUG: exit 0, `is_error` in the envelope (the real 2.1.241 keychain-less
    #     shape). The old seam read the exit code only, so this was a weekly STRIKE.
    stdout(json.dumps({"type": "result", "is_error": True, "api_error_status": 401,
                       "result": "Failed to authenticate"}))
    with pytest.raises(F.ResearchUnavailable) as e:
        F.research_company("X")
    assert e.value.kind == "auth"

    # (c) prose: a fact about the ANSWER, with a reason that now survives the run
    stdout(json.dumps({"type": "result", "is_error": False, "result": "I'm not sure, sorry."}))
    rec, why = F.research_company_detail("X")
    assert rec is None and "no JSON" in why
    assert company_info.summarize_company("X") == ""


# --- 12. the analysis reads the committed export ---------------------------------------
def test_company_type_analysis_reads_the_committed_export_by_default():
    import company_type_analysis
    assert os.path.abspath(company_type_analysis.FIRMO) == os.path.abspath(F.SHARED_EXPORT)


# --- 13. the stats key reaches all three audit renderers -------------------------------
def test_company_intel_line_reaches_all_three_audit_renderers():
    s = {"company_intel": ["all 10 board companies profiled"]}
    _, md = digest.build_markdown([], TODAY, s, {})
    assert "- **Company intel:** all 10 board companies profiled" in md
    assert "COMPANY INTEL: all 10" in digest._text_audit(s)
    assert "<b>Company intel:</b> all 10" in digest._html_audit(s, lambda x: str(x))


# --- 14. §7 tells the truth about the code --------------------------------------------
def test_architecture_section_7_names_the_real_identity_function():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "ARCHITECTURE.md"), encoding="utf-8").read()
    sec = text[text.index("## 7. "):text.index("## 8. ")]
    assert "identity_key" in sec and "private-enterprise" in sec
    for claim in ("enrich_for_run", "audit_lines", "union_store", "chip_safe", "derive_blurb",
                  "FIRMO_TIME_BUDGET_MIN", "load_shared_status"):
        assert claim in sec, f"section 7 no longer describes {claim}"


# --- the tie rule and the record contract ----------------------------------------------
def test_newer_prefers_the_later_as_of_then_the_fuller_record():
    a, b = {"as_of": "2026-08-01", "x": 1}, {"as_of": "2026-08-02"}
    assert F.newer(a, b) is b and F.newer(b, a) is b
    filled = {**REC, "employees_source": "linkedin"}
    assert F.newer(REC, filled) is filled and F.newer(filled, REC) is filled


def test_facts_chips_are_unchanged_for_a_full_record():
    assert digest._firmo_facts(REC) == ["fintech", "growth-stage private", "~42 employees",
                                        "founded 2015", "Tel Aviv (HQ)"]


# --- mutation-sweep survivors and wave-2 findings, pinned ------------------------------
def test_a_soft_outage_in_the_digest_records_no_strikes(env):
    """Three exit-0 prose answers in a row and no success is the CLI misbehaving, not three
    bad company names — the hook used to strike all of them for a week (wave 1, A1)."""
    st, _, _, fake = env
    fake.script = lambda p, t: "I'm not sure which company you mean, but {X} might match." if t else "Co does X. It earns Y."
    _, _, rep = _run(st, [_job("A"), _job("B"), _job("C")])
    assert rep["failed"] == 3 and rep["soft_outage"] and st.load_firmo_failures() == {}
    assert "soft outage suspected" in CI.audit_lines(rep)[1][0]
    fake.script = lambda p, t: '{"unknown": true}' if t else "Co does X. It earns Y."
    _, _, rep = _run(st, [_job("A"), _job("B")])
    assert rep["failed"] == 2 and not rep["soft_outage"] and set(st.load_firmo_failures()) == {"A", "B"}


def test_extract_json_survives_a_brace_bearing_preamble():
    """`re.search(r"\{.*\}")` was greedy: "I'll research {X}.\n{...}" spanned both braces
    and a paid-for valid answer became a weekly strike (wave 1, A3)."""
    good = json.dumps(REC)
    assert F.extract_json("I'll research {X} for you.\n" + good + "\nSources: {a}") == REC
    assert F.extract_json(good + " trailing note {unbalanced") == REC
    assert F.extract_json("no json here {") is None


def test_display_records_are_chip_safe_but_stored_records_are_not_touched(env):
    st, _, _, _ = env
    long = {**REC, "il_center": "Tel Aviv (HQ; registered as Zipher Technologies Ltd, no. 517004768)"}
    st.save_firmographics({"Zipher": long}, TODAY)
    _, disp, _ = _run(st, [_job("Zipher")], use_llm=False)
    assert disp["Zipher"]["il_center"] == "Tel Aviv"
    assert st.load_firmographics()["Zipher"]["il_center"] == long["il_center"]
    assert CI.chip_safe({"il_center": "Caesarea (ABB Technologies Ltd — sales/engineering); HQ in Zurich"})["il_center"] == "Caesarea"
    assert all(len(CI.chip_safe({"il_center": s})["il_center"]) <= CI.CHIP_MAX for s in ("x " * 60, "(" * 60, "a" * 60))


def test_the_chain_export_writes_the_union_through_save_shared(env, monkeypatch, tmp_path):
    """`research_firmographics.py --export` wrote the LOCAL table over the shared file, deleting
    every record the cloud had researched since (19 on 2026-08-24, wave 1 B1)."""
    import research_firmographics as RF
    st, export, _, _ = env
    export.write_text(json.dumps({"CloudOnly": REC}), encoding="utf-8")
    st.save_firmographics({"LocalOnly": REC}, TODAY)
    monkeypatch.setattr(RF, "EXPORT", str(tmp_path / "state" / "firmographics.json"))
    monkeypatch.setattr(RF, "SeenStore", lambda *a, **k: st)
    monkeypatch.setattr(sys, "argv", ["research_firmographics.py", "--export"])
    RF.main()
    assert set(json.load(open(export, encoding="utf-8"))) == {"CloudOnly", "LocalOnly"}
    assert set(json.load(open(tmp_path / "state" / "firmographics.json", encoding="utf-8"))) == {"CloudOnly", "LocalOnly"}


def test_hand_written_profiles_pass_the_same_junk_rule(tmp_path):
    p = tmp_path / "company_profiles.json"
    p.write_text(json.dumps({"Good": "Acme builds widgets for retailers. It earns subscription fees.",
                             "Bad": "UNKNOWN", "Err": "Error: could not reach the API.", "Short": "x"}),
                 encoding="utf-8")
    assert set(CI._load_profiles(str(p))) == {"Good"}


def test_the_front_door_never_raises_and_the_line_says_what_broke(env, monkeypatch):
    st, _, _, _ = env
    st.save_firmographics({"Wix": REC}, TODAY)
    monkeypatch.setattr(st, "load_company_info", lambda: (_ for _ in ()).throw(RuntimeError("database is locked")))
    ci, disp, rep = _run(st, [_job("Wix")], use_llm=False)
    assert rep["error"].startswith("RuntimeError") and disp == {} or disp.get("Wix")
    lines, warn = CI.audit_lines(rep)
    assert "company intel FAILED (RuntimeError: database is locked)" in lines[0] and warn


def test_audit_lines_survive_a_cp1252_console_and_a_hebrew_error(env):
    rep = {**CI._report(), "board_companies": 3, "candidates": 2, "unavailable_after": 0,
           "unavailable_reason": "\u256d\u2500 Invalid API key \u2717", "error": "KeyError: '\u05e4\u05e0\u05d9\u05e7\u05e1'",
           "export_records": 1, "export_newest": TODAY}
    for line in CI.audit_lines(rep)[0] + CI.audit_lines(rep)[1]:
        line.encode("cp1252", "strict")


def test_an_unwritten_export_is_said_and_leaves_no_tmp(env, monkeypatch):
    st, export, _, _ = env
    st.save_firmographics({"Wix": REC}, TODAY)
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError("Access is denied")))
    _, _, rep = _run(st, [_job("Wix")], use_llm=False)
    assert rep["published"] is False and "PermissionError" in rep["publish_error"]
    lines, warn = CI.audit_lines(rep)
    assert "export NOT written (PermissionError: Access is denied)" in lines[0] and warn
    assert not [f for f in os.listdir(export.parent) if f.endswith(".tmp")]


def test_save_shared_uses_a_per_process_temp_name_and_reports_a_noop(env):
    st, export, _, _ = env
    assert F.save_shared({}) is False
    assert F.save_shared({"A": REC}) is True
    assert str(os.getpid()) in F.SHARED_EXPORT + f".{os.getpid()}.tmp"
    assert not [f for f in os.listdir(export.parent) if f.endswith(".tmp")]


# --- wave 2 (quota & time budget) ------------------------------------------------------
class _FakeClock:
    def __init__(self, step):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def test_blurb_calls_are_counted_and_three_empties_in_a_row_stop_the_loop(env):
    """30 calls for one blurb read as "blurbs: 1 written" and the empties guard was disarmed by
    the first success (wave 2, A1)."""
    st, _, calls, fake = env
    n = {"i": 0}

    def script(p, t):
        if t:
            return json.dumps(REC)
        n["i"] += 1
        return "Good Co does X. It earns Y." if n["i"] == 1 else "UNKNOWN"
    fake.script = script
    jobs = [_job(f"C{i:02d}") for i in range(12)]
    _, _, rep = _run(st, jobs)
    assert rep["blurbs_asked"] == 4 and rep["blurbs_written"] == 1 and rep["blurbs_empty"] == 3
    assert rep["blurbs_stopped"] and not rep["soft_outage"]
    assert "blurbs: 4 asked, 1 written, 3 empty" in CI.audit_lines(rep)[0][0]


def test_one_wall_clock_bounds_blurbs_and_research_together(env, monkeypatch):
    """The research budget used to start AFTER the blurb loop (wave 2, A2)."""
    st, _, calls, fake = env
    monkeypatch.setattr(F, "_Clock", lambda budget_min, now=None: _FakeClock.__new__(_FakeClock)) if False else None
    clock = CI._Clock(10, now=_FakeClock(200))   # every look at the clock costs 200 s
    rep = CI._report(); rep["budget_min"] = 10
    ci, missing = CI._blurbs(st, [_job("A"), _job("B"), _job("C"), _job("D")], TODAY, True, rep, None, clock)
    assert rep["blurbs_asked"] + rep["blurbs_skipped_budget"] == 4 and rep["blurbs_skipped_budget"] >= 1
    CI._research(st, ["X", "Y"], [_job("X"), _job("Y")], TODAY, rep, clock)
    assert rep["researched"] == 0 and rep["skipped_budget"] == 2, "no research after the shared budget is gone"


def test_a_blurb_soft_outage_skips_research_entirely(env):
    st, _, calls, fake = env
    fake.script = lambda p, t: "UNKNOWN" if not t else json.dumps(REC)
    st.save_firmographics({"P": REC}, TODAY)      # P has facts but no blurb
    jobs = [_job("P"), _job("Q"), _job("R"), _job("S")]
    _, _, rep = _run(st, jobs)
    assert rep["blurb_outage"] and rep["researched"] == 0 and rep["failed"] == 0
    assert not [c for c in calls if c["tools"]], "the research loop uses the same CLI"
    assert st.load_firmo_failures() == {}
    assert st.load_company_info() == {}, "an outage must not month-gate the three names it hit"
    assert "blurb soft outage" in CI.audit_lines(rep)[1][0] and "research soft outage" not in CI.audit_lines(rep)[0][0]


def test_a_blurb_outage_names_its_loop(env):
    st, _, _, fake = env
    fake.script = lambda p, t: F.ResearchUnavailable("timed out")
    _, _, rep = _run(st, [_job("A"), _job("B")])
    line = CI.audit_lines(rep)[0][0]
    assert "claude unavailable after 0 blurbs calls (timed out)" in line and "0 research calls" not in line


def test_an_all_fail_research_run_warns_even_below_the_outage_threshold(env):
    st, _, _, fake = env
    fake.script = lambda p, t: '{"unknown": true}' if t else "Co does X. It earns Y."
    _, _, rep = _run(st, [_job("A"), _job("B")])
    assert rep["failed"] == 2 and CI.audit_lines(rep)[1]


def test_one_blurb_call_per_identity_not_per_name_variant(env):
    st, _, calls, _ = env
    _, _, rep = _run(st, [_job("Meta"), _job("Meta Israel")])
    assert rep["blurbs_asked"] == 1 and len([c for c in calls if not c["tools"]]) == 1
    st2 = st
    ci, _, _ = _run(st2, [_job("Meta"), _job("Meta Israel")])
    assert ci["Meta"] == ci["Meta Israel"]


def test_a_scoped_run_writes_neither_the_export_nor_the_store(env):
    st, export, _, _ = env
    export.write_text(json.dumps({"CloudOnly": REC}), encoding="utf-8")
    _, _, rep = _run(st, [_job("Wix")], use_llm=False, scoped=True)
    assert rep["synced"] == 0 and st.load_firmographics() == {}


# --- wave 2 (re-attack) ----------------------------------------------------------------
def test_extract_json_prefers_the_substantive_object_over_a_restated_escape_hatch():
    good = json.dumps(REC)
    assert F.extract_json('plan: {} then the answer ' + good) == REC
    assert F.extract_json('{"unknown": true} — actually: ' + good) == REC
    assert F.extract_json('{"unknown": true}') == {"unknown": True}
    assert F.extract_json("{}") == {}


def test_display_index_prefers_the_canonical_name_over_an_alias_or_a_site_form():
    aws = {**REC, "employees_global": 150000, "employees_source": "linkedin", "employees_as_of": TODAY}
    amazon = {**REC, "employees_global": 1576000}
    amazon_il = {**REC, "employees_global": 1550000}
    idx = F.display_index({"AWS": aws, "Amazon": amazon, "Amazon Israel": amazon_il})
    assert idx["amazon"]["employees_global"] == 1576000
    idx = F.display_index({"Dell Israel": {**REC, "founded": 1990}, "Dell Technologies": {**REC, "founded": 1984}})
    assert idx["dell"]["founded"] == 1984
    idx = F.display_index({"AMD Israel": REC, "AMD": {**REC, "founded": 1969}})
    assert idx["amd"]["founded"] == 1969


def test_merge_keeps_the_losers_facts_but_not_a_superseded_counts_companions():
    old = {**REC, "as_of": "2026-08-01", "employees_global": 100, "employees_source": "linkedin",
           "employees_range": "51-200"}
    fresh = {**REC, "as_of": "2026-08-24", "founded": None, "employees_global": 500, "il_center": ""}
    out = F.merge(old, fresh)
    assert out["founded"] == 2015 and out["il_center"] == "Tel Aviv (HQ)"
    assert out["employees_global"] == 500 and out["size_band"] == "M"
    assert "employees_source" not in out and "employees_range" not in out
    fresh2 = {**REC, "as_of": "2026-08-24", "employees_global": None, "size_band": ""}
    out = F.merge(old, fresh2)
    assert out["employees_global"] == 100 and out["employees_source"] == "linkedin" and out["size_band"] == "S"


def test_soft_outage_threshold_is_three_not_one_or_ninety_nine(env):
    st, _, _, fake = env
    fake.script = lambda p, t: '{"unknown": true}' if t else "Co does X. It earns Y."
    rep = CI._report()
    CI._research(st, ["A"], [_job("A")], TODAY, rep)
    assert not rep["soft_outage"] and set(st.load_firmo_failures()) == {"A"}
    rep = CI._report()
    CI._research(st, ["B", "C", "D"], [_job("B"), _job("C"), _job("D")], TODAY, rep)
    assert rep["soft_outage"] and not ({"B", "C", "D"} & set(st.load_firmo_failures()))


# --- 2026-08-26: the junk gate, the seam's audit, and the shim that must not guess -------

def test_the_rehearsal_shim_can_classify_every_argv_the_real_seam_builds():
    """The old shim branched on the literal string `allowedTools` in its argv, with a `||`
    fall-through to the BLURB branch. When the seam moved onto pipeline/llm.py that predicate
    became a coin flip and the fall-through would have answered every research call with a
    blurb -- every one reading as a name failure, while the driver printed a plausible line
    and exited 0 regardless. This goes red instead."""
    import sys as _sys
    _sys.path.insert(0, "tests/fixtures/company_intel")
    import fake_claude
    import fill_employees_llm
    for want, schema in (("research", F._RESEARCH_SCHEMA),
                         ("blurb", company_info._SCHEMA),
                         ("employees", fill_employees_llm._SCHEMA)):
        assert fake_claude.classify(["-p", "--json-schema", schema])[0] == want, want
    # and it must not be made to always-pass
    assert fake_claude.classify(["-p"])[0] == "unknown"
    assert fake_claude.classify(["-p", "--json-schema", '{"required":["nope"]}'])[0] == "unknown"


def test_a_bare_job_title_is_junk_and_no_real_company_in_the_repo_is(tmp_path):
    """BACKLOG 11, restated as 101: `_JUNK_NAME` needs a role word FOLLOWED BY a separator,
    so "Senior Data Analyst" and "BI Developer" were not junk and reached the auto-expand
    queue. Closure rule: every token role/modifier vocabulary AND at least one head noun.

    The head requirement is the safety. Swept over every real name in the repo on 2026-08-26
    (companies.csv 1,244 + the export + research_companies.json + discovered_cache.json =
    1,690 names) it fires on exactly two: "my team" (already junk) and "Infrastructure Team",
    which was live in research_companies.json, one auto_expand run from being a row."""
    for junk in ("Senior Data Analyst", "BI Developer", "Product Analyst", "Head of Data",
                 "Infrastructure Team", "QA Engineer", "Full Stack Developer"):
        assert F.is_bare_job_title(junk) and F.looks_like_junk(junk), junk
    # the realistic false positives: all-vocabulary but head-less, or outside the vocabulary
    for real in ("Unit", "Team8", "Data.ai", "Cloud Security", "Solutions IQ", "Riskified",
                 "Lead Edge Capital", "CyberArk", "Check Point Software"):
        assert not F.is_bare_job_title(real), real
    # `Unit` is an ACTIVE ashby registry row; the first draft of this rule junked it
    assert not F.looks_like_junk("Unit")


def test_only_a_multiword_place_is_a_place_and_the_gate_is_this_lanes_alone():
    """"Tel Aviv" became a registry row, a firmo_failed strike, and a board section carrying
    another company's blurb (BACKLOG 167/223). MULTI-WORD only is the whole safety argument:
    "Nesher", "Eilat", "Azor", "Yakum" are single-word entries in israel._IL_PLACES that are
    also real Israeli company names (Nesher Israel Cement).

    And it must stay OUT of `looks_like_junk`: `discovery` decided on 2026-08-25 that the
    place gate is Telegram-only because the same check on the structured sources would veto
    real employers, and `looks_like_junk` reaches six modules across four lanes and,
    transitively, check_invariants' pool D."""
    for place in ("Tel Aviv", "Tel-Aviv", "Ramat Gan", "Petah Tikva", "petahtikva"):
        assert F.is_place_name(place) and F.not_a_company(place), place
        assert not F.looks_like_junk(place), f"{place} must NOT reach the shared predicate"
    for real in ("Tel Aviv Stock Exchange", "Jerusalem Venture Partners", "Haifa Chemicals",
                 "Nesher", "Eilat", "Yakum", "Afek", "Caesarea", "Riskified"):
        assert not F.is_place_name(real), real
    # derived from the classifier lane's lists, never retyped (the ISRAEL_LOC precedent)
    from pipeline import israel
    multi = [x for x in israel._IL_PLACES + israel._IL_PLACES_HE if len(x.split()) > 1]
    assert len(multi) > 20, "the classifier's place lists shrank under us"
    assert all(F.is_place_name(x) for x in multi)


def test_no_active_registry_row_is_refused_by_the_money_gate():
    """A false positive here is a silently excluded company (ARCHITECTURE.md section 8).
    Re-derive it rather than trusting the number in the commit message."""
    import csv as _csv
    rows = [r["company_name"] for r in _csv.DictReader(open("companies.csv", encoding="utf-8-sig"))
            if r["active"].strip().lower() == "true"]
    refused = [n for n in rows if F.not_a_company(n)]
    assert not refused, f"the gate would refuse ACTIVE registry rows: {refused}"


def test_the_blurb_loop_refuses_a_name_that_is_not_a_company(env):
    """THE 2026-08-25 DAMAGE. `_research_targets` has always gated on junk; `_blurbs` had no
    gate at all, so the model was handed "Tel Aviv" plus a secrettelaviv job's text as
    context and profiled a company mentioned INSIDE the context -- company_info['Tel Aviv']
    came back as Alma/Sisram Medical, was cached, and rendered as a board section. Widening
    `looks_like_junk` would NOT have prevented it: this loop never consulted it."""
    st, _export, calls, _ = env
    ci, _fd, rep = _run(st, [_job("Tel Aviv"), _job("Senior Data Analyst"), _job("Wix")])
    assert rep["blurbs_refused"] == 2
    assert "Tel Aviv" not in ci and "Senior Data Analyst" not in ci
    assert not [c for c in calls if "Tel Aviv" in c["prompt"]], "no call was spent on it"
    assert rep["gated_junk"] == 2 and rep["researched"] == 1


def test_the_mail_separates_a_weekly_retry_from_a_name_that_is_never_retried(env):
    """One `gated` counter called every gated name "research failed, weekly retry" -- false
    for a job title or a bare place, which are never retried at all."""
    st, _export, _calls, _ = env
    st.record_firmo_failure("Peak Innovation", TODAY)
    _ci, _fd, rep = _run(st, [_job("Peak Innovation"), _job("Tel Aviv"), _job("Wix")])
    line = CI.audit_lines(rep)[0][0]
    assert "1 research failed, weekly retry" in line and "1 not a company" in line


def test_the_export_line_counts_what_was_published_not_what_was_read(env):
    """Today's mail said `export 942 records, newest 2026-08-25` on a morning that went on to
    write 946, four of them dated 2026-08-26 -- the run understating its own work."""
    st, export, _calls, _ = env
    export.write_text(json.dumps({"Old": REC}), encoding="utf-8")
    _ci, _fd, rep = _run(st, [_job("Wix")])
    assert rep["published"] and rep["export_records"] == 2, rep["export_records"]
    assert f"export {rep['export_records']} records" in CI.audit_lines(rep)[0][0]


def test_a_research_answer_that_never_searched_is_counted_and_warned(env):
    """Measured 2026-08-26: a prompt that merely SUGGESTED search searched on 1 of 4
    companies, and every searchless answer was staler than the record it would have replaced.
    A searchless research answer is a parametric guess cached until 2027-02, and the only
    reason anyone would ever notice is this counter."""
    st, _export, _calls, fake = env

    def script(prompt, tools):
        return json.dumps(REC)
    fake.script = script
    _ci, _fd, rep = _run(st, [_job("Wix")])
    assert rep["llm"]["searches"] == 1 and not rep["llm"].get("searchless")

    # now make the seam report a search-free research answer
    rep2 = CI._report()
    res = {"data": REC, "envelope": {}, "models": ["claude-sonnet-5"], "searches": 0,
           "seconds": 1.0}
    F.record_call(rep2["llm"], res, "sonnet")
    rep2["llm"]["searchless"] = 1
    rep2["llm"]["calls"] = 1
    _line, warn = CI.audit_lines(rep2)
    assert any("no web search" in w for w in warn), warn
    assert "SEARCHLESS" in CI.audit_lines(rep2)[0][0]


def test_the_seam_audit_reaches_the_mail(env):
    """Today's whole company-intel step was one line and an opaque 2m22s group: 8 calls, no
    model, no timing, no evidence the search ran."""
    st, _export, _calls, _ = env
    _ci, _fd, rep = _run(st, [_job("Wix"), _job("Fiverr")])
    line = CI.audit_lines(rep)[0][0]
    assert "seam:" in line and "calls" in line and "searches" in line, line


def test_a_failed_name_carries_its_reason_into_the_mail(env):
    """`research_company` collapses three different outcomes into None and `firmo_failed` has
    no reason column, so the cause of a 7-day strike existed only in stderr."""
    st, _export, _calls, fake = env
    fake.script = lambda p, t: json.dumps({"unknown": True}) if t else "Co does X. It earns Y."
    _ci, _fd, rep = _run(st, [_job("Nowhere Ltd")])
    assert rep["failed"] == 1 and rep["failed_reasons"], rep
    assert "could not identify" in rep["failed_reasons"][0][1]
    assert "why failed: Nowhere Ltd" in CI.audit_lines(rep)[0][0]


def test_audit_lines_never_raises_on_a_legacy_report(env):
    """`audit_lines` is called at run.py:468, OUTSIDE enrich_for_run's never-raises guard, so
    a KeyError there kills the run after classification and before rendering."""
    legacy = {"research_off": False, "board_companies": 1, "candidates": 0, "researched": 0,
              "failed": 0, "skipped_budget": 0, "unavailable_after": None,
              "unavailable_reason": "", "unavailable_in": "", "soft_outage": False,
              "blurb_outage": False, "blurbs_stopped": False, "cap": 5, "budget_min": 8,
              "blurbs_written": 0, "blurbs_asked": 0, "blurbs_empty": 0, "blurbs_missing": 0,
              "blurbs_skipped_budget": 0, "blurbs_derived": 0, "blurbs_waiting": 0,
              "export_status": "ok", "export_records": 1, "export_newest": "2026-01-01",
              "store_records": 1, "synced": 0, "published": True, "publish_error": "",
              "scoped": False, "error": "", "gated": 0}
    lines, warn = CI.audit_lines(legacy)      # every new key must be read with .get
    assert lines and isinstance(warn, list)


def test_the_budget_knobs_are_read_at_call_time_not_at_import(monkeypatch):
    """As module constants they froze at first import, so a rehearsal that set the env
    afterwards silently tested the defaults it meant to override."""
    monkeypatch.setenv("FIRMO_MAX_PER_RUN", "2")
    monkeypatch.setenv("FIRMO_TIME_BUDGET_MIN", "3")
    monkeypatch.setenv("BLURB_MAX_PER_RUN", "4")
    rep = CI._report()
    assert (rep["cap"], rep["budget_min"], rep["blurb_cap"]) == (2, 3.0, 4)


def test_the_digest_budget_fits_inside_the_mail_relay_slack():
    """Measured 2026-08-26: the digest ran 05:38:55 -> 06:04:13 (25m18s) and the inbox relay
    polls at 06:17, so there are ~13 minutes of slack before the mail slips an hour to the
    07:17 poll. A 15-minute budget was LARGER than the slack -- safe only because it was
    never spent. The bulk backlog belongs to the 10:00 UTC cron, not to the mail's path."""
    assert CI._DEFAULTS["FIRMO_TIME_BUDGET_MIN"] <= 10


def test_a_blurb_already_cached_under_a_non_company_name_is_dropped_at_read_time(env):
    """Gating the loop only stops us BUYING another one. cloud_state/seen.db holds
    company_info['Tel Aviv'] = "Alma, a Sisram Medical company, ..." — cached 2026-08-25 from
    a secrettelaviv job's text used as context — and that is the text rendering under
    `### Tel Aviv` on the board today. Dropping it at read time fixes every machine at once
    and needs no write to seen.db, which is SINGLE_WRITER: daily-digest (committing the
    laptop's copy would clobber the runner's matched/roles/llm_cache)."""
    st, _export, _calls, _ = env
    st.save_company_info({"Tel Aviv": "Alma, a Sisram Medical company, makes lasers."}, TODAY)
    st.save_company_info({"Wix": "Wix builds websites. It sells subscriptions."}, TODAY)
    ci, _fd, rep = _run(st, [_job("Tel Aviv"), _job("Wix")])
    assert "Tel Aviv" not in ci, "the poisoned blurb must not reach a card"
    assert ci.get("Wix"), "a real blurb is untouched"
    assert rep["blurbs_dropped"] == 1
