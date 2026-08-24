"""Per-company structured firmographics: sector, stage, size, business model.

The structured sibling of company_info.py's prose blurb. Generated once per company
via `claude -p` (with web search allowed so headcount/stage are current, not
training-data stale) and cached in the store, so the daily run only pays for
companies it has never seen. Powers company-type <-> requirement-type analysis.

Record shape (all researched fields; code stamps as_of):
    {
      "sector":            str,   # e.g. "cybersecurity", "fintech", "healthtech"
      "sub_sector":        str,   # free-text niche
      "stage":             str,   # public | acquired-by-bigtech | growth-private | early-private
      "stage_note":        str,   # e.g. "NASDAQ: MNDY" / "acquired by Xero 2025"
      "size_band":         str,   # S (<200) | M (200-1000) | L (1000-5000) | XL (>5000)
      "employees_global":  int|None,
      "founded":           int|None,
      "business_model":    str,   # how it earns money
      "customer_type":     str,   # who buys: enterprises | SMBs | consumers | hospitals | ...
      "il_center":         str,   # main Israel site(s)
      "as_of":             "YYYY-MM-DD"  (stamped by us, not the model)
    }
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import sys

# "growth-private" means venture/growth-STAGE — Bosch and EY are private but not that;
# without "private-enterprise" the by_stage axis folds century-old giants into startup stats
STAGES = {"public", "acquired-by-bigtech", "growth-private", "early-private", "private-enterprise"}
SIZE_BANDS = {"S", "M", "L", "XL"}

_BAND_CAPS = [(200, "S"), (1000, "M"), (5000, "L"), (10 ** 9, "XL")]


def band_for(n):
    """Canonical employee-count -> size_band mapping. Any code that writes
    employees_global MUST re-derive size_band with this, or the two contradict."""
    return next(b for cap, b in _BAND_CAPS if n < cap)


class ResearchUnavailable(Exception):
    """The research INFRASTRUCTURE failed (claude CLI missing/logged out, timeout,
    network) — says nothing about the company name. Callers must NOT record a
    per-name failure for this; a whole cohort would be gated by one outage."""


# Discovery sometimes leaks job TITLES as company names ("Sql developer - X", "my team").
# Researching those profiles the embedded company under the junk key (duplicate identity)
# or hallucinates a match — so callers pre-filter with this and never spend a call.
_JUNK_NAME = re.compile(
    r"(?i)\b(developer|engineer(ing)?|scientist|researcher|analyst|architect|designer|"
    r"manager|lead|specialist|consultant|intern|student|qa|devops|full[- ]?stack|"
    r"back[- ]?end|front[- ]?end)\b.*([-–—@]|\bat\b)"   # role word + separator = title leak
    r"|^(my team|our team|the team)$")


# bare category/tech names leaked as "companies". These are the WORST junk class: they
# collide with real companies ("AppSec" confidently profiled as AppSec Labs, a random
# 15-person consultancy) and cache as successes nothing ever revisits. Exact-match only.
CATEGORY_NAMES = {"appsec", "devops", "devsecops", "data", "security", "cyber", "qa",
                  "fintech", "hr", "it", "ai", "ml", "cloud", "digital", "r&d", "backend",
                  "frontend", "fullstack", "mobile", "web"}


def looks_like_junk(name):
    """True when a 'company name' is really a leaked job title / category / team phrase."""
    n = " ".join(str(name or "").lower().split())
    return n in CATEGORY_NAMES or bool(_JUNK_NAME.search(name or ""))


# ---- firmographics identity -------------------------------------------------------- #
# store._norm_company strips ONE trailing suffix, which is too weak here: "Check Point
# Software Technologies" and "Check Point Software" normalize to two DIFFERENT keys and
# get researched (and employee-filled) twice. This key strips suffixes repeatedly, folds
# "X Israel" site-forms into X, and applies a small alias map. Used ONLY by firmographics
# targeting/gating/joins — digest dedup semantics are untouched.
_ID_SUFFIX = re.compile(
    r"\s+(ltd|inc|llc|corp|corporation|co|gmbh|group|technologies|technology|software|"
    r"labs|solutions|systems|israel|global)$")

ALIASES = {  # spelling/brand forms the suffix rules can't derive; grow as found
    "aws": "amazon", "amazon web services": "amazon",
    "jpmorganchase": "jpmorgan chase",
    "aqurate data": "aqurate",
    "cadence design": "cadence",  # "Cadence Design Systems" after suffix stripping
    # acquirer/brand annotations in parens keep their token (so divisions stay distinct);
    # these known annotation forms still fold to the base identity
    "habana labs intel": "habana",  # alias VALUES must be post-suffix-strip forms
    "vmware broadcom": "vmware",
    "simply joytunes": "simply",
    "merck msd": "merck",
}


# parenthetical content is DISTINGUISHING ("Sony (PlayStation)" vs "Sony (Semiconductor)")
# unless it's an annotation — dropping all parens made two Sony divisions one identity,
# and targeting would then have researched only whichever surfaced first, forever
_PAREN_NOISE = re.compile(r"(?i)^\s*(formerly|now|part of|acquired|previously|by |a |an )")


def is_division_name(name):
    """True when the name carries a DISTINGUISHING parenthetical ("Sony (PlayStation)").

    Division records must never strong-match the parent company's LinkedIn page — the
    parent's global headcount would fill in as a confident, never-re-verified count."""
    return any(not _PAREN_NOISE.match(m.group(1))
               for m in re.finditer(r"\(([^)]*)\)", str(name or "")))


def identity_key(name):
    def _paren(m):
        inner = m.group(1)
        return " " if _PAREN_NOISE.match(inner) else f" {inner} "
    s = re.sub(r"\(([^)]*)\)", _paren, str(name or "")).lower()
    s = " ".join(re.sub(r"[^0-9a-z֐-׿]+", " ", s).split())
    prev = None
    while s != prev:
        prev = s
        s = _ID_SUFFIX.sub("", s).strip()
    return ALIASES.get(s, s)


def _is_windows():
    import os
    return os.name == "nt"


_PROMPT = (
    "Research the company \"{company}\" (an Israeli high-tech company or a multinational "
    "with an Israeli R&D site) and output ONLY a JSON object — no prose, no markdown fence — "
    "with exactly these keys:\n"
    '  "sector": short primary field, e.g. "cybersecurity", "fintech", "healthtech", '
    '"SaaS / productivity", "automotive / semiconductors"\n'
    '  "sub_sector": one-line niche description\n'
    '  "stage": exactly one of "public", "acquired-by-bigtech", "growth-private", '
    '"early-private", "private-enterprise". The growth-vs-enterprise test is the FUNDING '
    "MODEL, never size or age: any venture/growth-equity-backed private company is "
    '"growth-private" even at $100B (OpenAI, Stripe are growth-private); '
    '"private-enterprise" is ONLY for non-venture private ownership — family, partner, '
    "PE-buyout, cooperative, state (Bosch, EY, a bank)\n"
    '  "stage_note": one line of evidence (ticker / acquirer+year / last round+valuation)\n'
    '  "size_band": "S" (<200 employees), "M" (200-1000), "L" (1000-5000), "XL" (>5000) — global\n'
    '  "employees_global": integer or null if unknown\n'
    '  "founded": 4-digit year the company was founded; if no founding year is published, use the '
    "official incorporation/registration year as a proxy (Israeli Companies Registrar, state "
    "registries, SEC filings); null only if neither is findable\n"
    '  "business_model": one line on how it earns money\n'
    '  "customer_type": who buys it, e.g. "enterprises", "SMBs", "consumers", "hospitals", "automakers"\n'
    '  "il_center": main Israel site(s), e.g. "Tel Aviv (HQ)" or "Haifa (R&D); HQ in US"\n'
    "Use web search if available to get CURRENT facts (headcount, acquisitions, funding); "
    "prefer recent numbers and never invent them — use null over a guess. "
    "If you cannot identify the company at all, output exactly {{\"unknown\": true}}. "
    "IMPORTANT: if the given string is not itself a company name (a job title, a team, a "
    "category, a phrase), also output {{\"unknown\": true}} — never profile a company that "
    "is merely mentioned INSIDE the string.\n\n"
    "Context from one of its job posts (may help, may be empty): {context}\n"
)


def _coerce(rec, company):
    """Validate/clean a parsed record; return the clean dict or None if junk."""
    if not isinstance(rec, dict) or rec.get("unknown"):
        return None
    out = {}
    for key in ("sector", "sub_sector", "stage_note", "business_model", "customer_type", "il_center"):
        v = rec.get(key)
        out[key] = " ".join(str(v).split())[:300] if isinstance(v, str) and v.strip() else ""
    if not out["sector"]:                       # sector is the one field we insist on
        return None
    stage = str(rec.get("stage", "")).strip().lower()
    out["stage"] = stage if stage in STAGES else ""
    band = str(rec.get("size_band", "")).strip().upper()
    out["size_band"] = band if band in SIZE_BANDS else ""
    emp = rec.get("employees_global")
    out["employees_global"] = int(emp) if isinstance(emp, (int, float)) and 1 <= emp <= 5_000_000 else None
    if out["employees_global"]:
        # the invariant: a written count always re-derives the band — the model may pair a
        # training-data-stale band with a freshly searched count
        out["size_band"] = band_for(out["employees_global"])
    yr = rec.get("founded")
    # lower bound 1600, not 1900 — the list holds multinationals like Barclays (1690),
    # Merck (1668), Pfizer (1849); a too-tight clamp silently nulled all of them
    out["founded"] = int(yr) if isinstance(yr, (int, float)) and 1600 <= yr <= _dt.date.today().year else None
    out["as_of"] = _dt.date.today().isoformat()
    return out


# ---- the one `claude -p` seam ------------------------------------------------------ #
# Three callers used to spawn the CLI themselves (one of them with shell=True on every
# platform, which on Linux runs a bare `claude` with no arguments). One function, one
# platform rule, one failure contract: infrastructure trouble RAISES, a bad answer returns.

def _claude(prompt, *, tools=(), timeout=240):
    """Run `claude -p` once and return its stdout. Raises ResearchUnavailable when the CLI is
    missing, times out, or exits non-zero (logged out, rate-limited, 529) — never for what
    the model said."""
    cmd = ["claude", "-p"]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              shell=_is_windows())
    except Exception as e:  # noqa: BLE001 — CLI missing, timeout: infrastructure, not the name
        raise ResearchUnavailable(str(e)[:200])
    if proc.returncode != 0:
        raise ResearchUnavailable((proc.stderr or proc.stdout or "").strip()[:200])
    return proc.stdout or ""


def claude_json(prompt, *, tools=("WebSearch",), timeout=240):
    """`_claude`, parsed: the outermost {...} of the answer as a dict, or None when the answer
    holds no JSON (prose, a fence with nothing inside). None is a fact about the ANSWER."""
    return extract_json(_claude(prompt, tools=tools, timeout=timeout))


def extract_json(raw):
    """The first JSON object that decodes from anywhere in `raw`, or None.

    The old `re.search(r"\\{.*\\}")` was greedy: one brace in a preamble ("I'll research
    {X}...") or a trailing note spanned first-brace-to-last-brace, `json.loads` failed, and
    a paid-for, valid answer became a weekly strike against the company name."""
    dec = json.JSONDecoder()
    found = []
    for i, ch in enumerate(raw or ""):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(raw, i)
        except ValueError:
            continue
        if isinstance(obj, dict):
            found.append(obj)
    # the prompt itself shows the model `{"unknown": true}`; a restated escape hatch or a
    # `{}` before the real answer must not be the answer we score
    substantive = [d for d in found if set(d) - {"unknown"}]
    return substantive[0] if substantive else (found[0] if found else None)


def claude_text(prompt, *, timeout=90):
    """`_claude` for prose answers (the blurb). Same failure contract."""
    return _claude(prompt, timeout=timeout)


def research_company(company, context="", timeout=240):
    """Return a validated firmographics dict for `company`, or None if the NAME fails.

    None (never a partial/junk record) when the model answers unknown, the output is
    non-JSON prose, or validation rejects the record — callers may record a per-name
    failure for these. Raises ResearchUnavailable for CLI/timeout/network problems —
    callers must NOT blame the name for those (see the exception's docstring).
    """
    prompt = _PROMPT.format(company=company, context=(context or "")[:600])
    rec = claude_json(prompt, tools=("WebSearch",), timeout=timeout)
    return _coerce(rec, company) if rec is not None else None


# ---- the shared export: one file, two stores --------------------------------------- #
SHARED_EXPORT = os.path.join(os.path.dirname(__file__), "..", "cloud_state",
                             "firmographics.json")


def load_shared_status():
    """(records, status) for the committed export — status is `ok`, `missing` or `corrupt`.

    The local store and the cloud store are separate sqlite files that cannot be merged,
    which is why the cloud digest rendered nothing while 919 profiles sat on a laptop.
    Both sides read this file, so whichever machine researched a company, every consumer
    sees it. `missing` and `corrupt` are reported, never raised: an absent export is not a
    reason to fail a run — but a corrupt one must never be silently REPLACED by the
    smaller sqlite table (that is what the old `{}`-on-any-error did)."""
    try:
        with open(SHARED_EXPORT, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}, "missing"
    except Exception:  # noqa: BLE001 — bad JSON, a half-written file, permissions
        return {}, "corrupt"
    if not isinstance(d, dict):
        return {}, "corrupt"
    return {k: v for k, v in d.items() if isinstance(v, dict)}, "ok"


def load_shared():
    """The export as a dict; empty when absent or unreadable (see load_shared_status)."""
    return load_shared_status()[0]


def _evidence(rec):
    return sum(1 for v in rec.values() if v not in ("", None))


def newer(a, b):
    """Of two records for the same company, the one researched later (by `as_of`); on the
    same day, the one carrying more filled fields (a fill pass adds `employees_*` without
    bumping `as_of`, and that evidence must not lose a coin toss); still tied -> `a`."""
    if not isinstance(a, dict):
        return b
    if not isinstance(b, dict):
        return a
    ka, kb = str(a.get("as_of") or ""), str(b.get("as_of") or "")
    if ka != kb:
        return b if kb > ka else a
    return b if _evidence(b) > _evidence(a) else a


_COUNT_COMPANIONS = ("employees_lookup_miss", "employees_linkedin_miss", "employees_source",
                     "employees_as_of", "employees_range", "size_band_pre_linkedin")


def merge(a, b):
    """`newer(a, b)` with the loser's non-empty fields filling the winner's empties — the
    field-generic merge-preserve the bulk script applies inside one store, applied across
    the two. A fresh record that re-found no `founded` must not erase the one we had; a
    fresh `employees_global` supersedes the old count's companions, never inherits them."""
    win = newer(a, b)
    lose = b if win is a else a
    if not isinstance(lose, dict) or win is lose:
        return win
    out = dict(win)
    fresh_count = bool(out.get("employees_global"))
    for k, v in lose.items():
        if v in ("", None) or k == "as_of" or out.get(k) not in ("", None):
            continue
        if fresh_count and k in _COUNT_COMPANIONS:
            continue
        out[k] = v
    if out.get("employees_global"):
        out["size_band"] = band_for(out["employees_global"])
    return out


def union_store(st, shared=None):
    """sqlite ∪ export, `merge` per company. The one view every consumer and both writers
    must use — the chain used to read sqlite alone and re-researched companies the cloud
    had profiled hours earlier (2 on 2026-08-24), and `--export` then wrote the local
    table over the file, deleting the cloud's records (19 at risk that evening)."""
    out = dict(load_shared() if shared is None else shared)
    for c, rec in st.load_firmographics().items():
        out[c] = merge(out.get(c), rec)
    return out


def display_index(records):
    """identity_key -> the record that answers for a whole identity group. Deterministic
    and quality-ranked: the CANONICAL name first (its own normalized form — "Amazon", not
    the alias "AWS" nor the suffixed "Dell Technologies"), then a non-site-form ("Dell
    Technologies" over "Dell Israel": a site record carries the site's founding year and,
    for AWS-class groups, the wrong headcount), then the fullest record, then the shortest
    name. Evidence-first let a fill pass's two bookkeeping fields promote AWS to answer for
    Amazon; a plain dict comprehension had handed the group to whichever sorted last."""
    def rank(name, rec):
        plain = " ".join(re.sub(r"[^0-9a-z\u05d0-\u05ff]+", " ", name.lower()).split())
        canonical = plain == identity_key(name)          # no stripped suffix, not an alias
        site_form = bool(re.search(r"\bisrael\b", plain))  # "X Israel" carries the site's facts
        return (canonical, not site_form, _evidence(rec), -len(name))
    best = {}
    for name, rec in records.items():
        k = identity_key(name)
        cur = best.get(k)
        if cur is None or rank(name, rec) > rank(*cur):
            best[k] = (name, rec)
    return {k: rec for k, (_n, rec) in best.items()}


def sync_store(st, run_date, shared=None):
    """Bring sqlite up to the union: write every export record sqlite lacks or holds an
    older copy of. Returns the number written. The export stays authoritative; sqlite is a
    per-machine cache, so seeding it is idempotent and safe to repeat every run."""
    shared = load_shared() if shared is None else shared
    have = st.load_firmographics()
    fresh = {c: rec for c, rec in shared.items()
             if newer(have.get(c), rec) is rec and rec != have.get(c)}
    if fresh:
        st.save_firmographics(fresh, run_date)
    return len(fresh)


def save_shared(records):
    """Write the union back to the committed export (sorted, so the diff is readable).
    Returns True iff the file on disk now holds `records`. The temp name carries the pid:
    the digest and the local chain both write this file on the laptop, and a shared
    `.tmp` let one publish the other's half-written buffer; a failed `os.replace` (Windows
    refuses it while any reader holds the file) must not leave a `.tmp` in a tracked dir."""
    if not records:
        return False
    path = os.path.abspath(SHARED_EXPORT)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return True


# ---- the digest hook: blurbs + facts for one run ----------------------------------- #
# Everything the digest needs from this lane, in one call that never raises, is bounded
# in calls AND minutes, and reports itself (`audit_lines`) into the mail. Env-overridable
# with today's values as defaults; `pipeline/run.py` holds none of these numbers.
FIRMO_MAX_PER_RUN = int(os.environ.get("FIRMO_MAX_PER_RUN", "5"))
FIRMO_TIME_BUDGET_MIN = float(os.environ.get("FIRMO_TIME_BUDGET_MIN", "15"))  # blurbs AND research
BLURB_MAX_PER_RUN = int(os.environ.get("BLURB_MAX_PER_RUN", "30"))
RESEARCH_TIMEOUT_S = 240
BLURB_RETRY_DAYS = 30      # a company the blurb model could not identify is asked again monthly
STRIKE_RETRY_DAYS = 7      # a name research failed on is retried weekly
SOFT_OUTAGE_MIN_FAILS = 3  # this many name-failures and no success in one run = not the names


def _report():
    return {"research_off": False, "board_companies": 0, "candidates": 0, "researched": 0,
            "failed": 0, "skipped_budget": 0, "unavailable_after": None,
            "unavailable_reason": "", "unavailable_in": "", "soft_outage": False,
            "blurb_outage": False, "blurbs_stopped": False,
            "cap": FIRMO_MAX_PER_RUN, "budget_min": FIRMO_TIME_BUDGET_MIN,
            "blurbs_written": 0, "blurbs_asked": 0, "blurbs_empty": 0, "blurbs_missing": 0,
            "blurbs_skipped_budget": 0, "blurbs_derived": 0, "blurbs_waiting": 0,
            "export_status": "ok",
            "export_records": 0, "export_newest": "", "store_records": 0, "synced": 0,
            "published": False, "publish_error": "", "scoped": False, "error": "", "gated": 0}


def _load_profiles(path):
    """`company_profiles.json` — hand-written blurbs that outrank the generated ones. They
    pass the same junk rule as a generated blurb: the file is the one input with no gate,
    and "UNKNOWN" is exactly what a backfill from a failed research pass would carry."""
    from .company_info import _JUNK_OUT
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (ValueError, OSError):
        return {}
    return {k: v for k, v in d.items()
            if isinstance(v, str) and len(v.strip()) >= 15 and not _JUNK_OUT.search(v)}


CHIP_MAX = 48


def chip_safe(rec):
    """The record as the card renders it: `il_center` cut to its first clause and at most
    CHIP_MAX chars. 309 of 940 researched records answer "main Israel site" with a
    paragraph ("Tel Aviv (HQ; registered as Zipher Technologies Ltd, no. 517004768)"), and a
    chip is `white-space: nowrap`. The stored record keeps the full text."""
    if not isinstance(rec, dict):
        return rec
    site = " ".join(str(rec.get("il_center") or "").split())
    if len(site) <= CHIP_MAX:
        return rec
    short = site.split(";")[0].strip()
    if len(short) > CHIP_MAX:
        short = short[:CHIP_MAX]
        if " " in short:
            short = short[:short.rfind(" ")]
    # never leave a parenthesis open: drop the dangling "(" clause instead
    while short.count("(") > short.count(")"):
        short = short[:short.rfind("(")]
    short = short.strip(" ,;(-\u2014\u2013")
    return {**rec, "il_center": short or site[:CHIP_MAX]}


def _context_for(company, jobs):
    return next((j.get("description") for j in jobs
                 if j.get("company") == company and j.get("description")), "")


def _research_order(board_jobs, email_jobs):
    """Who gets the budget first: the companies in tomorrow's email (48h + first-scan), then
    the board by live-role count, then alphabetical — the reader opens the mail, not the
    archive."""
    live = {}
    for j in board_jobs:
        live[j["company"]] = live.get(j["company"], 0) + 1
    mailed = {j["company"] for j in email_jobs or ()}
    return sorted(live, key=lambda c: (c not in mailed, -live[c], c.lower()))


class _Clock:
    """One wall clock for the whole hook: blurbs and research share FIRMO_TIME_BUDGET_MIN.
    A research-only budget let 30 blurbs at 90 s each run for 45 minutes before the
    'budget' even started (wave 2)."""

    def __init__(self, budget_min, now=None):
        import time
        self.now = now or time.time
        self.t0 = self.now()
        self.budget_s = budget_min * 60

    def remaining(self):
        return self.budget_s - (self.now() - self.t0)


def _blurbs(st, board_jobs, run_date, use_llm, rep, profiles_path, clock=None):
    from . import company_info as _ci
    company_info = {**st.load_company_info(), **_load_profiles(profiles_path)}
    board = {j["company"] for j in board_jobs}
    # one blurb per identity: "Meta" and "Meta Israel" are one company (both had paid)
    by_key = {}
    for c, s in company_info.items():
        if s:
            by_key.setdefault(identity_key(c), s)
    for c in board:
        if not company_info.get(c) and by_key.get(identity_key(c)):
            company_info[c] = by_key[identity_key(c)]
    missing = sorted(c for c in board if not company_info.get(c))
    rep["blurbs_missing"] = len(missing)
    if not use_llm or not missing:
        return company_info, missing
    # '' is a cached answer ("UNKNOWN", junk, a CLI error) — asking again every morning
    # spent a call per run on the same names. Retry monthly, like the employee misses.
    cutoff = (_dt.date.fromisoformat(run_date) - _dt.timedelta(days=BLURB_RETRY_DAYS)).isoformat()
    recent = {c for (c,) in st.conn.execute(
        "SELECT company FROM company_info WHERE (summary='' OR summary IS NULL) "
        "AND updated > ?", (cutoff,))}
    todo, batch = [], set()
    for c in missing:
        if c in recent:
            continue
        if identity_key(c) in batch:
            continue
        batch.add(identity_key(c))
        todo.append(c)
    rep["blurbs_waiting"] = len(missing) - len(todo)
    todo = todo[:BLURB_MAX_PER_RUN]
    clock = clock or _Clock(rep["budget_min"])
    empties, empty_names = 0, []
    for i, company in enumerate(todo):
        if clock.remaining() < 30:
            rep["blurbs_skipped_budget"] = len(todo) - i
            break
        try:
            rep["blurbs_asked"] += 1
            summ = _ci.summarize_company(company, _context_for(company, board_jobs),
                                         timeout=int(max(10, min(90, clock.remaining()))))
        except ResearchUnavailable as e:
            rep["blurbs_asked"] -= 1
            rep["unavailable_after"] = i
            rep["unavailable_in"] = "blurbs"
            rep["unavailable_reason"] = str(e)
            break
        company_info[company] = summ
        st.save_company_info({company: summ}, run_date)
        if summ:
            rep["blurbs_written"] += 1
            empties, empty_names = 0, []
            for other in missing:  # the group's other name-forms read the same blurb
                if identity_key(other) == identity_key(company) and not company_info.get(other):
                    company_info[other] = summ
        else:
            rep["blurbs_empty"] += 1
            empties += 1
            empty_names.append(company)
            if empties >= SOFT_OUTAGE_MIN_FAILS:
                # three UNKNOWN/junk answers in a row: the model is not identifying anything
                # this morning — stop walking the list (30 x 90 s). If nothing at all was
                # written it is an outage, and the three '' rows just cached would gate
                # three real companies for a month on the strength of it: take them back.
                rep["blurbs_stopped"] = True
                if not rep["blurbs_written"]:
                    rep["blurb_outage"] = True
                    st.conn.execute(
                        "DELETE FROM company_info WHERE summary='' AND updated=? AND company IN (%s)"
                        % ",".join("?" * len(empty_names)), [run_date, *empty_names])
                    st.conn.commit()
                    for c in empty_names:
                        company_info.pop(c, None)
                break
    return company_info, [c for c in missing if not company_info.get(c)]


def _research_targets(st, board_jobs, email_jobs, firmo, run_date):
    failures = st.load_firmo_failures()
    cutoff = (_dt.date.fromisoformat(run_date) - _dt.timedelta(days=STRIKE_RETRY_DAYS)).isoformat()
    norms = {identity_key(c) for c in firmo}
    failed_norms = {identity_key(c) for c, (_att, last) in failures.items() if last > cutoff}
    out, batch, gated = [], set(), 0
    for c in _research_order(board_jobs, email_jobs):
        k = identity_key(c)
        if c in firmo or k in norms or k in batch:
            continue  # profiled, or "X Israel" beside "X" in one digest: one slot, one record
        if k in failed_norms or looks_like_junk(c):
            gated += 1  # a failed name retries weekly; a leaked job title never
            continue
        batch.add(k)
        out.append(c)
    return out, gated


def _research(st, targets, board_jobs, run_date, rep, clock=None):
    clock = clock or _Clock(rep["budget_min"])
    todo = targets[:rep["cap"]]
    done, failed_names = {}, []
    for i, company in enumerate(todo):
        remaining = clock.remaining()
        if remaining < 60:
            rep["skipped_budget"] = len(todo) - i
            break
        if not done and len(failed_names) >= SOFT_OUTAGE_MIN_FAILS:
            # exit-0 prose, a revoked WebSearch grant: every answer so far failed and none
            # succeeded — evidence about the infrastructure, not about three company names
            rep["soft_outage"] = True
            rep["skipped_budget"] = len(todo) - i
            break
        try:
            rec = research_company(company, _context_for(company, board_jobs),
                                   timeout=int(min(RESEARCH_TIMEOUT_S, remaining)))
        except ResearchUnavailable as e:
            # infrastructure outage: don't blame the names, don't burn the budget
            rep["unavailable_after"] = i
            rep["unavailable_in"] = "research"
            rep["unavailable_reason"] = str(e)
            break
        if rec:
            st.save_firmographics({company: rec}, run_date)
            done[company] = rec
        else:
            failed_names.append(company)
    rep["researched"] = len(done)
    rep["failed"] = len(failed_names)
    if failed_names and not done and len(failed_names) >= SOFT_OUTAGE_MIN_FAILS:
        rep["soft_outage"] = True
    else:
        for c in failed_names:
            st.record_firmo_failure(c, run_date)
    return done


def enrich_for_run(st, *, board_jobs, email_jobs=(), all_companies=None, run_date,
                   use_llm=True, scoped=False, profiles_path=None):
    """Blurbs + firmographics for one digest run -> (company_info, firmo_display, report).

    The never-raises front door: company intel is best-effort by design and must not cost
    the day's email and board (one locked sqlite `save_firmographics` used to). On an
    unexpected exception the reader still gets whatever was assembled, and the audit line
    says `company intel FAILED: ...`."""
    rep = _report()
    holder = {"company_info": {}, "firmo_display": {}}
    try:
        return _enrich(st, board_jobs=board_jobs, email_jobs=email_jobs,
                       all_companies=all_companies, run_date=run_date, use_llm=use_llm,
                       scoped=scoped, profiles_path=profiles_path, rep=rep, holder=holder)
    except Exception as e:  # noqa: BLE001
        rep["error"] = f"{type(e).__name__}: {e}"[:160]
        print(f"  [company-intel] FAILED: {rep['error']}", file=sys.stderr, flush=True)
        return holder["company_info"], holder["firmo_display"], rep


def _enrich(st, *, board_jobs, email_jobs, all_companies, run_date, use_llm, scoped,
            profiles_path, rep, holder):
    """The work behind `enrich_for_run`; `holder` carries partial results out on failure.

    Never raises. Spends at most BLURB_MAX_PER_RUN + FIRMO_MAX_PER_RUN `claude` calls and
    FIRMO_TIME_BUDGET_MIN minutes on research; stops at the first infrastructure failure.
    Reads sqlite ∪ the shared export, seeds sqlite from the export, and writes the union
    back — except on a scoped run (`--only`/`--limit`), which must leave the committed
    file alone, and except when the export is corrupt, which must not be replaced by
    the smaller sqlite table. `audit_lines(report)` turns the report into the mail."""
    rep["research_off"] = not use_llm
    rep["scoped"] = bool(scoped)
    shared, rep["export_status"] = load_shared_status()
    rep["export_records"] = len(shared)
    rep["export_newest"] = max((str(r.get("as_of") or "") for r in shared.values()), default="")
    clock = _Clock(rep["budget_min"])
    if not scoped:  # a scoped local run is produce-only: it writes neither store
        try:
            rep["synced"] = sync_store(st, run_date, shared)
        except Exception as e:  # noqa: BLE001 — a locked sqlite must not cost the digest
            print(f"  [company-intel] store sync skipped: {e!r}", file=sys.stderr, flush=True)
    firmo = union_store(st, shared)
    rep["store_records"] = len(firmo)
    board = {j["company"] for j in board_jobs}
    rep["board_companies"] = len(board)

    company_info, still_missing = _blurbs(st, board_jobs, run_date, use_llm, rep, profiles_path,
                                          clock)
    holder["company_info"] = company_info

    targets, rep["gated"] = _research_targets(st, board_jobs, email_jobs, firmo, run_date)
    rep["candidates"] = len(targets)
    if use_llm and targets and rep["unavailable_after"] is None and not rep["blurb_outage"]:
        firmo.update(_research(st, targets, board_jobs, run_date, rep, clock))
    # else: the CLI is down or not answering — the outage sentence carries the count

    # every company we have ever matched renders a card (board, email, archive), looked up
    # under the normalized identity so "SolarEdge Technologies" finds the stored "SolarEdge"
    by_key = display_index(firmo)
    wanted = set(all_companies or ()) | board
    firmo_display = {c: (firmo.get(c) or by_key.get(identity_key(c))) for c in wanted}
    firmo_display = {k: chip_safe(v) for k, v in firmo_display.items() if v}
    holder["firmo_display"] = firmo_display

    # a company with facts but no blurb reads its facts as prose — no call, not cached
    from . import company_info as _ci
    for c in still_missing:
        text = _ci.derive_blurb(c, firmo_display.get(c))
        if text:
            company_info[c] = text
            rep["blurbs_derived"] += 1

    if not scoped and rep["export_status"] != "corrupt":
        try:
            rep["published"] = save_shared(firmo)
        except Exception as e:  # noqa: BLE001
            rep["publish_error"] = f"{type(e).__name__}: {e}"[:120]
            print(f"  [company-intel] shared export NOT written: {e}", file=sys.stderr, flush=True)
    return company_info, firmo_display, rep


def _ascii(s, n=80):
    """CLI stderr and exception text carry box-drawing glyphs and Hebrew names; the line
    they land in is printed to a console that may be cp1252 (the laptop's `run_daily.ps1`
    pipe), and `pipeline/run.py` does not reconfigure stdout — so the never-raises guard
    would be undone by the act of reporting. Fold to ASCII before it leaves the report."""
    return " ".join(str(s or "").split()).encode("ascii", "replace").decode()[:n]


def audit_lines(rep):
    """(mail lines, ::warning:: lines) from `enrich_for_run`'s report. Pure; no I/O.

    One line a reader can reconcile: researched + failed + skipped + waiting = candidates."""
    parts, warn = [], []
    n, c = rep["board_companies"], rep["candidates"]
    if rep.get("error"):
        msg = f"company intel FAILED ({_ascii(rep['error'], 160)}) — cards render from whatever was assembled"
        parts.append(msg)
        warn.append(msg)
    gated = (f" ({rep['gated']} more unprofiled: research failed, weekly retry)"
             if rep.get("gated") else "")
    if rep["research_off"]:
        parts.append((f"research off (--no-llm); {c} of {n} board companies unprofiled"
                      if c else f"research off (--no-llm); all {n} board companies profiled") + gated)
    elif c == 0:
        parts.append(f"all {n} board companies profiled" + gated)
    else:
        bits = [f"{rep['researched']} researched", f"{rep['failed']} failed"]
        if rep["skipped_budget"]:
            bits.append(f"{rep['skipped_budget']} skipped (budget {rep['budget_min']:g}m spent)")
        waiting = c - rep["researched"] - rep["failed"] - rep["skipped_budget"]
        if rep["unavailable_after"] is None and waiting > 0:
            bits.append(f"{waiting} over the cap wait for the next run")
        parts.append(f"{c} of {n} board companies unprofiled (cap {rep['cap']}/run, "
                     f"budget {rep['budget_min']:g}m): " + ", ".join(bits) + gated)
    if rep["soft_outage"]:
        msg = ("research soft outage suspected: every answer failed and none succeeded — "
               "stopped, no strikes recorded")
        parts.append(msg)
        warn.append(msg)
    if rep.get("blurb_outage"):
        msg = ("blurb soft outage suspected: three empty answers and none written — stopped, "
               "nothing cached, research skipped")
        parts.append(msg)
        warn.append(msg)
    if rep["unavailable_after"] is not None:
        k = rep["unavailable_after"]
        loop = rep.get("unavailable_in") or "research"
        left = c - rep["researched"] - rep["failed"]
        msg = (f"claude unavailable after {k} {loop} call{'' if k == 1 else 's'} "
               f"({_ascii(rep['unavailable_reason'])}) — {left} unprofiled board "
               f"compan{'y waits' if left == 1 else 'ies wait'} for the next run")
        parts.append(msg)
        warn.append(msg)
    elif rep["failed"] and not rep["researched"] and not rep["soft_outage"]:
        warn.append(f"every research answer failed ({rep['failed']} of {rep['failed']}) — "
                    f"below the {SOFT_OUTAGE_MIN_FAILS}-fail outage rule, so the names were struck")
    b = [f"{rep['blurbs_asked']} asked", f"{rep['blurbs_written']} written"]
    if rep["blurbs_empty"]:
        b.append(f"{rep['blurbs_empty']} empty" + (" — stopped" if rep.get("blurbs_stopped") else ""))
    if rep["blurbs_skipped_budget"]:
        b.append(f"{rep['blurbs_skipped_budget']} skipped (budget)")
    if rep["blurbs_derived"]:
        b.append(f"{rep['blurbs_derived']} derived from facts")
    if rep["blurbs_waiting"]:
        b.append(f"{rep['blurbs_waiting']} waiting (monthly retry / same company)")
    parts.append("blurbs: " + ", ".join(b))
    if rep["export_status"] == "ok":
        e = f"export {rep['export_records']} records, newest {rep['export_newest'] or '?'}"
        if rep["synced"]:
            e += f", {rep['synced']} newer than the store"
        parts.append(e)
        if rep.get("publish_error") or (not rep["published"] and not rep.get("scoped")
                                        and not rep.get("error")):
            msg = "export NOT written" + (f" ({_ascii(rep.get('publish_error'), 120)})"
                                          if rep.get("publish_error") else " (nothing to write)")
            parts.append(msg)
            warn.append(msg)
    else:
        e = (f"export {rep['export_status'].upper()} at cloud_state/firmographics.json — cards "
             f"render from sqlite only ({rep['store_records']} records)"
             + ("; file left untouched" if rep["export_status"] == "corrupt" else ""))
        parts.append(e)
        warn.append(e)
    return [" · ".join(parts)], warn
