"""A fake `claude` for company-intel rehearsals. Emits a real CLI result envelope.

WHY THIS REPLACED THE .cmd ONE-LINER (2026-08-26). The old shim told a research call from a
blurb call by looking for the literal string `allowedTools` in its argv, with a `||`
fall-through to the blurb branch. When the seam moved onto `pipeline/llm.py` that predicate
became a coin flip, and the fall-through meant EVERY call would have been answered with a
blurb: every research call would have read as a name failure, the driver would have printed
a plausible `0 researched, 2 failed`, and it exits 0 regardless. A rehearsal that cannot
fail is not a rehearsal.

So: dispatch on the SCHEMA's `required` key-set -- a value the production call cannot stop
sending -- and have NO default branch. An argv this shim cannot classify writes to stderr
and exits 3, which `llm._invoke` turns into `LLMUnavailable`, which the mail reports as
`claude unavailable`. Loud, in the artefact you are already reading.

FAKE_CLAUDE = json | unknown | prose | fail | sleep | is_error | no_structured |
              unknown_flag | no_search | empty_schema
FAKE_CLAUDE_LOG = a path; one JSON line per call: {mode, kind, argv, cwd, stdin_len}
"""
import json
import os
import sys

REC = {"known": True, "sector": "fintech", "sub_sector": "fake niche",
       "stage": "growth-private", "stage_note": "fake", "size_band": "S",
       "employees_global": 42, "founded": 2015, "business_model": "fake SaaS subscriptions",
       "customer_type": "SMBs", "il_center": "Tel Aviv (HQ)"}
BLURB = {"known": True, "blurb": "FakeCo builds fake things for fake customers. "
                                 "It makes money from fake subscriptions."}
EMPLOYEES = {"employees": 42, "is_estimate": False, "source": "fake source (2026)"}

ANSWERS = {
    frozenset(REC): ("research", REC),
    frozenset(BLURB): ("blurb", BLURB),
    frozenset(EMPLOYEES): ("employees", EMPLOYEES),
}


def classify(argv):
    """research | blurb | employees, from the REAL argv. Never guesses."""
    if "--json-schema" not in argv:
        return "unknown", None
    try:
        req = frozenset(json.loads(argv[argv.index("--json-schema") + 1]).get("required") or ())
    except Exception:                                          # noqa: BLE001
        return "unknown", None
    return ANSWERS.get(req, ("unknown", None))


def envelope(payload, *, mode, searches=1, model="claude-sonnet-5", is_error=False,
             result=None):
    return {
        "type": "result", "subtype": "success", "is_error": is_error,
        "num_turns": 2 + (1 if searches else 0),
        "result": result if result is not None else json.dumps(payload),
        "structured_output": payload,
        "total_cost_usd": 0.01,
        "usage": {"server_tool_use": {"web_search_requests": 0}},   # the WRONG counter, on purpose
        "modelUsage": {model: {"inputTokens": 10, "outputTokens": 20,
                               "canonicalModel": model.replace("claude-", "").rsplit("-", 1)[0],
                               "webSearchRequests": searches}},
    }


def main():
    argv = sys.argv[1:]
    mode = os.environ.get("FAKE_CLAUDE", "json") or "json"
    kind, payload = classify(argv)
    log = os.environ.get("FAKE_CLAUDE_LOG")
    stdin = sys.stdin.read() if not sys.stdin.isatty() else ""
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"mode": mode, "kind": kind, "argv": argv,
                                "cwd": os.getcwd(), "stdin_len": len(stdin)}) + "\n")

    if mode == "fail":
        sys.stderr.write("Not logged in . Please run /login\n")
        return 1
    if mode == "unknown_flag":
        sys.stderr.write("error: unknown option '--tools'\n")
        return 1
    if mode == "sleep":
        import time
        time.sleep(400)
        return 0
    if mode == "is_error":                       # exit 0 with an error envelope: the real
        print(json.dumps({"type": "result", "is_error": True,   # 2.1.241 keychain-less shape
                          "api_error_status": 401,
                          "result": "Failed to authenticate. API Error: 401"}))
        return 0

    if kind == "unknown":
        sys.stderr.write(
            "FAKE CLAUDE: cannot classify this argv. The seam's schema changed and this shim\n"
            "would have had to GUESS -- which is the 2026-08-26 defect it exists to prevent.\n"
            f"argv={argv!r}\n")
        return 3

    if mode == "unknown":
        payload = {"known": False, "blurb": ""} if kind == "blurb" else {"unknown": True}
    elif mode == "prose":
        print(json.dumps(envelope(None, mode=mode, result="I'm not sure which company you "
                                  "mean, but {something} might match.")))
        return 0
    elif mode == "empty_schema" and kind == "research":
        payload = {k: ("" if isinstance(v, str) else None) for k, v in REC.items()}
        payload["known"] = True
    elif mode == "no_structured":
        env = envelope(payload, mode=mode)
        env["structured_output"] = None
        print(json.dumps(env))
        return 0

    searches = 0 if mode == "no_search" else (1 if kind != "blurb" else 0)
    print(json.dumps(envelope(payload, mode=mode, searches=searches)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
