"""Per-company plain-language summary: what the company does + how it makes money.

Generated once per company via `claude -p` (a judgment/knowledge task the keyword layer
can't do) and cached in the store so it's not regenerated daily. Used to populate the
expandable "About <company>" section of the interactive digest. When no blurb exists but
the firmographics record does, `derive_blurb` reads the facts as prose instead — no call.
"""
from __future__ import annotations

import re

from .firmographics import ResearchUnavailable, claude_text  # noqa: F401 — re-exported

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
    """Return a 2-sentence 'what it does + how it earns money' summary, or '' when the model
    could not identify the company (UNKNOWN, junk, first-person). Raises ResearchUnavailable
    when the CLI itself failed — the caller must not cache '' for an outage."""
    prompt = _PROMPT.format(company=company, context=(context or "")[:600])
    out = " ".join(claude_text(prompt, timeout=timeout).split())
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


_STAGE_PROSE = {"public": "a public company", "acquired-by-bigtech": "an acquired company",
                "growth-private": "a growth-stage private company",
                "early-private": "an early-stage private company",
                "private-enterprise": "a privately held company"}


def derive_blurb(company, rec):
    """The firmographics record read as an About blurb, or '' when there is nothing to say.

    Two `claude` calls used to answer overlapping questions for every new company: the blurb
    ("what it does, how it earns") and the research (`sub_sector`, `business_model`). When
    the blurb is missing — never asked, or the model answered UNKNOWN — the researched facts
    already hold the answer. Pure string assembly, so it is never cached and a real blurb
    written later still wins."""
    if not isinstance(rec, dict):
        return ""
    what = " ".join(str(rec.get("sub_sector") or "").split()).rstrip(".")
    how = " ".join(str(rec.get("business_model") or "").split()).rstrip(".")
    if not (what or how):
        return ""
    stage = _STAGE_PROSE.get(str(rec.get("stage") or ""), "a company")
    sector = " ".join(str(rec.get("sector") or "").split())
    head = f"{company} is {stage}" + (f" in {sector}" if sector else "")
    first = head + (f": {what}" if what else "") + "."
    second = (f" It makes money through {how}." if how else "")
    who = " ".join(str(rec.get("customer_type") or "").split()).rstrip(".")
    third = f" Customers: {who}." if who and how else ""
    return (first + second + third)[:600]
