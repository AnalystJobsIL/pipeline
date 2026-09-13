# 2026-09-13 — classifier: the posting's own word on where it is, the verdicts nobody could date, Ballerine

Lane `classifier` (`ARCHITECTURE.md` §7b). **51 `claude-sonnet-5` calls through
`pipeline/llm.py`, 0 Bright Data credits** (every invocation `JD_BD=0 BD_RUN_CAP=0`; the seam
ran from the shared checkout against the worktree's store, everything else from the worktree).
Planned ≤ 45; the overrun is the one-vote own-text check on the 11 kept cached cells, which
the plan had not counted. Calls: 16 (the backfill pass over the 31) + 10 (two votes on each of
five paid flips) + 9 (three votes on each of three cached flips) + 11 (one vote on each kept
cached cell) + 2 (SemiConductor Devices' tie-break) + 3 (Ballerine).

Cross-lane, all named: one predicate added to `pipeline/roles.py` (`class_unjudged`) and its
use in `record_run`'s backfill loop (`roles`' file, the backfill map is this lane's input to
it); six lines appended to `cloud_state/roles_retractions.jsonl` (the sanctioned channel);
`cloud_state/seen.db` (Ballerine's key forgotten, 17 verdicts cached). The `_jd_why` clause
in the unreachable alarm is `jd-text`'s ask, agreed live by message.

Every number was read on 2026-09-13 from `origin/master` `640eb3c`.

## 1. `566` — the feed's location against the posting's own words

**What was wrong.** `is_israel_job` read `country_code`, `location` and `url` and nothing
else. Two shapes put foreign roles through it: a careers widget copying one chip onto every
card (Wiliot's eight cards read `Israel`; each office is glued to the title,
`Data Solutions AnalystSan Mateo`), and an aggregator stamping its search region over a JD
that names its office (`il.indeed.com` wrote `מחוז המרכז` over Diageo's `Location: 3 WTC (New
York)`). `LLM_RULES` asks nothing about geography, so the seam judged Diageo YES on scope and
was right to.

**The finding that decided the design: the gate cannot see the text that matters.** The gate
runs at fetch time (`run.py:432`), before `classify_grouped` fills the description. Diageo's
and TransUnion's discovered cards carry 163 characters; the `Location:` line lives only in the
filled text. So the rule runs at two sites: the gate (on the card) and the classifier's
deterministic head (`_classify` and `judge_backfill`, after the shared-text guard), both
through one predicate, `israel.stated_foreign_place`.

**The rule, and the draft it replaced.** A broader draft (any listed country, region or city
ending a title, any `Location:` line) flipped 49 scraped and 9 discovered cards. All 9
discovered flips were territories of Israeli roles: `Airwallex | Senior KYC Analyst …
EMEA` in Tel Aviv, `Bright Data | Technical Product Marketing Manager - EMEA` in Netanya,
`CONTROP | Marketing Manager, Central Asia & Eastern Europe`, `Deel | … (EMEA)`, `Waterfall |
Sales account manager – europe`, `Strada | … - Turkey`, `Pazu Games | … South America/ Europe`.
Every unambiguous right flip named a CITY. So a title fires only on a listed city after a
separator, or on a listed city or country GLUED to it (a widget artefact, never a territory).
The description arm fires only when the card's own location is weak (empty, bare `Israel`, a
work mode, an aggregator url), because Gamida Cell's own board says Kiryat Gat while its
stored text carries `Location: US – Remote` from sibling-posting bleed. Any Israeli place in
the title or the description silences both arms.

**Measured, `python tools/measure_israel_rule.py --base origin/master --texts`:**

| | before | after |
|---|---|---|
| cached cards passing the gate | 6,691 | 6,655 |
| flips read | | 36, **36 right, 0 wrong** |
| discovered-cache flips | | 0 |
| published records the head would reject | | 0 |
| ledger records the head would reject | | 1 (Diageo, already `withdrawn`) |

The 36, by company: Wayve 23 → 4 (`…Leonberg, Germany` ×10, `…Tokyo, Japan` ×6,
`…Sunnyvale, California USA` ×3, `…London, United Kingdom` ×3, `…Detroit`), Wiliot 8 → 0
(Kyiv, San Mateo, Dallas ×4, New York, Portugal glued), Bright Data 27 → 23 (`- San
Francisco` ×2, `- China / Singapore`, `- Cyprus, Limassol`), Adcore 1 → 0 (`– Toronto,
Canada`), Flytrex 1 → 0 (`- Houston`), ctera (`Eastern US New York`), Freightos (`Montreal, CA
Accounting Assistant`, a card blob that leads with its office), Lightbits Labs (own
`Location: USA (Remote – Central or Mountain Time Zones preferred)` under a bare `Israel`).
Every row with its label: `tests/fixtures/classifier/2026-09-13-geo-and-unknown-contract.json`.

**Named misses.** TransUnion ("We are India's leading credit information company" is company
boilerplate; reading it would move every Tel Aviv posting of a foreign company). A bare
country or region ending a title (`Ballerine | Deployment Strategist - USA` ×2 and `- Europe`,
`Bright Data | … - China` / `- Japan`, `888 | … - Spain`, `Orbit | … - Europe`). Freightos'
`Dallas, US Business Development Executive Read more` (the tail after the comma is over 40
characters).

**The published check the item asked for** — descriptions of published rows with a
`Location:` line naming a non-Israeli place that the rule does not refuse: **0**. The one
`Location: US – Remote` row (Gamida Cell) is protected by its own board's Israeli city, which
is the design.

**Rehearsed** on a copy of `cloud_state/` (`python -m pipeline.run --only
"Discovery,Wiliot,Ballerine" --no-llm --db <copy>`): `classify: … geo: 0 refused on the
posting's own text + 8 at the gate`, and the tree untouched.

## 2. `rows_unknown` — 31 verdicts no contract stood behind

**What was wrong.** `roles.csv.meta.json` read `rows_unknown 30` of 170 on 2026-09-12 (31
ledger records; `8fig|credit risk analyst` is the one outside the file's window). Every one
was `closed`, stamped before the verdict dict carried its contract (2026-09-11). A closed
record never re-enters `merged`, and the backfill (the only writer that reaches one) read any
decision as judged. `544` had said it in so many words: nothing DRAINS them.

**What changed.** `roles.class_unjudged(rec)`: no decision, or no contract. `class_backfill.
candidates` and `apply_to` read it; `record_run`'s backfill loop replaces such a cell with a
verdict that names its contract, never on a record the run judged itself (`by_key`,
`class_rejects`) and never unknown-for-unknown. The `backfill:` line now says how many of its
records were an unknown-contract decision. Bounded by the existing `CLASSIFY_BACKFILL_CAP` 60.

**The re-judge, on each record's stored text** (`tools/rejudge_rows.py --unknown-contract
--judge`, then `--votes`): 16 bought, 15 served from a live-contract cell. **23 kept, 8 moved.**

| record | stamped | now | seam | adjudication |
|---|---|---|---|---|
| Cato Networks \| Marketing Ops & Analytics Manager | accept | reject | cached NO + NO/NO/NO | **withdrawn** — marketing-ops routing, scoring, SDR enablement |
| dentsu Israel \| Marketing Analyst | accept | reject | cached NO + NO/NO/NO | **withdrawn** — ad-account management, client-facing |
| Paz - yellow \| Trade Marketing Analyst | accept | reject | cached NO + NO/NO/NO | **withdrawn** — planogram and layout execution |
| DealHub \| GTM Business Analyst | accept | reject | NO/NO/NO | **withdrawn** — GTM programs and daily operations |
| SuperPlay \| Head of BI | accept | reject | NO/NO/NO | **withdrawn** — leads data engineering and architecture |
| Zipher \| Data Scientist | accept | reject | NO/NO/NO | **withdrawn** — condition (2), model development |
| Zipher \| Senior Data Analyst | accept | reject | NO/YES/NO | kept, no line — a flap resolves conservatively (09-11 rule); the cell reads `reject` |
| Parametrix GmbH \| Technical Data Analyst (Tel Aviv) | reject | accept | YES/YES/YES | kept — dashboards and data-quality analysis for Product and Sales |

Kept, with an own-text vote that agreed: Armis, Bounce AI, CommIT, Harel, HiBob, SuperPlay
Senior Marketing Data Analyst, Tenengroup, ZOLL, הפניקס, מנורה מבטחים. Kept on a flap:
SemiConductor Devices `מהנדס/ת נתונים` (cached YES, fresh NO/NO/YES — an SPC-statistics role
the seam reads both ways). Kept, bought fresh and agreeing: Blockaid, Chargeflow, Gamida Cell,
Holisto, Keshet, Oak, ONE ZERO, Taboola ×2, Trivago, Yotpo. `8fig` has no text at all and
serves its live-contract `|bare` YES.

The six lines are in the 545 shape (url AND `role_id`), bound with the predicate that decides
(`Retractions.load` → `bind` → `match_all`): **60 lines, 6 new, each binding exactly 1 record,
0 bad**. The rehearsal above printed `roles withdrawn 6 role(s)`.

**The six unreachable verdicts of 09-13**, from the run log, and jd-text's reading of each by
address (message, same afternoon): `gong|senior data scientist - ai research & reliability`
(LinkedIn card, 0 chars; Gong is a Greenhouse row), `legit security|appsec analyst team lead`
(url is another role's Comeet posting), `centraleyes|cyber analyst` and `…for reporting and
content` (url is the careers listing page), `fortinet|incident response analyst:` (oraclehcm,
render cap 0), `plus500|business development analyst` (listing page). Four structural, one
free own-board copy, one needs one rendered credit — and every title is one the gate would
refuse anyway, so none is a published row. The brief's "9" was the 09-11 count; 09-13 is 6.
At jd-text's request the per-key line now ends `- jd: <why>` and the alarm groups by it.

## 3. Ballerine — the deferral closes: IN

`v3.0f84ab84|ballerine|ai fraud data analyst (senior)|jd => 0` was bought on 2026-09-02 over
3,998 characters of which 2,671 were site chrome. jd-text replaced the text with the
posting's own 1,662 characters on 09-11 (`1c1e4a3`); the key has no text hash (`551` b), so
the 09-12 digest served the old NO and stamped the record `reject` (the mail's
`class-rejected 1`). `tools/rejudge_rows.py --role-id "ballerine|ai fraud data analyst senior"
--forget --judge --votes 2`: 1 key forgotten, **YES/YES/YES** ("a direct hire … on-site
analytic role at Ballerine analyzing fraud/payments data"). Its card is in `scraped_cache.json`,
so the next digest judges it from the new cell. Morning check below.

## 4. ClixScale — a 94-character snippet, measured and left alone

`v3.0f84ab84|clixscale|bi analyst|bare => 1` on `Skills: SQL, BI tools, Data analysis,
Communication, Flexibility, Teamwork. Seniority: Junior.`. Measured over the live contract's
752 cells: `|bare` YES **7**; of those, stored text under 300 characters **2** (8fig 0,
ClixScale 94); **on the board or in the mail today: 0** (held, closed, superseded or
withdrawn). A snippet is judgeable in the only sense the contract uses: `looks_like_jd`
refuses it, so the verdict is keyed `|bare`, is provisional, and is re-judged free the day a
real description lands. Meanwhile `run.py`'s publish gate holds the role and the ledger keeps
`held_since`, so it is emailed when the text arrives. **Rejected:** a seam-side defer (it
turns withholding into losing — no record, no `held` alarm, no re-offer — to save at most one
call a day) and a floor in the rules text (a contract bump re-supersedes ~560 cells for 7).
No code, no test: a test of the status quo cannot fail against base.

## 5. Green, and where

**Locally, from the worktree at `origin/master` + this diff, after the last rebase:**
`python -m pytest` (not `-q`, and without `JD_BD`/`BD_RUN_CAP` in the environment, which reds
three paid-rung tests on their own) **2 failed, 2010 passed, 13 skipped** — the two are
`infra`'s bd-gauge tests, red on `origin/master` before this commit (run `34755843907`).
`python check_invariants.py` `companies.csv OK: 2383 rows, 1381 active, 0 orphans, pool=841`;
`python docs/check_docs.py` **0 error(s), 0 warning(s) over 132 documents**; `python
docs/backlog.py check` clean. `python tools/guard_kill.py --base origin/master`: **KILLS 13,
CANNOT-FAIL 0** — the country-code assertion read CANNOT-FAIL first (it pins the status quo)
and is folded into the glued-title test. `python tools/mutate.py --id` with baseline, one at a
time: `geo-gate-veto-removed`, `geo-head-removed-from-classify` and
`backfill-reads-a-decision-as-judged` **killed** (direct killers), and the re-anchored
`desc-appeal-survives-a-shared-careers-page` **killed** (behavioural).

**In CI, on the commit that was pushed (`f74f650`): run 34763188734, conclusion `failure`,
15 of 16 jobs green** — `guard-kill`, six `rehearse` shards and all eight `mutation-gate`
shards. `guard` red: `2 failed, 2032 passed, 1 skipped`, and the two are exactly
`test_the_gauge_alarms_on_the_free_tier_and_refuses_nothing` and
`test_an_unreadable_account_still_reports_a_gauge_from_the_repos_own_ledger` (`infra`).

**Diff** (`git show --numstat f74f650`): +1,870 / −33 over 15 files, of which 771 lines are
the measurement artifact, 229 tests, 298 the two tools, 227 the four pipeline modules.

**Clause 1 — the lane's number.** *0 role records without a classifier verdict*: 0 before, 0
after. The number under it moved: published verdicts no contract stands behind, **30 → 0 on
the next digest** (predicted, morning check 2026-09-14), and foreign-office cards passing the
Israel gate, **36 → 0** in both caches.

**Clause 2 — delivered or a hand-drain.** Delivered: both the geography rule and the
unknown-contract drain run inside `daily-digest.yml` at 05:00 UTC with nobody watching; the
alarms are the `classify:` line's `geo:` clause and the `backfill:` line, and the 09-14
morning-check rows are the unattended proof. A hand-drain by construction: the six withdrawal
lines and Ballerine's forgotten key.

## 6. Clause 4

* *Deleted or unified?* `git diff --stat origin/master...HEAD` (numbers in §5). Three
  inline copies of "is this cell judged" (`candidates`, `apply_to`, `record_run`) became one
  predicate; the `551` hand-SQL became a tool. Not unified, on reading: the scraper's
  `_FOREIGN_PLACES` and `_FOREIGN_PAGE_RX` carry regions on purpose (a territory is evidence
  on a single-role page, not in a title), and `scraper` was editing that file today.
* *Extended, not duplicated:* `is_israel_job` (one new check), `Classifier._classify` and
  `judge_backfill` (the head), `class_backfill.candidates`/`apply_to`, `Ledger.record_run`'s
  backfill loop, `Retractions.load/bind/match_all` for the binding check,
  `measure_scope_rule._flatten`'s shape for the new tool's cache walk.
* *Rejected, with the number:* a region/country title arm (9 of 9 discovered flips wrong); the
  description arm on a company board's Israeli city (Gamida Cell); a TransUnion-shaped
  boilerplate arm (moves every Tel Aviv posting of a foreign company); a contract bump to reach
  31 cells (~560 re-superseded); a seam-side snippet defer (0 roles on the board, ≤ 1 call a
  day); withdrawing either flap.
* *Would the next session find it?* `grep -n "def stated_foreign_place" pipeline/israel.py`;
  `grep -n "def class_unjudged" pipeline/roles.py`; `ls tools/` shows `rejudge_rows.py` and
  `measure_israel_rule.py`; `grep -n "566" ARCHITECTURE.md` lands on the Gate 1 paragraph.
* *Harder for the next lane, counted — six.* (1) A foreign-place vocabulary in `israel.py`
  that a reader of "why was this card dropped" must know. (2) A module counter
  (`israel.VETOED`). (3) A `geo:` clause on the `classify:` line. (4) `roles.class_unjudged`,
  which widens what the backfill spends on. (5) Two tools. (6) A fixture file.

## Traps this session hit

* **The Bash heredoc ate a backslash again**, in a Python patch whose search string held
  `\n` — the assert failed, which is the only reason it did not silently patch nothing. `sed`
  did the same and wrote a real newline into a test string. `chr(92)` works.
* **`sed -i` rewrote `tests/test_units.py` from CRLF to LF.** Harmless here (`autocrlf` and an
  LF blob), but a CRLF-aware patch run after it must re-detect the line ending.
* **Opening the store rewrites `seen.db`**: a dry run of the tool against the worktree's store
  left the binary modified. Commit it on purpose or copy the store first.
* **A test fixture put `Location:` mid-sentence**, which the label regex deliberately ignores —
  read a failing new test as a fixture bug before touching the rule.
