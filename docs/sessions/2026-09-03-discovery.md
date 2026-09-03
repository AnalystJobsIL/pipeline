# 2026-09-03 — description-term discovery queries, measured

*lane: `discovery`. Section: `ARCHITECTURE.md` §1a. Worktree `discovery-2026-09-03`, cut from
`origin/master` `5ad8a1d`. The operator's question: "Is there any way to expand discovery to
look for roles that look for analyst but with different names? for example look for
descriptions with insights or recommendations or analyze as options for LLM classification?"*

## 0. The query set, frozen BEFORE the first fetch

Written here first so the set cannot be tuned to its own results. Six description-term probes
and two controls. **No booleans** — the result pool is per QUERY (`discovery_daily.py:63-65`:
one combined `OR` bought 10 new companies against 76 from nine flat queries).

| # | query | lang | why it is not already covered by the nine title keywords |
|---|---|---|---|
| D1 | `SQL Tableau` | en | the two-tool signature of an analyst JD; neither word is ever an analyst title |
| D2 | `Power BI dashboards` | en | `BI developer` is a title query; `dashboards` is description-only |
| D3 | `SQL insights` | en | the operator's own word, paired with the tool that makes it the job |
| D4 | `A/B testing metrics` | en | the product/growth-analyst signature, title-free |
| D5 | `SQL נתונים` | he | Hebrew postings write the tool in Latin; `נתונים` reaches JDs `אנליסט` misses |
| D6 | `תובנות עסקיות` | he | "business insights" — the Hebrew of the operator's ask |
| C1 | `data analyst` | en | **control** — an existing keyword, same session, to prove the harness matches production and fix the baseline overlap |
| C2 | `insights analyst` | en | **negative control** — dropped 2026-08-23 as saturated (`+0` employers, `discovery_daily.py:61`) |

The existing set it must not duplicate (`discovery_daily.py:66-68`, `:96-97`):
`data analyst · business intelligence · product analyst · BI developer · analytics ·
data scientist · אנליסט · growth analyst · marketing analyst` (LinkedIn, × Israel + Be'er Sheva
+ Haifa = 27 queries) and `data analyst · business intelligence · BI developer ·
product analyst · אנליסט` (Indeed, 5 queries).

## 1. Denominators, re-derived at `5ad8a1d` before the walk

```
discovered_cache.json      2,521 cards   (1,026 distinct employers)
research_companies.json      471 names
companies.csv              2,162 rows    (1,195 active)
Bright Data pool           1,346 / 5,000 credits month-to-date (27%)
```

## 2. Declared spend

- Bright Data: hard cap 40 (`BD_RUN_CAP=40`). LinkedIn half is keyless and costs 0.
- LLM: ≤30 `claude -p` calls, from a scratch `cwd`.
- SerpApi: 0 (dead).

## 3. What was run, in order

All four phases are re-runnable. Phases A-C need no credentials at all; only phase D does.

```bash
# A -- the keyless walk. 0 credits: pages=0 makes the paid fallback unreachable, and the
#      worktree has no secrets.env, so a paid rung could not fire even if asked.
#      LINKEDIN_GUEST_PAGES=15 caps every query at 150 cards, probes and controls alike.
python - <<'PY'
import os, sys
os.environ["LINKEDIN_GUEST_PAGES"] = "15"; os.environ["BD_RUN_CAP"] = "0"
os.environ.pop("BRIGHTDATA_API_KEY", None)
sys.path.insert(0, ".")
import discovery_daily as dd
cards = dd.linkedin_search("SQL Tableau", pages=0, days=7, location="Israel")
print(len(cards), dict(dd.SOURCE_PATH), dict(dd.UNLOCKER_CALLS))   # UNLOCKER_CALLS stays {}
PY

# B -- descriptions for the frontier, through production's own fetcher, still 0 credits
#      (`bd=None` means the Bright Data rung is never reached).
#   jdfill.fetch_jd(url, bd=None, company=..., title=...)  -> 129 usable of 133

# C -- the counterfactual, 30 calls. REUSED, not rewritten: measure_title_gate.judge already
#      sends seniority._posting(job) under _rules() at LLM_MODEL from a scratch cwd.
#   from tools.measure_title_gate import judge; judge(job, seniority.LLM_MODEL, 90)

# D -- Indeed, the only paid half. From the SHARED CHECKOUT: a worktree has no credentials
#      and a disarmed rung returns a convincing mass-zero (57/57 false "dead", 2026-08-28).
BD_RUN_CAP=3 python -c "import discovery_daily as d; d._load_secrets(); print(d.indeed_search('SQL Tableau', tries=1))"
```

**Spend, actual:** 4 Bright Data credits (`[bd-spend] this step bought 3 ... of a 3 cap`, then
`1 ... of a 1 cap`), 30 `claude -p` calls under contract `v3.0f84ab84`, model `sonnet`. Both
paid runs appended their line to the shared checkout's `cloud_state/bd_spend.jsonl` by design
(`bd_rescue.py:146-160`); this session staged nothing there.

## 4. The mass-zero tripwire, and why the numbers are believable

The address LinkedIn answers from is throttled — the 2026-08-26 dry run got 18 blocked and 41
blank of 152 fetches. Today it did not: `SOURCE_PATH` over round 1 read
`linkedin_free 112 · linkedin_blank 28 · linkedin_blank_recovered 13`, **zero blocked**, and
`UNLOCKER_CALLS {}`. The control is what makes that checkable rather than hopeful: **`C1 data
analyst` returned 129 cards and `C2 insights analyst` 132**, so a probe returning few new
employers is a measurement and not a blocked walk. Every query stopped on the 15-page cap, so
**every count in the decision record is a FLOOR**.

## 5. The 53 new employers, and the role that surfaced each

This is the table the decision turns on: **0 of 53** was surfaced by a posting the classifier
reads as analyst-shaped (41 `none`, 12 `excluded`). Listed in full so the next reader can
check every call rather than trust the summary.

| probe | employer | gate verdict | the posting that surfaced it |
|---|---|---|---|
| D1 | Applause | `none` | Solution Delivery Manager |
| D1 | Cloudera | `none` | Sales Account Manager |
| D1 | Comet | `excluded` | Full Stack Engineer |
| D1 | PayPlus - The Future of Payments & Commerce | `excluded` | QA Engineer |
| D1 | Planview | `none` | Database Operations Engineer |
| D1 | UNIT AI | `excluded` | Experienced BackEnd Engineer |
| D2 | Dematic | `excluded` | Senior Project Manager (m/f/d) |
| D2 | Hozek Technologies Ltd. | `none` | Senior Microsoft Cloud & Security Architect (Power Platform, Copilot, Intune, M365 Security) |
| D2 | iTalent - Hire Smarter | `none` | Procurement Specialist |
| D2 | Nalco Water, An Ecolab Company | `none` | Co-Op Student |
| D2 | Strauss Group | `none` | Information Technology Specialist |
| D2 | The Center for Educational Technology (CET) | `none` | Lead Designer |
| D2 | WAXMAN GROUP | `none` | BIM Manager |
| D2 | יו-מאן בע"מ | `none` | Information System Manager |
| D3 | Fluent Trade Technologies | `none` | MySQL DBA |
| D4 | Xpend | `excluded` | Full Stack Software Engineer (AI Automation) |
| D5 | Accenture España | `none` | Penetration Tester |
| D5 | Crusoe | `excluded` | Senior Cloud Support Engineer |
| D5 | Equashield Israel | `excluded` | Full Stack Engineer |
| D5 | Grubhub | `excluded` | Senior Software Engineer (Backend) |
| D5 | MedDev Soft | `none` | מהנדס/ת תוכנה Senior לצוות הפיתוח |
| D5 | Rylo | `excluded` | Senior Software Engineer, Backend Team |
| D5 | TSG | `excluded` | Backend Developer - 2117 |
| D6 | Anomity | `none` | Head of Sales, Founding Team | Agentic AI Security |
| D6 | Barnes Israel | `none` | Luxury sales consultant |
| D6 | COSENTINO | `none` | Accounting Supervisor |
| D6 | eOS (esh Group) | `none` | מנהל/ת חשבונות ראשי/ת |
| D6 | HUNTHEAD | `none` | עוזר/ת חשב/ת |
| D6 | Neema - Better Than a Bank | `none` | Assistant Controller |
| D6 | Nicklas LTD | `none` | Sales Manager |
| D6 | Philip Morris International | `none` | ITP Manager |
| D6 | Snatch UP Jobs | `none` | Account Executive |
| D6 | Superkit | `none` | Bookkeeper |
| D6 | TASC Consulting & Capital | `none` | Senior Org & Op Excellence Consultant | Financial Services |
| D6 | TikTok | `none` | Business Partnerships Lead (Gaming) - Israel |
| D6 | Undisclosed | `none` | Sales Manager Israel (Cyber) |
| E1 | Botanica Software Labs | `none` | Security Researcher and Engineer |
| E1 | Child2Parent | `none` | Postdoctoral Researcher |
| E1 | HomeLend | `excluded` | Senior Fullstack Developer |
| E3 | HUMAN | `none` | UX/UI Designer |
| E3 | Wizedom | `none` | VP Marketing – Next-Generation Computing - HPC |
| E4 | Discreet Company | `none` | Quality Manager - Manufacturing |
| E4 | MAGNUS International Search and Rescue | `none` | דסקאי/דסקאית במחלקה המבצעית של MAGNUS |
| E4 | Phibro Middle East & Europe | `none` | Director of Quality Assurance |
| E4 | Radio-Canada | `none` | Video Producer, World News, Jerusalem (English Services) |
| E4 | Rail Vision Ltd | `none` | Global Sales Director |
| E4 | State Comptroller and Ombudsman of Israel - משרד מבקר המדינה ונציב תלונות הציבור | `excluded` | Head of Infrastructure |
| E4 | SuperCom (NASDAQ: SPCB) | `none` | Junior Product Designer |
| E4 | TMF Group | `none` | Junior Bookkepper |
| E4 | TransIsrael - חוצה ישראל | `none` | מנהל/ת תחום תכנון בחטיבת הנדסה ופיתוח |
| E4 | Turpaz Industries Ltd. | `none` | Office Coordinator |
| E4 | US Foods | `none` | Territory Manager - Metro Chicago |
| E4 | V2X Inc | `none` | Plumber Lead |

**Noise, by hand-read: 15 of 53 (28 %)** — statistically the queue's existing 27 %. Agency-
shaped: `HUNTHEAD`, `Snatch UP Jobs`, `iTalent - Hire Smarter`, `TASC Consulting & Capital`,
`יו-מאן בע"מ`. Placeholder, not an employer: `Undisclosed`, `Discreet Company`. Wrong entity or
wrong country: `Accenture España`, `US Foods` (a Metro Chicago territory role), `Radio-Canada`,
`V2X Inc`, `Phibro Middle East & Europe`, `COSENTINO`. A division rather than an employer:
`Nalco Water, An Ecolab Company`, `eOS (esh Group)`.

**One name that was nearly filed wrongly, kept here as the lesson:**
`MAGNUS International Search and Rescue` reads as a recruiter for its first three words and is
a search-and-RESCUE organisation. It was on the filed agency list until the exact string was
printed rather than the 30-character truncation. Print the whole name before writing it into a
document.

## 6. Traps this session hit

- **The heredoc ate two backslashes, again.** Writing `` inside a `<<'PYEOF'` heredoc put a
  literal BACKSPACE (0x08) into `pipeline/recruiters.py`, so `_ANON_ANY` compiled to a regex
  with no word boundaries and every name returned `False` — a gate that silently refuses
  nothing. `od -c` is what found it. The same file already carried **two more** backspaces in
  a comment from an earlier session (`staffing`, line 61), repaired in this commit;
  `tests/test_units.py` carries seven more, in other lanes' docstrings, left alone.
  Build regex source with `chr(92)` or the Edit tool, never a heredoc.
- **A long heredoc failed to parse entirely** (`unexpected EOF while looking for matching`),
  losing a 140-line document. Write documents with the file tool.
- **`open(path, "w")` truncated a tracked file before the read that was meant to feed it.**
  `io.open(a, "w").write(io.open(a).read().rstrip() + row)` evaluates the OUTER open first,
  so the inner read returned `""` and `docs/morning-checks.md` went from **137 lines to 2** —
  58 archived predictions deleted, silently, exit 0. Nothing in the diff looked wrong; the
  only reason it was caught is `check_morning_rows_survive`, which noticed a row that was "in
  neither HANDOFF.md nor docs/morning-checks.md" and named it. **Read the whole file into a
  variable on its own line, then open for write** — the same shape as intake rule 5
  (`ARCHITECTURE.md` §1a), which exists because a truncating write replaced 1,606 queued
  names. Recovered with `git checkout HEAD -- docs/morning-checks.md`.
- **`tools/mutate.py` runs against `git archive HEAD`**, so the mutation catalogue must be
  committed before it can see a new record.
- **The per-query counts are not a distinct set.** Summing the `marginal_new_employers`
  columns gives 56; the union across both rounds is **53** (`Accenture España`,
  `Strauss Group`, `Superkit` are marginal in both, because each round's accumulator starts
  empty). The first draft of the decision record carried 56 as a distinct count.
