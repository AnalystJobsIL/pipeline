# 2026-08-31 (b) — `company-intel`

Lane: `company-intel` (`ARCHITECTURE.md` §7). Brief: the operator's correction. This lane —
and the orchestrator — closed `Oak` that morning as *"not an employer: a Teamtailor division
filter"*. The operator then found Oak's live Product Analyst posting on LinkedIn: the
employer is **Oak Identity Security OS**, a real company, and our own row holds the same role
via `il.indeed.com` `jk=9784c063c918d237`. His words: *"you should be more goal oriented and
find ways to generically close gaps as we find them."*

## 0. What was actually wrong

The lane judged a bare NAME against a registry row's URL and never looked at the evidence the
role itself carries. The morning session had just fixed the empty-context bug — every bulk
call became `research_company(name, anchor)` instead of `research_company(name, "")` — and
the fix stopped one rung short: an anchor says *where we read the name*, and the question that
was failing is *who is this*. A posting answers that, and nothing read it.

Two live proofs that an anchor alone is not enough, both from the same day:

- **`Oak`.** Every word of the morning's verdict is true about the ROW (`companies.csv` has
  `Oak` parked on `operagroup.teamtailor.com/jobs?...&division=Oak`, and the string really is
  a query parameter) and wrong about the COMPANY. Our ACTIVE Ashby row
  `Oak - Identity Security OS` publishes the SAME `Product Analyst`, first seen 08-21, with a
  correct profile already on file since 08-22.
- **`Kidum Rehab Projects`.** The 16:23Z cron re-bought it as the mental-health hostel
  operator **again**, this time WITH the correct `kidum.com` anchor. That measurement is what
  decided the fix: the board's own six listings are teachers and tutors, and no anchor
  carries that.

## 1. The rule, as a mechanism

**A company with a live published role can never be closed "not an employer" or "cannot
identify."** Refusal stays correct for ACTIVATING a board — `identity_gate`'s domain, where a
wrong yes costs a whole company's listings — and is wrong for describing what we already
publish. In code (`ARCHITECTURE.md` §7 carries the full version):

`evidence_context(company, *, board_url, postings, jd, board_titles)` is ONE formatter for
the bulk cron, the digest hook and a session alike. Trusted half first and never squeezed
(the urls we resolved, the board's own live titles, the sentence *"The profiled company must
be the one hiring for these postings"*); the JD excerpt last, flattened and cut. Cap 600 →
**1,800**, with 600 reserved for the trusted half — a prompt travels on stdin, so only
`_RESEARCH_SYSTEM` is bound to one argv line.

`research_with_evidence(company, ev, *, timeout, meta, budget)` is what both crons call. A
refusal on a name whose evidence carries a **url** buys ONE more call which flips the
subject: *"A live job posting exists and a real employer published it. Identify THAT
employer."* Same seam, same schema, both fence sentences verbatim. Skipped rather than
clamped under `DISAMBIG_MIN_S` = 120 s, because a clamped call arrives as
`ResearchUnavailable` and would read as an outage — the wave-1 bug in `_research`, rebuilt if
we had clamped. And when even the posting cannot name the publisher the reason is
**`unidentified despite role evidence`**: still exactly ONE failure for the name (every
strike, soft-outage and mass-failure counter untouched), but the weekly retry now re-asks the
answerable question and the mail says which kind of morning it was.

Three supporting pieces, each with the number that asked for it:

| | what | why |
|---|---|---|
| the board's own titles | ≤3, from `matched`, else `scraped_cache.json` (read-only; `scraper` owns it) | `matched` holds only the roles this board is ABOUT, so an active row whose roles we never match reached the model with a url and nothing else — the Kidum shape |
| Comeet uids resolved | after `todo` is cut, ≤10 GETs, unresolvable ones DROPPED | `521`. `.../company/A4.000/positions` names no employer; a GET per active row would be ~205 |
| two reads before caching | the `il_center` admission regex; the optional `employer_name` echo + `_same_company` | `525`. Both produce a ROUTABLE refusal, so the name gets the second question rather than a strike |

`--only "A,B"` is the session channel and it stamps **nothing** — not the shared `firmo`
stage (all three sites, crash stamp included) and not `state/firmo_last_ok.txt`. It exists
because of the trap this lane hit that morning: a hand-run overwrites the cron's own liveness
with a laptop's numbers, and the mail then prints `bulk cron: last ran ...` about a laptop.

## 2. The residuals, each closed on evidence

**Gap 3 → 0, published unmatched 3 → 0.** The brief said 4 and 3; the 16:23Z cron had moved
the state under it, so both were re-derived from `origin/master` before starting and again at
the end.

| name | what it actually was | how it closed |
|---|---|---|
| `Oak` | one company, two strings, beside a third thing that shares the word | `ALIASES["oak"] = "oak identity security os"`. The morning's test pinned the REFUSAL; it now pins the fold and says why it turned over |
| `Hila & Co.` | a boutique **headhunting** practice (Hila Malka, Shoham) placing a role at an FMCG company it never names | researched from its own posting. The JD says it outright: the poster's headline is *"Headhunter & Talent Acquisition"*, LinkedIn's industry tag is *Marketing Services*, and the role is at *"חברה מובילה בתחום מוצרי הצריכה (FMCG)"* |
| `University of Notre Dame` | not retired on the smell of its name | its OWN SmartRecruiters board carries 96 postings, of which exactly one is `country: il` — **`Rector - Tantur Ecumenical Institute`, Jerusalem**. `il_center` came back empty and was corrected to `Jerusalem (Tantur Ecumenical Institute)` with the provenance in `stage_note` |
| `Kidum Rehab Projects` | the wrong קידום, bought twice | the wrong record STRIPPED, re-researched with the board's titles: `education / test prep, founded 1985` |
| `Landacorp` | the board's own API returns `company_name: "Landa Corporation"` on all 13 positions | record kept (it was correct by then); `display_name` **`Landa`** |
| `Voodoo` | plausible as bought (mobile games, TLV/Raanana studios, HQ Paris) | kept; the Ashby API 403s to a plain client, so this is the one name whose board I did NOT read first-party — said here rather than implied |
| `NVIDIA AI` | the alias landed that morning | verified it joins: `identity` match, `firmo_match: none` gone |

**`Hila & Co.` is the honest asterisk.** The seam answered it on **one of three** attempts —
two `--only` runs refused and a direct call answered. Rather than re-run until it came back
green, the record is saved by hand with every field traceable to the posting text quoted
above, which I read in full, and `employees_global`/`founded` left null because nothing in
the evidence supports a number. The nondeterminism is real and is filed as what it is.

**Row-name corrections are registry's** (`534`, filed after `docs/backlog.py next`): the
`Landacorp`/`Kidum Rehab Projects` row names, and a `Landacorp`/`Landa` DUPLICATE this
session found — two rows, one employer, one `identity_key`. This lane shipped the
user-visible half as `display_name`, and both strings are byte-identical to what
`display_name_from_evidence` would write from the page they were read off (`Landa`, not
`Landa Corporation`, because `_clean_display` strips the legal tail — the table supplies a
missing READING, never a different rule). `528`'s "Landa Digital Printing" is corrected in
place: that is the operating brand, and the board writes the corporate name.

## 3. Numbers

- **Intel gap (§7's own gauge): 3 → 0.** Render set 1,146; export 1,349 → **1,351** records.
- **Published unmatched: 3 → 0** of 167, by the dataset's two-rung rule over `roles.csv`'s
  `company_registry`. The CSV itself re-publishes at the 05:00 digest — that is the 09-01
  morning check, not a claim about today's file.
- **Strike ledger 9 → 6.** Cleared `Hila & Co.`, `Oak`, `University of Notre Dame` through
  `save_failures(cleared=...)`, the only path that can express "researched since". The 6 that
  remain are `Agency`, `Discovery`, `Sivo`, `Tel Aviv` (all pre-existing) and `Ecommerce
  Guide` / `Konsortium Ziviler Friedensdienst`, which are `524` — registry's to retire.
- **Spend: 11 `claude -p` calls**, all sonnet, against a declared cap of 30 (1 seam
  smoke-test, 6 for the three-name batch, 2 for the direct Hila call, 2 for the second
  `--only`). **Bright Data: 0** — this lane's only paid rung is the subscription. Free HTTP:
  3 board reads (Notre Dame, Landa's Comeet API, kidum.com) plus one 403 (Voodoo's Ashby).
- **Gates:** `1689 passed, 13 skipped`; `companies.csv OK: 2110 rows, 1100 active, 0
  orphans, pool=886`; `docs check: 0 error(s), 4 warning(s) over 95 documents` (the four are
  other lanes' unanswered morning checks).
- **Guards:** 11 new tests, and `tools/guard_kill.py --base origin/master` reports **KILLS
  10 of 10** — every one fails when its fix is reverted. 15 mutation records added or
  re-aimed in `tests/fixtures/company_intel/mutations.json` (68 → 83).

## 4. Clause 4 — what this cost and what it removed

- **Deleted / unified:** `_row_anchor`, `_posting_anchor` and `_context_for`'s research use
  were ABSORBED into `_row_evidence` / `_posting_evidence` / `_evidence_for` over one shared
  `evidence_context`. Three sentence-builders and two context shapes became one formatter
  and one entry point; the blurb loop keeps `_context_for`, which needs no identification.
- **Extended, not duplicated:** `research_company_detail` gained two optional parameters
  (`data`, `system`) so the disambiguation ask reuses the same validator, `_coerce` and
  `result_object`. `research_with_evidence` wraps it; it does not reimplement it.
  `_same_company` reuses `_stem` / `_acronym` / `identity_key` rather than
  `display_name_from_evidence`, whose verdicts answer a different question (is this name
  worth SHOWING).
- **Rejected, with the number:** a host-vs-website check for `525` — `kidumpro` and `kidum`
  edge-contain, so the stem form passes the very case it was written for. Per-caller retry
  logic — the same classification, budget clamp and echo check in three places. A second
  "verify" call on every success — doubles the cost of the 95 % good path for a 3-in-23
  failure.
- **Would the next session find this?** `grep -n "research_company(" pipeline/` now hits the
  primitive and its two wrappers, and every caller reads `research_with_evidence`;
  `grep -rn "_row_anchor"` hits nothing.
- **What got harder for the next lane — four things, named.** One new flag (`--only`), one
  new optional schema key (`employer_name`, popped before storing), one new prompt pair
  (`_DISAMBIG_DATA` / `_DISAMBIG_SYSTEM` derived from `_RESEARCH_SYSTEM` by a `.replace`,
  which will break loudly if that sentence is reworded — a test pins it), and a read-only
  dependency on `scraped_cache.json`, which is the `scraper` lane's file.

## 5. What is NOT finished

- **Not delivered unattended yet.** The seam rides existing crons (05:00 digest hook, 10:00
  bulk) and needs no workflow change, so there is nothing for `infra` to apply — but no
  `event: schedule` run has exercised it. The 09-01 morning check is the proof.
- `Hila & Co.`'s row is still `hila.mt` (Malta) and parked — `523`, registry's. And now the
  profile says what the row is: an **agency**, the `527`/Peak Innovation class, so its
  published role is arguably out of scope. That is `registry`/`classifier`'s call, not this
  lane's; the profile is what makes it decidable.
- `Voodoo`'s board was not read first-party (Ashby 403 to a plain client). The record is
  plausible and unverified, and says so here.
- The disambiguation call is **probabilistic**: `Hila & Co.` answered on 1 of 3 attempts with
  the same evidence. Nothing measures that rate; a run of the same name twice is the cheapest
  experiment and nobody has done it.
- `522` (retire the Opera-division `Oak` row), `524`, `526`, `528`/`534` are all registry's.
