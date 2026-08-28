# An LLM judges whether stored text is the employer's own posting

**Date:** 2026-08-28 (evening) · **Lane:** `jd-text` · **Decided by:** the operator
**Supersedes:** `docs/decisions/2026-08-26-no-llm-in-jd-text.md`

## What was decided

`pipeline/jdfill.jd_quality` sends an ambiguous stored description to Claude Sonnet and asks
one question: *is this the employer's own complete posting for this role, or is it page
furniture, a careers-page blob, or a truncated fragment?* A `complete` verdict finishes the
role; anything else puts it back in the todo.

The operator's words, when asked what to store for a role whose text is 394 characters of job
description followed by 5,606 characters of LinkedIn's login form:

> give description page to an LLM like an ambiguous role. if claude sonnet thinks this is a
> full listing its done.

## Why the previous decision no longer holds

`2026-08-26-no-llm-in-jd-text.md` recorded, with a measurement behind it, that this lane
spends zero Claude tokens. That decision was correct for the question it faced. The question
had been *"can an LLM fetch or repair text better than the ladder?"* — and no, the ladder is
cheaper and more reliable at getting bytes off a page.

This is a different question. It is not about fetching; it is about **judging text we already
hold**, and the two keyword rules that judge it today have a floor they cannot cross:

* `looks_like_jd` asks whether a text is long enough and names two section families. It cannot
  distinguish 300 characters of prose that are a whole posting from 300 that are its first
  paragraph.
* `_PAGE_FURNITURE` asks where the page chrome begins. It is a list of literal strings chosen
  by measurement, and on 2026-08-28 three plausible candidates had to be rejected because they
  cut real text — so the list is deliberately narrow, and a wall it has never seen goes
  through.

Both are cheap and both are right most of the time. Neither can be extended to cover the
ambiguous middle without starting to cut job descriptions, which is the failure that costs
data. A model reading the text is the right instrument for that middle.

## What it costs, and what bounds it

| | |
|---|---|
| candidates | only text that PASSES `looks_like_jd` and hits one cheap suspicion — a furniture marker survived the cut, the text sits exactly on `DESC_MAX`, or it is byte-identical to another posting at the same employer |
| measured population | **32 ledger texts** on the first run at `66d9e3c`, then **1–3 a day** |
| cost per call | **7.8 s**, measured 2026-08-28 |
| cache | the sha1 of the TEXT, in the existing `llm_cache` table under a `jdq1|` namespace — the same bytes are never bought twice and a re-run is free |
| call cap | `JD_QUALITY_LLM_CAP`, default 60 |
| wall clock | `JD_QUALITY_TIME_BUDGET_MIN`, default 4 min — at 7.8 s the call cap alone is 7.8 minutes on top of the 20-minute fetch budget, against a 25-minute step |
| off switch | `JD_QUALITY=0`, the shape `JD_BD=0` already has |

`CLAUDE_CODE_OAUTH_TOKEN` is one subscription shared by four consumers, which is why the tier
is a tier and not a pass.

## The safety property, stated as a rule

**A verdict can only ever move a role between the todo and done. No branch writes, shortens or
blanks a description on the model's word** — text is only ever changed by a rung that fetched
it. So the worst a prompt-injecting job description can achieve is to re-queue itself or to
declare itself finished, and neither corrupts what a visitor reads.
`test_the_llm_tier_cannot_touch_a_single_character_of_text` parses `_quality_pass` and fails if
the word `description` appears anywhere in its executed code.

Two more rules, both with a guard:

* **An unavailable model returns `None`, never `False`.** A tier that could demote a role on an
  outage would empty the board every time the token expired
  (`test_an_unavailable_model_leaves_the_cheap_verdict_standing`).
* **A row incomplete only because it sits on `DESC_MAX` is reported, never re-queued.** It is
  incomplete because *we* truncated it; re-fetching returns the same 6,000 characters and the
  role would come back every week having changed nothing (`docs/BACKLOG.md` 341).

## What was rejected

* **Widening `_PAGE_FURNITURE` until it covers the middle.** Measured: `privacy policy` hits 77
  stored bodies and cuts C2A Security's posting at 916 of 4,000 characters with the job still
  to come. A furniture list that reaches the ambiguous cases is a list that cuts descriptions.
* **Asking the model about every stored text.** 542 bodies × 7.8 s is 70 minutes against a
  25-minute step, for a question that is already settled for 510 of them.
* **Letting the model return the trimmed text.** It would make the model a writer rather than a
  judge, and the safety property above is the whole reason this is affordable.

## How to reverse it

Set `JD_QUALITY=0` in `daily-digest.yml`. The keyword rules stand on their own; coverage
returns to the 2026-08-28-morning bar, and the roles the tier catches go back to reading as
finished.
