# 2026-09-11 — classifier: the weekly delta audit adjudicated, the agency class closed, the seam's own miss measured

Lane `classifier` (`ARCHITECTURE.md` §7b). One commit of code, state and docs, one of the
CI verdict. **60 `claude-sonnet-5` calls through `pipeline/llm.py`, 0 Bright Data credits**
(every local invocation ran `JD_BD=0 BD_RUN_CAP=0`; the seam ran from the shared checkout,
everything else from a worktree). Declared ≤ 70; spent 60: 25 (one seam pass over all 25
rows) + 18 (two more passes over the nine rows that disagreed with this lane) + 3 (the
vocabulary cards) + 14 (item D, the chrome-stripped re-judges).

Cross-lane, all named: 6 appended + 45 re-keyed lines in `cloud_state/roles_retractions.jsonl`
(`roles`' hand-curated input, the sanctioned channel); four entries in
`pipeline/recruiters.py` (`discovery`'s file, by the spawn brief's dispensation); the
`contract` key on every verdict dict at the `roles` lane's live request; three one-line
fixes in `tools/` this lane owns.

## 1. Item A — 25 rows, 6 withdrawn, 18 kept, 1 deferred

The audit's claims were judged on each row's published text (`cloud_state/roles_text.jsonl`)
against the live contract `v3.0f84ab84` and the 09-01 records. Procedure: read the text;
check it is the row's own (all 25 are — the McCann, Fiverr and Fetcherr captures are partial
but not another posting's); one seam pass over all 25; where the seam and this lane
disagreed, two more passes so a stable verdict can be told from a flap (the 08-30 record's
method). Artifact: `tests/fixtures/classifier/2026-09-11-delta-audit.json` — every vote,
every reason, every ground.

| row | audit | seam (1 / 2 / 3) | adjudication |
|---|---|---|---|
| Peak Innovation \| Data Analyst | OUT | YES / NO / NO | **withdrawn** — condition (4); the seam's YES is its own documented miss (§3) |
| Edikted \| Retail Data Analyst | BORDERLINE | NO / NO / NO | **withdrawn** — execution: six of nine bullets are the analyst's own replenishment; this lane's first read was IN |
| Flex \| Material Planning Analyst | OUT (carried) | NO | **withdrawn** |
| aQurate \| DATA analyst | OUT (carried) | NO | **withdrawn** — condition (4); the row is `321@registry` |
| Qlik Israel \| BI Developer (Qlik Specialist) | OUT | NO | **withdrawn** — an implemented project plus its management at client sites |
| Bank Leumi \| Business Analyst, Corporate Banking HQ | BORDERLINE (carried) | NO | **withdrawn** — a staff-and-projects analyst; coordination and events lead |
| Mobileye \| Algorithm Data Analyst | OUT | YES / YES / YES | **kept** — the analytics-engineer record's OUT clause is conjunctive; the role has a reporting output of its own. The audit's claim is refuted on the record's wording |
| Ferrero \| Business Analyst | BORDERLINE | YES / YES / YES | **kept** — this lane read the merchandising-operations lead as execution and defers to a stable verdict |
| Intelligent Business \| Power BI Developer / Analyst | BORDERLINE | YES / YES / YES | **kept** — one weak workplace tell; the row is `321@registry` |
| ICE \| Analyst, Index Operations | BORDERLINE | YES / YES / NO | **kept** — a named report deliverable (withfaye / CloudHiro) |
| Experda \| BI Consultant & Data Developer | BORDERLINE | NO / NO / YES | **kept** — dashboards and metrics for clients; `321@registry` |
| Keshet Media \| BI / Data Developer | BORDERLINE | NO / NO / YES | **kept** — the closest call; Domo dashboards for business users are in the stated output |
| Voyantis \| Data Analyst | BORDERLINE | NO / NO / YES | **kept** |
| Check Point, EY (senior), Jazz, McCann, Practical Vision ×2, JTI, ONE datAI, Commit, Parametrix, Cal | BORDERLINE / IN | YES | **kept** (McCann provisional: requirements-only capture, the snippet rule) |
| Ballerine | BORDERLINE (carried) | NO on the stored text | **deferred** to jd-text's `567`/`572` — the buried JD answered YES on 09-02 |

**The abort rule, re-counted honestly.** The pre-committed rule was the 09-01 one: more than
3 disagreements with the seam ⇒ stop and file. Against pass 1 alone this session had **9**,
which is why passes 2 and 3 were bought. Against the STABLE verdicts (3 of 3) it has **0** —
every 3-of-3 answer was followed, including three where this lane had read OUT (Ferrero,
Mobileye, Intelligent Business) and one where it had read IN (Edikted). Against the
majority it has 3 (Experda, Keshet, Voyantis: NO/NO/YES), each resolved by keeping the row.
No stable verdict was overridden, and no row was withdrawn against the seam. That is written
into the execution record as a rule so the next session does not re-derive it.

**Cal (item B's rider): IN.** Its text names Cal's own underwriting portfolio and models; the
registry lane opened Cal's own careers page and found the posting verbatim, so the `JB-26786`
requisition code is Cal's own stamp. A JB- number alone is not a tell (Central Bottling 17621).

**The lines.** Six, in the 545 shape (url AND `role_id`), `status: withdrawn`, reasons citing
the condition and the record, JD quotes and the seam votes in `evidence`. The binding check
ran with the predicate that decides — `Retractions.load` → `bind(records, extra=<sqlite
rows>)` → `match_all` over both stores: **54 lines, 0 bad, 108 pairs, 0 naming no record,
0 naming more than one**; each new line exactly 1. Then a scoped rehearsal of the digest on
a COPY of `cloud_state/` (`python -m pipeline.run --only Discovery --no-llm --db <copy>`):
`roles withdrawn 6 role(s)`, the tree untouched.

## 2. The rehearsal found a second defect — a re-post un-withdraws an agency posting

The first rehearsal also logged `roles retraction lifted for 1 role(s) … INGIMA | Data
Analytics Team Lead (5485)` and `roles retraction unmatched (…-ingima-4460874869)`. Traced:
INGIMA's placement, withdrawn 2026-09-01 on condition (4), was **re-posted on 2026-09-03
under LinkedIn id 4462787120**; the card reached `discovered_cache.json` in the 09-11 digest
commit; the ledger absorbed it into the same record (same `merge_key`) and moved the record's
`url` to the new id; and the 09-01 line — url-only — named nothing: no record owns the old
address any more, and the `seen_id` arm needs an id half that is an http url
(`discovery-linkedin:linkedin:4460874869` is not). The record returned to `open`. Tomorrow's
real digest would have done the same.

Taken, in the sanctioned channel: **every url-only line (45) was stamped with the `role_id`
of the one record that owned its url today** — re-checked, 54 lines still bind 1:1 — and a
second rehearsal reads `roles withdrawn 6`, INGIMA `withdrawn`, no lifted, no unmatched.
`test_the_delta_audit_lines_bind_to_exactly_one_record_each` refuses a bare line from now on.
Not taken, `roles`' file: the durable fix in `Retractions.bind` (`583@roles`).

## 3. Item B — the agency class, closed by a test and not by two names

`grep -c "recruiter 2026" companies.csv` = **2** (Peak Innovation, Hila & Co.), and
`is_recruiter()` was False for **both**; the six undated `recruiter` notes were all in
`_CONFIRMED`. `_never_ours` has three sources and none reads the registry note (`518`), so
`peak innovation|data analyst` was created by LinkedIn intake on 09-04 and published, open,
for eight days. Added: `peak innovation`, `peak tech innovation` (the LinkedIn slug, so the
slug arm catches it), `hila & co.`, `hila & co`. Measured on today's discovery cache: **3
cards newly dropped at intake, 0 before** (2 Peak, 1 Hila). Pinned negatives untouched.

The class: `test_every_registry_recruiter_verdict_is_a_mechanism` reads `companies.csv` and
demands `is_recruiter()` True for every row with a dated `recruiter` verdict — a tripwire on
the registry's next park, named to that lane directly. The registry session confirmed the
same two names from its side and is adding a `registry_health.py` census line; the
enrichment-layer view of the class (20 active rows whose firmographics say staffing and the
name test misses) is on `321`.

**The seam's own miss, measured.** Peak's posting answered YES on its own JD twice (pass 1,
and again with the chrome stripped) with `ahinoam@pickpeak.co` inside the 1,400-character
window. A model told the company is "Peak Innovation" cannot know `pickpeak.co` is a
recruiter's domain. The workplace record now says so; the mechanism, not a rule, is the fix.

## 4. Item C — the two vocabulary holes, measured and refused

Over both caches (6,368 Israel cards; 5,832 cards / 5,572 pairs refused on the title; the
shipped appeal admits 29 / 29 today), each candidate arm alone: Hebrew `אקסל` **+0**, bare
`BI` **+0**, `ניתוח ועיבוד מידע` **+0**, `כלכלן`/`economist` **+1**, `חוקר`/`מדידה והערכה`
**+0**. All arms at once (the audit's `כלכלן/ית מנוסה` needs the phrase AND the Hebrew tool):
**+3 cards / +3 pairs**, judged: **3 of 3 NO** — two Amitim pension-fund investment
economists and the Leiman Schlussel FP&A economist. Rule from the brief: an arm that gains 0
in-scope roles is not added. Pinned by
`test_the_refused_vocabulary_arms_reach_nothing_the_shipped_appeal_does_not`.

Logica-IT's suffix: stripping the board's category/region labels moves 11 of 94 titles — 10
`excluded→none` and 1 `signal→none` (`Enterprise Data Lead BI השפלה` loses its hearing) —
0 gained, so not a gate change; `584@scraper`. Every Logica card is condition-(4) OUT anyway.

`574` closed: the three tool call sites pass the description, and `tools/measure_title_gate.py`
prints cards AND pairs. Dry run on today's cache: `rejected: 2,815` of 2,967.

## 5. Item D — chrome in the slice: 14 of 32 reached, 0 verdicts moved

Of the 55 audited rows, 32 are LinkedIn-hosted (30 `il.linkedin.com`). `prompt_slice`'s
window reaches LinkedIn chrome on **14** and carries another employer's listings (the
`עבודות דומות` block) on **9**. Re-judged on the JD alone (login prefix and everything from
the first chrome marker dropped): **13 YES, 1 NO — and the NO is Edikted, which is NO on
three full-text passes too.** So **0 of 14 verdicts were made BY the chrome**, and no
re-judge pass is owed when jd-text strips the class. Mechanism, written on `551`: the key
has no text hash, so a strip would not trigger one anyway; if a re-judge is ever owed the
tool is the `551` precedent (delete the row's `llm_cache` keys under every prefix), never a
contract bump (~560 rows re-superseded for a dozen). The Ballerine finding (a leading chrome
PREFIX inverting a verdict, 09-02) is a different shape from these trailing lists and stands.

## 6. The roles lane's live request — `contract` on every verdict

Mid-session the `roles` lane asked for the verdict dict to carry the contract that judged it
so it can close `544` tonight. Done: `base` carries the live contract, `_lookup` returns the
prefix that answered fifth, the three cache-serving returns carry it, the backfill whitelist
keeps it, and the superseded verdicts the mail counts as unreachable now print one key per
line (`[classify] superseded verdict cannot be re-judged (…): <key> <- <prefix>`).

## 7. Green, and where

**Locally, from the worktree at `origin/master` + this diff:** `python -m pytest` (not `-q`)
****3 failed, 1859 passed, 13 skipped** (run twice on the merged tree; the three are the inherited calendar-rot tests below)**; `python check_invariants.py` **`companies.csv OK: 2330 rows, 1365 active, 0
orphans, pool=824`**; `python docs/check_docs.py` ****0 error(s), 3 warning(s) over 119 documents****; `python docs/backlog.py check`
clean. `python tools/guard_kill.py --base origin/master`: ****KILLS 3, CANNOT-FAIL 0** — the vocabulary guard read CANNOT-FAIL on its first run (a refusal is the status quo, the 09-03 lesson) and now also pins the `574` tool fix, which reverting `tools/measure_title_gate.py` breaks**. The one new
mutation record, `confirmed-loses-peak-innovation`, run singly: ****killed** (`tools/mutate.py --id`, with baseline, 311 s); the re-anchored `desc-appeal-survives-a-shared-careers-page` was proven directly — both mutants applied in the working tree red their named killers and both are green after the revert — because a `--skip-baseline` run today is not evidence (four inherited reds unfilter the killers)**.

**In CI, on the commit that was pushed: run **34611525857**, conclusion `failure`, **14 of 16 jobs green** — `guard-kill`, six `rehearse` shards and seven of eight `mutation-gate` shards. `guard` red: `3 failed, 1871 passed, 1 skipped` and the three are exactly the inherited calendar-rot tests named below (`infra`). `mutation-gate (5)` red: `39 mutation(s): 38 killed, 1 SURVIVING/failed` — the one is jd-text's `jd-head-skip-uses-the-classifier-regex-again`, "killed ONLY by source-text guard(s)", inherited from `1c1e4a3` where it red that run's shard 3 (run 34610661040); both of this session's records read `killed`.** Inherited before this push: run
34595704316 on `284f0af` was `failure` on `guard` alone — `3 failed, 1848 passed` — the three
calendar-rot tests `infra` owns (`test_a_junior_posting_still_contributes_its_employer`,
`test_workable_reads_the_field_names_the_api_actually_sends`,
`test_wayback_run_writes_one_line_per_attempt_and_verifies_yesterdays_pending`).

**Clause 1 — the lane's number.** *0 role records without a classifier verdict*: 0 before,
0 after. What moved is the published file — 6 rows the operator's bar says it may not carry
leave it tomorrow — and the mechanism under one class of them.

**Clause 2 — delivered or a hand-drain.** The `_CONFIRMED` entries run inside
`daily-digest.yml` at 05:00 UTC with nobody watching; the alarm is the mail's `cache: dropped`
counter and, for the store record, the `roles withdrawn` clause; the 2026-09-12 morning-check
row is the unattended proof. The six lines and the 45 re-keys are a hand-drain by
construction (`543`, and `583` for the re-key), and the `roles` lane says its `543` map lands
tonight — which does NOT cover these six (their cached verdicts are live-contract YES, so the
drain never re-judges them). The vocabulary and the chrome are measurements, not deliveries.

**Clause 4.**

* *Deleted or unified?* `git diff --stat origin/master...HEAD`: nothing deleted; one
  duplication removed by folding the cards/pairs count into the tool that measures instead
  of a fourth ad-hoc script. `−` is small and that was right: every item was a line to add,
  a name to add, or a number to refuse.
* *Extended, not duplicated:* `Retractions.load/bind/match_all` for the binding check (never
  a hand-rolled matcher); `measure_title_gate.judge` and `measure_scope_rule --source ledger`
  for every seam call; `_relevance`'s existing `desc` parameter in the three tools;
  `_CONFIRMED` rather than a fourth `_never_ours` source (that is `518`, `roles`').
* *Rejected, with the number:* the five vocabulary arms (3 of 3 NO); the Logica suffix strip
  (11 moved, 0 gained, 1 lost); a contract bump to re-judge the chrome rows (0 of 14 moved,
  ~560 rows re-superseded); withdrawing Ferrero / Mobileye / Intelligent Business against a
  3-of-3 YES (0 overrides of a stable verdict); a `purged` status for Peak (the retraction
  wins the ladder and `withdrawn` is what the sibling line carries).
* *Would the next session find it?* `grep -n "peak innovation" pipeline/recruiters.py`
  hits the entry and its evidence; `grep -c '"role_id"' cloud_state/roles_retractions.jsonl`
  reads 54; `grep -rn "2026-09-11-delta-audit" tests/` hits the two guards.
* *Harder for the next lane, counted — four.* (1) A tripwire on the registry's `recruiter`
  parks. (2) A shape lock on retraction lines (no more url-only lines). (3) A fifth element
  on `_lookup`'s tuple and a `contract` key on every verdict dict that whitelists must carry.
  (4) A new fixture file.

## Traps this session hit

* **A bash heredoc with Hebrew and an apostrophe dies at the wrong line.** Three patch
  scripts were rewritten as files; the pairs-tally patch matched nothing because the
  heredoc had re-escaped `\n`.
* **`_versioned` wants a hex prefix** — a smoke test with `v3.old1234` found no superseded
  row and looked like a bug in the fifth tuple element. It was the test key.
* **`grep … && python patch.py`: a grep with no hit stops the chain silently** and the patch
  never ran while the tests after the `;` did. Check `git diff --stat` before believing a
  patch landed.
* **A scoped rehearsal on a COPY still reads the tree's caches**, which is how it found the
  INGIMA re-post — and why the copy, not the shared tree, is where a rehearsal belongs.
