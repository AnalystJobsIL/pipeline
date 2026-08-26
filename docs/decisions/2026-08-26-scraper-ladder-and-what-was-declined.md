# 2026-08-26 — the scraper ladder, and what was deliberately NOT done

*Lane: `scraper`. Companion to `docs/sessions/2026-08-24-scraper.md` (the 2026-08-26 evening
section), which records what shipped. This file records what was **rejected**, and the
measurement that decided it — so the next session does not re-open a settled question, and
does not mistake a declined option for an unnoticed one.*

Every number here was measured on the night, most of them over the 81 captured real pages.

## Decisions where an alternative was measured and lost

**1. A url-less reading must not end the ladder — but a later pass may only COMPLETE it.**
Rejected: letting the next strategy append freely. Measured on the captured Port.io page: a
free union adds **16 entries** — 10 mangled twins of real cards plus 6 Palo Alto roles
stamped Tel Aviv — and the `(title, location)` dedupe catches none of them. Also rejected:
"strong replaces weak when strong ≥ weak", which loses the roles a listing-only pass never
links (Aleph Farms: 3 cards, 1 of them url-less). What shipped is `promote_only` for the
passes that re-read the LISTING's own markup, and free appending only for the pass that
opens each position page — where the title and place come from the posting itself.

**2. Matching one reading's title against another's is a WHITELIST, not a blacklist.**
Rejected: a blacklist of seniority words. Measured over the committed cache: **40 pairs of
titles at one company contain each other**; the blacklist leaves **24** of them crossable
(`Backend Engineer` could still claim `Backend Engineer – Data Pipeline`'s address), the
decoration whitelist leaves **3**, and all three are the same posting written twice
(`… Engineer` / `… Engineer, Modi'in`). A wrong address is worse than none: it puts the
reader on another role and sends `jdfill` to the wrong description.

**3. The LLM tier's titles take an address from the page's own anchors, not from the model.**
Rejected: passing an anchor index into the prompt and asking for the href. It costs tokens on
every call, makes a wrong address the model's guess rather than a deterministic rule, and
cannot be replayed offline. The anchor rule was measured at **0 wrong** over the corpus.

**4. The LLM gate is "no Israeli place in the excerpt and no Israel-scoped url".**
Rejected: a gate on role words — it skips Central Bottling, a real winner whose 20 titles are
Hebrew. Rejected: a minimum excerpt length — measured to save **0 calls** on all 81 pages,
and it broke a legitimate small page in the test suite the moment it was added. The rule that
shipped is not a heuristic about what the model can read: `_Adder` refuses every non-foreign
job whose location holds no Israeli place, and the model sees nothing but the excerpt, so a
gated page can only produce rows that would be dropped.

**5. A live response outranks the copy the page embeds beside it.**
Rejected: reading embedded state first. Quantum Machines answers a Comeet XHR *and* embeds 52
JSON-LD blocks pointing at its own white-label front; reading the embedded copy first would
have moved **19 live postings** off their canonical `comeet.com` addresses for no gain.

**6. The board decides "names no place → Israel", and a held page is refused only on its own
evidence.** Rejected: deciding per page (it shipped **11 US account executives** of VAST
Data's global board as Israeli). Also rejected: refusing the whole group when any sibling
names a foreign region — that emptied Pecan AI's six genuinely Israeli roles, which is a mass
zero committed silently, the failure `ARCHITECTURE.md` §2 rule 2 exists for.

**7. `page_foreign` was left as a page-wide scan.** An anchored variant (foreign evidence
within 1,500 characters of the title, the way `_loc_from_ctx` anchors a place) was written
and measured: it disagrees with the page-wide test on **0** of the pages the rule can
actually refuse. Exposure was re-measured at **1 page**, and that page is a correct refusal.
Shipping a change that buys nothing is how a rule acquires an untested branch.

## Decisions the operator made, recorded so they are not quietly re-opened

**8. No cap on the residential unlocker.** Proposed: `SCRAPE_UNLOCK_CAP`, default 40 per run,
shared across the four spawn workers, with a capped company recorded as `budget:unlock` so it
could never read as `empty`. The operator's answer on 2026-08-26 was *"No cap, just log it"*.
What shipped instead is attribution: `unlock=2/5` on the company's own progress line,
`unlock_won` in the stamp. **The measured exposure is unchanged and real**: the `strong` gate
sends ~29 companies further down the ladder than before, each of which can make one
listing-level unlocker call, so the nightly 48 requests can grow by up to ~29 (~+60 %) against
a Bright Data pool the discovery lane reports at 111 %. The per-company ceiling
(`listing + all prefixes ≤ SCRAPE_UNLOCK_PAGES`) was designed and also **not built** — with
no run cap it is the only remaining bound, and it is the first thing to reach for if the pool
empties. Filed with the numbers rather than built against the decision.

**9. All adversarial waves before a single push**, rather than pushing the core early and
attacking it afterwards. The operator chose this on 2026-08-26; it cost a night's proof (the
first evidence is the 08-27 mail rather than 08-27 being the second data point) and bought
the two HIGH blockers the wave-2 confirmer found — a `/about/careers/` filter that rejected
six live boards, and a `partial_n` clock that reset on the night it existed for. Both would
have shipped.

## Work deliberately not done, and whose it is

**10. Nothing was merged from the residential pass.** Measured: of 218 active scrape rows with
no cache entry, a home-address pass produced jobs for **6** — and **5 of the 6 came `via
links`**, i.e. from the prefix-walk fix the cloud gets for free. Merging them would have been
churn dressed as coverage. The carry mechanism is built and inert; it does nothing until an
entry is marked. Rejected outright: a cloud pinned list sent through the unlocker with JS
rendering (recurring credits against a pool at 111 % for an unmeasured yield), and a Windows
scheduled task pushing weekly (an unattended second writer of `scraped_cache.json` under the
identity rules in `CLAUDE.local.md`).

**11. No code was renamed, moved or deleted.** `docs/AGENT_BRIEF.md` is explicit that a rename
here breaks four other lanes silently, and this diff already absorbed a design critic, three
attackers and a confirmer. The one deletion taken was a dead literal added the same night
(`"r&d"` in `_DECORATION`, which normalisation can never produce — it becomes two single
letters).

**12. Four things belonging to other lanes were left alone**, each reported rather than
touched: the five `docs/check_docs.py` errors in the shared checkout (a stale working-tree
copy, not master — verified green in a clean worktree); the unresolved merge conflict in
`docs/BACKLOG.md`; the colliding item numbers 215 and 240-246 (three lanes filed into that
range within an hour — cite by section until `docs` renumbers); and the 32 health baselines
built on nav junk that now read `regressed-to-zero`.

## What is still open in this lane, and why it is open rather than filed-and-forgotten

`docs/BACKLOG.md`, `scraper` 2026-08-26 (evening): **243** is scratchpad tooling, not repo
code. **247** is a place list, which is never finished — the gap the confirmer could reach
through is closed and pinned, and the durable fix is the role's own location field. **248**
is decision 7 above. **89, 219, 220, 221** need a week of live data or live multi-column
renders and cannot be measured tonight; 219 in particular cannot be re-measured before
~2026-09-02 by construction.
