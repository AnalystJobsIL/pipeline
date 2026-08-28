# The pre-push gate may not spend money

**Date:** 2026-08-28 · **Lane:** infra · **Closes:** `docs/BACKLOG.md` 374, 381

## What happened

The `jd-text` lane copied the gitignored `secrets.env` into its git worktree to run a test.
`python -m pytest` then booked **4 Bright Data requests** and appended
`{"credits":4,"tool":"__main__.py"}` to that worktree's `cloud_state/bd_spend.jsonl`. The lane
reverted the line rather than commit a record it could not vouch for, removed the secrets, and
filed it. Nothing had stopped it, and nothing would have said so if the lane had not
volunteered it.

Separately, `registry` reported `[bd-spend] bought 3` surviving on pristine master and routed
it here. **They are the same event.** Reproduced in a clean worktree at `759ba36`:

```
$ python -m pytest tests/test_registry.py -q          # no secrets.env
[bd-spend] this step bought 3 Bright Data credit(s) (no cap set)
$ git status --porcelain
 M cloud_state/bd_spend.jsonl
$ tail -1 cloud_state/bd_spend.jsonl
{"at":"...","cap":null,"capped":false,"credits":3,"pid":34508,"tool":"__main__.py"}
```

and with a `secrets.env` beside it, **4** credits across two tests — 381's number exactly:

```
    1  tests/test_registry.py::test_validate_empty_a_readable_page_decides_and_a_refusal_is_visible
    3  tests/test_registry.py::test_bd_rescue_reads_the_unlockers_error_code_and_never_retries_a_policy_host
```

**The 3 were phantom; the 1 was real.** The second test stubs `urlopen`, so its three credits
were a counter increment and nothing left the machine. The first does not: with the transport
guard installed it dies on `PaidCallInTests: a test reached https://api.brightdata.com/request`.
BACKLOG 381 hoped "the count is probably phantom, but nothing proves it" — something proves it
now, and the answer is *mostly, but not entirely*. One request was really bought.

Two independent defects made that possible:

1. `bd_rescue.py` did `SPENT["n"] += 1` one line **above** the two `os.environ[...]` reads, so
   a call that died on a missing zone booked a credit it never spent.
2. The `atexit` reporter added that morning (`47719bc`) wrote those fabrications into the
   tracked ledger — and `persist_state` auto-owns that path for **every** workflow, so a
   fabricated line is staged and committed by design. The artefact built to be believed by a
   later session was the one being falsified.

## The decision

Three changes, all at a chokepoint, none conditional on the environment:

1. **`tests/conftest.py` bans the paid transport.** It wraps `urllib.request.urlopen` and
   refuses `api.brightdata.com`, raising a **`BaseException`** subclass.
2. **The credit is counted after the request is built, never before** (`bd_rescue.py`).
3. **`_report_spend` refuses to write the ledger from a test process** — `"pytest" in
   sys.modules` *and* `ROOT` holds a `.git`. A `tmp_path` `ROOT` still writes, which keeps the
   durability guard from `47719bc` meaningful instead of vacuous.

Two details are load-bearing and were both found by measurement, not by reasoning:

- **`BaseException`, not `Exception`.** All three unlockers (`bd_rescue.unlock_status`,
  `bd_employees.unlock`, `pipeline/jdfill`) end in a blanket `except Exception` that turns any
  failure into `("", "timeout")` or `None`. An `Exception` subclass is swallowed there and the
  suite stays green while the guard does nothing.
- **The credential names are set present-and-empty, not popped.** Four modules carry their own
  `_load_secrets`, and every one arms the environment with `os.environ.setdefault`, which fills
  an *absent* name. With the names merely popped, a `secrets.env` re-armed the key and the run
  reached the live account — measured, then fixed. An empty string is falsy to every credential
  check in the repo and refuses the setdefault.

## What was rejected, and why

**A guard that refuses to spend when the process runs from a worktree.** Rejected. The worktree
is not the hazard — a credential in a process running unattended code is. `secrets.env` is
loaded with `setdefault`, so anyone with the key exported in their shell is unaffected: it
guards the file, not the credential. Applying it to `bd_rescue` alone while `bd_employees`,
`pipeline/run` and `pipeline/jdfill` keep their own loaders would teach "worktrees are safe",
which is worse than no guard at all. And decisively, `docs/BACKLOG.md` already records what
environment-conditional behaviour costs here: eleven guards had never once run locally because
`os.path.isdir(".git")` is False in a worktree — **a false local green**, which is the exact
thing `CLAUDE.md` rule 1 exists about. The chosen guard behaves identically in CI, in the
primary checkout and in a worktree.

*(One argument for this option turned out to be wrong in the other direction, and is recorded
so nobody re-runs it: refusing `secrets.env` in a worktree was thought to silently disable LLM
classification, because `secrets.env` was believed to hold `CLAUDE_CODE_OAUTH_TOKEN`. It does
not — it holds `SERPAPI_KEY`, `BRIGHTDATA_API_KEY`, `BRIGHTDATA_ZONE` and nothing else. The
option is still rejected, on the false-local-green ground alone.)*

**A louder ledger — an unexplained-delta alarm the next morning.** Rejected. It would not have
caught this incident: the line was written to the worktree's own `cloud_state`, on a branch
nobody merges, and was reverted. It cannot be made to work cheaply either. The ledger is
structurally incomplete — `bd_employees` and `jdfill` never write to it, and `_report_spend`
returns early when the count is zero, so a clean run leaves no heartbeat — and the only truth
to reconcile it against is the live account, which `pipeline/bd_budget.py` reads **failing
open** on purpose. A delta that is noisy from day one is the alarm nobody reads, which is the
failure `test_the_cache_shrink_alarm_fires_on_every_regression_it_was_built_from` was written
to avoid. What *was* taken from this option is its cheap half: the record now carries
`ci: true|false`, so a stray line is self-identifying. A boolean, never the path — `ROOT` under
a home directory would put a personal username into a public repo.

**`BD_RUN_CAP=0` / `PAGE_UNLOCK_BUDGET=0` as the lock** (what `drain_queue._lock_the_paid_rungs`
does for itself). Rejected, both measured. `BD_RUN_CAP` guards one of the six paths that bill —
`bd_rescue`, `bd_employees`, `pipeline/jdfill` and `setup_brightdata` all POST to
`api.brightdata.com`, and `bd_discover` and `discovery_daily` trigger a `datasets/v3` job that
bills per **record** — and the run-cap guard in `tests/test_units.py` pops the variable from
`os.environ` with no restore, so everything after it would run uncapped anyway. It also reds
`tests/test_registry.py`'s stubbed-unlock assertion. `PAGE_UNLOCK_BUDGET=0` buys nothing the
transport ban does not, and reds `test_the_unlocker_rung_inside_the_page_test_still_exists`,
which uses the ambient budget as its positive control. `sys.modules["bd_rescue"] = None` was
not considered: `drain_queue` records that it broke 77 tests.

**Documentation and nothing more.** Rejected as the whole answer — the session that spent the
money was *following* the documentation, since the documented pre-push command is what spent —
but adopted for the half no mechanism reaches. `python -m pipeline.run` locally still arms the
key inside `run()` and buys up to 100 unlocks through the identity gate, and `JD_BD` defaults
to 1. `docs/AGENT_BRIEF.md`'s "Rules that will bite you" had **no rule about money at all**;
it has one now, and the "local runs are safe by default" line beside it — false about spend —
was corrected in the same commit.

## What this does not cover

- `python -m pipeline.run`, `python bd_rescue.py` and every other deliberate local run. Bounded
  by `JD_BD=0` / `BD_RUN_CAP=0` and by rule 5, not by a mechanism.
- `tests/rehearse_*.py`, `tests/role_leak.py` and `tests/schedule_census.py` run under plain
  `python`, so no conftest loads for them. They scrub the environment themselves today.
- `bd_employees.py` still has no cap, no counter and no ledger line of its own.
