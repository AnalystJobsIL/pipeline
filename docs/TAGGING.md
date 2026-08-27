# Board tagging system

How every tag, badge and chart on the published board is computed, and which file to open to
change it. Everything is **deterministic** — regex lexicons and header rules over the stored
posting text, recomputed on every render. No LLM at render time, so a tag is reproducible and
free; the flip side is that a tag can be missing simply because the posting never said it, and
coverage is capped by how much description text the fetch layer stored.

Every number below was produced on 2026-08-25 by the command beside it; re-run it rather than
trust the line. `ARCHITECTURE.md §7d` is the model of the render layer this doc details.

## The four files (lane: `render`)

| file | owns | may import |
|---|---|---|
| `pipeline/roleprofile.py` | **the lexicon**: skills + clusters, role family, IC/lead track, years, degree, day-to-day task groups, AI usage, soft skills, per-board aggregation | stdlib |
| `pipeline/jdtext.py` | **the JD as text**: requirements / responsibilities sections as bullets with MUST/PLUS badges, the company one-liner, the location label, the seniority chip, posted-date labels | stdlib; `roleprofile` for two checks (a 3–7-character fragment that IS a skill; a two-word fragment that is a skill or a soft skill) |
| `pipeline/rolecard.py` | **the card**: one dict per role from a `matched` row (+ its ledger record), the stage labels, the blurb gate, the seniority canon (the classifier's vocabulary), the cross-card wrong-company checks | `jdtext`, `roleprofile`, `seniority`, `firmographics`, `company_info`, `roles` |
| `pipeline/digest.py` | **rendering only**: cards → the board, the archive, the email; every escape (the local `esc` closures, `_md_esc`, `_md_line`, `_md_blurb`, `_md_alarm`, `_safe_url`) | `rolecard`, `roleprofile`, `jdtext` (two helpers) |

Tags are **not persisted for rendering**: `cloud_state/roles.jsonl` carries a `tags` snapshot,
but that is the `roles` lane's column (`ARCHITECTURE.md §7c`); the board recomputes from the
text so a lexicon change shows on every card the same morning. What the ledger *does* give a
card: `also listed as` (the other registry rows that fetched the same posting), the re-post
dates, and — archive only — `closed on`.

## Skills

`roleprofile.SKILLS` — `(canonical name, category, regex)`; **98 entries**
(`python -c "from pipeline import roleprofile as r; print(len(r.SKILLS))"`). Patterns are
word-bounded and case-insensitive; risky short names (R, Excel, VBA, Java) carry context
guards; Hebrew transliterations where seen in the wild (טאבלו, פייתון, אקסל). `SKILL_DESC`
holds the tooltip for every skill — a test-free invariant checked by
`python -c "from pipeline import roleprofile as r; print([n for n,_,_ in r.SKILLS if n not in r.SKILL_DESC])"`
(`[]` on 2026-08-25). The board legend prints `len(SKILLS)` at render time, so it cannot
drift (it said "~55" until 2026-08-25).

Skills roll up into **five non-overlapping clusters** for the dashboard (`CLUSTERS`,
`_CAT2CLUSTER`, per-name overrides in `_NAME_CLUSTER`): SQL & Databases · ETL & Infrastructure
· Coding, ML & Statistics · Visualization & BI (which deliberately includes product
event-analytics platforms — GA4, Amplitude, Mixpanel, Pendo, Heap — because the market files
them with BI tools, decision 2026-08-21) · Other (ad platforms, MMPs, SEO, CRM, ERPs, work
tools). Languages (English) are tagged on cards but excluded from the charts.

## Requirements ("What you'll need")

`jdtext._requirements_snippet`: find a requirements **header** (`_REQ_HARD`, English + Hebrew
forms), reject a candidate whose following text opens with a responsibility verb ("…ad-hoc
requirements Develop dashboards…") or is the equal-opportunity footer ("…without regard to
race…" — added 2026-08-25, 0 of the 111 stored roles at that time changed), cut at the next section header
(`_SECTION_END`), split bullets (recovering lists whose `•` markers were lost in scraping:
`_RUNON_SPLIT`, `_DASH_SPLIT`), drop junk (`_BULLET_JUNK`: hashtags, links, "Apply now",
culture blurbs, "Send your CV to: …", an e-mail address, a LinkedIn footer's `רמת ותק`), cap at 12. A fragment of 3–7 characters survives only when it IS a lexicon skill ("Python", "Excel"); a two-word fragment starting with a capital is a decorative header unless it is a skill or a soft skill ("Team player"); a run-on is never split after Fluent / Native / Excellent / Good / Strong ("Fluent English" is one bullet) — measured on the store 2026-08-25: 8 of 108 cards changed, listed in `docs/sessions/2026-08-24-render.md`.

**MUST / PLUS badges** mirror the posting's own wording — leading or trailing "must /
mandatory / חובה" and "advantage / a plus / nice to have / יתרון" (`_req_badge`). A whole
"Advantages:" / "Bonus points:" sub-section auto-badges everything after it as PLUS
(`_PLUS_SECTION`). No badge means the posting didn't mark that line — absence is not signal.

Coverage on the committed store, **re-derived 2026-08-27** with the command beside it:
**118 of 135** roles have a requirements section, **97** a responsibilities section, **130** a
description longer than 200 characters. (It was 93/75/104 of 111 on 2026-08-25 - the
denominator moved, not the rule.)
(`python -c "import sqlite3;from pipeline import jdtext as j;c=sqlite3.connect('file:cloud_state/seen.db?mode=ro',uri=True);r=[d for (d,) in c.execute('select description from matched')];print(sum(1 for d in r if j._requirements_snippet(d)),sum(1 for d in r if j._responsibilities_snippet(d)),sum(1 for d in r if len(d or '')>200))"`).

## Day-to-day ("Responsibilities")

`jdtext._responsibilities_snippet` mirrors the requirements extractor for the
responsibilities section (`_RESP_HEAD`, `_RUNON_RESP`), up to 8 bullets. `roleprofile.TASK_GROUPS`
then classifies the bullets into **eight action-titled groups**, in tie-priority order (most
specific first): Instrument & manage tracking · Assure data quality · Run experiments & build
models · Define metrics & KPIs · Build pipelines & data models · Build dashboards & track
performance · Analyze & recommend · Partner & present. `TASK_DESC` holds the tooltips. When a
JD has no responsibilities section (prose-style), the pre-requirements text is split into
sentences and classified instead — chips without bullets (`rolecard._fill`).

**Single assignment** (2026-08-22 workshop, modeled bottom-up from the board's responsibility
bullets): `classify_bullet` gives every bullet exactly ONE group — most vocabulary hits wins,
ties go to the earlier group — so a bullet can never feed two clusters. **Chip rule**
(`classify_tasks`): a group earns its chip when it wins ≥2 bullets, or ≥25 % of a short list;
chips are ordered dominant-first. *(The per-group percentages the earlier version of this
page quoted — "Analyze 70 %, Partner 33 %…" — were from the 2026-08-22 board and were not
re-derived; `company_type_analysis.py` recomputes them over the current store.)*

Known residual seams, single-bullet ties left as-is: Airflow orchestration with
"alerting/SLAs" can land in Assure-data-quality instead of Pipelines; Hebrew ממשק can pull a
tool-building bullet into Partner & present.

## AI usage 🤖

`roleprofile.classify_ai` answers *what is the analyst expected to DO with AI*, not whether
the posting mentions AI:

1. Find AI mentions (`_AI_HIT`: LLM / GenAI / AI tools / ChatGPT / Copilot / Claude /
   prompt engineering…).
2. Skip mentions of the **company's product** (`_AI_PRODUCT`: "our AI agents", "AI-powered
   platform") — analysing an AI product is product analysis, not AI usage.
3. Judge the remaining mentions by the words inside the **same bullet** (window clipped at
   `•`) into `AI_USAGE`: **AI for efficiency** · **AI for automation** · **Building with AI**
   · **AI (unspecified)** (a real mention with no stated purpose). Three buckets plus the
   fallback; `AI_DESC` has the four tooltips.

**Requirement vs. day-to-day** — WHERE the mention sits decides what it means, and the card
keeps the two apart: in the requirements section it is *prior experience you must bring*
(chips in the requirements column, filter tokens suffixed `-req`, dashboard group "Required
coming in"); in the responsibilities section, or only in intro prose, it is *part of the job*
(day-to-day chips, plain tokens, dashboard group "In the day-to-day").

## Soft skills

`roleprofile.SOFT_SKILLS` — **nine** person-traits, tagged from the **requirements section
only**: Communication & storytelling · Team player · Ownership & independence · Business
acumen · Problem solving · Attention to detail · Curiosity & learning · Thrives in fast pace ·
Leadership & mentoring. Presence-based, English + Hebrew, `SOFT_DESC` for tooltips; dotted
chips under the requirements column, single-word filter tokens (`ownership`, `curiosity`,
`fastpaced`…), a purple chart on the dashboard.

## Other markers

- **Years** — `roleprofile._YEARS_EXP`: the first plausible (1–15) number adjacent to
  "experience" / ניסיון; שנתיים → 2.
- **Degree** — `roleprofile._degree`: level (BSc/MSc/PhD), up to three fields, and
  required-vs-plus judged only inside the degree's own clause, so "BSc required (MSc an
  advantage)" stays a required BSc.
- **Seniority chip** — `jdtext._seniority_chip` reads the posting's own "Experience level:"
  or "N+ years"; `rolecard.sen_canon` collapses it with the title to Junior / Mid / Senior /
  Lead+ using the **classifier's** regexes (`seniority._SENIOR`, `_JUNIOR`, `_HEBREW_SENIOR`)
  and the lexicon's `roleprofile._LEAD` — one vocabulary, not three copies (2026-08-25: two
  "… Analytics Lead" titles moved from Senior to Lead+; a Hebrew בכיר title now reads Senior,
  pinned by test — no stored role has a Hebrew title yet).
  The stored `matched.seniority` column is empty for all 135 rows and is not read (re-derived
  2026-08-27: `select count(*) from matched where coalesce(seniority,'')<>''` returns 0).
- **Location** — `jdtext._norm_location`: one label per place from `_LOC_GROUPS` (every
  spelling `israel.py` recognises, Latin and Hebrew; pinned by
  `test_every_place_israel_py_recognises_renders_as_one_label`), regions only when no city is
  named ("Central Israel", "Tel Aviv area"), a city glued into a scraped string still found
  ("On Site - Kiryat Gat" → Kiryat Gat), an unknown town kept as written.
- **Role family / track** — `roleprofile._FAMILIES`, `_LEAD`; used for search, not displayed.
- **reposted** — `posted_date` ≥ 3 days after `first_seen` (`rolecard.REPOST_DAYS`, the same
  rule `roles.py` records); when the ledger record is present its `reposts` dates are shown.
  **new** = first seen within the last day and not a repost.
- **also listed as** — the ledger's `attribution.claimed_by` (or this morning's
  `_claimed_by`): the other registry rows that fetched the same posting. Shown on the card,
  in the archive, and in the email heading; the name is searchable.
- **closed on** — archive cards only, from the ledger's `closed_on`.
- **Employment badge** — Maternity cover / Temp / Contract / Intern / Part-time from the title.
- **Company facts chips** — `rolecard.firmo_facts`: sector · stage (every `firmographics.STAGES`
  value has a label — pinned by test; `private-enterprise` rendered raw until 2026-08-25) ·
  ~employees · founded · Israel centre.

## What the mail says about rendering

`- **Render:** board N cards[, M degraded (why)][, K hidden: mangled title][, shared-board A/B][, title-twin A/B…]
· archive N cards[…] · email N cards[…]` in every run audit; degraded, hidden, shared-board, title-twin
and FAILED cases also stand above the fold under **Needs a look** and print `::warning::render …`
in the step log. `ARCHITECTURE.md §7d` has the grammar and what each case means.

## Where users see it

Tooltips on every tag/bar explain meaning; the board carries a collapsible "How the tags on
this board are computed" legend generated from `TASK_DESC` / `AI_DESC` / `CLUSTERS` /
`len(SKILLS)` at render time, so it cannot drift from the code.
