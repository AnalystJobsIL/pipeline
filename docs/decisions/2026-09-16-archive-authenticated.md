# 2026-09-16 — the evidence archive runs on the account's Save Page Now API, and the backlog question is re-shaped, not closed

*lane: `infra`. Supersedes the "anonymous, one request every few seconds" design of
`docs/sessions/2026-09-04-infra.md` §3 and re-scopes `620`. Every number below is from
`cloud_state/wayback_ledger.jsonl` at `9bae94a`, the three run logs of 09-13..09-15, the
first authenticated run on this machine (16:04–16:19Z, `--limit 20`), or archive.org's own
SPN2 API document, read the same day. Two numbers in the spawn prompt were wrong and are
corrected where they appear. Bright Data credits spent: 0 — this path has no paid rung.*

## 1. What the anonymous rung cost

Twelve nights, 09-04..09-15, 768 ledger lines: **52** captures named at once, **53** verified
later, **271** `pending` lines that were every one a 60-s timeout (`http: 0`), of which
**206** were `unverified` three days on, six nights in twelve that named nothing (the
09-15 record has the two failure families it took to tell an archive-down night from a
host refusing us). ~9 captures a night against a backlog that rose from 4,603 to 6,193 with
~124 new addresses a day. `620` was filed on that: "the queue cannot drain at any ordering".

The mechanism, not the ordering, was the limit: an anonymous `GET /save/<url>` answers a
302 naming the capture after 18 s or after minutes, so the step could only hold a connection
open and guess, and the archive holds an anonymous IP to 15 requests a minute and blocks it
for five past that.

## 2. What the account gives (measured, not quoted)

The operator created an archive.org account on 09-16 and set `ARCHIVE_ORG_ACCESS_KEY` /
`ARCHIVE_ORG_SECRET_KEY` as repo secrets and in `secrets.env`. `GET /save/status/user`
answered `available 3, daily_captures_limit 30000, daily_status_limit 70000`. The SPN2 API
document says, for an authenticated account: **7 captures a minute**, 30,000 a day, 5 a day
per url, a capture at most 2 minutes, and `error:<word>` ends with a fixed vocabulary.

The first authenticated run from this machine, `--limit 20`, 16:04:20–16:19:36Z:

| what | reading |
|---|---|
| jobs opened / captures named | **13 / 4** (connecteam ×2 in 17 and 25 s, il.linkedin ×1, ashby ×1) |
| `error` ends | 7 `il.indeed.com` `error:bad-request`, 2 `www.linkedin.com/jobs/view/<id>` `error:not-found` — the address's refusal both times; il.indeed.com parked after five |
| `pending` | **0** — every job ended (the anonymous rung: 271 of 271 lines a timeout) |
| pre-commit `pending` lines asked of the availability API | 12, all `unverified` (past three days, none answered) |
| status reads | 39 for 13 jobs, 3 a job at 10 s; `daily_status` allows 70,000 |
| the account's count after the run | `daily_captures` 0 → **13 = jobs**, not `captured` (an error end is a capture to the archive); `available` 3 → **2 with nothing in flight** |
| 429s | **two, to a POST, with no `Retry-After`**, at requests 16 and 21 — each time the POST that followed a job's end with two other jobs in flight |
| wall clock | 15 m 16 s, of which **10 m were the two 300-s pauses** the 09-15 rule (a 429 = the per-IP block, five minutes) answered them with |

So the account's 429 is not the anonymous block: it is the archive's slot count lagging a
finished job (`available` still read 2 after the run), and the document's own words for a
429 are "delay any subsequent captures for 10 to 20 sec". **Shipped on that**: on the keyed
rung a 429 with no `Retry-After` is a 20-s wait in the thread that got it (`SLOT_WAIT_S`),
then one more ask; a second 429 in a row opens the day's pause at `OUTAGE_WAIT_S` (90 s),
not five minutes; a 429 that names its `Retry-After` pauses every thread for it, as before.
The two-pause rule stays the backstop.

## 3. The three corrections to the spawn prompt

| the prompt said | what is true | consequence |
|---|---|---|
| raise the caps to drain the backlog in ~3 nights | the archive allows an account **7 captures a minute**; a capture takes 17–50 s; three slots | 2,064 a night is 295 minutes of sends at the archive's own limit. The 60-minute budget lands at most ~340 jobs by the pace gate and, at the measured 3-slot rate (13 jobs in ~5 unpaused minutes), more like **150–250**. The backlog (6,085 after this run) drains in weeks, not nights; tier 1 (~500 disputed addresses) in two or three. |
| `error:too-many-daily-captures` is the archive's daily limit; `error:no-access` means fall back to anonymous | the document: `too-many-daily-captures` = "this URL has been captured 10 times today"; `no-access` = "target URL could not be accessed (status=403)" | per-url → the existing `limit-url` class; `no-access` → the address's `http`. The ACCOUNT's day is read from `/save/status/user` before the plan; the keys being refused is an HTTP 401/403 to the POST or that probe, and that — only that — falls back. |
| morning row `captured >= 500` | ≤ ~340 jobs possible in the budget, and 9 of 13 on the tier-1 slice were refusals (Indeed, LinkedIn) | the row asks `jobs >= 120` and `captured >= 40`, and quotes both |

## 4. What was decided, and what was rejected

- **No `capture_all`.** A capture of a 404 page would mark the address done for ever
  (`eligible`: a posting once captured is done) with an error page where a dispute needs the
  posting's text. `error:not-found` is a 7-day cooldown and the address is asked again until
  tired. Rejected on the ledger's own rule, not on taste.
- **The POST carries `url` only.** No `if_not_archived_within` (the ledger is the dedupe), no
  `delay_wb_availability`, no `skip_first_archive`, no `use_user_agent` — the target page
  sees the archive's crawler, the Authorization header goes to archive.org only, and a
  capture carries no public attribution. Nothing links the public repo to the account.
- **`pending` keeps its token and gains a `job_id`.** On the keyed rung it can only mean a
  job whose end this run did not read (the status endpoint failing for the whole 150-s
  ceiling), and the next run asks `/save/status/<job_id>` — exact — before the availability
  API, which stays for the 09-04..09-15 lines that have no id. A POST that times out is
  `net:TimeoutError`, never `pending`: the anonymous `pending` went to the availability API
  and, unanswered, to `unverified`, a refusal of the address.
- **`err` stays a bare class; `status_ext` carries the archive's word**, mapped by
  `archive_evidence.STATUS_EXT` onto the 09-15 families — a word about the archive's own
  machinery is `server` (the streak, never a park), a word about the target is the address's
  refusal, and **a word not in the table is `server`**: a host is never parked on a word we
  do not know. The ledger's field set is otherwise unchanged; the two new fields are written
  only when set, so every anonymous-rung line is the 09-04 shape byte for byte.
- **Workers = min(`WAYBACK_WORKERS`, `available`)**, read every run; the env is a ceiling.
  `WAYBACK_DAY_CAP` = min(the cap, what the account has left today); nothing left is
  `stop=daily-limit` before any POST. Rejected: workers = `available` − 1 to dodge the lag
  429 — the slot wait costs 20 s a hit, a lost slot costs a third of the night; the first
  scheduled night's `throttled` count decides it (above a fifth of `jobs`, take the −1).
- **The alarm composes.** `unauthenticated: …; zero-produce: …` — the first clause no longer
  suppresses the second, which the old `if not rep.alarm` did.
- **Rejected: a batch `POST /save/status` with `job_ids`.** The document names it; it was
  not measured, and 39 reads for 13 jobs sit under a 70,000-a-day allowance. One measured
  night decides whether it is worth a second code path.
- **Rejected: a Fact for every cap.** One, `wayback_day_cap`, read from the workflow — the
  §4 row had said 100 postings for twelve days while the step ran 150.

## 5. `620`'s new shape

Capacity was the anonymous rung's number. The account's rung is bounded by the archive's
7 a minute and 3 slots (~150–250 jobs a night at a 60-minute budget), so the backlog drains
in weeks and tier 1 in days — and the question that is left is not ordering but **which
addresses can capture at all**: on this slice every `il.indeed.com` job ended
`error:bad-request` (7 of 7) and every `www.linkedin.com/jobs/view/<id>` ended
`error:not-found` (2 of 2), while `il.linkedin.com/jobs/view/<slug>-<id>` captured. Indeed
and LinkedIn are 46.5 % of the target set. `620` is re-scoped to that measurement: a week
of scheduled nights, the capture rate per host from the ledger, and then the operator's
call on whether a host that never captures stays in the tiers. The Check line on the item
is the command.

## 6. What this made harder

`Auth` in the `run()` signature and `_wb_quiet`'s `real_auth` seam (a test of the fallback
must ask for it); `job_id` in every hand-built ledger state that reads it; `STATUS_EXT` as a
table the next `status_ext` word has to be added to (an unknown word is safe, `server`);
`tests/conftest.py` holding two more names empty; the `wayback_day_cap` Fact, which now
refuses a §4 row that drifts from the workflow.
