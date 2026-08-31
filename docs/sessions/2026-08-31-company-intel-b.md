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
**1,800**, of which the first 600 bound what we QUOTE — and the rule sentence is appended
AFTER that cut, because wave 2 found it inside and last, i.e. the first casualty of a long
posting: one real row (`Computer Guard Technologies LTD`, a 430-char percent-encoded
LinkedIn url beside a 67-char Hebrew title) already deleted the one sentence `525` is closed
on, silently, exactly when the evidence is richest — a prompt travels on stdin, so only
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
| Comeet uids resolved | after `todo` is cut, ≤10 GETs, unresolvable ones DROPPED | `521`. `.../company/A4.000/positions` names no employer; a GET per active row would be 190 |
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
| `Hila & Co.` | a boutique **headhunting** practice (Hila Malka) placing a role at an FMCG company it never names | researched from its own posting. The JD says it outright: the poster's headline is *"Headhunter & Talent Acquisition"* and the role is at *"חברה מובילה בתחום מוצרי הצריכה (FMCG)"*, an employer it never names. `il_center` first stored **Shoham** and wave 2 was right that that is the posting's — i.e. the CLIENT's — town, not the agency's site; it is now empty, with the reason in `stage_note`. LinkedIn's industry tag reads *Marketing Services*, which is a signal AGAINST the read, not for it — the headhunter headline and the withheld employer are what carry it |
| `University of Notre Dame` | not retired on the smell of its name | its OWN SmartRecruiters board carries 96-97 postings (`totalFound` moved between two reads), of which exactly one is `country: il` — **`Rector - Tantur Ecumenical Institute`, Jerusalem**. `il_center` came back empty and was corrected to `Jerusalem (Tantur Ecumenical Institute)` with the provenance in `stage_note` |
| `Kidum Rehab Projects` | the wrong קידום, bought twice | the wrong record STRIPPED, re-researched with the board's titles: `education / test prep`. Its `founded` came back **1985 and is 1981** — the About page this session had already opened says so; wave 2 caught it |
| `Landacorp` | the board's own API returns `company_name: "Landa Corporation"` on all 13 positions | record kept (it was correct by then); `display_name` **`Landa`** |
| `Voodoo` | plausible as bought (mobile games, TLV/Raanana studios, HQ Paris) | kept; the Ashby API 403s to a plain client, so this is the one name whose board I did NOT read first-party — said here rather than implied |
| `NVIDIA AI` | the alias landed that morning | verified it joins: `identity` match, `firmo_match: none` gone |

**`Hila & Co.` is the honest asterisk.** The seam answered it on **one of three** attempts —
two `--only` runs refused and a direct call answered. Rather than re-run until it came back
green, the record is saved by hand with every field traceable to the posting text quoted
above, which I read in full, and `employees_global`/`founded` left null because nothing in
the evidence supports a number. The nondeterminism is real and is filed as what it is.

**Row-name corrections are registry's** (`538`): the `Landacorp` / `Kidum Rehab Projects`
row names, and a DUPLICATE — and wave 2 corrected me on which duplicate. I filed the parked
`Landa` row, which is **Kärcher's** pressure-washer brand on `landa.com`, an unrelated
company. The real one is **`Landa Digital Printing`**: a second ACTIVE row, carrying its own
paid record (460 employees, 2002, Rehovot) for the same employer as `Landacorp`. Their
`identity_key`s differ (`landacorp` vs `landa digital printing`), so nothing in the pipeline
can see it — two active rows, two records, one company.

`Kidum` shipped as a `display_name`; **`Landa` shipped and was withdrawn the same evening.**
It could never have rendered: `rolecard.display_name` refuses a derived name whose identity
belongs to another company, and `Landa Digital Printing`'s record makes it exactly that —
measured, `""` against the real export and `"Landa"` only against a one-record dict. An
override that cannot appear is worse than none, because it lets a backlog item claim a fix
no reader can see. So for that row the name follows the merge; it does not substitute for
it. And the string itself was right: the board's API returns `company_name: "Landa
Corporation"` on all 13 positions, which is why `528`'s "Landa Digital Printing" is
annotated in place — that is the operating brand, and the board writes the corporate name.

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
  10 of 10** — every one fails when its fix is reverted. mutation records 68 → 86, but see the
  wave section: this shard's scoring cannot tell a real kill from its own anchor test
  (`540`), so that count is NOT evidence and is reported only as work done.

## 3b. What the adversarial waves took back

Two Opus attackers were run against the committed diff. The data/claims wave found **sixteen**
defects and it was right about the ones that mattered; every fix below is in the same branch.

**Four that were wrong in the product, not the prose:**

1. **The rule sentence could be truncated out of the prompt.** `_CTX_RULE` sat last inside the
   600-char trusted cut, so a long posting deleted the one sentence `525` is closed on — and
   a real matched row already did it (`Computer Guard Technologies LTD`: a 430-char
   percent-encoded LinkedIn url beside a 67-char Hebrew title). It is now appended AFTER the
   cut, with a guard built from that exact row. 177 tests passed while this was live; none of
   them had a trusted half over 600 characters.
2. **`Kidum` `founded: 1985` is 1981.** The board's own About page says so — *"רשת קידום הוקמה
   בשנת 1981"* — in the title, the og:description, the schema.org block and the body. I had
   that page open to read the job titles and did not check the one number in the record that
   could be checked. Corrected, with the legal entity (קידום ידע והשכלה בע"מ) and the Holon HQ
   the record had left as "central Israel". **Prevention put the right COMPANY in the record;
   it did not make the record's numbers true**, and those are separate jobs.
3. **`Hila & Co.`'s `il_center: Shoham` was the client's town.** The record's own logic says
   the job is at an unnamed FMCG company; Shoham is the posting's location, i.e. that
   client's site, not the agency's. `il_center` renders as a location chip (`394`), so it
   would have shipped one company's town under another's name. Now empty, with the reason in
   `stage_note`.
4. **`Landacorp` → `Landa` could never render.** `rolecard.display_name` refuses a derived
   name whose identity is another company's, and `Landa Digital Printing` — a second ACTIVE
   row for the same employer, with its own paid record — makes it exactly that. Withdrawn,
   and a guard now checks every override against the REAL export rather than a fixture, with
   `finbounce` listed as the one knowingly shadowed entry (`487`). That guard also found the
   duplicate I had filed wrongly: the row I named in `538` was Kärcher's `Landa`.

**Four documents that said something untrue:**

5. **`522` still told the next `registry` session that this alias is the Bounce/Bounce AI
   failure** — its own lane's item, contradicting shipped code, which is precisely the
   failure `CLAUDE.md` names as punished hardest. Annotated in place: the morning's reasoning
   kept, the verdict marked superseded, and the row itself still registry's to retire.
6. **"The published dataset agrees: 0 of 167"** — the committed `roles.csv` was generated at
   12:15Z and its own `firmo_match` column still says **8**, two of them `emailed: true`. The
   session record had this right and §7 did not; §7 now quotes the column, gives the
   one-liner that reads it, and says the 0 arrives with the next digest.
7. **"37 of the 43" and "~205"** — re-derived: **38 of 44** matched-only names sit on
   LinkedIn or Indeed (29 on the `il.` hosts), and **190** active rows carry a Comeet API
   endpoint. §7 had quoted 190 correctly two paragraphs earlier and ~205 here.
8. **`COMEET_RESOLVE_MAX` caps resolutions, not requests** — each goes through
   `pipeline.http`, which retries 3 times, so the true ceiling is 30 GETs. Stated.

**And one the wave was right to press even though nothing is broken:** two values in the
export were written by hand and the schema cannot say so, so they are invisible to a reader
and to the 2027-02 refresh — and both bypassed `_coerce`, i.e. neither passed the two checks
this same commit added. Filed as `539` with the `employees_source` pattern to copy.

The waves also **verified** what I had claimed and could not: the gauge command's own output
(`1351 1146 1146 []`), the strike ledger 9 → 6 by name, `display_names` 82 → 84 (now 83 after
the withdrawal), the Oak premise in `matched`, that no third name keys to `oak identity
security os`, the Comeet board's `company_name` on all 13 positions, `1689 passed / 13
skipped`, and that `_ADMITS_UNIDENTIFIED` spares `526`'s honest records. Where the report was
wrong I checked before acting: `Landa`'s identity_key really does differ from `Landacorp`'s,
and the `finbounce` "defect" is a documented, deliberate shadow.

### The seam wave, and the two it found that would have lied in the mail

The second attacker read the mechanism rather than the data, and found **fourteen** more.
Four mattered enough to change shipped behaviour:

1. **Our own budget clamp could report an outage that never happened.** Both callers decide
   *"that timeout was our budget, not the CLI"* from the time left when the NAME started —
   and the second call is clamped to the time left after the first one FINISHED. A 250 s
   slot launches a 210 s call, hits our clamp, and reaches `_research`'s handler with
   `remaining (250) <= RESEARCH_TIMEOUT_S (240)` **false**: the outage arm, which breaks the
   loop and prints `claude unavailable after N research calls` on a healthy morning. The
   bulk cron had no such compensator at all, and three of those is `infra abort` — **every
   strike of the run suppressed**. The clamp is now caught inside `research_with_evidence`,
   where it is known to be ours, and the name keeps the first call's honest verdict.
2. **`--only` was still writing the one piece of shared state it exists to protect.** It
   bypasses the 7-day gate so a session can re-ask a hard name — and recorded a strike each
   time, into the tracked ledger, incremented against the merged prior. Four honest hand
   retries reach `att >= 4`, which is `refresh_abandoned`: that company evicted from the
   refresh layer for ever, by a laptop. A hand retry is not evidence about a name; no strike
   is written now, and clearing an ANSWERED one still is.
3. **`_ADMITS_UNIDENTIFIED` searched, so it ate honest records.** `"Tel Aviv (HQ); US
   subsidiary not identified separately"`, `"Herzliya (R&D). Global HQ unknown/not public."`
   — each names a real Israeli site and each was being rejected before caching, becoming a
   strike where a usable record used to be stored. It is now a WHOLE-STRING test
   (`_admits_unidentified`), which also catches the plainest admission the first version
   missed: bare `"Unknown"`, which two committed records say. Over the real export it fires
   on exactly 4 records, and all four are genuine (`Abakus Center`, `Chalk`, `Gramian
   Consulting`, `Happy Mammoth`).
4. **`_DISAMBIG_SYSTEM` was built by a `.replace()` that could silently no-op.** One reworded
   word in the base prompt and the disambiguation call becomes a copy of the first, carrying
   the OPPOSITE instruction — with every assertion about it still true, because both strings
   say the same things. It is now `_swap`, which raises at import. The same review caught
   that the retained fence forbade the very act being asked for (*"never profile a company
   merely mentioned INSIDE the context"* against *"identify the company that operates that
   careers site"*); the disambiguation prompt now says the publisher is the subject and every
   OTHER company the JD names is the mention.

**And one that makes a number I quoted worthless.** The lane's own
`test_every_company_intel_mutation_still_aims_at_real_code` re-reads each record's `find`
text, so ANY mutation reddens it and `tools/mutate.py` scores every company-intel mutant
`killed` — as `direct`, no less, because `_classify_killer` looks for `inspect.getsource`
and this test uses `open().read()`. Measured: `ci-cached-board-titles-never-read` reported
killed, and with the anchor test deselected the same mutant **survived the whole suite**.
What it hid was real: `_cached_board_titles`'s CALL SITE had no behavioural guard, so
`main()` could have stopped calling it with everything green — the exact hole this file's
own `test_the_anchor_actually_reaches_the_call_the_bulk_pass_makes` docstring describes, one
function later. That test exists now; the scoring is `540`, filed for `infra`. **Until it
lands, this lane's shard count is not evidence** — which is why the earlier
"68 → 83 mutation records" line is struck from the report below: the full-catalogue run
(81 records, 80 killed, 1 unsettled) cannot distinguish a real kill from the anchor test.
`guard_kill` and named behavioural tests are what count here.

Smaller, all fixed: `--only "Discovery"` would have researched the aggregator pseudo-row
(excluded by PLATFORM, which `--only` skipped) and `--export` would have published facts for
it; `--only "Wix,Wix"` researched Wix twice; `--only` paired with `--export` silently did
nothing; `evidence_context` crashed the cron on a malformed `postings` element (past
`except ResearchUnavailable`, into `crashed(TypeError)`); `_resolve_comeet` counted attempts
and printed them as resolutions, and past its cap it DELETED the only evidence an active
Comeet row has, letting `todo` order decide which names get a second call; four docstrings
still said the digest spends at most `FIRMO_MAX_PER_RUN` **calls** when it now caps NAMES and
can spend twice that; two assertions were tautologies (one tested the report dict for a key
it never has, the other a dict literal passed to nothing); and `research_company` — both the
`firmographics` one-liner and the `company_intel` shim — had no production caller left and
is deleted, its tests moved onto `research_company_detail`.

**Two the wave raised that I did not change, with the reason.** `_same_company` compares
NAMES, so it cannot catch a differently-*named*… it cannot catch a SAME-named different
company, which is `525`'s literal shape — true, and the §7 table now says "a record about a
differently-named company" instead of overclaiming; prevention (the board's own titles) is
what closes that class and detection is the backstop. And the `oak` alias would fold a THIRD
company if `registry` ever activated the parked Opera Group row under that bare string —
`522` now says the row must be retired or **renamed off the bare word**, never activated as
`Oak`.

### The one CI caught that neither wave did, and it could spend money

`tests.yml` run `33439962130` on `ba6dbb3`: **`guard` FAILED**, one test —
`test_the_digest_hook_asks_with_the_posting_every_board_company_has` — with `seen` empty.
Green on this laptop five times, red on the runner, and the reason is the half that matters:
the test called `enrich_for_run(use_llm=True)` with the BLURB loop live. On a machine with
`claude` on PATH the blurb seam answers, research runs, the assertion passes — and a real
sonnet call is spent summarising `Oak` on every local suite run. On the runner there is no
CLI, so the seam raised `missing`, `rep["blurb_outage"]` latched, `_enrich` skipped research
entirely, and nothing reached the spy.

So the test read its ENVIRONMENT rather than the code, in both directions at once. Fixed by
stubbing `_blurbs` and wiring `F.ask` to `pytest.fail("this test must never spend")`, which
is the assertion that should have been there from the start: this test is about the research
path, and it now proves nothing else is touched. The lane's other two `enrich_for_run` call
sites were checked and are safe (`use_llm=False`, and the `env` fixture's fake CLI on PATH).

**Declared, because it is spend:** roughly 5-8 unbudgeted sonnet blurb calls, one per local
full-suite run, on top of the 11 research calls this session declared. `python -m pytest`
can no longer buy Bright Data (`tests/conftest.py` bans that transport) but it can still
reach `claude`, and this is what that costs when a test forgets to say so.

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
- `522` (retire the Opera-division `Oak` row), `524`, `526`, `528`/`538` are all registry's.
