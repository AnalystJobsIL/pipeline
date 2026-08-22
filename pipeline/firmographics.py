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
import re
import subprocess

STAGES = {"public", "acquired-by-bigtech", "growth-private", "early-private"}
SIZE_BANDS = {"S", "M", "L", "XL"}


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
    '  "stage": exactly one of "public", "acquired-by-bigtech", "growth-private", "early-private"\n'
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
    "If you cannot identify the company at all, output exactly {{\"unknown\": true}}.\n\n"
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
    yr = rec.get("founded")
    # lower bound 1600, not 1900 — the list holds multinationals like Barclays (1690),
    # Merck (1668), Pfizer (1849); a too-tight clamp silently nulled all of them
    out["founded"] = int(yr) if isinstance(yr, (int, float)) and 1600 <= yr <= _dt.date.today().year else None
    out["as_of"] = _dt.date.today().isoformat()
    return out


def research_company(company, context="", timeout=240):
    """Return a validated firmographics dict for `company`, or None on any failure.

    None (never a partial/junk record) on: claude CLI missing/not logged in, timeout,
    non-JSON output, or the model answering unknown — so failures are retried on a
    later run instead of poisoning the cache.
    """
    prompt = _PROMPT.format(company=company, context=(context or "")[:600])
    try:
        proc = subprocess.run(
            ["claude", "-p", "--allowedTools", "WebSearch"],
            input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, shell=_is_windows(),
        )
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None
    raw = (proc.stdout or "").strip()
    # tolerate a stray markdown fence or preamble: take the outermost {...}
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        rec = json.loads(m.group(0))
    except ValueError:
        return None
    return _coerce(rec, company)
