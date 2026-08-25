# Identity gate calibration record (2026-08-24)

The rules live in `pipeline/identity_gate.py`, one line each with one reason. The
MEASUREMENTS that produced them -- every number, every incident, every rejected design --
live here, moved verbatim out of that module's docstrings on 2026-08-24 so the module
reads as rules (61% prose before, with the activation rule at line 434 of 548). Nothing
below is re-derived: each section is the docstring as it stood when moved. The registry
is rewritten nightly, so every count is dated by construction; the commands that
re-derive the load-bearing ones are in `docs/sessions/2026-08-24-registry.md` and the
plan those sessions executed.

Declared identity (`pipeline/identity_facts.py`) landed the same day and supersedes the
string heuristics for declared rows; the records below describe the UNDECLARED fallback.

## The module, and the four measurements that shaped it

The one identity gate every registry writer consults before writing `api_url`/`active`.

**Why this module exists.** These predicates lived in `crack_walled.py` — a leaf tool — and
four other modules imported them, three of them *lazily from inside a function* to dodge an
import cycle (`crack_walled` imports `deep_validate` and `audit_empty_rows` at module level;
both imported back from `crack_walled` inside `main()`). A gate reachable only through a lazy
import is invisible to any static check of "does this tool gate its writes", which is exactly
the check the registry needs most. `docs/BACKLOG.md` 30.

**What it is for.** "There are Israel jobs on this page" is not "these are THIS company's
jobs". Activating a row onto another company's board publishes one company's roles under
another's name, on a public board and in an email. That has happened repeatedly: FairFly off
`fireflyspace.com` (25 Firefly Aerospace roles), SimilarTech off Similarweb's Greenhouse,
Bancor onto The Bancorp Bank's iCIMS, DiA Imaging Analytics onto `dia.mil`.

**The measurements that shaped it — do not re-litigate these** (`docs/BACKLOG.md` 21 and 33):

* `company_identity.is_foreign` returns `False` for **every** ATS host by design, because an
  acquirer's tenant is legitimate — Momentis Surgical really does post under `memic`. So on
  the ~461 active ATS rows, `is_foreign` is not a gate at all.
* A blanket tenant-mismatch veto refuses **24 legitimate acquisitions** (36 when first measured; Momentis→memic,
  Habana Labs→intel, VMware→broadcom, Splunk→cisco) and 7 of the 9 active rows on
  `crack_walled`'s own target platforms — Oracle CX pod ids (`hctz`, `edel`, `iawmqy`) are
  opaque and can never near-match a name. Proposed and rejected three times.
* `company_identity.verdict()` is wrong in **both** directions: `mismatch` for correct rows
  (onsemi, Fortinet, Verint, Dell) and a plain `ats` for the two boards most needing refusal
  (Riskified→`novartis.wd3.myworkdayjobs.com`, Bancor→`careers-bancorpbank.icims.com`).
  **The tenant string is not evidence in either direction.**
* Requiring a page read where the tenant is undecidable refuses **358 path-tenant rows**:
  `boards-api.greenhouse.io/.../jobs` returns 0 bytes, `comeet.co/careers-api/...` 0 bytes,
  `api.ashbyhq.com/posting-api/...` 28 bytes, and `_page_names_company` needs 2000 chars to
  answer anything but `None`. Machine API endpoints are not readable pages — all 66 active
  Workday rows are `/wday/cxs/<tenant>/<site>/jobs`, which returns HTTP 400 on GET.

So: **page content is the only discriminator that works in both directions**, and the page
test is scoped to candidates that could plausibly BE a page.

lane: `registry` owns the behaviour; the module is `pipeline/` because five root tools import
it. Changing it affects `ats-fetch`, `scraper` and `infra`, which all read the registry.

## `is_walled` -- why the crack pool derives from the host, not a note token

Is this row in the walled-ATS pool? DURABLE data first, note token second.

The pool used to be the literal string `unsupported ATS` in the note and nothing else.
That string is written by `deep_validate` inside ITS OWN segment
(`deep-validated <date>: unsupported ATS icims.com`), and `pipeline.notes.replace_own`
deletes a tool's previous segment when it writes a new one — by design. So every
`deep_validate` verdict that is not `unsupported` silently removed the row from
`crack_walled`'s pool, permanently.

Measured on the real registry 2026-08-24: the token lived only inside `deep_validate`'s
own segment on **24 of the 25** pool rows, and one simulated all-dark Saturday took the
pool 25 -> **0**, with pytest, `check_invariants` and `registry_health` all green —
no guard has a per-tool floor (`docs/BACKLOG.md` 34).

A pool predicate must not be a string another tool owns and rewrites.


## `tenant_is_this_company` -- where the tenant lives, and why near-equality

Does an ATS URL's TENANT really belong to `name`? Use INSTEAD of `is_foreign` here.

`pipeline.company_identity.is_foreign` early-returns **False for every ATS host** — by
design, because a rebrand or acquisition looks identical to a mis-resolution and blocking
outright costs real coverage (Momentis really does post under `memic`). The cost is that
clauses 2 and 3 of the activation rule are inert on 432 of the 1,199 rows, and it even
overrides an explicit `mismatch`:

    NanoLock Security -> gen.wd1.myworkdayjobs.com   verdict=mismatch  is_foreign=False
                                                      (that is Gen Digital's tenant)

So, for the paths that ACTIVATE or PERSIST an address:

* an explicit `mismatch` is honoured even on an ATS host — `verdict` only says that when
  it found a tenant belonging to someone else;
* **where the tenant lives differs by platform**, and `_slug_candidates` returns host
  labels and path segments in ONE flat list, so an `any()` over it accepts a foreign
  tenant whenever the PATH happens to match. `novartis.wd3.myworkdayjobs.com/riskified`
  is Novartis's Workday with a site named `riskified`. If the host carries a
  non-generic label, THAT is the tenant and the path is only a site name;
* the tenant must be NEAR-EQUAL to the name, not merely contain it. `_slug_matches`
  passes `Bancor`/`careers-bancorpbank` and `Bit`/`careers-bitdefender` on plain
  containment — the same "containment must be TIGHT" lesson `company_identity` already
  learned for domains (rad.com/RADLogics);
* a Comeet uid (`60.002`) is opaque and comes from the company's own page — exempt.

Non-ATS URLs return True: `is_foreign` is the right gate there and works correctly.


## `embedded_board_ok` -- a held page can refuse a board, never admit one

May a board found INSIDE a held page be written onto this row?

The callers that hold a page (`validate_empty`, `bd_rescue`) fetch the row's CAREERS
page and run `extract_ats` on it -- so their `api_url` is whatever board that page
EMBEDS, while their `html` is the page itself. `page_names_company`'s affirmative
answer is about the page, and `activation_ok` treating it as evidence about the board
promoted Riskified's Greenhouse onto Cogniteam's row off Cogniteam's OWN page carrying
a stale shared-template embed (wave-4 R1, reproduced on the scheduled Sunday path;
the SimilarTech-off-Similarweb incident is the same shape). A held page can REFUSE a
board -- it names someone else -- but it can never ADMIT one.

So the board must vouch for itself: an explicit subdomain-tenant mismatch refuses
(Bancor / careers-bancorpbank.icims.com), and otherwise the extracted tenant token
must near-equal the company name, by the same `_tenant_near` rule the subdomain check
uses. "Cannot tell" (opaque Comeet uid, an acquirer's slug like Momentis->memic)
REFUSES here, unlike in `tenant_is_this_company` -- because both callers surface the
refusal visibly (a `suspect` line, a bd refusal print) on rows that stay parked with
their re-check tokens, while a wrong acceptance ships another company's jobs. That is
the census resolution's direction, applied to the same bar. Cost filed with the
derivation: docs/BACKLOG.md 61.


## `page_names_company` -- three-valued, and the 12-of-60 lesson

Three-valued: True = the page names this company, False = it names someone else,
None = we could not read it, which is NO EVIDENCE and must not read as either.

On a walled ATS the tenant lives in the SUBDOMAIN (`careers-bancorpbank.icims.com`), and
`company_identity.verdict` only checks a tenant in the PATH — so it returns the blanket
`"ats"`, which its own docstring defines as "we cannot tell", and `is_foreign` reads that
as False. `_slug_matches("Bancor", "bancorpbank")` passes too, on plain containment. Both
were true on 2026-08-23 and one `--apply` would have moved Bancor (Israeli crypto,
ex-Bprotocol) onto The Bancorp Bank's iCIMS board: that page says "Bancorp" 18 times and
Bancor-as-a-word zero times.

The first version of this gate was a plain strict-TLS urllib fetch returning a bare bool,
and review measured it False on **12 of 60 rows the pipeline had already verified as that
company's own board** (Meta, Akamai, Ford, Microsoft Israel, ...). Three causes, each a
paid-for lesson:

1. **403 to a plain fetch** — `Bit`'s own careers page. The crack loop reaches these with
   Playwright, so re-fetching with urllib is strictly weaker evidence than the evidence
   that produced the candidate; prefer HTML the caller already has, via `html=`.
2. **Strict TLS** — see `_LENIENT`.
3. **`strict=True` wants the name's words consecutively**, so any row whose registry name
   carries a suffix the page omits fails structurally: 46 rows contain "Israel". Retry
   against the name with the generic/geographic words stripped.


## `ok_to_write` -- positive confirmation only, and the dead `platform` parameter

May this url be written into the row's `api_url`? Positive confirmation only.

A tool has several exits and gating them individually is how two 0-Israel-jobs paths were
missed: `crack_walled`'s `cracked-api` never called the gate at all, and `novrfy`
persisted on an UNREADABLE page. This is the one check a write block runs regardless of
which branch produced the candidate, so a future `return` that forgets the gate cannot
re-open the hole. Unreadable (`None`) is refused: a persisted ADDRESS is what
`listing_hunt`'s fast path later activates on, and "we could not look" is not evidence.

**The tenant string is deliberately NOT a veto here** — see this module's docstring. It
reads like the obvious extra safety net and it is wrong in both directions at once, so
stacking it on top of a mandatory page test buys nothing and costs silent exclusion
(ARCHITECTURE.md section 8's first bug class). Each false refusal also stamped a *wrong*
`not this company's board` verdict into the row's note.

The signature deliberately has no `platform` parameter. It used to, the body read
it nowhere, and a reviewer transposed `(name, platform)` at four call sites with
the whole suite green -- `platform` absorbed the name and the identity decision
silently ran on the platform string. A parameter that gates nothing is a slot for
a transposition to hide in. (Transposing the two that remain is caught: a URL in
the name slot fails every predicate and the positive controls go red.)

Pass `html=` when the caller already has the page; it avoids a second fetch and is
stronger evidence than a re-fetch (see `page_names_company` cause 1).


## `activation_ok` -- tenant-OR-page, and the census that fixed its ordering

May this row be ACTIVATED onto `api_url`? For tools that verified jobs first.

The five schedule-driven tools that build a whole row literal
`[name, plat, tok, api, "true", note]` -- `bd_rescue` and `retry_unreachable` (02:30
daily), `wayback_rescue` and `validate_empty` (Sun 04:00), `auto_expand` (08:00/20:00) --
had NO identity check of any kind until 2026-08-24. They were invisible to the guard in
`tests/test_units.py`, which finds writers by looking for a subscript assignment to
index 4 and therefore cannot see a list literal. Fourteen of the repo's 22 registry
writers are that shape.

The clauses, and why each is the one it is:

* **`n_jobs`** -- a board that verifies with zero jobs is the `empty-board` shape, not a
  recovery. Callers pass whatever they actually counted (Israel jobs for a scrape row,
  total for an API row); zero from either is refused.
* **`is_foreign`** -- the right gate on an ordinary domain, and inert on an ATS host,
  where it returns False by design for all ~461 active ATS rows.
* **`looks_like_a_job_listing_page`** -- clause 3 of the activation rule
  (ARCHITECTURE.md section 2). Measured 2026-08-24: all 861 active rows pass it,
  including every machine API endpoint, so it costs nothing and catches a nav menu.
* **the identity evidence** -- `html` if the caller already fetched the page (strictly
  stronger than a re-fetch, and free), else tenant-or-page.

**Why tenant-OR-page and not tenant-AND-page.** `tenant_is_this_company` answers True
when there is nothing checkable -- a path-tenant platform, an opaque Comeet uid. If a
failure there fell through to a mandatory page read, the gate would refuse the 358
path-tenant rows whose endpoints return 0-28 bytes (`boards-api.greenhouse.io` 0,
`comeet.co/careers-api` 0, `api.ashbyhq.com/posting-api` 28) because
`page_names_company` needs 2000 chars to answer anything but `None`. That was built,
measured and reverted: `docs/BACKLOG.md` 33. And a tenant MISMATCH cannot be a veto on
its own either -- it costs 24 legitimate acquisitions (item 21; 36 when first measured). So the tenant string
admits; refusal needs page evidence.

**What that costs, stated rather than implied.** `page_names_company` returns `None` for
a page it could not read, and `is True` refuses `None` -- so on a subdomain-tenant host
whose endpoint is a machine API (`/wday/cxs/<tenant>/<site>/jobs`, HTTP 400 on GET) a
failed tenant near-match IS the refusal, because no page can ever be read there:

    activation_ok("Habana Labs (Intel)",
                  "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/x/jobs", 12)
    -> False        # a real acquisition, refused

That is item 21's shape re-entering through the `None` branch rather than through a
`mismatch` veto. It is accepted here deliberately and for a narrower reason than item 21
covers: these five callers ACTIVATE a currently-parked row, so a wrong refusal leaves the
row parked, visible and recoverable, while a wrong acceptance publishes another company's
jobs under this company's name. Item 21 measured the cost of vetoing rows that were
already ACTIVE, which is not this. `docs/BACKLOG.md` 49 carries the measurement; the fix
is an `acquired-by` column, not a cleverer string test.


## `identity_ok` -- scoped to ATS hosts on purpose

The gate for tools that hunt or repair an ordinary careers page, not just an ATS.

Scoped deliberately: the page test runs **only** on ATS hosts, where `is_foreign` is
inert by design. On an ordinary careers domain `is_foreign` works and nothing changes,
because `page_names_company` answers `None` for any page under 2000 chars and a great
many legitimate company careers pages are JS-rendered — routing those through it would
trade a real hole for silent exclusion, which is the mistake this lane has already made
once and measured at 358 rows.


## The `activation_ok` ordering census (was a comment inside the function)

A page the CALLER already holds is decisive when it is readable -- in either
direction. This ordering is the resolution of a measured calibration dispute in which
both error cells were non-empty, and it has flipped once already, so the census is
recorded here rather than re-derived a third time:

  * page-first, page-only (the first form): refused `Siemens Healthineers` on its own
    page (readable, says only "Siemens" -- `strict=True` wants the registry name's
    words consecutively), and the refusal was SILENT. That silence, not the refusal,
    was the blocking finding; the refusal path is visible now (`validate_empty`
    returns `suspect` and writes a note).
  * tenant-first (the second form): `tenant_is_this_company` answers True by VACUITY
    on every path-tenant platform (greenhouse/lever/ashby/comeet -- 6 of the 7
    platforms `extract_ats` can return), so the page in hand was never consulted and
    `Cogniteam` was activated onto Riskified's greenhouse board off a careers URL
    that no longer serves Cogniteam's page. A proven wrong write, on a schedule.

No string predicate separates every wrong-page case from every name-shape mismatch
(`Sight` matches Sight Sciences' page and Sight Diagnostics is a different company on
that same board -- head-token matching is measured unsafe). So the rule follows the
bar: these callers ACTIVATE a parked row, where a wrong refusal is parked, visible
and recoverable, and a wrong acceptance ships another company's jobs. Readable page
evidence decides; only an UNREADABLE page (None -- machine endpoints, bot walls)
falls through to the tenant clause, which keeps the 358 path-tenant rows and the
filler-stripped-core rows activatable. The name-shape cost this accepts is filed
with the row names in docs/BACKLOG.md.


## The third state (2026-08-25, registry batch 4)

Both error cells of the calibration above stayed non-empty because "cannot tell" was
spelled `True` on every path-tenant platform (greenhouse, lever, ashby, comeet, recruitee,
bamboohr, breezy): `tenant_is_this_company` scopes them out, `_slug_matches` was a
five-character prefix, and the only page there is a machine endpoint. The fix that was
built and reverted (read the endpoint) refused 358 rows; the fix that was measured wrong
(a tenant veto) refused 81 of 460 active rows.

**Decision.** `identity_gate.board_vouches(name, token, api_url)` is three-valued and is the
only string test the activation paths consult. `False` = a declared `not_tenants` token, a
subdomain-tenant mismatch, or a declared row on an undeclared tenant — refuses without a
page. `True` = a declared tenant or a near-equal one — admits without a page. `None` =
nothing checkable (a Comeet uid, an all-plumbing host, an ordinary host) or a slug that merely
fails near-equality — and the consumer of `None` is ONE read of the platform's **human** board
page (`human_board_url`; for Comeet's API form, learned from the endpoint's own positions:
`comeet.com/jobs/x/49.004` serves a generic 200, `jobs/upwind/49.004` names Upwind). Where
nothing can be read the row is `unverified`: deferred, unstamped, tokens kept.

**Census, 2026-08-25.** 360 active path-platform rows: 187 near, 120 Comeet uid, 2 declared,
51 not near (24 `scrape` rows whose slug is read from the URL; 27 native-ATS rows —
`check_invariants` C3b's hand-check list, 28 with `Findings -> findigs`). The 30
parked path-platform rows: 14 get a human-page read, 12 (Comeet API-form twins, all
`alias-of`) are `unverified`, 0 admitted by vacuity. Item 22's eight rows: NanoLock Security,
Sight Diagnostics, Lili cleared (`url-cleared`, negatives declared); Deutsche Telekom declared
(`telekom-growthhub`); NVIDIA declared (`nvidia`, `mellanox`); Sight Sciences, Synopsys,
Nutanix, Genoox, Sony left; Quris AI and Fetcher stay in the hunt pool.

**Census A, honestly (confirmation wave R3):** `tenant_is_this_company`, `embedded_board_ok`
and `is_walled` answer identically on every one of the 521 ATS-host rows (457 active) — one
named delta, Deutsche Telekom, now declared. `activation_ok` does NOT: with no readable page
at all, 197 of the 457 active rows that the old gate admitted by tenant vacuity are now
`unverified` (lever 24/24, smartrecruiters 16/16, comeet 123 — 121 of them via the learned
page, greenhouse 10, ashby 4, workable 5, recruitee/bamboohr/breezy/eightfold 13; workday,
oracle and icims 0). In production each costs one GET of the human page on re-activation;
nothing is unsettleable, and a row can be declared. The 121 uid rows are not on C3b's list
(`docs/BACKLOG.md` 206); the Sunday `deferred (nothing vouches; no stamp): N` line is the count.

**Deliberately not done.** A tenant veto on undeclared rows; reading API endpoints as pages;
`_tenant_near` window changes (69); a display-name column (58/61). The precondition stated,
not assumed: human board pages exceed 2000 chars — if one does not, the failure mode is
deferral, and the first Sunday's `[??] ... deferred` lines measure it.

