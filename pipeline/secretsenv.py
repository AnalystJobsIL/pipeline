"""The one loader for the gitignored `secrets.env` (lane: infra, BACKLOG 438).

Four modules carried their own copy of `_load_secrets`, each resolving `secrets.env` against
ITS OWN tree root -- and as of 2026-08-30 three still do (`bd_rescue.py`, `bd_employees.py`,
`pipeline/jdfill.py`: BACKLOG 468, their lanes' three-line diffs), so `AJIL_SECRETS` arms
`pipeline.run` today and the Bright Data tools only once 457 lands. A git worktree under `.claude/worktrees/<x>/` is a different root, so a
session there had no credentials, every paid rung was silently DISARMED, and a disarmed rung
does not error -- it returns a refusal that reads as evidence (one such pass wrote 57 of 57
rows `dead`). The only two ways out were copying the file into the worktree (an uncapped
spender in a tree nobody watches -- banned by `docs/AGENT_BRIEF.md` rule 5) or working in
the shared checkout.

This module gives the third: **`AJIL_SECRETS=<path>`** names the operator's file where it is.
Nothing else arms a worktree -- deliberately. Auto-discovering the main checkout's file from a
worktree would arm every worktree by default, and with `BD_RUN_CAP` unset that is exactly the
uncapped spender the rule forbids. So:

    AJIL_SECRETS set          -> that file, wherever the tree is
    the tree IS the main checkout (`.git` is a directory)
                              -> `<root>/secrets.env`, as before
    the tree is a worktree (`.git` is a file), AJIL_SECRETS unset
                              -> nothing, and ONE stderr line saying the paid rungs are
                                 disarmed, so a mass-zero from here cannot pass as a finding
    GitHub Actions            -> nothing, silently (the names are repo secrets there)

`os.environ.setdefault`, never assignment: `tests/conftest.py` disarms Bright Data by setting
the two names to the EMPTY STRING, and `setdefault` declines a name that is present. Assigning
would hand the key back and make `python -m pytest` a spender again (BACKLOG 381).

    from pipeline import secretsenv
    secretsenv.load(REPO_ROOT)          # returns the path it loaded, or ""
"""
from __future__ import annotations

import os
import sys

ENV_VAR = "AJIL_SECRETS"
FILENAME = "secrets.env"
_warned: set = set()


def is_worktree(tree_root: str) -> bool:
    """A linked worktree's `.git` is a FILE (`gitdir: .../.git/worktrees/<name>`); the main
    checkout's is a directory. Neither (no `.git` at all) is an archive or a runner tree."""
    return os.path.isfile(os.path.join(tree_root, ".git"))


def resolve(tree_root: str, env=None) -> tuple:
    """(path or '', reason). The path may not exist; `load` handles that."""
    env = os.environ if env is None else env
    explicit = (env.get(ENV_VAR) or "").strip()
    if explicit:
        return os.path.expanduser(explicit), ENV_VAR
    if is_worktree(tree_root):
        return "", "worktree"
    return os.path.join(tree_root, FILENAME), "tree-root"


def parse(text: str) -> dict:
    """KEY=VALUE lines; blank lines and `#` comments skipped; the first `=` splits; both
    sides stripped (the root copies did not strip, so `KEY = v` armed a name with a
    trailing space -- a divergence nobody meant)."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def load(tree_root: str, env=None, out=None) -> str:
    """Arm `env` (default `os.environ`) from the resolved file with `setdefault`. Returns
    the path that was loaded, or '' when nothing was -- and says why on stderr, once per
    process, when the reason is the worktree trap."""
    env = os.environ if env is None else env
    out = sys.stderr if out is None else out
    path, reason = resolve(tree_root, env)
    if reason == "worktree":
        if not env.get("GITHUB_ACTIONS") and tree_root not in _warned:
            _warned.add(tree_root)
            print(f"secretsenv: {tree_root} is a git WORKTREE and {ENV_VAR} is unset -- "
                  f"{FILENAME} not loaded; every paid rung is DISARMED and a zero from here is "
                  f"not evidence. To arm: {ENV_VAR}=<path to the operator's {FILENAME}> and an "
                  f"explicit BD_RUN_CAP (docs/AGENT_BRIEF.md rule 5).", file=out, flush=True)
        return ""
    if not path or not os.path.isfile(path):
        if reason == ENV_VAR:
            print(f"secretsenv: {ENV_VAR}={path!r} is not a file -- nothing loaded, paid rungs "
                  f"DISARMED", file=out, flush=True)
        return ""
    with open(path, encoding="utf-8-sig") as f:      # -sig: Notepad writes a BOM by default
        pairs = parse(f.read())
    for k, v in pairs.items():
        env.setdefault(k, v)
    return path
