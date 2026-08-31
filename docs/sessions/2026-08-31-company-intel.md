# 2026-08-31 — `company-intel`

Lane: `company-intel` (`ARCHITECTURE.md` §7). Brief: drain the registry backlog, close the
8 unmatched rows in the published dataset, answer `512`, diagnose the transient that ate
the blurb run.

## 0. The morning check, answered

`HANDOFF.md`'s `2026-08-31 | company-intel` row is **PASS**, from run `33387229779`
(`event: schedule`, `success`, dispatched 11:29Z — the 05:00 slot again):

- `registry backlog 28 (+7 since 2026-08-30)` — a **signed delta**, not `(first
  measurement)`, so the `intel` stamp survived `persist_state` and `451` holds.
- `bulk cron: last ran 2026-08-31 (today), 13 researched of 15 to do, 0 left, 2 failed`.
- no `blurb dropped, not a company: Tel Aviv`; the step log carries only
  `skipping 1 junk (job-title) names: Tel Aviv`, which is the gate working at the other end.

The operator's question — *does the gap hold without a session?* — is answered **NO**, with
both readings: **21 → 28** by the digest's own baseline (25 on the 08-30 mail, 28 today,
`+7`). It grew while two crons drained it, which is the fact the rest of this session is
about.

## 1. The queue was built out of the empty string

Re-derived from `origin/master` blobs with §7's own gauge (active ∪ matched − the
`discovery` pseudo-row − `not_a_company`, joined through `display_index`/`identity_key`):
**28**, reproducing the mail exactly. 21 are active registry rows, 7 are matched-only.

Then the part that matters: **every one of the 21 carried a strike in
`cloud_state/firmo_failed.json`**, and the bulk pass calls
`research_company(name, "")` — no context at all. So the class raised
`model could not identify the name` (run `33387229779` logged two of them itself,
`Peak Innovation` and `Nascompany`), the name gated for 7 days, and the weekly retry
re-asked *the same unanswerable question*. A queue of `Jafi`, `Make Gems`,
`Kidum Rehab Projects`, `Gdolim Mehachaim` against a bare name is not a research backlog —
it is a prompt with the evidence left out, and it could never drain on its own.

The other 7 are reachable only by the digest's tier-1 hook, which is what §2 killed.

## 2. One failed call, six companies

`_blurbs` latched **any** `ResearchUnavailable` into `rep["unavailable_after"]`, and
`_enrich`'s research gate reads that flag. On 08-31 blurb call 15 returned the CLI's error
envelope `error_max_structured_output_retries` — the model failing to emit `{known, blurb}`
for one company — and the run researched **0 of 6** unprofiled board companies inside a
budget that had spent **81 s of 480**, on a morning the same token served 14 blurbs and 192
classifier calls. `449` is closed, which is the only reason the subtype reached the mail at
all; `452` (drop the blurb's JD context) explicitly waits for a week of subtypes, so today
is day 1 and the context was **not** touched.

Now: `auth` / `missing` / `drift` still latch on the first hit; a `transient` skips that one
name, caches nothing, and is asked again next run; **three consecutive failed CALLS** latch.

**Two counters, because they answer two questions** — and this is the correction wave 1
forced. My first version incremented the latch counter on an empty answer too. An empty
answer is a call that *succeeded*: the model came back and said UNKNOWN, which is evidence
about a **name**, not about the seam. Counting it re-armed the entire bug, because
`written, empty, empty, transient` is an ordinary morning — this one read
`14 asked, 11 written, 3 empty` — and it would have latched, skipped research, and printed a
mail byte-indistinguishable from the broken one. `empties`/`empty_names` still decide what is
rolled back; `stalls` decides when the seam is down.

Two more from the same wave: `unavailable_after` was `i`, the loop **index**, which stopped
being the number of calls that came back the moment a transient could skip a name (it read
"after 2 blurbs calls" on a run of 3 calls, beside `0 asked`); it is now `blurbs_asked`. And
a failed call is spent wall clock **nothing** counts — `ask` raises before `record_call` —
so an unbounded skip could burn the budget invisibly and leave research reporting
`skipped (budget)`, a sentence blaming work never done; the loss is now carried as
`[Ns of budget]` on the mail's `blurbs:` clause.

## 3. Two anchors, and each claims only what it can

The bulk pass now asks with an ANCHOR. `_row_anchor` gives an **active** row *the careers
board we read this name from*; `_posting_anchor` gives everything else *the posting we saw
the name on*.

The asymmetry is the design, and wave 2 is why it exists. My first version said the posting
anchor was "first-party: the url names the host that published it" — false for **37 of the
43** matched-only names, which sit on `il.linkedin.com` or `il.indeed.com`. Worse, `anchors`
is seeded from `load_companies()`, which is active-only, so a **parked** row was absent from
it and fell through to the posting path — and `entrypoint`, the row whose mis-resolution my
own docstring cites, thereby got back the *exact url* `_row_anchor` refuses. Fixed by making
the two anchors claim different things: a posting anchor is safe for a row the board anchor
rejects precisely because it asserts less.

The row side needed the same honesty. I had written "an active row's url passed
`identity_gate`, so it is evidence about which company this name is". `check_invariants.py`
prints **14 active rows whose endpoint names a different company** and 33 whose tenant
cannot vouch for the name. What *active* buys is that the url has been through the ladder at
all; the doc and the docstring now say that and nothing more.

Also from wave 2: query strings never travel (**190** active rows carry a Comeet
`token=<hex>`); the url goes before the title, because `research_company_detail` cuts context
at 600 chars and nothing caps `matched.title`, so a long title could have pushed the half we
trust off the end; the title is capped at 120; and `ORDER BY last_seen DESC` gained a
tie-break — 115 of 187 rows share today's date and sqlite returns insertion (oldest) order
inside a tie, so 9 of 143 companies were being anchored to a posting that was not their
newest, non-reproducibly.

## 4. `nvidia ai` → `nvidia`, and the alias I refused

`NVIDIA AI` reached the published dataset with `firmo_match: none` while NVIDIA's record sat
on file; render warned `title-twin NVIDIA/NVIDIA AI` about the same pair. It is LinkedIn's
showcase page for NVIDIA, no registry row is named that, and the join is `identity_key` —
one `ALIASES` entry.

**`oak identity security os` → `oak` REFUSED.** It would have matched the dataset's `Oak`
row, but the registry's `Oak` is **Opera Group's Teamtailor division board**
(`operagroup.teamtailor.com/...&division=Oak`) and the Indeed posting confirms neither.
Folding them stamps one company's facts onto another's card — the Bounce/Bounce AI failure
with an alias table instead of a name. `Oak` is researched under its own name instead.

Named because it is otherwise undocumented: `rolecard._SITE_WORDS` already folded this pair
at render, so the alias fixes the **dataset join** and not the title-twin warning, and it
does suppress an `also listed as NVIDIA AI` disclosure on the NVIDIA card.

## 5. `390`, and the date clause that is the whole rule

Only a run's own successes were cleared, and the digest hook — which researches board
companies every morning — never appears in them. `Varonis` and `Steakholder Foods` were
struck 2026-08-23, researched successfully on 08-26, and were still in the ledger on 08-31.

Cleared now at **both** exits: the night a stale strike sits longest is the drained one, and
`main()` returns on `if a.dry_run or not todo` above the working path's ledger write.

And the clause wave 2 saved me from shipping without: the record must **post-date** the
strike. A refresh candidate is `n in have` *by definition*, so clearing on membership alone
would have erased every refresh failure's strike in the run that recorded it — `attempts`
could never pass 1, `refresh_abandoned` (4+) could never fire, and a permanently failing
stale name would hold a `REFRESH_CAP` slot for ever, which is the squatter this file's own
eviction comment exists to prevent. Latent until the store's first refresh wave (~2027-02 at
`--refresh-days 180`), which is also the first day anyone would have looked.

Two limits, stated rather than discovered later: a strike held in the committed `seen.db` is
not cleared by this (that table is `SINGLE_WRITER: daily-digest`, so `_failure_union`
re-supplies it — 3 names today); and a run clearing more than a quarter of a ≥20-key ledger
that then loses a push race has the deletions restored by `persist_state.s_company_dict`'s
broken-run guard, which cannot tell a deliberate drain from a mass-zero.

## 6. `512` — entrypoint, closed on evidence, not as filed

The item asks for a `display_name` with first-party evidence, or an honest residual. The
answer is neither: **the company writes its own name lowercase.** `entrypoint.co.il`'s
footer reads *"2004-2026 © All rights reserved to entrypoint"*, and the site describes an
IT-services / systems-integration business — which is what the stored record already says
(Petah Tikva, Registrar 513513267, founded 2004). So the registry key **is** the employer's
own styling and `DISPLAY_NAME_OVERRIDES` needs no fifth row; the table stays at 4 and
`display_names` stays at 77, which also keeps the 09-01 check's `±drift` clean.

The agency half: the captured JD (`cloud_state/roles_text.jsonl`) is an in-house BI role —
*"collaborating with various business units across the organization"*, Power BI / Azure /
Fabric / DWH — and LinkedIn's own furniture names **אנטריפוינט ישראל**. The company does
sell technical recruitment (its record's `sub_sector` already says so), but this posting is
not a placement. Not an agency; `recruiters.is_recruiter` was right.

The one thing that IS wrong on that row is registry's, not mine: `companies.csv` has
`entrypoint` parked with `wrong-url ... board names Entry Point USA` and a LinkedIn *job
view* as its url. Handed back, not written.

## 7. What the waves cost, and what they bought

Two Opus waves, run against the committed diff. They found **six** defects in it: the empty
answer counting toward the outage latch (would have re-armed the bug), `unavailable_after`
counting names instead of calls, the same-run refresh-strike erasure (would have disabled
`refresh_abandoned` permanently), the parked-row fallthrough re-admitting the refused url,
the false "passed `identity_gate`" claim, and the untie-broken `ORDER BY`. Every one is
fixed above.

The mutation harness found two more, both about my own guards rather than my code:
`ci-transient-caches-the-name` was **equivalent** (an in-memory `""` is falsy, the name stays
in `missing`, nothing changes) and was re-aimed at the write that actually harms — a `''` in
the *store* is a monthly gate; and `ci-bulk-research-drops-its-anchor` was killed only by the
aims-test on the full-suite fallback, a **vacuous** kill, because the unit test proved
`_row_anchor` builds a string and the source pin matched the mutant too. It now has a
behavioural test over a real `main()`, verified to fail when the submit site is reverted.
Two more strike-clear records had the same vacuous shape and got behavioural tests as well.

## 8. Numbers

**The queue: 28 -> 7.** Re-derived with §7's own gauge before and after, from the same
command. 21 names researched (3 in a first pass that was killed at 90 s, 18 in the pass that
replaced it, 2 more on a retry after the `human_board_url` fix); 4 refused by the model; 3
bought records **stripped** by the audit in §7 and returned to the gauge rather than shipped.

**Spend: 29 `claude -p` calls** (3 + 22 + 4), all sonnet, 632 s, 39 searches, against a
declared ceiling of 40. **Bright Data: 0** — this lane's only paid rung is the subscription,
and `research_firmographics` imports nothing that disarms it.

**The strike ledger: 28 -> 8.** The 21 target strikes were cleared through the sanctioned
`save_failures(cleared=...)` path (deletion is the only way that file can say "researched
since"), and the run then cleared three more *on its own* — `cleared 3 strike(s) whose record
is already on disk: Peak Innovation, Steakholder Foods, Varonis`, which is BACKLOG 390 firing
live, with the date guard correctly keeping the four strikes that same run had just written.
The 8 that remain are `Agency`, `Discovery`, `Sivo`, `Tel Aviv` (all pre-existing) and this
session's four residuals.

### The 7 residuals, each with its reason

| name | why it is still in the gauge |
|---|---|
| `Ecommerce Guide` | an e-commerce **content site**; research refused it twice, anchored to its own careers page both times. `524`, registry to retire |
| `Konsortium Ziviler Friedensdienst` | the German **civil peace service**; never bought a profile — the one name this session refused on the "not plausibly an Israeli employer" rule. `524` |
| `Oak` | not an employer: the string is a Teamtailor **division filter** on Opera Group's shared board. `522` |
| `Hila & Co.` | the row resolved to `hila.mt` (**Malta**) and is parked, so the anchor correctly refuses it. A real Israeli posting exists — a resolution failure, not a junk name. `523` |
| `Landacorp` | STRIPPED: the board is Landa Digital Printing, the record was a US healthcare-IT firm. `525`, cause `521` |
| `Kidum Rehab Projects` | STRIPPED: two Israeli companies named קידום; the board is the test-prep group, the record was the rehab operator. `525` |
| `Rockerbox` | STRIPPED: acquired by DoubleVerify (closed 2025-03-13); the record said "no IPO or acquisition found" and the careers url now redirects. `525` |

### What the audit corrected rather than stripped

`Tailor Brands` founded 2014 -> 2015; `Paz - yellow` il_center Haifa/Ashdod -> **Yakum** (Paz
Oil's HQ; Ashdod is the refinery); `Computer Guard` employees 150 -> ~70 (its own site says
"over 70 professionals"); `Galil Systems` 250 -> 200; `Replai` il_center Unknown -> Tel Aviv;
`Nascompany` and `Golan` gained a dated correction in `stage_note`. Every `employees_global`
change re-derives `size_band` — 0 band/count contradictions after.

**`employees_global` is the least reliable field in the batch** and that is worth carrying
forward: it was overstated on two of the seven checked and is unsupported on three more.

### A trap this session hit

**A local `research_firmographics.py` run stamps the shared `firmo` stage.** That stamp is the
cron's own liveness and queue measurement, read by `stages.alarms("firmo", 2)` and printed in
the mail as `bulk cron: last ran ...`. My runs overwrote it with a laptop's numbers
(`attempted 4, budget_min 5.0`), and it was restored with `git checkout` before the commit.
`--dry-run` does not stamp; nothing else protects you. Do not commit
`cloud_state/pipeline_stages.json` from a hand-run.
