"""The one `claude -p` seam (shared plumbing, ARCHITECTURE.md §7b).

`call()` runs the CLI once — tool-less, schema-constrained, no session, no shell, never from
the repo — and returns the model's answer, or raises `LLMUnavailable(kind)` for anything
that is infrastructure rather than opinion. `pipeline/seniority.py` is the first consumer;
`pipeline/firmographics.py` keeps its own seam until it migrates (docs/BACKLOG.md 117).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time

_AUTH = re.compile(r"\b401\b|oauth[^.]{0,40}(invalid|expired)|not logged in|/login\b|"
                   r"failed to authenticate|authentication_error", re.I)
_MAX_SCAN = 200_000        # chars of stdout the envelope scan will walk (it is quadratic past that)
_DRIFT = re.compile(r"unknown option|unknown command|too many arguments", re.I)


class LLMUnavailable(Exception):
    """Infrastructure, never the model's opinion: CLI missing, non-zero exit, `is_error`,
    timeout. `.kind` is `auth` / `drift` / `missing` / `transient` — the breaker treats the
    first three as final on the first hit."""

    def __init__(self, msg, kind="transient"):
        super().__init__(msg)
        self.kind = kind


def _ascii(s, n=160):
    """CLI stderr carries box glyphs; the step log may be a cp1252 console (see
    company_intel._ascii). One line, ASCII, capped."""
    t = " ".join(str(s or "").split())
    for ch, rep in (("\u00b7", "-"), ("\u2014", "-"), ("\u2013", "-"), ("\u2018", "'"),
                    ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"')):
        t = t.replace(ch, rep)
    return t.encode("ascii", "replace").decode()[:n]


def _envelope(raw):
    """The CLI's result envelope inside `raw`: the LAST object carrying `is_error` or
    `structured_output` (an update notice, an init event or a stray `{}` may precede it),
    else the first object at all. Scans at most the final `_MAX_SCAN` chars."""
    raw = (raw or "")[-_MAX_SCAN:]
    dec = json.JSONDecoder()
    first = env = None
    i = raw.find("{")
    while i != -1:
        try:
            obj, end = dec.raw_decode(raw, i)
        except ValueError:
            i = raw.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            first = first if first is not None else obj
            if "is_error" in obj or "structured_output" in obj:
                env = obj
        i = raw.find("{", end)
    return env if env is not None else first




def _kind(text):
    t = text or ""
    if _AUTH.search(t):
        return "auth"
    if _DRIFT.search(t):
        return "drift"
    return "transient"


def call(prompt, *, system, schema, model, timeout, cwd=None, effort="low"):
    """Run `claude -p` once, tool-less and structured. Returns
    {"verdict": "YES"|"NO"|None, "reason", "models", "seconds"} — `verdict=None` means the
    MODEL failed to answer in-schema (a fact about the answer, not cached, no breaker strike).
    Raises LLMUnavailable for infrastructure: CLI missing, non-zero exit (bad token, unknown
    flag, rate limit), `is_error` in the envelope (a keychain-less login exits 0!), timeout.

    No shell on any OS: `shutil.which` resolves claude.EXE / claude.cmd / the npm shim, and
    the schema and rules travel as argv elements verbatim (through cmd.exe they did not).
    `cwd` is never the repo: from the repo root every call read CLAUDE.md and the gitignored
    CLAUDE.local.md — 24,845 cache-creation tokens against 4,633 from a scratch directory."""
    exe = shutil.which("claude")
    if not exe:
        raise LLMUnavailable("cli-missing: claude is not on PATH", kind="missing")
    cmd = [exe, "-p", "--model", model, "--effort", effort, "--tools", "",
           "--no-session-persistence", "--output-format", "json",
           "--json-schema", schema, "--system-prompt", system]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              cwd=cwd or tempfile.gettempdir())
    except subprocess.TimeoutExpired:
        raise LLMUnavailable(f"timeout({timeout:g}s)", kind="transient")
    except Exception as e:  # noqa: BLE001 — spawn failure is infrastructure
        raise LLMUnavailable(_ascii(f"{type(e).__name__}: {e}"), kind="missing")
    # 2.1.241 exits 1 on a bad token with EMPTY stderr and the envelope on stdout
    # (`is_error`, `api_error_status: 401`, `result: "Failed to authenticate…"`): read the
    # envelope first, whatever the exit code, and classify on ITS words — never on a blob of
    # stdout, which on a good call is the model's reason, i.e. the posting's own text
    data = _envelope(proc.stdout)
    if data is not None and data.get("is_error"):
        status = data.get("api_error_status")
        msg = _ascii(data.get("result") or f"is_error (api_error_status={status})")
        kind = "auth" if status in (401, 403) else _kind(msg)
        raise LLMUnavailable(msg, kind=kind)
    if proc.returncode != 0:
        msg = _ascii(proc.stderr or (data or {}).get("result") or f"exit {proc.returncode}")
        raise LLMUnavailable(msg, kind=_kind(msg))
    if data is None:
        return {"verdict": None, "reason": "no JSON envelope", "models": [],
                "seconds": time.time() - t0}
    so = data.get("structured_output")
    if not isinstance(so, dict):          # a string payload, or the field gone: `result` holds it
        so = _envelope(so if isinstance(so, str) else "") or _envelope(str(data.get("result") or "")) or {}
    v = str(so.get("verdict") or "").strip().upper()
    usage = data.get("modelUsage") or {}
    # the CLI bills a haiku side-turn on every call; the model that ANSWERED is the one that
    # read the most input
    served = max(usage, key=lambda m: (usage[m] or {}).get("inputTokens") or 0) if usage else None
    return {"verdict": v if v in ("YES", "NO") else None,
            "reason": _ascii(so.get("reason") or "no structured verdict"),
            "models": [served] if served else [],
            "seconds": time.time() - t0}


