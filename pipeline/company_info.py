"""Per-company plain-language summary: what the company does + how it makes money.

Generated once per company via `claude -p` (a judgment/knowledge task the keyword layer
can't do) and cached in the store so it's not regenerated daily. Used to populate the
expandable "About <company>" section of the interactive digest.
"""
from __future__ import annotations

import re
import subprocess


def _is_windows():
    import os
    return os.name == "nt"


_PROMPT = (
    "In 2 short, plain-English sentences, describe (1) what the company \"{company}\" does, "
    "and (2) how it makes money (its revenue model — e.g. SaaS subscriptions, ads, "
    "transaction fees, licensing). Be concrete and factual. Write in the third person only, "
    "for a job seeker reading a job board — never mention yourself, your knowledge, this "
    "prompt, or the job post; no first-person ('I', 'I'm not sure'), no hedging filler like "
    "'isn't stated in the available information'. If you genuinely cannot identify the "
    "company even with the context, output exactly the single word UNKNOWN instead. "
    "Output ONLY the two sentences (or UNKNOWN), no preamble, no bullet points.\n\n"
    "Context from one of its job posts (may help, may be empty): {context}\n"
)


def summarize_company(company, context="", timeout=90):
    """Return a 2-sentence 'what it does + how it earns money' summary, or '' on failure."""
    prompt = _PROMPT.format(company=company, context=(context or "")[:600])
    try:
        proc = subprocess.run(
            ["claude", "-p"], input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, shell=_is_windows(),
        )
    except Exception:  # noqa: BLE001
        return ""
    if proc.returncode != 0:
        return ""
    out = " ".join((proc.stdout or "").split())
    # strip any accidental leading label
    out = re.sub(r"^(sure[,:]?|here('|)s|answer:)\s*", "", out, flags=re.I).strip()
    # Never persist a CLI/auth error or other non-prose as a company blurb — a failed
    # `claude -p` (e.g. "Not logged in · Please run /login") must yield '' , not junk.
    if len(out) < 15 or _JUNK_OUT.search(out):
        return ""
    return out


_JUNK_OUT = re.compile(
    r"not logged in|please run|/login|usage:|command not found|invalid api|api key|"
    r"traceback|rate limit|quota|unauthor|permission denied|error:|"
    # first-person / meta answers ("I'm not familiar with...") and the UNKNOWN escape
    # hatch must never be cached as a blurb either — '' lets the renderer fall back.
    r"^unknown\b|\bI['’]?m\b|\bI\s+(?:don['’]?t|do not|can['’]?t|cannot|couldn['’]?t|"
    r"am|have|would|need|recommend)\b|\bI['’]d\b|no (?:job post )?context was provided|"
    r"web[- ]search access", re.I)
