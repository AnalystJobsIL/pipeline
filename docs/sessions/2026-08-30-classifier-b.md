# classifier (b) — 2026-08-30 evening: the drain that fits in one run

Lane: `classifier`. Worktree `classifier-0830b` off `origin/master` `deb030c`. Spent:
**0 paid sonnet calls** (every measurement below is cache/ledger arithmetic; the audit needed
no seam call). Bright Data: 0. SerpApi: 0. No workflow dispatched, none cancelled.
Tomorrow's unattended 05:00 run is *expected* to spend ~316 sonnet calls (~17 min) draining
the queue; hard ceiling now 450 calls ≈ 24 min (was 300 ≈ 16).

## The one job: 210 → 0 in one unattended run

The morning session left `classify 210 roles decided by a SUPERSEDED verdict … about 4 more
run(s) at this rate` in the mail, and GitHub dropped 5 of its last 75 cron slots (lags to
+734 min), so "4 more runs" meant Wednesday at best. Re-derived from the committed
`cloud_state/seen.db` (commit `8eb1340`): the versioned stale pool is exactly **210 cache-key
suffixes over 205 distinct company|title = 201 NO priors + 9 YES priors** (winning prefixes:
`v2` ×185, `v3.a517bb77` ×25) — and the 33 reachable legacy rows (27 NO) are drain demand ON
TOP of it: a legacy row has no versioned key, so it is not in the 210, while the digest
alarm's 210 counts postings and does include legacy encounters. The two 210s agreeing is a
coincidence of populations, not a reconciliation.

**What was actually binding.** Not `CLASSIFY_REJUDGE_CAP`. Demand tomorrow ≈ 205 versioned
stale + 33 reachable legacy + ~78 fresh ≈ **316 attempts against `CLASSIFY_LLM_CAP` = 300** —
the global call cap was the wall, and raising only the rejudge cap would have starved fresh
roles behind the drain in encounter order (a fresh role skipped can fall out of the 48-hour
email window forever). An adversarial design pass caught this before it shipped: the first
draft (reserve 80 at cap 300) capped the drain at 220 attempts and would have left ~60–90
stale rows queued tomorrow while its own tests passed.

**Shipped** (all in `pipeline/seniority.py` defaults — production sets no `CLASSIFY_*` env,
so the defaults are the production values and no workflow was touched):

| change | why |
|---|---|
| `CLASSIFY_LLM_CAP` 300 → **450** | the actually-binding bound; 450 ≈ 24 min of the 60-min budget (~1,150 calls fit) |
| `CLASSIFY_FRESH_RESERVE` = **80**, new | the drain — BOTH cohorts, YES included — may never spend the run's last 80 call slots (`_may_rejudge` refuses at `attempts >= cap − reserve`, counted in `reserve_held`). The structural form of the promise the YES cap's "deliberately generous 150" only gestured at; it is what makes a big NO cap safe |
| `CLASSIFY_REJUDGE_CAP` 60 → **250**, permanent | pool self-drains, so steady-state cost is zero; a deliberate contract change drains in ONE run. Reverses the morning session's "cap stays at 60" — its simulation saw 82 queued; the real run measured 210 (jd-fill delivered more descriptions) |
| stalled-alarm gated on `reserve_held` | a reserve pause is the reserve working, not the scope change stalling |
| runs-to-empty divides by `min(rejudge_cap, cap − reserve)` | the mail must not promise a rate the run cannot deliver |
| deleted the "legacy rows are never re-judged" comment (was seniority.py:812-816) | dead prose: legacy rows join the drain since `3bf54c2`; the code five lines below said the opposite |

Arithmetic for tomorrow: ~205 + 33 + ~78 ≈ 316 < 370 (= 450 − 80) drain-inclusive demand;
NO cohort ≤ 234 ≤ 250; YES cohort ≤ 9 + a few legacy YES ≤ 150; ~316 × 3.2 s ≈ 17 min ≪
60-min classifier budget ≪ 110-min step budget (the 08-30 digest run used 51 min — from its
run page, not re-derivable from the tree).

**The mass-flip guard at 210-row volume: structurally silent, by construction.** Only
same-contract, same-seam re-judgements feed `_v2_*` (`same = prior[2] and prior[3]`), and
drain purchases are in `_drain_keys`, which `quarantined_keys()` never withholds — BACKLOG
123's exact design. The one line that CAN mention the drain is the informational
"drain moved N … ALL of them the same way" (fires only if every flip is one-directional);
expected-possible tomorrow and flagged in the morning-check row so it is not read as the
mangled-rules case.

Rejected designs, per done-clause 4: date-gated one-off boost (dead code with a live
trigger; the next contract change re-needs it); deferred end-of-run drain (cleanest shape —
fresh can never starve and no reserve constant — but needs job-payload retention, a second
pass around `classify_grouped` (run.py:389/:410) and an inline-YES/deferred-NO hybrid; wrong
risk <24 h before an unattended run — see BACKLOG 503); leave 60, zero on Wednesday (cost of
waiting is small — the board serves only 8 stale rows — but the operator's one-run
requirement was explicit).

Kill-tests (all three verified red against base `seniority.py` before push):
`test_the_drain_never_spends_the_fresh_reserve`,
`test_a_reserve_pause_is_not_a_stalled_scope_change`,
`test_a_deliberate_contract_change_drains_in_one_unattended_run` (the 2026-08-30-shaped
morning: 210 stale NOs interleaved with 80 fresh under the shipped defaults → everything
drains, every fresh path is `llm`, no SUPERSEDED/stalled line).
`test_the_stale_yes_drain_cannot_starve_the_fresh_roles_behind_it` now passes
`fresh_reserve=0` to keep isolating the YES-cap mechanism. `tests/rehearse_classifier.py`
pops the three rejudge/reserve env vars so a local export cannot skew a rehearsal.

## The 87-YES audit (item 4): condition (5) is biting; the surge is the drain

The 05:00 run's step log reported `llm 191 (87 yes)` (the `(87 yes)` shape is
`Classifier.summary()`, which never reaches the digest — the digest itself carries only
`llm=191`); the committed db is the 10:54 run
(`funnel.csv` says `judged_llm=63` for it), so the auditable population is the **93** YES
rows written 2026-08-30 under `v3.da2cb878`. Decomposition against older-prefix verdicts for
the same job suffix:

    45  re-confirmed YES   (the uncapped stale-YES drain re-buying its own cohort)
     6  flipped NO -> YES  (the experience-bar removal reaching old rejects)
    42  fresh              (no versioned prior; 1 has an exact-normalised legacy twin)

So 51 of 93 are the drain, not a loosened rule. `_QUALITATIVE_HINT` matches **0** of the 93
YES titles, and the fresh-YES sample is uniformly quantitative (senior data / product / BI /
fraud analyst at 365Scores, Aidoc, Armis, Chargeflow, Checkout, Fiverr, Gong…). The rate
went up because the un-starved LLM finally read descriptions AND the YES-drain re-confirms —
not because condition (5) stopped biting. The two Comcast YES rows in the sample are the
fabricated-location pair: correctly judged in-scope on their text; their exclusion is
`withdrawn`'s job (roles), not the classifier's.

## Bare `location == "Israel"` (item 5): rule rejected with a number, nothing shipped

Of the **13** published rows whose location is exactly `Israel`/`ישראל`, 11 are genuine and
2 are the Comcast pair — and corroboration is nearly absent: `text_mentions_israel(url)` is
False for all 13 (three sit on `il.linkedin.com`/`il.indeed.com` hosts the predicate does not
read); the ledger keeps no `country_code` at all, and of the SOURCE records exactly one —
Nebius via `discovered_cache.json`, `country_code: "IL"` — is decided before the location
test ever runs. A corroboration rule would drop **10 of the 11 genuine** (Percepto ×2,
Tavily, HiBob, Ecoppia, Nebius/greenhouse, EPAM, Jobgether, Nestlé/אסם measured one by one)
to catch 2 rows that three belts already catch (registry's query-URL park, roles'
`withdrawn`, `462@scraper`'s card-level fix). Answer to scraper's
coordination question: **the record alone cannot distinguish the nine from the two** — the
distinguishing fact (did the card have a place of its own, or did the board's query echo it)
exists only at scrape time, so `462@scraper`'s `_from_cards`/`_FOREIGN_PAGE_RX` direction is
the only real fix and no `israel.py` change is warranted (`500@roles` owns reading each bare
row's own page once). §7b now records this with the measurement. Found while measuring, other lanes' to fix: the Nestlé/אסם pair is the same
posting under two company names (superseded-detection miss), **seven** rows (all
`purged`, three distinct location values) have company/location swapped
(`company="Tel Aviv"`), one location is un-normalised `NETANYA_ISRAEL`.

## Legacy keys (item 6): morning number stands, refined

254 non-contract rows = **235 legacy proper** (233 `company|title` + 2 with `|` in the
title) + 12 title-only (unreachable by construction) + 7 `jdq1|`. They drain since
`3bf54c2`, and they are demand beside the 210, not inside it (see above). On the 10:54 db
the shadowed/reachable split is **202 / 33 (27 NO)** — the morning's 193/42 was the 05:00 db,
and the split decays every run as the drain writes versioned twins. Purge (`116@classifier`)
only after the drain completes, re-derived fresh, from a cloud run's own commit, never a
local checkout.

## The audit trail without touching `store.py` (item 7)

`454@roles` (evidence columns) is explicitly blocked until this drain completes, and the
cross-lane debt rule permits only N-copies→one-function unifications — a schema change is
not that. The drain is still auditable because `cloud_state/seen.db` is committed:

    BEFORE = commit 8eb1340 (2026-08-30 10:54 UTC), AFTER = the first digest commit ≥ 2026-08-31.
    git show <commit>:cloud_state/seen.db > seen.db, then for each contract-keyed suffix
    (pipeline/seniority._versioned) compare the served verdict (newest prefix wins) —
    tonight's before-state: 464 suffixes, 254 current (161 NO / 93 YES), 210 superseded-only
    (201 NO / 9 YES; v2 ×185, v3.a517bb77 ×25).

## The adversarial waves (two opus agents, throwaway copies, never a worktree)

**Wave B (fact-check) found six wrong numbers in this record's first draft**, all corrected
above and in §7b/HANDOFF/AGENT_BRIEF: "11 non-digest callers" was really 33 call sites in 28
files; "3 swapped rows" was 7 (3 distinct locations, all purged); "0 of 13 corroborated"
missed the Nebius discovery record's `country_code: "IL"` (so 10/11 FN, not 11/11); the
"290 vs 300" arithmetic didn't close until the 33 reachable legacy rows were counted (316 vs
300); the 193/42 legacy split had decayed to 202/33 by the audited db; the §7b bounds row's
mail sample still said `cap 300 calls`. It also caught `tools/drain_forecast.py` defaulting
to the retired cap 60 — now it asks the Classifier.

**Wave A (attack) confirmed the headline** (its own simulation of the true queue shape —
188 `|jd` + 22 `|bare` + 78 fresh — drains to 0 with `reserve_held` 0) **and broke three
edges**, all fixed with kill-tests:
1. A drain attempt whose call FAILED served the stale verdict but fell out of
   `stale_served`, so `queued` undercounted by the failure count — a flaky morning could
   report the queue empty with 16 % of it left. Fixed (one line in the verdict-None branch);
   guard `test_a_failed_drain_attempt_still_counts_as_a_served_stale_verdict`.
2. A run the reserve paused before ANY drain printed "about 1 more run(s)" (a rate it did
   not achieve) and the stalled alarm stayed gagged. Now such a run prints its own line —
   "the fresh reserve paused the drain before it re-judged anything (N held…)" — and no
   forecast; guard extended in `test_a_reserve_pause_is_not_a_stalled_scope_change`.
3. A superseded `|bare` prior whose description today is another role's byte-identical text
   was a drain purchase that `commit()` then refused — paid and re-bought daily. `drainable`
   now requires `not shared`; the row counts unreachable (the truth); guard
   `test_a_shared_description_is_never_a_drain_purchase`.
Wave A also reshaped the one-run kill-test to the measured queue (188 `|jd` re-read on text
+ 22 `|bare`), which the first version — 210 `|bare` — did not certify. Two accepted,
documented edges: `fresh_reserve >= cap` turns the drain off for the run (visible via the
new paused line, an operator lever, no clamp), and the bare→jd upgrade path spends outside
every drain cap, as it always has (≤ ~60 rows tomorrow).

## Housekeeping the word cap forced

`HANDOFF.md` stood at exactly 3,200/3,200 words when this session arrived, so every added
word had to be bought. Bought by pruning the "Closed since this list was written, verified
2026-08-27" footnote (items 6–7, ~70 words) down to a one-line pointer — the verifications
live in the 08-26/27 session records. If `docs` disagrees, that block is restorable from
`git show deb030c:HANDOFF.md`.

## What this session did NOT finish

- The queue is **still 210 tonight**; it moves at the next unattended run (~05:00 UTC
  2026-08-31, ~9 h away). Predicted: 210 → 0 reachable in that one run; honest date if
  GitHub drops the slot: the next fired slot (worst observed lag +734 min). The 08-31
  morning-check row carries the completion criteria.
- ~30 unreachable superseded verdicts still need descriptions (`464@jd-text`); 193 shadowed
  legacy rows still need purging (`116@classifier`, after the drain).
- The intake bugs found in §item-5 (Nestlé/אסם duplicate, company/location swap,
  `NETANYA_ISRAEL`) are scraper/roles material, reported here, not filed as new items
  (462/`board-data-issues` cover the class).
