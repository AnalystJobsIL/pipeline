# 2026-09-13 — the free search rung is deleted, on the measurement it was kept to produce

*lane: `infra`. Closes the keep/delete rule of `2026-09-11-bd-unlimited-optimize-once.md` §5
item 1. Every number below is from a run log (`gh run view <id> --log`, each line mapped to its
step by the step's own start/end times) or from `cloud_state/bd_spend.jsonl` at `origin/master`
`ef5a2ea`.*

## The rule, fixed in advance

On 2026-09-11 `deep_validate.ddg` (DuckDuckGo's keyless HTML endpoint) was hardened and put
ahead of the paid Google search in every search tool, and every paid search also asked it the
same question and printed `[search-ab] <name> ddg=<host> unlocker=<host> agree=y/n`. **Keep the
rung at ≥ 70 % agreement with the unlocker on the names it answers; below that, delete it and
say so.** The first reading, on the 09-12 19:00 hunt, was
`duckduckgo answered 0 of 1 names ... (0%)`, and the 09-13 brief asked for the parse to be
checked before trusting it and for two nights of the A/B on every searched name.

## It was not a parse miss, and two more nights could not have produced a sample

Every process that asks DuckDuckGo a question prints `[ddg] rate-limited (HTTP 202)` on the
first 202 and switches the rung off for the rest of the process, and the A/B switches off with
it. A successful answer prints nothing. So the log answers "which processes were blocked, and
when", and the ledger answers "who bought a search anyway".

| run | step | first DuckDuckGo line |
|---|---|---|
| hunt 34649753733 (09-11 19:00) | hunt listings · 4 drain shards · re-crack walled · repair dead urls | 202 — within 5 s of the step starting for the first six; 3-5 min in for the repair step, after its DNS pass (7 processes) |
| hunt 34719109028 (09-12 19:00) | the same seven | the same (7) |
| audit-coverage 34749274896 (09-13) | re-audit parked rows · re-crack walled (30 d) | 202 within 5 s of each step starting (2) |
| self-heal 34752428352 (09-13) | re-resolve stale boards | answered one name: `ddg=en.axioma-in.com unlocker=www.axioma-in.com agree=n` |

**16 of the 17 processes that left a DuckDuckGo line were refused, 14 of them within five
seconds of starting.** The
drain's shards were refused within one second of starting (23:52:38-39 and 00:10:38-39), so
the 156 names they searched on those two nights (44 + 112) got **0** answers from the free rung.

Search credits in the window (09-11 21:30 → 09-13 11:12): **494** in the ledger (`listing_hunt`
300, `audit_empty_rows` 150, `crack_walled` 25, `repair_dead_urls` 18, `resolve_broken` 1) plus
**204** the drain shards printed on their `[bd-spend]` lines and did not book (fixed by
`registry` in `121ea58`). **697 of 698 were bought by a process DuckDuckGo had already
refused.** The one it answered disagreed on a subdomain of the same company, which the A/B's
exact-host compare scored as a disagreement.

The parse was checked anyway (`uddg=` redirect params, then bare `href`s, through
`is_aggregator` and the shared `_rank_hosts`) and it is not the cause: a 202 page has no
results to parse, and the one 200 the runners got was parsed into a correct host.

## Two defects in the measuring device

Recorded because a future session that re-adds a free rung will build the same A/B.

1. **It could only sample the names the free rung had already failed.** The A/B ran inside
   `google_via_unlocker`, and every caller asked `ddg` first and paid only when it came back
   with fewer than two hosts. A name DuckDuckGo answered well never reached the paid rung, so
   it was never compared. Agreement on the sample says nothing about the rung.
2. **It compared full hostnames**, so `en.axioma-in.com` against `www.axioma-in.com` read as
   two companies.

## Decision

**Deleted**: `deep_validate.ddg`, `_ddg_fetch`, `_DDG`, `DDG_PACE_S`, the A/B (`_AB`,
`_search_ab`, `_report_search_ab`, the `atexit` hook, `SEARCH_AB`, `SEARCH_AB_CAP`), and the
free-first block in nine callers: `queue_resolve_search.search_one`, `listing_hunt.hunt_one`,
`crack_walled.crack_one`, `resolve_broken`, `audit_empty_rows.serp`,
`repair_dead_urls.candidates`, `resolve_llm._search_candidates`, `deep_validate.validate_one`,
and `registry_health`'s reachability probe of the rung. Every ladder below the removed line is
byte-identical, so each tool now does on every night what it already did on every blocked one.
`tests/conftest.py` keeps both DuckDuckGo hosts in `FREE_BUT_LIVE_HOSTS`: the ban costs nothing
and is what stops a re-added live search from reaching the internet from the suite.

`validate_one` carried a defect that went with it: `ddg(name) + (google_via_unlocker(name) if
len(cands) < 2 else [])` evaluated `len(cands)` on the SEED list before DuckDuckGo's results
were appended, so it paid for a search even when the free rung had answered four hosts.

**What the deletion saves**: nothing, and that is the point. The rung never answered where the
money is. **What it costs**: at most the one self-heal name a day it might have answered, i.e.
~1 search credit, and a local session's free search (it was rate-limited there too).

## The spend this leaves, stated

Search was **301 credits/day** of a 423/day 7-day rate on 2026-09-13 (71 %). It will RISE, and
not because of this change: `registry` raised the queue drain's nightly capacity 112 → 176 on
2026-09-13 (`121ea58`). The drain's own rate is 145 credits for 112 names on 09-12 (**1.29 per
name**: `search_one` makes up to three attempts), so at 176 names it is **~228 a night, +83**,
about +2,500 a month, taking search to ~384/day. Under the operator's 2026-09-11 ruling that is
paid, not refused: about $3.75 a month at PAYG.

The remaining lever on search is not a free rung. It is how many names a night need one, which
is the drain's intake (`491@infra`) and the hunt's 14-day cadence, both already in place.

## Rejected

| alternative | why not, on the number |
|---|---|
| two more nights of the A/B, as the brief asked | the rung switches itself off at the first 202, and 14 of 14 hunt-night processes got one, 12 of them within five seconds: the sample would be n ≈ 1 again, and biased (defect 1) |
| keep the rung in the two workflows where it was not refused (self-heal, auto-expand) | they bought 1 and 0 search credits in the window; a rung that can save one credit a day is not worth nine callers and a test that must stub it |
| a different free endpoint (`lite.duckduckgo.com`, POST, other headers) | the HTML endpoint answered a runner once with a correct parse, so the request shape works; the refusal is the runner's address, and every DuckDuckGo endpoint shares it |
| move the A/B to a free-first sample instead of a paid-first one | it needs a free rung that answers on the runner, which is what was measured not to exist |
