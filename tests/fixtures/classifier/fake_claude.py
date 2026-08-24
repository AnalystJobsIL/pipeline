"""Fake `claude` for classifier rehearsals and tests (both OSes call this through the
`claude` / `claude.cmd` shims beside it). FAKE_CLAUDE = mode:

  yes | no            answer in-schema (default: yes for titles containing 'analyst', else no)
  all_no | all_yes    every posting the same way (a quarantine morning)
  is_error            exit 0, envelope {"is_error": true, "result": "Not logged in ..."}
  no_structured       exit 0, envelope without structured_output
  prose_before_json   an update notice printed before the envelope
  unknown_flag        exit 1, "error: unknown option '--json-schema'"
  fail                exit 1, "Failed to authenticate. API Error: 401 OAuth access token is invalid."
  rate_limit          exit 1, "API Error: 429 rate limit exceeded"
  sleep               answers after FAKE_CLAUDE_SLEEP seconds (default 6; the caller's timeout fires first)
  flaky               every third call fails with a 529, the rest answer

Every call appends `mode argv cwd stdin_len` to FAKE_CLAUDE_LOG when set."""
import json, os, sys, time

mode = os.environ.get("FAKE_CLAUDE", "yes")
stdin = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"mode": mode, "argv": sys.argv[1:], "cwd": os.getcwd(),
                            "stdin_len": len(stdin)}, ensure_ascii=False) + "\n")
counter = os.environ.get("FAKE_CLAUDE_COUNTER")
n = 0
if counter:
    try:
        n = int(open(counter).read() or 0)
    except Exception:
        n = 0
    open(counter, "w").write(str(n + 1))


def envelope(verdict, reason="fake reason", model="claude-sonnet-5"):
    return json.dumps({"type": "result", "is_error": False, "num_turns": 1,
                       "result": json.dumps({"verdict": verdict, "reason": reason}),
                       "structured_output": {"verdict": verdict, "reason": reason},
                       "modelUsage": {model: {"inputTokens": 900}}})


title = ""
for line in stdin.splitlines():
    if line.lower().startswith("job title:"):
        title = line.split(":", 1)[1].strip().lower()
default = "YES" if "analyst" in title else "NO"

if mode == "fail":
    sys.stderr.write("Failed to authenticate. API Error: 401 OAuth access token is invalid.\n"); sys.exit(1)
if mode == "rate_limit":
    sys.stderr.write("API Error: 429 rate limit exceeded\n"); sys.exit(1)
if mode == "unknown_flag":
    sys.stderr.write("error: unknown option '--json-schema'\n"); sys.exit(1)
if mode == "sleep":
    # bounded: on Windows the caller's timeout kills claude.cmd but not this grandchild, and
    # the pipes stay open until it exits (the accepted Windows caveat, ARCHITECTURE §7b)
    time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "6"))); print(envelope("YES")); sys.exit(0)
if mode == "is_error":
    print(json.dumps({"type": "result", "is_error": True, "result": "Not logged in · Please run /login",
                      "structured_output": None, "modelUsage": {}})); sys.exit(0)
if mode == "no_structured":
    print(json.dumps({"type": "result", "is_error": False, "result": "I think YES",
                      "modelUsage": {"claude-sonnet-5": {}}})); sys.exit(0)
if mode == "prose_before_json":
    print("Update available: 9.9.9 -> run npm i -g @anthropic-ai/claude-code")
    print(envelope(default)); sys.exit(0)
if mode == "flaky" and n % 3 == 2:
    sys.stderr.write("API Error: 529 overloaded\n"); sys.exit(1)
if mode == "all_no":
    print(envelope("NO")); sys.exit(0)
if mode == "all_yes":
    print(envelope("YES")); sys.exit(0)
if mode == "no":
    print(envelope("NO")); sys.exit(0)
print(envelope(default if mode in ("yes", "flaky") else "YES"))
