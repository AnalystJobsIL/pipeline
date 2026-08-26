"""The one `claude -p` seam (shared plumbing, ARCHITECTURE.md §7b).

`call()` runs the CLI once — tool-less, schema-constrained, no session, no shell, never from
the repo — and returns the model's answer, or raises `LLMUnavailable(kind)` for anything
that is infrastructure rather than opinion. `pipeline/seniority.py` is the first consumer;
`call_json()` (2026-08-25, `resolve_llm`) is the same invocation returning the structured
object itself, for callers whose schema is not a YES/NO verdict.
`call_meta()` (2026-08-26, `company-intel`) is the same invocation with the envelope's
audit read out -- which model actually answered, how long it took, and how many web
searches ran. `tools=` lets a caller grant the CLI's own tools, which is what let
`firmographics` migrate and close docs/BACKLOG.md 117: no bare `claude -p` is left.
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


def _tools(tools):
    """The `--tools` value: "" (all off -- the default, and the byte every tool-less caller
    has always built), a comma list, or "default". A sequence is joined."""
    return tools if isinstance(tools, str) else ",".join(str(t) for t in (tools or ()))


def _invoke(prompt, *, system, schema, model, timeout, cwd=None, effort="low", tools=""):
    """The one invocation. Returns (envelope, structured_output-or-None, seconds); raises
    LLMUnavailable for infrastructure. `call()` and `call_json()` are two readings of it.

    `tools` is BOTH the availability list (`--tools`) and the permission allowlist
    (`--allowedTools`), and they are ONE argument on purpose. They are different axes, and
    a caller that sets one and forgets the other fails SILENTLY: the model answers, in
    schema, having never searched. `cwd` is a scratch dir, so no project settings file
    grants anything -- the grant has to be argv. Default "" keeps every tool-less caller's
    argv byte-identical, which tests/test_units.py and tests/test_registry.py pin.

    No shell on any OS: `shutil.which` resolves claude.EXE / claude.cmd / the npm shim, and
    the schema and rules travel as argv elements verbatim (through cmd.exe they did not).
    `cwd` is never the repo: from the repo root every call read CLAUDE.md and the gitignored
    CLAUDE.local.md — 24,845 cache-creation tokens against 4,633 from a scratch directory."""
    exe = shutil.which("claude")
    if not exe:
        raise LLMUnavailable("cli-missing: claude is not on PATH", kind="missing")
    tl = _tools(tools)
    cmd = [exe, "-p", "--model", model, "--effort", effort, "--tools", tl,
           "--no-session-persistence", "--output-format", "json",
           "--json-schema", schema, "--system-prompt", system]
    if tl:
        cmd += ["--allowedTools", tl]
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
        return None, None, time.time() - t0
    so = data.get("structured_output")
    if not isinstance(so, dict):          # a string payload, or the field gone: `result` holds it
        so = _envelope(so if isinstance(so, str) else "") or _envelope(str(data.get("result") or "")) or {}
    return data, so, time.time() - t0


def _served(data, model=""):
    """The model that ANSWERED. The CLI bills a haiku side-turn on every call, and when a
    tool runs it is haiku that reads the results: on a WebSearch probe haiku showed 23,449
    input tokens against the answering sonnet's 6, so the old "most input tokens" rule
    named haiku on every tool-using call (docs/BACKLOG.md 207, the mail's `haiku x237`).
    Most OUTPUT tokens is no better -- haiku's search summaries beat the answer on one
    probe. Trust what we asked for when it is present; fall back to output tokens."""
    usage = (data or {}).get("modelUsage") or {}
    if not usage:
        return None
    want = str(model or "").strip().lower()
    if want:
        for m, u in usage.items():
            canon = str((u or {}).get("canonicalModel") or m).lower()
            if want == canon or want in canon or want == str(m).lower():
                return m
    return max(usage, key=lambda m: (usage[m] or {}).get("outputTokens") or 0)


def _searches(data):
    """How many web searches actually ran. NOT `usage.server_tool_use.web_search_requests`
    -- that counts the SERVER-side tool and reads 0 even when Claude Code's client-side
    WebSearch ran twice (measured 2026-08-26). The per-model counter is the real one, and
    it is what tells a researched fact from a parametric guess."""
    usage = (data or {}).get("modelUsage") or {}
    return sum((u or {}).get("webSearchRequests") or 0 for u in usage.values())


def call(prompt, *, system, schema, model, timeout, cwd=None, effort="low", tools=""):
    """Run `claude -p` once, tool-less and structured. Returns
    {"verdict": "YES"|"NO"|None, "reason", "models", "seconds"} — `verdict=None` means the
    MODEL failed to answer in-schema (a fact about the answer, not cached, no breaker strike).
    Raises LLMUnavailable for infrastructure: CLI missing, non-zero exit (bad token, unknown
    flag, rate limit), `is_error` in the envelope (a keychain-less login exits 0!), timeout."""
    data, so, secs = _invoke(prompt, system=system, schema=schema, model=model,
                             timeout=timeout, cwd=cwd, effort=effort, tools=tools)
    if data is None:
        return {"verdict": None, "reason": "no JSON envelope", "models": [], "seconds": secs}
    v = str(so.get("verdict") or "").strip().upper()
    served = _served(data, model)
    return {"verdict": v if v in ("YES", "NO") else None,
            "reason": _ascii(so.get("reason") or "no structured verdict"),
            "models": [served] if served else [],
            "seconds": secs}


def call_meta(prompt, *, system, schema, model, timeout, cwd=None, effort="low", tools=""):
    """`call_json()` with the envelope's audit read out:
    `{"data", "envelope", "models", "searches", "seconds"}`.

    `_invoke` always had the envelope and `call_json` threw it away, so a caller could not
    say which model answered, how long it took, or whether the web search ran at all --
    the three things that separate a researched fact from a confident guess. `data` is the
    structured output or None; the caller applies its OWN reading of `envelope["result"]`
    when it wants one (`firmographics` does: `_envelope` takes the FIRST object, and a
    restated escape hatch ahead of the real record would become a weekly strike)."""
    data, so, secs = _invoke(prompt, system=system, schema=schema, model=model,
                             timeout=timeout, cwd=cwd, effort=effort, tools=tools)
    served = _served(data, model)
    return {"data": so if isinstance(so, dict) and so else None, "envelope": data,
            "models": [served] if served else [], "searches": _searches(data),
            "seconds": secs}


def call_json(prompt, *, system, schema, model, timeout, cwd=None, effort="low", tools=""):
    """`call()` for a caller whose schema is an OBJECT rather than a verdict: the structured
    output as a dict, or None when the model produced none (infrastructure still raises
    LLMUnavailable). `resolve_llm` was the last bare `claude -p` (default model, every tool,
    `shell=True` on Windows, the repo as cwd, the answer regex-extracted from prose)."""
    return call_meta(prompt, system=system, schema=schema, model=model, timeout=timeout,
                     cwd=cwd, effort=effort, tools=tools)["data"]
