# 2026-08-24 — `classifier` lane: one bounded seam, a reason for every verdict, the tier in the mail

Spec written from this session: `ARCHITECTURE.md` §7b. Open items: `docs/BACKLOG.md` 116–122.
Every number here was produced by a command run this session; the command is beside it or
in §7b.

## What was wrong (measured before touching anything)

| finding | number |
|---|---|
| bare `claude -p` model on this subscription | **claude-fable-5** — `total_cost_usd` 0.577 for a one-word YES; sonnet 0.104–0.137; haiku 0.027 (`--output-format json`, 3 probes) |
| the call's context | run from the repo root, a fresh context cost **24,845** cache-creation tokens vs **4,633** from a scratch dir — `CLAUDE.md` and the gitignored `CLAUDE.local.md` went into every classification |
| the call's surface | all tools on, session persisted, prose parsed with `re.search(YES|NO)`, stderr and return code ignored |
| yesterday's tier | 163 fresh calls, 228 cache hits, `paths` 4556+49+228 = 4833 israel-matched (the last cloud run) |
| `llm_cache` | 247 rows, 45 YES (18 %), 12 title-only keys, **every row `updated=2026-08-24`** (`save_llm_cache` upserted all keys each run) |
| BACKLOG 107 in the wild | `mobileye\|experienced data analyst` → NO, judged on an empty description, served forever |
| failure surfacing | token expiry ⇒ up to 163 × 90 s silent timeouts on `llm_failed_fallback`; no line in the mail |
| Windows seam | `shell=True` with a flagged argv fails outright (`filename syntax incorrect`); `shutil.which` + `shell=False` works on both OSes |
| CLI 2.1.241 | `--bare` ⇒ "Not logged in" with **exit 0 + is_error:true**; bad token ⇒ exit 1; unknown flag ⇒ exit 1; injection probe with tools off + system prompt + schema ⇒ NO, reason names the injection |
| Israel filter | per posting; 70-company API sample 3,370 → 674; the only bare Remote/Hybrid class is Cloudflare 296 (work-mode in `location.name`) + Aim Security 6; genuine loss ≈5 (0.15 %). Sampler: active API rows, `random.seed(7)`, shuffle, first 70, `fetchers.fetch_company(r)` each, count `is_israel_job`, bucket drops by country code / remote-hybrid / other / empty |
| requirements slice | 375 stored JDs: `_ROLE_START` 183, `_REQ_HEADER` 119, 29 requirements sections past the 1,400-char window |
| docs | no `classifier`-tagged section anywhere; `HANDOFF.md` 249/250; registry 1,220 rows / 862 active (docs said 846) |

## What changed

- `pipeline/seniority.py` — keyword layer verbatim (golden: 0 of the 252 asserted title-only rows moved on the first cut; 3 moved on purpose in wave 1);
  `prompt_slice` requirements-first; `_claude` seam (tools off, schema, system prompt, no
  session, no shell, scratch cwd, `is_error` read, `LLMUnavailable(kind)`); `Classifier`
  (cap 300 / 60 min / 45 s, breaker, quarantine, staging + commit, summary, alarms); key v2
  with the description bit and NFKC normalisation; legacy keys read as bare; the module
  `classify()` kept byte-identical in signature.
- `pipeline/israel.py` — 40 entries (10 Latin siblings of Hebrew names, six districts in seven spellings, 23 towns); a space in a name matches a hyphen, apostrophes and the maqaf are spelling, a digit after a name blocks it (wave 1 blocked digits before too and lost 2 `u0022Israel` rows — wave 2); dead `_IL_COUNTRY_CODES` gone.
- **Out of lane, approved by the user:** `pipeline/run.py` (one `Classifier` per run, both
  classify sites, commit-then-save right after the loop, summary + alarms, `llm_calls` =
  attempts, a reconcile warning), `pipeline/store.py` (`save_llm_cache` writes only changed
  rows), `pipeline/digest.py` (`llm_skipped` label), `.github/workflows/daily-digest.yml`
  (CLI pinned `@2.1.241`, and the conflict path's `cp -r` → `cp -rT` — BACKLOG 125).
- Tests: 61 new cases in `tests/test_units.py` (the file collects 344; the suite 448 → 509); golden fixture
  `tests/fixtures/classifier/titles.json`; fake CLI `tests/fixtures/classifier/` (py + sh +
  cmd, 12 fake-CLI modes + `nollm`); driver `tests/rehearse_classifier.py`.
- Docs: `ARCHITECTURE.md` §7b (new), §0 and §5b key sentences, the map line; BACKLOG 3 and
  107 closed, 116–122 filed; this file; one HANDOFF line (the file is at 250/250).

## Rehearsed as tomorrow's run

`python tests/rehearse_classifier.py --case <mode> --only "Fiverr,Wix,Lightricks,Riskified,Payoneer,Monday.com,Wiz,Similarweb,Taboola,Outbrain"`
— 12 fake-CLI modes + `nollm`, each PASS on: paths reconcile (154 = 154), attempts ≥ llm + failed, the predicted
`Stages:` text, cache rows 247 → 247 on a broken morning / 247 → 260 on a healthy one, the
pinned argv, cwd ≠ repo, `git status` unchanged. Real CLI, 15 companies:
`classify: 232 judged = keyword 213 + llm 19 (4 yes) + cache 0 + failed 0 + skipped 0;
attempts 19 in 4.3 min, rejudged 18 (flipped +1/-3); model claude-sonnet-5 x19`.

Full read-only pass (`--limit 2000 --no-llm`, scratch db, before wave 1): 862 companies scanned (5 failed), 23,190 jobs → **4,837 Israel-matched**; `Decision paths: keyword=4563, keyword_nollm=274` (sums to 4,837); accepted 151 → 121 after merge; `git status` unchanged. The 274 `keyword_nollm` postings are the LLM residue — tomorrow's upper bound on attempts.

Model A/B (25 hand-labelled postings × fable/sonnet/haiku, 75 calls): sonnet agrees with **18/19** hand labels, fable 17/19, haiku 15/19; sonnet–fable 23/25, sonnet–haiku 18/25; YES counts 11/11/14; mean wall 14.1 / 14.7 / 26.6 s. Sonnet stays the default. The set, labels and raw envelopes are in the session scratchpad (not committed); the 25 postings are the `keyword_nollm` residue of `matched` + `scraped_cache.json` with a ≥300-char slice (126 candidates, seed 11).

## Adversarial waves

**Wave 1 — five Opus attackers (read-only, each with repro commands), then fixes, then re-attack by re-running the repros + suite + rehearsals.**

| lens | confirmed | fixed | filed | accepted |
|---|---|---|---|---|
| LLM seam & injection (5 real calls) | 10 | 9 (real 2.1.241 401 envelope read as `auth`; `_AUTH` anchored and never run on a good call's stdout; envelope = last result object, scan bounded; `structured_output`→`result` fallback; one-line rules so the `.cmd` shim passes them; posting fields capped; served model = largest input; explicit args beat env; `\|` in keys) | 0 | 1 (Windows `.cmd` timeout leaves a grandchild — the fixture sleeps a bounded 6 s) |
| cache & regression | 11 | 10 (failed calls charge the budget; cohort quarantine + fresh-only YES rate + ratio flips + complete `commit()`; `_desc_is_ml` counts analytics over the whole role; `has_text` = jdfill's raw measure; `skipped` counts only lost roles; one fixed scratch dir; non-bool verdicts refused; empty-normalised titles keep the raw key; 235 not 247) | 1 (124: one role on two boards judged twice — `roles`) | 0 |
| cloud run & mail contract | 12 | 6 (budget charges timeouts; alarm splits accepted/rejected/served; steady-half breaker; reconcile warning reaches `Stages:`; cap 300 / budget 60; the run.py comment made true; **`cp -rT` in `daily-digest.yml`'s conflict path**) | 4 (125 conflict paths elsewhere, 127 collapsed block, 128 timeouts+npm, 123 quarantine re-spend) | 2 (`_ascii` folds `·` — now `-`; no single spend number across the four LLM consumers, BACKLOG 7) |
| Israel & keyword tiers (1,401 live + 2,322 cached titles) | 8 | 6 (`_REQ_HEADER` never the EEO footer; `analytics engineering`/PM hard-excluded; `_BA_DOMAIN` demotes IT/finance BAs; `analysis`/`analytical`/`head of data` signals; hyphen/apostrophe/maqaf/digit handling + districts + towns; Hebrew juniors and data anchor) | 2 (126 scraper boundaries, 129 residual gaps) | 1 (`Nazareth, PA` / `Eilat Street` pass without a country code — 0 today) |
| docs truth of §7b | 8 wrong + 8 unverifiable + 6 inconsistent | all corrected in the rewrite (252 asserted of 301; the budget/flip rows are unit-tested not rehearsed; density arm now tested and stated as ≥ half; `Decision paths` real format; "checked" not "asserted"; A/B filled; `git diff --stat` quoted; constants named; `CLASSIFY_QUARANTINE_MIN`; 12 modes + nollm; STRONG-beats-exclude row; `llm_is_relevant` deleted; `custom_json`) | 0 | 0 |

One attacker regression caught by the golden fixture before it shipped: putting `analyst` into `_DATA_ANCHOR` flipped 17 senior fraud/cyber/credit "analyst" titles to accept in fallback — reverted, and the reason is now a comment on the anchor.

**Wave 2 — three Opus confirmers (2026-08-25).**

| confirmer | result |
|---|---|
| re-attack + mutation pass (0 real calls) | all 10 wave-1 repros PASS; 13 of 15 mutations killed by behavioural tests, 2 survived (the `_REQ_HEADER` footer guard and the hyphen fold were unpinned — pinned now), 2 killed only by the source-string guard on `run.py` (BACKLOG 132); **1 new HIGH**: a morning broken in both cohorts committed the flipped `|jd` verdicts — fixed (`_suspect()` judges each cohort, `quarantined_keys()` unions) and pinned; `--fresh` on a `no`/`yes` case made the driver report a correct mass-NO as FAIL — fixed; a non-string description would have raised out of `classify` (unreachable today) — coerced; the foreign-country short-circuit and the scan window pinned |
| docs truth + legibility | 10 claims corrected (the scrape command's own output was `1225 1219` — **the wave-1 digit guard had dropped two real `u0022Israel` rows: fixed, now `1225 1221`**; `�` → en/em dashes; 344 not 343; the proof retitled to the first run after the push; 252 asserted; 235/12; budget 60 not 45 in BACKLOG 121; 40 names not 30; wave-1 counts 41/31/7); 8 unverifiable numbers marked or given their command; README:86 and AGENT_BRIEF:93 still describe the old classifier (BACKLOG 131, `docs`); §7b reordered: rehearsal first, alarms under one heading, the A/B after Guards |
| tomorrow's run + commit hygiene | **`ARCHITECTURE.md` in the working tree carried a 346-line duplicate of §7–7b** (a concurrent write; `check_docs.py` cannot see it) — every mixed file rebuilt as HEAD + this lane's hunks only (4 / 3 / 1 hunks, tests +577/−0); HEAD had moved (company-intel committed twice); `cp -rT` verified on a file source; classify wall time tomorrow 16–27 min at a plausible 6 s/call on ubuntu, 64 min only at the local 14 s (then the budget line appears, benignly); the `100755` shim is LF and execs on ubuntu |

## What was spent
Claude subscription: ≈ 120 calls — 12 probes (model/flags/tokens/injection), 3 latency variants, 2 seam smokes, 19 in the real scoped run, 75 in the A/B, 5 by the seam attacker, ~4 by the confirmers.
Bright Data: 0 (`JD_BD=0`, `JDFILL` unset locally). SerpApi: 0.

## NOT finished
BACKLOG 116 (legacy rows), 117 (one seam for the repo), 118 (Cloudflare offices), 119
(render's copies), 120 (company-intel and the breaker), 121 (runner start-up time — the one
unverified number), 122 (the cap bites the same tail), 123 (quarantine re-spend), 124 (a role
on two boards), 125 (the seven other conflict paths — `infra`, high), 126–129. Tomorrow's proof is §7b's last
paragraph. One scraper-lane test fails at HEAD on 2026-08-25 independently of this work (BACKLOG 130).

## Follow-up, 2026-08-25 — "fix everything that is mine or mechanical"

- `pipeline/llm.py` — the seam moved out of `seniority.py` (`call()`; seniority's `_claude` binds
  the rules to it; 117 half-closed, three other spawners still to migrate).
- `digest.build_markdown` — `Sources not producing` / `Registry` / `Stages` now render above the
  collapsed audit under **Needs a look** (127 closed, pinned).
- `cp -rT` in `auto-expand`, `listing-hunt`, `scrape-refresh`, `self-heal` (125 closed; it was
  four other workflows, not seven).
- A behavioural `run.py` guard: one fake company through `pipeline.run.run` (132 closed).
- README:86 and the brief's lane row (131 closed); the driver's dead line and the `_first_json`
  alias removed.
