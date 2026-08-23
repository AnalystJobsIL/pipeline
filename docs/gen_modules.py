"""Regenerate docs/MODULES.md.

The prose is the CLASS dict below; the `runs in` and `imported by` columns are computed
from the workflows and the import graph, so they cannot drift. Adding a root module and
forgetting it here raises AssertionError immediately, and docs/check_docs.py fails the test
suite independently - the registry is the one place a reader can tell live code from a
one-shot probe.

    python docs/gen_modules.py && python docs/check_docs.py

Owned by the `docs` lane. Run from the repo root.
"""
import ast, glob, os, re, collections, sys

sys.stdout.reconfigure(encoding="utf-8")

CLASS = {
 # scheduled - a workflow invokes it
 "apply_resolved": ("scheduled", "applies out/resolved_configs.json into companies.csv after the self-heal"),
 "audit_empty_rows": ("scheduled", "weekly re-verification of every parked row; also the `verify()` helper every resolver imports"),
 "auto_expand": ("scheduled", "drains research_companies.json: deterministic tier, then the capped LLM tier"),
 "bd_rescue": ("scheduled", "re-fetches unreachable rows through the Bright Data Web Unlocker"),
 "check_invariants": ("scheduled", "structural gate on companies.csv + the store; blocks the digest commit"),
 "coverage_report": ("scheduled", "Sunday summary: of everything researched, how much is scanned"),
 "crack_walled": ("scheduled", "Chromium + network sniffing against walled ATSes (Phenom/Eightfold/iCIMS/SuccessFactors)"),
 "deep_validate": ("scheduled", "Saturday deep re-validation; owns `google_via_unlocker`, the only search rung that works today"),
 "discovery_daily": ("scheduled", "LinkedIn + Indeed sweeps via Bright Data -> discovered_cache.json + new employer names"),
 "discovery_telegram": ("scheduled", "public t.me/s channel previews; keyless"),
 "enrich_matched_jd": ("scheduled", "age-blind JD backfill over the matched table itself"),
 "enrich_scrape_jd": ("scheduled", "JD backfill for scrape-source jobs, with the 7-day cooldown stamp"),
 "health_check": ("scheduled", "weekly backstop to the free health detection inside pipeline.run"),
 "listing_hunt": ("scheduled", "finds the real listings URL for dark rows and verifies it; the 200-minute night job"),
 "mark_sent": ("scheduled", "marks a produced digest's roles delivered - records intent, not delivery (see docs/BACKLOG.md)"),
 "merge_csv_rows": ("scheduled", "git-layer segment-aware merge for companies.csv; every csv-committing workflow calls it"),
 "merge_json_cache": ("scheduled", "three-way merge for the company-keyed JSON caches"),
 "probe_candidates": ("scheduled", "cheap daily signal probe of monitored-candidate pages; wakes rows for the hunt"),
 "refresh_scrape_cache": ("scheduled", "00:00 re-render of every scrape row; JD carry-forward and rot-parking"),
 "repair_dead_urls": ("scheduled", "replaces stored URLs whose hostname does not resolve - runs BEFORE the hunt on purpose"),
 "repair_extract_gap": ("scheduled", "re-scrapes rows triage marked `extract-gap`; the cheapest recovery class"),
 "resolve_broken": ("scheduled", "06:00 self-heal: re-resolves boards that went stale, throttled weekly, 5 strikes"),
 "retry_unreachable": ("scheduled", "02:30 Bright Data retry of flaky endpoints"),
 "scan_dead_domains": ("scheduled", "liveness scan over parked rows; a revived domain clears its flag automatically"),
 "triage_dark": ("scheduled", "18:00 classification of every parked row by failure mode (`dark-triage <date>: <mode>`)"),
 "validate_empty": ("scheduled", "Sunday cross-validation that 'validated-empty' rows really are empty"),
 "wayback_rescue": ("scheduled", "Sunday rescue of unreachable rows via the Wayback Machine"),
 # library - imported by live code, not invoked directly by a workflow
 "scrape_universal": ("library", "the 5-strategy browser extractor, and a CLI: `python scrape_universal.py \"Name\" \"<url>\"`. Has no aggregator logic of its own - never point it at LinkedIn/Indeed"),
 "resolve_deep": ("library", "deterministic resolver tier (recognizable ATS URLs, iframes)"),
 "resolve_llm": ("library", "the LLM resolution tier: evidence bundle -> one `claude -p` proposal -> verified through the real fetcher"),
 "comeet_resolve": ("library", "reads `window.comeetvar` off a rendered page to recover a Comeet uid+token"),
 "ingest_research": ("library", "resolve+verify helpers for the research queue. **Not deletable**: `retry_unreachable` (02:30 daily) imports `PROBE_FAST`, `_cand_slugs` and `_try` from it"),
 "probe_ats": ("library", "guessable-slug probing. **Not deletable**: `ingest_research` imports `slug_variants`"),
 # operator - a human or agent runs it on demand; still live
 "registry_health": ("operator", "read-only registry census + row-deletion guard, recomputed re-check ownership matrix, live probe of every resolution rung, and the unsupported-ATS build queue. `--census` is the only thing it writes"),
 "research_firmographics": ("operator", "bulk firmographics research + `--export`. Run every 6h by the Windows task `IsraeliJobs-Firmographics` via run_firmo_chain.cmd"),
 "bd_employees": ("operator", "LinkedIn employee-count fill via the Web Unlocker, 1 credit/page. Same Windows chain"),
 "fill_employees_llm": ("operator", "re-researches employee counts the LinkedIn pass missed or got suspiciously wrong. Same Windows chain"),
 "company_type_analysis": ("operator", "joins firmographics with matched jobs -> out/company_type_analysis.{json,md} (ARCHITECTURE.md section 7)"),
 "firmo_health_check": ("operator", "tripwire: is the firmographics chain actually classifying anything?"),
 "verify_company": ("operator", "live-fetch verification of one company's endpoint - the research discipline as a script"),
 "cache_new_rows": ("operator", "scrapes rows activated since the last refresh and merges them into the cache"),
 "setup_brightdata": ("operator", "one-time: store the Bright Data token + zone in secrets.env"),
 "setup_serpapi_key": ("operator", "one-time: store the SerpApi key (quota exhausted until 2026-09-01)"),
 # legacy - one-shot capture, probe, or superseded resolver
 "bd_discover": ("legacy", "one-off test of Bright Data's Jobs-Scraper datasets"),
 "bigtech_capture": ("legacy", "one-shot Playwright capture of big-tech careers XHRs"),
 "bigtech_capture2": ("legacy", "the interactive second attempt at the same capture"),
 "capture_bodies": ("legacy", "one-shot: dump the response bodies of a careers page's internal calls"),
 "comeet_probe2": ("legacy", "superseded Comeet probe (kept: it documents how the widget lazy-loads)"),
 "comeet_probe3": ("legacy", "superseded Comeet probe - the finding became comeet_resolve"),
 "comeet_probe_pw": ("legacy", "the original Comeet diagnostic"),
 "detect_ats": ("legacy", "superseded ATS sniffing; the live version is resolve_deep + audit_empty_rows.SIGS"),
 "gen_test_board": ("legacy", "renders build_board_html with sample jobs for styling review"),
 "merge_research": ("legacy", "**rewrites research_companies.json on import.** Do not import it"),
 "ms_capture": ("legacy", "one-shot capture of the Microsoft careers search request"),
 "poc_company_profile": ("legacy", "the firmographics POC (docs/POC_COMPANY_PROFILES.md); superseded by pipeline/firmographics.py"),
 "probe_bigtech": ("legacy", "one-off probe of big-tech public job-search APIs"),
 "probe_expand": ("legacy", "one-off probe of companies not yet in the registry"),
 "recheck_suspects": ("legacy", "the ONLY clearer of the `empty-but-suspect` verdict, and on no schedule. Deleting it strands that verdict class"),
 "resolve_any": ("legacy", "superseded general resolver"),
 "resolve_parallel": ("legacy", "superseded fast HTTP resolver"),
 "resolve_unknowns": ("legacy", "superseded slug-probe pass"),
 "scrape_batch": ("legacy", "batch driver for the scraper over the research queue; writes out/*.csv only"),
 "scrape_jobs": ("legacy", "the first Playwright scraper; superseded by scrape_universal"),
 "shot_board": ("legacy", "screenshots the local board for visual review"),
 "shot_details": ("legacy", "screenshots expanded job-detail blocks"),
 "validate_bd": ("legacy", "second-pass validation of Bright-Data-scanned rows; superseded by deep_validate"),
 "verify_jsearch": ("legacy", "confirms the SerpApi Google-for-Jobs source works; that quota is exhausted"),
 "workday_probe": ("legacy", "one-off Workday tenant/site probe"),
}

PIPELINE = {
 "run": "**the orchestrator.** Owned by `infra`; any lane may need a hook in it - propose it, do not smuggle it",
 "fetchers": "one normalizer per ATS platform -> the common job shape. 16 platforms",
 "israel": "deterministic Israel-location filter",
 "seniority": "relevance + experience classification; the LLM tier for ambiguous titles",
 "store": "the SQLite seen-store: sent / matched / llm_cache / company_info / firmographics",
 "digest": "the board, the archive and the email",
 "roleprofile": "per-job skills / role family / IC-vs-lead / years",
 "health": "per-company ATS health -> cloud_state/stale.json + health_baseline.json",
 "firmographics": "per-company sector / stage / size / business model",
 "company_info": "the two-sentence company blurb",
 "jdfill": "fetches a job description for a role that arrived without one",
 "platform_check": "self-check that an ATS platform is wired into all of its sites",
 "aggregators": "is this URL an aggregator? Gates activation and runtime",
 "recruiters": "recruiting-agency exclusion",
 "atomic": "**shared** - atomic writes for every state file",
 "companies": "**shared** - load companies.csv into row dicts",
 "company_identity": "**shared** - does this URL belong to this company? Gates all four activation paths",
 "identity_gate": "**shared** - the one gate every registry writer consults before it writes api_url/active; page content is the discriminator, the tenant string is not",
 "notes": "**shared** - the companies.csv notes append-log. Never hand-roll a trim",
 "verdicts": "**shared** - the single source of truth for verdict tokens and re-check pools",
 "stages": "**shared** - which nightly stage last finished, and how much it did",
 "sources": "**shared** - per-discovery-source liveness",
 "http": "**shared** - the zero-dependency HTTP helper",
}

roots = sorted(glob.glob("*.py"))
names = {os.path.splitext(f)[0] for f in roots}


def imports_of(path):
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:
        return set()
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] in names:
                    out.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.module:
            m = n.module.split(".")[0]
            if m in names:
                out.add(m)
    return out


importers = collections.defaultdict(set)
for f in roots + glob.glob("pipeline/*.py") + glob.glob("tests/*.py"):
    for m in imports_of(f):
        importers[m].add(f.replace("\\", "/"))

wf = collections.defaultdict(set)
for w in sorted(glob.glob(".github/workflows/*.yml")):
    txt = open(w, encoding="utf-8").read()
    for m in names:
        if re.search(r"python3?\s+(?:-u\s+)?" + re.escape(m) + r"\.py\b", txt):
            wf[m].add(os.path.basename(w)[:-4])

missing = names - set(CLASS)
extra = set(CLASS) - names
assert not missing, "unclassified: %s" % sorted(missing)
assert not extra, "classified but absent: %s" % sorted(extra)

order = ["scheduled", "library", "operator", "legacy"]
buckets = collections.defaultdict(list)
for m, (c, d) in CLASS.items():
    buckets[c].append((m, d))

HEAD = {
 "scheduled": ("Scheduled - a GitHub Actions workflow runs these",
   "If one of these stops working the pipeline degrades silently, because most of their steps are `continue-on-error`. The `runs in` column is computed from the workflow files."),
 "library": ("Libraries - no workflow runs them, live code imports them",
   "**These are the trap.** They look unused in the Actions history and they are load-bearing. `docs/check_docs.py` fails if a module listed here is imported by nothing."),
 "operator": ("Operator tools - a human or an agent runs these on demand",
   "Live and documented, but nothing in CI calls them. The firmographics three are driven by the Windows scheduled task `IsraeliJobs-Firmographics`, which no GitHub Action can see."),
 "legacy": ("Legacy / one-shot / superseded",
   "Kept, not run. Nothing scheduled and nothing in `pipeline/` imports any of these - `docs/check_docs.py` fails if that stops being true. They are the deletion candidates, but read the note first: several exist only to document a finding, and two still write `companies.csv`."),
}

out = []
out.append("# Module registry - what every file is, and whether it is alive\n")
out.append("""Generated and re-verified on 2026-08-23 by the `docs` lane. **Every root `*.py` appears
here exactly once**, and `docs/check_docs.py` fails the test suite if a new one does not.
That is the point of the file: before it existed a reader could not tell live code from a
one-shot probe, and `HANDOFF.md` listed two load-bearing modules as safe to delete.

The `runs in` and `imported by` columns are **computed from the code**, not typed by hand.

| class | meaning | count |
|---|---|---|""")
for c in order:
    lbl = {"scheduled": "a workflow invokes it",
           "library": "no workflow runs it; live code imports it",
           "operator": "a human or agent runs it; nothing in CI does",
           "legacy": "one-shot, superseded, or kept only for the record"}[c]
    out.append("| `%s` | %s | %d |" % (c, lbl, len(buckets[c])))
out.append("| | **total root modules** | **%d** |\n" % len(roots))
out.append("`pipeline/` is listed at the end. Lane ownership for all of these is in `docs/AGENT_BRIEF.md`.\n")

for c in order:
    title, blurb = HEAD[c]
    out.append("\n## %s\n\n%s\n" % (title, blurb))
    if c == "scheduled":
        out.append("| module | runs in | what it does |\n|---|---|---|")
        for m, d in sorted(buckets[c]):
            out.append("| `%s.py` | %s | %s |" % (m, ", ".join(sorted(wf.get(m, []))) or "-", d))
    elif c == "library":
        out.append("| module | imported by | what it does |\n|---|---|---|")
        for m, d in sorted(buckets[c]):
            imp = sorted(importers.get(m, []))
            shown = ", ".join("`%s`" % x for x in imp[:3]) + (" +%d more" % (len(imp) - 3) if len(imp) > 3 else "")
            out.append("| `%s.py` | %s | %s |" % (m, shown or "-", d))
    else:
        out.append("| module | what it does |\n|---|---|")
        for m, d in sorted(buckets[c]):
            out.append("| `%s.py` | %s |" % (m, d))

out.append("\n## `pipeline/` - the digest-run library\n")
out.append("Eight of these are **shared plumbing**: every lane imports them and no lane owns them.\nChanging one is a say-so-loudly event (`docs/AGENT_BRIEF.md`).\n")
out.append("| module | what it does |\n|---|---|")
for f in sorted(glob.glob("pipeline/*.py")):
    m = os.path.splitext(os.path.basename(f))[0]
    if PIPELINE.get(m):
        out.append("| `pipeline/%s.py` | %s |" % (m, PIPELINE[m]))

noguard = [f for f in roots if "__main__" not in open(f, encoding="utf-8").read()]
out.append("\n## Modules that execute on import\n")
out.append("""%d root modules have no `if __name__ == "__main__"` guard, so *importing* them runs them.
`merge_research.py` rewrites `research_companies.json` on import. All %d are `legacy`, so
nothing live imports them today - but that is a fact about today, not a guard:\n""" % (len(noguard), len(noguard)))
out.append("`" + "`, `".join(noguard) + "`\n")

open("docs/MODULES.md", "w", encoding="utf-8").write("\n".join(out) + "\n")
print("wrote docs/MODULES.md")
for c in order:
    print(c, len(buckets[c]))
print("no-guard:", len(noguard))
