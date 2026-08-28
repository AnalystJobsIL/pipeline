# 2026-08-28 — the relay gets an event, not a clock

**Lane `infra`. Re-opens `308@infra`, which the operator declined on 2026-08-27, with two more
days of evidence. Decision taken by the operator the same day; this records what it costs and
what was rejected, so nobody re-derives it.**

## What actually happened, measured against `origin/master`

The brief this session started from said "the relay has no working scheduler" and "the pipeline
side is not the problem". Half of that is right. The measurement:

| date | digest artefact | relay polls fired | mail |
|---|---|---|---|
| 2026-08-26 | `b2090f6`, 06:03 | 4 of 4 | issue #10, from a scheduled poll |
| 2026-08-27 | **never written** | 1 of 4 (17:39) | **none, ever** |
| 2026-08-28 | `9bbaf69`, 07:08 | **0 of 4** | issue #11, from a hand dispatch at 08:28 |

`git log --format='%ad %h' --date=iso-strict origin/master -- digests/latest.md` jumps straight
from 2026-08-26T06:03 to 2026-08-28T07:08. **There is no 2026-08-27 digest at all.** That day's
`daily-digest` cron was dispatched at 16:18 — eleven hours and eighteen minutes late — and
`persist_state.py deliver` then correctly refused to publish it, because 16:18 is past the
relay's last poll and a digest written then is overwritten by tomorrow's before anyone reads it.
The relay's single 17:39 poll behaved perfectly: it found the 2026-08-26 file, matched the hash
it had already posted, and exited 0.

So the two days failed in two different places — 08-27 on the pipeline side, 08-28 on the relay
side — and both needed a human. **Nothing here was a relay bug.** Both are the same underlying
fact: GitHub dispatches a cron when it feels like it, and lately it often does not.

Also worth recording, because it is the part that worked: the second (dispatched) digest run on
08-28 FAILED at its `pipeline` step, and `cloud_state/last_run.json` shows
`"delivered": true, "notice": false` — the delivery guard from 2026-08-27 refused to overwrite
the morning's good digest with a failure notice. That is `304@infra` earning its keep.

## Why more polling cannot work

`python tests/schedule_census.py` counts **0** isolated single-slot drops: 38 of 38 due
dispatches fired 08-22..08-26, and when it fails it fails wholesale — on 08-27, four consecutive
pipeline slots and all of the other repo's polls went together. **Redundancy inside GitHub's
scheduler buys nothing, because the scheduler is the single point of failure.** That is why
`292@infra` rejected a watchdog cron, and it is equally why adding a fifth and sixth relay poll
would not have helped on 08-28. Only a trigger that is not a schedule can.

There is no credential-free cross-repo trigger on GitHub. `workflow_run` does not cross
repositories; `repository_dispatch` needs a token; a deploy key needs a push. So the honest
framing of the choice is not "event or clock" but **"which credential, and where does it point".**

## The options, and what each costs

**(a) An outbound dead-man's-switch ping to a third party.** *Rejected — it does not deliver.*
It tells the operator that a morning was lost; it cannot get the mail out. It also adds an
external service to a design whose whole premise is that there is no server, and the operator
declined it on 2026-08-27. It remains the right answer to a different question (`308@infra`:
how do you notice when GitHub is down *and* the laptop is asleep) and is left open there.

**(b) `repository_dispatch` from the pipeline, using a fine-grained PAT.** *Rejected — strictly
dominated by (c).* Identical blast radius: a fine-grained PAT scoped to the inbox repo needs
`contents: write`, exactly what a deploy key grants. But a PAT belongs to a **person**, so its
use is attributable, and — decisively — **it expires silently**. A dead PAT reproduces precisely
the failure this is meant to fix, with no alarm, on a day nobody is looking.

**(c) A write deploy key, pushing a receipt; the relay triggers on `push`. CHOSEN.** A deploy
key belongs to a **repository, not a person**, so no run page names the owner
(`CLAUDE.local.md` §3) and there is nothing to expire. It is the pattern `BOARD_DEPLOY_KEY`
already uses in the same job to publish the board, so it is proven here rather than merely
plausible. The four crons stay as a backup — about four minutes of private Actions minutes a
month, and the thing that still delivers if the key is revoked or never installed.

**(d) Keep the cron and extend the local watchdog only.** *Rejected as the primary fix — it does
not deliver either.* Taken anyway as the cheap second layer, because it is nearly free and it
covers the case where the new path itself fails. (`digest_watchdog.py` **is** tracked in this
repo, contrary to the session brief; the copy under `C:\Users\svald\AnalystJobsIL-watchdog\` is
an installed copy the operator re-deploys.)

## What `292@infra`(b) said, and why this is not that

292 rejected this class in one line: *"the public repo holds no credential for the private
notification repo and must not."* That rule is not free-standing — the public repo **already**
holds `BOARD_DEPLOY_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `BRIGHTDATA_API_KEY` and `SERPAPI_KEY`, in
the same job, and takes no pull requests, so no fork ever sees a secret. Adding one more is a
marginal change of degree, not of kind. **What is genuinely new, and is stated here rather than
glossed: a compromise of this repo's Actions secrets would now also expose the private inbox
repo, which contains the `cc @` mention — i.e. the identity everything else is arranged to
protect.** That is the price, the operator was shown it, and the operator chose it. Mitigations
applied: the repo address is itself a secret, so the public workflow file names no private
repository, and the key is write-scoped to the one repo.

## The race this closes — and the version of it that an adversary killed

`raw.githubusercontent.com` serves a cached copy after a push. A naive push trigger therefore
arrives *before* the content and mails yesterday's digest — or, worse, matches yesterday's hash,
deduplicates, and mails nothing at all, which looks exactly like success.

**The first design fetched from raw and retried until the body hashed to the receipt.** An
adversarial pass measured the flaw: that CDN sends `Cache-Control: max-age=300`, and the retry
budget was six attempts twenty seconds apart — about two minutes. **Inside the TTL every retry
returns the identical stale object, so the loop could not win the one case it existed for**, and
its fall-through was "mail whatever we have", i.e. yesterday's digest. On the very day the crons
are dropped — the day this whole change is for — that is total mail loss with a green run.

**So the receipt is the digest itself.** `daily-digest` pushes the receipt body (`receipts/**`) (the bytes,
read back from `git show origin/<branch>:digests/latest.md` after every earlier step has pushed)
alongside a one-key its hash file (`receipts/**`) holding their sha256. On a push the relay reads its
own checkout and never touches the network; the hash is a cross-check that the two files agree,
not a race to win. The CDN, the retry loop and that whole failure class are gone. The cron path
still curls, unchanged, because a scheduled run has no fresh receipt to trust.

Three more things the same pass found and that are fixed here: the relay had **no `concurrency`
group**, and a push overlapping a late cron poll would have had both runs pass the dedup and
both mail; the dedup inspected **one** issue, so any non-digest issue at the head of the list
would blind it permanently (now twenty); and the notify step could **fail the digest job** —
`git fetch`, `git clone` and `ssh-keyscan` all abort under `bash -e` with no `exit 1` anywhere,
turning a morning the mail shipped into a red run. It is now `continue-on-error`, and the guard
asserts that property rather than grepping the script for `exit 1`.

Two details a later reader will otherwise re-derive:

* The receipt hash is a **raw-byte** `sha256sum`, deliberately the same number the relay
  computes. It happens to equal `persist_state.digest_sha` today (both `5d4a0f8a4256`, verified
  2026-08-28) only because that function normalises CRLF and the runner's file has none. They
  are different computations; a CRLF checkout separates them.
* The notify step runs **after** `outcome`, which is the step that replaces a lost morning's
  `digests/latest.md` with a failure notice. A lost morning is when the mail matters most, so
  the notice has to reach the event-driven path too. It only announces a file whose **first
  line carries today's date** — true of both the digest H1 and the notice — because on a
  deferred day origin still holds yesterday's digest, and announcing that either re-mails it
  or deduplicates against it so the day goes quiet.
  `test_daily_digest_steps_have_ids_no_swallows_and_an_outcome_step` was widened to encode
  exactly that, and tightened at the same time: what follows `outcome` must write no repo state
  and must never fail the job.

## Proof

Run **`33159616979`** in `AnalystJobsIL/inbox`, `event=push`, `success`, 8 seconds after a
receipt landed — no scheduled poll involved. Its log:

```
push event: waiting for the digest that hashes to 5d4a0f8a4256
raw is current (attempt 1)
already posted: 🎯 4 new senior analytics roles — 2026-08-28 (5d4a0f8a4256)
```

That proves the trigger, the receipt read, and the hash gate, and it proves the dedup refused to
send a second copy of a digest already mailed as issue #11.

**What it does NOT prove, stated plainly:** no issue was *created* on a push event, because
today's digest had already been mailed and the dedup — correctly — declined. Forcing that would
have meant sending the operator a duplicate email for no information. The posting code is
unchanged and has worked eleven times; the untested link is `gh issue create` under a `push`
event's permissions. It is filed as a morning check for the first digest after the operator
installs the secrets.

## What the operator must do for this to become live

Until both secrets exist the new step prints one line and exits 0, so this change is inert.

1. `ssh-keygen -t ed25519 -f inbox_deploy -N ""`
2. `AnalystJobsIL/inbox` → Settings → Deploy keys → add `inbox_deploy.pub`, **Allow write access**
3. `AnalystJobsIL/pipeline` → Settings → Secrets → `INBOX_DEPLOY_KEY` = the private key,
   `INBOX_REPO_GIT` = `git@github.com:AnalystJobsIL/inbox.git`

## What this does not fix

The digest's *own* cron. On 2026-08-28 `daily-digest` was not dispatched at all, and a receipt
is only pushed by a run that happens. That is `292@infra`/`308@infra`, whose re-measurement is
pre-committed for **2026-09-10**: ≥ 3 isolated single-slot drops ⇒ build the recovery cron. This
decision narrows that gap by one repository; it does not close it.
