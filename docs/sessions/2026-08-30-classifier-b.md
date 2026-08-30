# classifier (b) — 2026-08-30 evening: the drain that fits in one run

Lane: `classifier`. Worktree `classifier-0830b` off `origin/master` `deb030c`. Spent:
**0 paid sonnet calls** (every measurement below is cache/ledger arithmetic; the audit needed
no seam call). Bright Data: 0. SerpApi: 0. No workflow dispatched, none cancelled.
Tomorrow's unattended 05:00 run is *expected* to spend ~290 sonnet calls (~16 min) draining
the queue; hard ceiling now 450 calls ≈ 24 min (was 300 ≈ 16).

## The one job: 210 → 0 in one unattended run

The morning session left `classify 210 roles decided by a SUPERSEDED verdict … about 4 more
run(s) at this rate` in the mail, and GitHub fired 66 of the last 71 cron slots (lags to
+734 min), so "4 more runs" meant Wednesday at best. Re-derived from the committed
`cloud_state/seen.db` (commit `8eb1340`): the queue is exactly **210 job-identities = 201 NO
priors + 9 YES priors** (winning prefixes: `v2` ×185, `v3.a517bb77` ×25).

**What was actually binding.** Not `CLASSIFY_REJUDGE_CAP`. Demand tomorrow ≈ 210 drain +
~80 fresh ≈ 290 attempts against `CLASSIFY_LLM_CAP` = **300** — the global call cap was the
wall, and raising only the rejudge cap would have starved fresh roles behind the drain in
encounter order (a fresh role skipped can fall out of the 48-hour email window forever).
An adversarial design pass caught this before it shipped; the first draft would have left
~50–60 queued tomorrow while its own tests passed.

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

Arithmetic for tomorrow: 210 + ~80 ≈ 290 < 370 (= 450 − 80) drain allowance; NO cohort 201 ≤
250; YES cohort 9 ≤ 150; ~290 × 3.2 s ≈ 16 min ≪ 60-min classifier budget ≪ 110-min step
budget (yesterday's whole digest: 51 min).

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

The digest's `llm 191 (87 yes)` is the 05:00 run; the committed db is the 10:54 run
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
2 are the Comcast pair — and **0 of 13 carry any corroboration**: every `country_code` is
blank, no URL mentions an Israeli place (Percepto ×2, Tavily, HiBob, Ecoppia, Nebius ×2,
EPAM, Jobgether, Nestlé/אסם measured one by one). A corroboration rule = 100 % false
negatives on the class it judges, to catch 2 rows that three belts already catch (registry's
query-URL park, roles' `withdrawn`, `462@scraper`'s card-level fix). Answer to scraper's
coordination question: **the record alone cannot distinguish the nine from the two** — the
distinguishing fact (did the card have a place of its own, or did the board's query echo it)
exists only at scrape time, so `462@scraper`'s `_from_cards`/`_FOREIGN_PAGE_RX` direction is
the only real fix and no `israel.py` change is warranted (`500@roles` owns reading each bare
row's own page once). §7b now records this with the measurement. Found while measuring, other lanes' to fix: the Nestlé/אסם pair is the same
posting under two company names (superseded-detection miss), three rows have
company/location swapped (`company="Tel Aviv"`), one location is un-normalised
`NETANYA_ISRAEL`.

## Legacy keys (item 6): morning number stands, refined

254 non-contract rows = **235 legacy proper** (233 `company|title` + 2 with `|` in the
title) + 12 title-only (unreachable by construction) + 7 `jdq1|`. They drain since
`3bf54c2`; of the queue's 210, the legacy-reachable subset rides the same one-run drain.
The 193 versioned-shadowed rows are dead weight for `116@classifier` — purge only after the
drain completes, from a cloud run's own commit, never a local checkout.

## The audit trail without touching `store.py` (item 7)

`454@roles` (evidence columns) is explicitly blocked until this drain completes, and the
cross-lane debt rule permits only N-copies→one-function unifications — a schema change is
not that. The drain is still auditable because `cloud_state/seen.db` is committed:

    BEFORE = commit 8eb1340 (2026-08-30 10:54 UTC), AFTER = the first digest commit ≥ 2026-08-31.
    git show <commit>:cloud_state/seen.db > seen.db, then for each contract-keyed suffix
    (pipeline/seniority._versioned) compare the served verdict (newest prefix wins) —
    tonight's before-state: 464 suffixes, 254 current (161 NO / 93 YES), 210 superseded-only
    (201 NO / 9 YES; v2 ×185, v3.a517bb77 ×25).

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
