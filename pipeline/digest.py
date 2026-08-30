"""Render the products (lane: render, ARCHITECTURE.md §7d, part 2).

Three products from the same cards: the Markdown that becomes the daily email
(`build_markdown` -> digests/latest.md), the board and the archive (`build_board_html` ->
docs/index.html, docs/archive.html), and the legacy html/text digest (`build_digest`, whose
`subject` is the only part anything reads). `render_all` is the one entry point run.py uses.

The digest is intentionally auditable: besides the job listings it carries a run-summary
(how many scanned / Israel-matched / accepted / new, the keyword-vs-LLM path breakdown,
and any companies whose fetch failed) so the reader can trust what they're seeing.

This file derives nothing from a posting's text — `pipeline/jdtext.py` does, and
`pipeline/rolecard.py` assembles one card per role. This file is where escaping happens
(`esc`, `_md_esc`, `_safe_url`) and the only place it may.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

from . import rolecard, roleprofile
from .jdtext import _company_blurb, _age_note   # markdown's company-level blurb; footer count


def _safe_url(u):
    """Only http/https survive — blocks javascript:/data: from scraped/discovered links — and
    only printable ASCII with no quotes or angle brackets: the mail prints it bare, so a
    space — or a zero-width character — inside a scraped url is a markdown injection, not a
    url (every one of the 973 real urls in the registry and the store is plain ASCII)."""
    u = str(u or "").strip()
    if not (u[:7].lower() == "http://" or u[:8].lower() == "https://"):
        return ""
    return "" if re.search(r"[^\x21-\x7e]|[<>\"'`\\]", u) else u


_MD_META = re.compile(r"[\\`*_{}\[\]()#+\-!@~|<>]")   # `<` too: the issue body is rendered as HTML


def _md_esc(s):
    """Escape Markdown metacharacters so scraped company/title text can't inject links,
    @mentions, or formatting into the emailed issue. One line: a newline in a scraped title
    would end the bullet and open a heading. `\\` first, or the input's own backslash eats
    the escape just added."""
    return _MD_META.sub(lambda m: "\\" + m.group(0), " ".join(str(s or "").split()))


_MD_LINE = re.compile(r"[\\`\[\]@]|<(?=[A-Za-z/!])")     # `<` only where it opens a tag: `A<-B` stays


def _md_line(s):
    """A line another lane wrote into `stats` (a registry name, an exception text, a stage
    stamp) goes into the issue body as its own bullet: neutralise what can open a link, a
    tag, a code span or an @mention, and nothing else — `keyword_nollm` must stay readable."""
    return _MD_LINE.sub(lambda m: "\\" + m.group(0), " ".join(str(s or "").split()))


def _fmt_date(d):
    return d or "—"


_MD_BLURB = re.compile(r"[\\`\[\]<>*_]")


def _md_alarm(s):
    """An alarm line carries scraped company names; strip what can open a link, a tag or a
    span and neutralise @mentions — without the backslashes `_md_esc` leaves in prose."""
    return _MD_BLURB.sub("", " ".join(str(s or "").split())).replace("@", "\\@")


def _md_blurb(s):
    """A blurb goes into the mail as italic prose. Escaping it prints backslashes (the
    code-span lesson, test_company_facts_are_not_backslash_escaped…); stripping the seven
    characters that can open a link, a span, a tag or a style is enough (parentheses stay:
    without a `]` before them they are prose)."""
    return _MD_BLURB.sub("", " ".join(str(s or "").split())).replace("@", "\\@")


def build_markdown(jobs, run_date, stats, company_info=None, board_url="",
                   firmographics=None, ledger=None, render_issues=None):
    """Return (title, body_markdown) — a COMPACT, email-friendly digest.

    Grouped by company (freshest first). Each company shows its one-line "what it does /
    how it earns money", then its roles as a bullet list where the title is a direct apply
    link plus location/date/seniority. No `<details>` collapsibles in the listing: email
    clients (Gmail) render those expanded anyway, so a compact list reads better everywhere;
    the full role description is one tap away on the apply link.

    `company_info` maps company name -> a plain-text "what it does + how it earns money".
    `ledger` maps role_id -> the role record (pipeline/roles.py) when the caller has it;
    `render_issues` is `render_all`'s report over the board and archive, so what went wrong
    rendering the products the reader is about to click through reaches the mail.
    """
    company_info = company_info or {}
    firmographics = firmographics or {}
    ledger = ledger or {}
    render_issues = render_issues or {"lines": [], "alarms": []}
    # Two sinks, one per section, filled by `_render` with the cards it actually EMITTED (a
    # mangled title is dropped before it reaches either). The subject is computed from these
    # AFTER the body is rendered — never from the input lists: from 2026-08-2x to 08-30 the
    # H1 counted `fresh_jobs` alone while the body carried both sections, and 7 of 12 mails
    # went out saying "6 new roles" over 13 bullets (`docs/sessions/2026-08-30-render.md`).
    fresh_cards, newco_cards = [], []
    # Roles at an employer this digest has never scanned before. `_posted_in` refuses to
    # call their back catalogue 48h-fresh — correctly, we have no idea when they were
    # posted — but they are news to the reader, so they get their own honest heading
    # instead of being silently withheld for a day.
    fresh_jobs = [j for j in jobs if not j.get("_new_company")]
    new_co_jobs = [j for j in jobs if j.get("_new_company")]
    jobs = fresh_jobs

    by_company = {}
    for j in jobs:
        by_company.setdefault(j["company"], []).append(j)
    for c in by_company:
        by_company[c].sort(key=lambda x: str(x.get("posted_date") or ""), reverse=True)
    # companies ordered by their freshest posting
    companies = sorted(by_company, key=lambda c: max(str(x.get("posted_date") or "")
                                                     for x in by_company[c]), reverse=True)

    # The body's sections. The header (title, subtitle, board link, zero-copy) is built
    # LAST, from what these sections actually carry — see `head` below.
    lines = []
    email_hidden = [0]

    def _render(company, jobs_c, out, sink, dated=True):
        """Append one company's block to `out`; the cards it emitted go to `sink`."""
        cards = [rolecard.build(j, run_date, ledger_rec=ledger.get(j.get("mkey")),
                                company_info=company_info, firmographics=firmographics) for j in jobs_c]
        email_hidden[0] += sum(1 for c in cards if c["mangled"])
        cards = [c for c in cards if not c["mangled"]]     # a card blob is not a role, in the mail either
        if not cards:
            return
        sink.extend(cards)
        about = cards[0]["about"]
        heading = f"### {_md_esc(company)}"
        also = sorted({n for c in cards for n in c["also_listed_as"]})
        if also:
            heading += f" _(also listed as {_md_esc(', '.join(also))})_"
        out.append(heading)
        if about:
            out.append(f"_{_md_blurb(about)}_")
        facts = rolecard.firmo_facts(firmographics.get(company))
        if facts:
            # inside a code span markdown takes the text literally, so escaping it only
            # prints the backslashes: `\~16,068 employees`. Strip backticks instead, which
            # are the one character that could break out of the span.
            out.append("`" + "` · `".join(f.replace("`", "'") for f in facts) + "`")
        out.append("")
        for c in cards:
            title_txt = c["title"] + (" (Hebrew)" if c["hebrew_title"] else "")
            su = _safe_url(c["url"])
            bullet = (f"**{_md_esc(title_txt)}** — {su}" if su
                      else f"**{_md_esc(title_txt)}**")
            chip = c["raw_chip"]
            posted = c["posted"]
            meta = [f"📍 {c['loc']}"]
            # an undated role at a first-scan company: say "date unknown", never "—" next
            # to a heading that claims 48h freshness
            meta.append((f"🗓 {posted}" + c["age"]) if posted
                        else ("🗓 date not published" if not dated else "🗓 —"))
            if chip:
                meta.append(f"🎓 {chip}")
            out.append(f"- {bullet} · {' · '.join(meta)}")        # THE role-bullet shape: `_ROLE_BULLET`
        out.append("")

    for company in companies:
        _render(company, by_company[company], lines, fresh_cards)

    # The newly-covered section is rendered into its own list first, so its heading can
    # count the companies that actually produced a bullet — not the input list.
    newco_lines, newco_companies = [], 0
    by_new = {}
    for j in new_co_jobs:
        by_new.setdefault(j["company"], []).append(j)
    for company in sorted(by_new):
        before = len(newco_cards)
        _render(company, by_new[company], newco_lines, newco_cards, dated=False)
        if len(newco_cards) > before:
            newco_companies += 1
    if newco_cards:
        lines += ["---", "",
                  f"## Newly covered companies ({newco_companies})", "",
                  "Employers this scan reached for the **first time**, with whatever they "
                  "have open now — so these are not 48h-new, they are new *to you*. Where a "
                  "posting states its date it is shown; scraped cards often do not, and "
                  "\"we first saw it today\" is not a publication date. From tomorrow these "
                  "companies report like every other.", ""] + newco_lines

    # THE SUBJECT. Counted from the cards the two sections emitted — F from the 48h section,
    # C from the newly-covered one — so the number is the number of role bullets below it.
    # No level adjective: "senior" was shorthand for the experience bar the operator removed
    # on 2026-08-28 (docs/decisions/2026-08-28-analyst-scope.md), and it was already false
    # before that. This line is the mail's SUBJECT (the relay makes the issue title from it),
    # so it is the one sentence that cannot afford a qualifier; the split is in the subtitle.
    # When nothing is 48h-fresh the wording says what the mail IS, because every bullet in
    # it is then one the body itself says is NOT 48h-new.
    F, C = len(fresh_cards), len(newco_cards)
    email_cards = fresh_cards + newco_cards
    if F and C:
        # the split is IN the subject: "16 new roles" over one 48h role and fifteen at newly
        # covered companies would be the old defect inverted (wave 1), and the inbox list
        # shows no subtitle. The first number is still the number of bullets.
        title = (f"🎯 {F + C} new analytics roles ({F} posted in the last 48h, {C} at newly "
                 f"covered companies) — {run_date}")
    elif F:
        title = f"🎯 {F} new analytics role{'' if F == 1 else 's'} — {run_date}"
    elif C:
        title = (f"🎯 {C} analytics role{'' if C == 1 else 's'} at newly covered companies "
                 f"— {run_date}")
    else:
        title = f"🎯 0 new analytics roles — {run_date}"
    head = [f"# {title}", "",
            # "excluded", not "out of scope": the docs lane wrote the weaker word on
            # 2026-08-28 because `_NOT_A_JOB` was only enumerated in the singular and
            # `Data Analyst Interns` was accepted. 375@classifier closed the class in both
            # alphabets and pinned every variant, so the stronger promise is now the true
            # one. Do not strengthen it further: a title that never says "internship" still
            # reaches the LLM tier, which is judgement rather than exclusion.
            # the sentence follows the subject's case: a morning with no 48h role must not
            # open with "roles from the last 48h" over a section that says they are not
            ("Israeli high-tech scan — data / BI / analytics roles. Nothing posted in the last "
             f"48h at a company we already track; the {C} role{'' if C == 1 else 's'} below "
             f"{'is' if C == 1 else 'are'} at employers covered for the first time"
             if C and not F else
             "Israeli high-tech scan — data / BI / analytics roles from the **last 48h**, "
             "freshest first"
             + (f" — {C} of the {F + C} {'is' if C == 1 else 'are'} at employers covered for "
                f"the first time, in their own section below" if C else ""))
            + ". Any experience level; internships and student placements are "
            "excluded. Each role title links to apply.", ""]
    if board_url:
        head += [f"🔎 **[Open the full board →]({board_url})** — every role still open, "
                 "searchable & sortable.", ""]
    if not F and not C:
        head += ["_No new matching openings today._", ""]
    over = stats.get("email_overflow") or 0
    if over:
        head += [f"> {over} further new roles matched today and did not fit this email. "
                 f"They are on the board now, and they lead tomorrow's digest — nothing "
                 f"is dropped.", ""]

    # anything WRONG stands above the fold, bold, where a reader who never expands the audit
    # still sees it (docs/BACKLOG.md 127); the counts stay collapsed below
    s = stats
    alarms = []
    _email_issues = rolecard.cross_check(email_cards)
    _email_frag, _email_alarms = rolecard.report(email_cards, email_hidden[0])
    if _email_issues:
        _email_frag += ", " + _capped(_email_issues, 6)
        _email_alarms += _wrong_name_alarms(_email_issues)
    render_issues.setdefault("lines", []).append(f"email {_email_frag}")
    # the email's own alarms join the board's, so run.py's ::warning:: lines carry them too
    render_issues.setdefault("alarms", []).extend(a for a in _email_alarms if a not in render_issues["alarms"])
    if s.get("dead_sources"):
        alarms.append("- **Sources not producing:** " + "; ".join(_md_line(x) for x in s["dead_sources"]))
    if s.get("registry_alarms"):
        alarms.append("- **Registry:** " + "; ".join(_md_line(x) for x in s["registry_alarms"]))
    if s.get("stage_alarms"):
        alarms.append("- **Stages:** " + "; ".join(_md_line(x) for x in s["stage_alarms"]))
    # collapsed audit so the email stays clean but is still verifiable
    paths = ", ".join(f"{k}={v}" for k, v in sorted(s.get("paths", {}).items()))
    audit = [
        f"- Companies scanned: **{s.get('companies_scanned',0)}** (failed: {s.get('companies_failed',0)})",
        f"- Jobs fetched: {s.get('jobs_fetched',0)} · Israel-matched: {s.get('israel_matched',0)}",
        f"- Accepted: {s.get('accepted',0)} · after merge: {s.get('after_merge',0)} · **new: {s.get('new',0)}**",
        f"- Decision paths: {_md_line(paths)}",
        f"- LLM calls this run: {s.get('llm_calls',0)}"
        # printed whenever the counter EXISTS, zero included: a `0/148` morning used to render
        # identically to a run where the inline filler was never switched on (BACKLOG 263)
        + (f" · JDs fetched inline: {s.get('jd_filled_inline') or 0}" if "jd_filled_inline" in s else ""),
    ]
    if s.get("first_scan"):
        audit.append(f"- At newly covered companies: {s['first_scan']}")
    if s.get("email_overflow"):
        audit.append(f"- Held over (email cap): {s['email_overflow']}")
    for _line in s.get("fetch_health") or []:
        audit.append("- **Boards** " + _md_line(_line))
    if s.get("company_intel"):
        audit.append("- **Company intel:** " + "; ".join(_md_line(x) for x in s["company_intel"]))
    if s.get("roles"):
        audit.append("- **Roles:** " + "; ".join(_md_line(x) for x in s["roles"]))
    audit.append("- **Render:** " + " · ".join(_md_line(x) for x in render_issues["lines"]))
    if s.get("stages"):
        audit.append(f"- Stage order: {_md_line(s['stages'])}")
    if s.get("failed_companies"):
        audit.append("- Failed companies: " + _md_line(_capped(s["failed_companies"])))
    # The tripwire for the subject rule: the number the subject states is re-derived from the
    # TEXT of the whole delivered body (every role bullet has one shape, `_ROLE_BULLET`) —
    # the same text `grep -cE` counts in the morning check — and compared. Two independent
    # derivations: if a future edit changes the bullet shape, the counting, or lets a foreign
    # line grow the shape, the mismatch is a bold line in this mail, not a silent wrong
    # subject in the reader's inbox. Only the Render alarm line itself is not yet in the text.
    _mismatch = _subject_vs_body(title, "\n".join(head + lines + alarms + audit))
    if _mismatch:
        render_issues["alarms"].append(_mismatch)
    _render_alarms = list(render_issues.get("alarms") or [])
    if _render_alarms:
        alarms.append("- **Render:** " + "; ".join(_md_alarm(a) for a in _render_alarms))
    if alarms:
        lines += ["---", "**Needs a look**", ""] + alarms + [""]
    lines += ["---", "<details><summary>Run audit</summary>", ""] + audit + ["", "</details>"]
    return title, "\n".join(head + lines)


# THE role-bullet shape, as `_render` writes it (`- **title** — url · 📍 loc …`, or without the
# url when `_safe_url` refused it). `_subject_vs_body` counts these; that f-string is the only
# place they are written. Change one, change the other — pinned together by
# test_the_mail_subject_counts_every_role_bullet_the_mail_carries.
_ROLE_BULLET = re.compile(r"^- \*\*[^\n]*?\*\*(?: — \S+)? · 📍 ", re.M)
_SUBJECT_N = re.compile(r"^#?\s*🎯 (\d+) ")


def _subject_vs_body(title, body):
    """'' when the number the subject states is the number of role bullets `body` carries;
    otherwise one sentence naming both, for the mail's Render alarm."""
    m = _SUBJECT_N.match(str(title or ""))
    if not m:
        return f"email subject {str(title or '')[:60]!r} states no role count"
    said, carried = int(m.group(1)), len(_ROLE_BULLET.findall(str(body or "")))
    return "" if said == carried else f"email subject says {said} roles, the body carries {carried}"


# The cross-check shapes that stand above the fold, and what each one means for the reader.
# `same-posting` is a FACT (one url, two names) and says so; the other two are the guess the
# fact replaces. Filter first, then cap at three — the email path used to slice first and
# could push a real alarm out of the window with a shape it was about to discard.
_WRONG_NAME = ("same-posting", "shared-board", "title-twin")
_WRONG_NAME_TEXT = {"same-posting": "one posting url under two employer names — the same posting "
                                    "twice, or a listing page stored as one; two registry rows read "
                                    "one board (lane: registry)"}


def _wrong_name_alarms(issues, cap=3):
    """At most `cap` alarms, one per shape before any shape takes a second slot: three
    same-posting pairs on one morning must not push the only shared-board off the mail."""
    by_shape = {k: [x for x in issues if x.startswith(k + " ")] for k in _WRONG_NAME}
    picked = []
    while len(picked) < cap and any(by_shape.values()):
        for k in _WRONG_NAME:
            if by_shape[k] and len(picked) < cap:
                picked.append(by_shape[k].pop(0))
    return [f"{i} — {_WRONG_NAME_TEXT.get(i.split(' ', 1)[0], 'one posting may be under the wrong name, check the card')}"
            for i in picked]


def _capped(names, n=8):
    """Each failed company now carries its exception text (~100 chars); an outage morning
    with 30 failures must not be a 3,000-char line. Eight, then a count."""
    names = list(names or [])
    return ", ".join(names[:n]) + (f", +{len(names) - n} more" if len(names) > n else "")


def build_board_html(jobs, run_date, stats, company_info=None, analytics_html="", contact_url="",
                     # `heading` is also a CONTROL FLAG: `archived = "archived" in heading`
                     # below, and three more branches read it. A replacement must not carry
                     # that substring. "open" lives here rather than in the shared subtitle
                     # so the archive's own h1 supplies the contrast instead of contradicting
                     # it, and "at Israeli companies" rather than "in Israel" because the set
                     # is what we list, not what exists.
                     heading="open analytics roles at Israeli companies",
                     firmographics=None, ledger=None,
                     report=None):
    """Interactive board (GitHub Pages): an accessible, expandable, sortable TABLE.

    Columns: Company / Role / Location / Posted / Seniority. Rows expand (click or Enter/Space)
    to the company profile + role details + apply link; headers sort (click or Enter/Space,
    with real numeric seniority ranking); the search box filters live and shows a result count.
    Sticky header via a bounded-height scroll region. `analytics_html` injects a tracker;
    `contact_url` adds a Contact link.
    """
    company_info = company_info or {}
    firmographics = firmographics or {}
    ledger = ledger or {}
    archived = "archived" in heading

    # defensive: never render a run-together scraped card blob as a title — but count it,
    # so a scrape that mangles titles is a number in the mail, not a silent hole
    cards = [rolecard.build(j, run_date, ledger_rec=ledger.get(j.get("mkey")), company_info=company_info,
                            firmographics=firmographics, archived=archived) for j in jobs]
    hidden = sum(1 for c in cards if c["mangled"])
    cards = [c for c in cards if not c["mangled"]]
    issues = rolecard.cross_check(cards)
    frag, alarms = rolecard.report(cards, hidden)
    if issues:
        frag += ", " + _capped(issues, 6)
        alarms += _wrong_name_alarms(issues)
    ordered = sorted(cards, key=lambda c: str(c["posted"] or ""), reverse=True)
    n = len(ordered)

    def esc(s):
        return html.escape(str(s or ""))

    rows = []
    profiles = ordered
    _BADGE_TIP = {"must": "The posting marks this as a hard requirement",
                  "plus": "Marked as an advantage — nice to have, not required"}
    for c in ordered:
        company, rtitle = c["company"], c["title"]
        about, loc, pdate, age = c["about"], c["loc"], c["posted"], c["age"]
        chip, emp, skill_names = c["chip"], c["emp"], c["skill_names"]
        resp_parts, req_parts = c["resp"], c["req"]
        url = esc(_safe_url(c["url"]))
        blob = esc(c["blob"]).lower()
        emp_html = f' <span class="emp">{esc(emp)}</span>' if emp else ''
        fs0, pd0 = c["first_seen"], pdate[:10]
        repost = c["repost"]
        if repost:
            emp_html += (f' <span class="repb" title="Re-posted by the company on {esc(pd0)} — '
                         f'this listing first appeared here on {esc(fs0)}">reposted</span>')
        elif c["new"]:
            emp_html += ' <span class="newb">new</span>'
        # honest label: a LinkedIn URL is not "the company site" (judged on the host, not on
        # a tracking parameter that merely mentions linkedin.com)
        _host = urlsplit(_safe_url(c["url"])).netloc.lower() if url else ""
        apply_label = ('View the posting on LinkedIn →' if _host.endswith("linkedin.com")
                       else 'Apply on the company site →')
        apply = (f'<a class="apply" href="{url}" target="_blank" rel="noopener">'
                 f'{apply_label}</a>') if url else ''
        # --- two-column detail card: company + day-to-day (left) | demands (right) ---
        left = ""
        if about:
            left += f'<p class="about" dir="auto"><b>About {esc(company)}</b> — {esc(about)}</p>'
        facts = c["facts"]
        if facts:
            left += ('<p class="cofacts">'
                     + "".join(f'<span>{esc(f)}</span>' for f in facts) + '</p>')
        if repost:
            when = esc(", ".join(c["repost_dates"]) if c["repost_dates"] else pd0)
            left += (f'<p class="repline">↻ Re-posted {when} — this listing first '
                     f'appeared here {esc(fs0)}</p>')
        if c["also_listed_as"]:
            left += (f'<p class="repline" title="The same posting was fetched from another registry row; '
                     f'it is shown once, under the name the posting itself supports">'
                     f'Also listed as {esc(", ".join(c["also_listed_as"]))}</p>')
        if c["closed_on"]:
            left += f'<p class="repline">Closed on {esc(c["closed_on"])} — no longer on the employer&#8217;s page</p>'
        if c["issues"]:
            left += (f'<p class="about muted" dir="auto">Part of this card could not be built '
                     f'({esc("; ".join(c["issues"]))}) — open the listing for the details.</p>')
        ai_day, ai_req = c["ai_day"], c["ai_req"]
        if resp_parts or c["tasks"] or ai_day:
            left += '<p class="rlabel">Day to day</p>'
            chips = "".join(
                f'<button class="skilltag ttag" data-skill="{esc(tok)}" '
                f'title="{esc(roleprofile.TASK_DESC.get(lbl, lbl))} · click to filter the board">'
                f'{esc(lbl)}</button>' for lbl, tok in c["tasks"])
            chips += "".join(
                f'<button class="skilltag aitag" data-skill="{esc(tok)}" '
                f'title="{esc(roleprofile.AI_DESC.get(lbl, lbl))} · click to filter the board">'
                f'🤖 {esc(lbl)}</button>' for lbl, tok in ai_day)
            if chips:
                left += f'<div class="skills">{chips}</div>'
            if resp_parts:
                lis = "".join(f'<li dir="auto">{esc(p)}</li>' for p in resp_parts[:5])
                left += f'<ul class="reqs resp">{lis}</ul>'
        left += apply
        right = ""
        if req_parts:
            lis = []
            for txt, badge in req_parts:
                b = (f' <span class="rq rq-{badge}" title="{esc(_BADGE_TIP[badge])}">{badge}</span>'
                     if badge else "")
                lis.append(f'<li dir="auto">{esc(txt)}{b}</li>')
            right += (f'<p class="rlabel">What you&#8217;ll need</p>'
                      f'<ul class="reqs">{"".join(lis)}</ul>')
            if ai_req:
                achips = "".join(
                    f'<button class="skilltag aitag" data-skill="{esc(tok)}-req" '
                    f'title="{esc(roleprofile.AI_DESC.get(lbl, lbl))} — asked as prior '
                    f'experience · click to filter the board">'
                    f'🤖 {esc(lbl)}</button>' for lbl, tok in ai_req)
                right += f'<div class="skills">{achips}</div>'
        else:
            right += ('<p class="rlabel">What you&#8217;ll need</p>'
                      '<p class="about muted" dir="auto">Requirements aren&#8217;t captured '
                      'for this posting yet &mdash; open the listing for the full details.</p>')
        if skill_names:
            tags = "".join(
                f'<button class="skilltag" data-skill="{esc(s.lower())}" '
                f'title="{esc(roleprofile.SKILL_DESC.get(s, s))} · click to filter the board">'
                f'{esc(s)}</button>' for s in skill_names[:12])
            right += f'<p class="rlabel">Skills mentioned</p><div class="skills">{tags}</div>'
        if c["soft"]:
            stags = "".join(
                f'<button class="skilltag stag" data-skill="{esc(tok)}" '
                f'title="{esc(roleprofile.SOFT_DESC.get(lbl, lbl))} · click to filter the board">'
                f'{esc(lbl)}</button>' for lbl, tok in c["soft"])
            right += f'<p class="rlabel">Soft skills asked for</p><div class="skills">{stags}</div>'
        deg, deg_txt = c["degree"], c["deg_txt"]
        # no facts card on desktop — everything it held is on the row (or meaningless in
        # isolation, like a bare "Senior"). The dup-marked facts survive for MOBILE only,
        # where the Location/Posted/Degree columns are hidden.
        facts = [("Location", loc, True), ("Posted", c["rel_date"], True)]
        if deg_txt:
            facts.append(("Degree", deg_txt, True))
        shown = [f for f in facts if not f[2]]        # facts the row doesn't already show
        facts_html = ('<dl class="facts">' + "".join(
            f'<div class="fact{" dup" if dup else ""}"><dt>{esc(k)}</dt>'
            f'<dd{" class=nd" if (not v or v == "—") else ""}>{esc(v or "—")}</dd></div>'
            for k, v, dup in facts) + '</dl>')
        side = f'<aside class="dside{"" if shown else " monly"}">{facts_html}</aside>'
        detail = (f'<div class="dcard"><div class="dcol">{left}</div>'
                  f'<div class="dcol dcol2">{right}</div>{side}</div>')
        # dedicated columns carry the high-level ask: top skills, years, degree.
        # ALL skills render in the cell; the +N chip is computed live by JS from how
        # many actually fit, so dragging the column divider expands the visible list.
        if skill_names:
            sks = "".join(f'<span class="sk">{esc(s)}</span>' for s in skill_names)
            skl_cell = (f'<span class="sklist">{sks}</span>'
                        '<span class="skmore" style="display:none"></span>')
        else:
            skl_cell = '<span class="nd">—</span>'
        yrs_cell = f"{c['years']}+" if c["years"] else '<span class="nd">—</span>'
        if deg:
            deg_cell = esc(deg["level"]) + ((' <span class="rq rq-plus" title="The posting marks '
                                             'the degree as an advantage, not a requirement">plus</span>')
                                            if deg["status"] == "preferred" else '')
        else:
            deg_cell = '<span class="nd">—</span>'
        rows.append(
            f'<tr class="row" tabindex="0" role="button" aria-expanded="false" '
            f'data-blob="{blob}" data-company="{esc(company).lower()}" '
            f'data-role="{esc(rtitle).lower()}" data-loc="{esc(loc).lower()}" '
            f'data-date="{esc(pdate)}" data-years="{c["years"] or 99}" '
            f'data-deg="{c["deg_rank"]}" data-skills="{esc(" ".join(skill_names)).lower()}">'
            f'<td class="cco" title="{esc(company)}">{esc(c["display_company"])}</td>'
            f'<td class="cro">{esc(rtitle)}{emp_html}</td>'
            f'<td class="cskl">{skl_cell}</td>'
            f'<td class="cloc">{esc(loc)}</td>'
            f'<td class="cyrs" title="Years of experience asked for">{yrs_cell}</td>'
            f'<td class="cdeg">{deg_cell}</td>'
            f'<td class="cdate" title="{esc(pdate)}">{esc(c["rel_date"])}{esc(age)}</td></tr>'
            f'<tr class="detail"><td colspan="7"><div class="db">{detail}</div></td></tr>')

    # ---- aggregated demand view: what the market is asking for, computed per posting ----
    insights = ""
    if profiles and "archived" not in heading:
        agg = roleprofile.aggregate(profiles)

        def _bar(token, label, c, mx, desc=""):
            tip = (desc + " · " if desc else "") + f"{c} roles · click to filter"
            return (f'<button class="ibar" data-skill="{esc(token)}" title="{esc(tip)}">'
                    f'<span class="ibar-fill" style="width:{max(4, round(c / mx * 100))}%"></span>'
                    f'<span class="ibar-name">{esc(label)}</span><span class="ibar-n">{c}</span></button>')

        ccards = ""
        for clabel, items in agg["clusters"]:
            if not items:
                continue
            mx = items[0][1] or 1
            bars = "".join(_bar(s.lower(), s, c, mx, roleprofile.SKILL_DESC.get(s, ""))
                           for s, c in items)
            ccards += (f'<div class="ccard"><div class="fhead">{esc(clabel)}</div>'
                       f'<div class="cbars">{bars}</div></div>')
        if agg["tasks"]:
            mx = agg["tasks"][0][2] or 1
            bars = "".join(_bar(tok, lbl, c, mx, roleprofile.TASK_DESC.get(lbl, ""))
                           for lbl, tok, c in agg["tasks"])
            ccards += (f'<div class="ccard ctasks"><div class="fhead">Day-to-day focus'
                       f'<span class="fn">what these roles actually do</span></div>'
                       f'<div class="cbars">{bars}</div></div>')
        if agg["ai_req"] or agg["ai_day"]:
            mx = max([c for _, _, c in agg["ai_req"]] + [c for _, _, c in agg["ai_day"]]) or 1
            inner = ""
            if agg["ai_req"]:
                inner += ('<div class="aisub" title="The posting asks for prior AI '
                          'experience in its requirements">Required coming in</div>'
                          + "".join(_bar(tok + "-req", lbl, c, mx,
                                         roleprofile.AI_DESC.get(lbl, "") + " — asked as prior experience")
                                    for lbl, tok, c in agg["ai_req"]))
            if agg["ai_day"]:
                inner += ('<div class="aisub" title="AI appears in the responsibilities — '
                          'something the role does, learnable on the job">In the day-to-day</div>'
                          + "".join(_bar(tok, lbl, c, mx,
                                         roleprofile.AI_DESC.get(lbl, "") + " — part of the role\'s duties")
                                    for lbl, tok, c in agg["ai_day"]))
            ccards += (f'<div class="ccard cai"><div class="fhead">🤖 AI usage'
                       f'<span class="fn">required skill vs. part of the job</span></div>'
                       f'<div class="cbars">{inner}</div></div>')
        if agg["soft"]:
            mx = agg["soft"][0][2] or 1
            bars = "".join(_bar(tok, lbl, c, mx, roleprofile.SOFT_DESC.get(lbl, ""))
                           for lbl, tok, c in agg["soft"])
            ccards += (f'<div class="ccard csoft"><div class="fhead">Soft skills'
                       f'<span class="fn">asked for in requirements</span></div>'
                       f'<div class="cbars">{bars}</div></div>')
        if ccards:
            insights = (
                '<details class="insights"><summary>📊 Skills &amp; day-to-day demand — '
                f'across the {agg["with_skills"]} roles with captured postings '
                f'(of {agg["total"]} open; click anything to filter)</summary>'
                f'<div class="ins-clusters">{ccards}</div></details>')

    fresh = sum(1 for c in ordered if not c["age"])
    audit = (f"{n} {'archived' if archived else 'open'} roles · {fresh} posted recently · "
             f"{stats.get('companies_scanned',0)} companies scanned · refreshed {esc(run_date)}")
    if hidden or any(c["issues"] for c in cards):
        audit += f" · render: {frag}"
    contact = (f' · <a href="{esc(contact_url)}" target="_blank" rel="noopener">Contact</a>'
               if contact_url else '')
    if "archived" not in heading:
        contact += ' · <a href="archive.html">Job archive</a>'
    else:
        contact += ' · <a href="index.html">Back to live board</a>'
    # THE DATASET (roles lane's file, ARCHITECTURE §7c) is published beside this page by the
    # same workflow step (`daily-digest.yml`, "Publish the 2-week board"), so a relative link
    # is correct on Pages and nowhere else. Its population is NOT this page's: a 60-day
    # window on `last_seen`, closed roles included, and a store that only began observing on
    # 2026-08-16. So this string states nothing numeric; the script below fills the number,
    # window and coverage caveat from the file's own `roles.csv.meta.json` — the artefact's
    # truth, never a count computed here — and leaves this text when it cannot.
    # The per-page clause sits OUTSIDE the span on purpose: the script replaces the span's
    # text, and wave 1 found the first cut erasing the one clause the sentence exists for.
    contact += (' · <a href="roles.csv" download>Dataset (CSV)</a>: '
                '<span id="ds" aria-live="polite">one row per role, open and closed</span>'
                ' — this page lists only the ' + ('closed' if archived else 'open') + ' ones'
                ' · <a href="roles.csv.meta.json">columns</a>')

    css = """<style>
:root{color-scheme:light dark;--bg:#fff;--fg:#141821;--muted:#5b6470;--body:#333a44;--card:#f6f8fa;
--border:#e3e6ea;--line:#dfe3e8;--accent:#1a56db;--btn:#1f6feb;--head:#0a0d12;--rowh:#eef3fb;
--chipbg:#eef1f5;--emp:#8a5a00;--empbg:#fff4d6}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e9eef5;--muted:#9aa4b0;--body:#c4ccd6;
--card:#161b22;--border:#2a2f37;--line:#272d36;--accent:#6ea8ff;--btn:#2563eb;--head:#ffffff;
--rowh:#1a2130;--chipbg:#1e2530;--emp:#f0c674;--empbg:#3a2f12}}
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;
color:var(--fg);background:var(--bg);line-height:1.45}
.wrap{max-width:1560px;margin:0 auto;padding:18px 20px 40px}
h1{font-size:22px;margin:0 0 5px;color:var(--head);letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px;margin-bottom:14px}
#q{width:100%;padding:11px 13px;height:44px;font-size:15px;border:1px solid var(--border);
border-radius:10px;background:var(--card);color:var(--fg);margin-bottom:12px}
#q:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
#fbar{display:flex;align-items:center;gap:12px;margin:-4px 0 12px;font-size:12.5px;
color:var(--accent);font-weight:600}
#fbar[hidden]{display:none}
#fclear{border:1px solid var(--border);background:var(--card);color:var(--muted);cursor:pointer;
border-radius:999px;padding:3px 11px;font-size:11.5px;font-weight:600;font-family:inherit}
#fclear:hover{color:var(--accent);border-color:var(--accent)}
.tw{overflow:auto;max-height:calc(100vh - 150px);border:1px solid var(--border);border-radius:12px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:14px;
table-layout:fixed;min-width:880px}
thead th{position:sticky;top:0;z-index:5;background:var(--card);text-align:left;padding:11px 14px;
color:var(--muted);font-weight:600;font-size:12px;letter-spacing:.03em;text-transform:uppercase;
cursor:pointer;user-select:none;border-bottom:1px solid var(--border);white-space:nowrap;
box-shadow:0 2px 6px -4px rgba(0,0,0,.35);overflow:visible}
thead th:not(:last-child){border-right:1px solid var(--line)}
.rz{position:absolute;top:0;right:-5px;width:11px;height:100%;cursor:col-resize;z-index:7}
.rz:hover,.rz.on{background:linear-gradient(to right,transparent 4px,var(--accent) 4px,
var(--accent) 6px,transparent 6px)}
thead th:hover{color:var(--fg)} thead th:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
th[aria-sort=ascending]:after{content:" \\2191";color:var(--accent)}
th[aria-sort=descending]:after{content:" \\2193";color:var(--accent)}
tbody td{padding:11px 14px;border-top:1px solid var(--line);vertical-align:top}
tbody tr.row:first-child td{border-top:none}
tr.row{cursor:pointer} tr.row:hover td{background:var(--rowh)}
tr.row:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
td.cco{color:var(--body);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
td.cro{font-weight:700;color:var(--head);font-size:14.5px}
td.cco::before{content:"\\25B8  ";color:var(--muted)}
tr.row[aria-expanded=true] td.cco::before{content:"\\25BE  "}
td.cdate{white-space:nowrap;color:var(--muted);font-size:13px}
td.cro{overflow:hidden}
td.cloc{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
td.cskl{color:var(--muted);font-size:12.5px;white-space:nowrap;overflow:hidden;position:relative}
.sklist{display:inline-block;max-width:calc(100% - 30px);overflow:hidden;white-space:nowrap;
vertical-align:middle}
.sk+.sk::before{content:" · "}
.skmore{position:absolute;right:6px;top:50%;transform:translateY(-50%);color:var(--accent);
font-weight:700;font-size:11px;background:var(--chipbg);border-radius:6px;padding:1px 6px}
td.cyrs{white-space:nowrap;font-size:13px;color:var(--body);font-variant-numeric:tabular-nums}
td.cdeg{white-space:nowrap;font-size:12.5px;color:var(--body)}
td .nd{color:var(--muted)}
.sen{display:inline-block;white-space:nowrap;font-size:12px;font-weight:600;padding:2px 9px;
border-radius:999px;background:var(--chipbg);color:var(--fg)}
.sen.empty{background:transparent;border:1px dashed var(--border);color:var(--muted);font-weight:500}
/* one tidy vocabulary — Lead+ carries the most weight, Junior the least */
.sen-leadp{background:var(--empbg);color:var(--emp)}
.sen-junior,.sen-mid{background:transparent;border:1px solid var(--border);color:var(--muted)}
.emp{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:6px;
background:var(--empbg);color:var(--emp);vertical-align:middle}
.newb{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:6px;
background:#1a7f37;color:#fff;vertical-align:middle}
.repb{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:6px;
background:var(--empbg);color:var(--emp);vertical-align:middle;cursor:help}
tr.detail{display:none} tr.detail.open{display:table-row}
tr.detail td{background:var(--card);border-top:none;padding:0}
.db{padding:20px 18px 22px}
.dcard{display:grid;grid-template-columns:minmax(0,10fr) minmax(0,11fr);gap:6px 60px;
align-items:start;max-width:1280px}
.dcol{min-width:0}
.repline{color:var(--emp);font-size:12.5px;margin:-6px 0 16px;font-weight:500}
.dside{display:none}
.about{color:var(--body);margin:0 0 10px;font-size:14px;line-height:1.68}
.cofacts{margin:0 0 16px;display:flex;flex-wrap:wrap;gap:6px}
.cofacts span{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 9px;white-space:nowrap}
.about b{color:var(--fg);font-weight:700} .about.muted{color:var(--muted);font-style:italic}
.rlabel{display:flex;align-items:center;gap:12px;font-size:11px;text-transform:uppercase;
letter-spacing:.07em;color:var(--muted);font-weight:700;margin:2px 0 10px}
.rlabel:after{content:"";flex:1 1 auto;height:1px;background:var(--line)}
ul.reqs{margin:0 0 16px;padding:0;list-style:none}
ul.reqs li{position:relative;padding-left:18px;margin:7px 0;color:var(--body);font-size:13.5px;
line-height:1.5}
ul.reqs li:before{content:"";position:absolute;left:2px;top:8px;width:5px;height:5px;
border-radius:50%;background:var(--accent)}
.rq{display:inline-block;font-size:10px;font-weight:700;padding:1px 6px;border-radius:5px;
vertical-align:1px;text-transform:uppercase;letter-spacing:.04em}
.rq-must{background:var(--empbg);color:var(--emp)}
.rq-plus{background:transparent;border:1px solid var(--border);color:var(--muted)}
.facts{margin:0;border:1px solid var(--border);border-radius:11px;overflow:hidden;background:var(--bg)}
.fact.dup{display:none} .dside.monly{display:none}
.fact{display:flex;justify-content:space-between;align-items:baseline;gap:14px;padding:10px 13px;
border-top:1px solid var(--line)} .fact:first-child{border-top:none}
.fact dt{margin:0;color:var(--muted);font-size:10.5px;font-weight:700;text-transform:uppercase;
letter-spacing:.05em}
.fact dd{margin:0;color:var(--fg);font-size:13px;font-weight:600;text-align:right}
.fact dd.nd{color:var(--muted);font-weight:500}
.apply{display:inline-block;margin-top:2px;padding:11px 18px;background:var(--btn);color:#fff;
text-decoration:none;border-radius:9px;font-weight:600;font-size:13.5px}
.apply:hover{filter:brightness(1.08)} .apply:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.skills{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px}
.skilltag{display:inline-block;font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;
background:var(--chipbg);color:var(--fg);border:1px solid var(--border);cursor:pointer;
font-family:inherit}
.skilltag:hover{border-color:var(--accent);color:var(--accent)}
.insights{margin:0 0 12px;border:1px solid var(--border);border-radius:12px;background:var(--card)}
.insights summary{padding:12px 16px;cursor:pointer;font-size:13.5px;font-weight:600;color:var(--fg);
user-select:none}
.insights summary:hover{color:var(--accent)}
.insights[open] summary{border-bottom:1px solid var(--line)}
.ins-clusters{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px;
padding:16px}
.ccard{border:1px solid var(--border);border-radius:10px;padding:12px 13px;background:var(--bg)}
.ccard .fhead{margin-bottom:9px}
.cbars{display:flex;flex-direction:column;gap:4px}
.ctasks .ibar-fill{background:var(--emp)}
.cai .ibar-fill{background:#1a7f37;opacity:.22}
.csoft .ibar-fill{background:#8250df;opacity:.2}
.stag{border-style:dotted}
.aisub{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
color:var(--muted);margin:7px 0 2px;cursor:help}
.aisub:first-child{margin-top:0}
.aitag{border-style:solid;border-color:#1a7f37;color:inherit}
.aitag:hover{border-color:#2ea043;color:#2ea043}
.legend{margin:16px 0 0;border:1px solid var(--border);border-radius:12px;background:var(--card)}
.legend summary{padding:11px 16px;cursor:pointer;font-size:12.5px;font-weight:600;color:var(--muted)}
.legend summary:hover{color:var(--fg)}
.legend[open] summary{border-bottom:1px solid var(--line)}
.legend .lg{padding:14px 18px;font-size:12.5px;color:var(--body);line-height:1.65;max-width:110ch}
.legend .lg p{margin:0 0 10px} .legend .lg b{color:var(--fg)}
.ibar{position:relative;display:flex;align-items:center;gap:8px;height:26px;border:none;
background:transparent;cursor:pointer;padding:0 8px;border-radius:6px;font-family:inherit;
overflow:hidden;text-align:left}
.ibar:hover .ibar-name{color:var(--accent)}
.ibar-fill{position:absolute;left:0;top:0;bottom:0;background:var(--accent);opacity:.14;
border-radius:6px}
.ibar-name{position:relative;font-size:12.5px;font-weight:600;color:var(--fg);flex:1 1 auto;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ibar-n{position:relative;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.ins-fams{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
gap:12px;padding:0 16px 16px}
.fcard{border:1px solid var(--border);border-radius:10px;padding:11px 13px;background:var(--bg)}
.fhead{font-size:12.5px;font-weight:700;color:var(--fg);margin-bottom:8px;display:flex;
justify-content:space-between;align-items:baseline;gap:8px}
.fn{font-size:11px;color:var(--muted);font-weight:500;white-space:nowrap}
.fskills{display:flex;flex-wrap:wrap;gap:5px}
.fskills .skilltag{font-size:11px;padding:2px 8px}
ul.reqs.resp li:before{background:var(--emp)}
.ttag{border-style:dashed}
.nores{padding:26px;text-align:center;color:var(--muted)}
.foot{color:var(--muted);font-size:12px;margin-top:16px} .foot a{color:var(--accent)}
@media(max-width:600px){td.cloc,th.hloc,td.cdate,th.hdate,td.cskl,th.hskl,td.cdeg,th.hdeg{display:none}
.wrap{padding:14px 10px 30px} td.cro{font-size:14px} h1{font-size:22px}
.db{padding:16px 13px 18px} .dcard{grid-template-columns:1fr;gap:14px}
.fact.dup{display:flex} .dside{display:block;order:-1}}
</style>"""

    js = """<script>
var tb=document.getElementById('tb'),q=document.getElementById('q'),
    cnt=document.getElementById('cnt'),nores=document.getElementById('nores');
function R(){return [].slice.call(tb.querySelectorAll('tr.row'));}
function filt(){var v=q.value.toLowerCase().split(/\\s+/).filter(Boolean),shown=0;
  R().forEach(function(r){var s=v.every(function(w){return r.dataset.blob.indexOf(w)>-1;});
    r.style.display=s?'':'none'; if(!s){r.nextElementSibling.classList.remove('open');r.setAttribute('aria-expanded','false');}
    if(s)shown++;});
  if(cnt)cnt.textContent=shown; if(nores)nores.style.display=shown?'none':'';
  var fb=document.getElementById('fbar'),fbt=document.getElementById('fbtxt');
  if(fb){if(q.value.trim()){fb.hidden=false;
    fbt.textContent='Filtering by “'+q.value.trim()+'” — showing '+shown+' of '+R().length+' roles';}
  else fb.hidden=true;}
  updSk();}
q.addEventListener('input',filt);
var fclear=document.getElementById('fclear');
if(fclear)fclear.addEventListener('click',function(){q.value='';filt();q.focus();});
/* skills cells hold the FULL list; count how many names are clipped and show +N */
function updSk(){[].slice.call(document.querySelectorAll('td.cskl')).forEach(function(td){
  var list=td.querySelector('.sklist'),more=td.querySelector('.skmore');
  if(!list||!more||td.offsetWidth===0)return;
  var base=list.offsetLeft,lim=list.clientWidth+2,hidden=0;
  [].slice.call(list.children).forEach(function(s){
    if(s.offsetLeft-base+s.offsetWidth>lim)hidden++;});
  if(hidden>0){more.textContent='+'+hidden;more.style.display='';}
  else{more.style.display='none';}});}
/* draggable column dividers on the headers */
var cols=[].slice.call(document.querySelectorAll('colgroup col')),
    ths=[].slice.call(document.querySelectorAll('thead th'));
[].slice.call(document.querySelectorAll('.rz')).forEach(function(h){
  h.addEventListener('click',function(e){e.stopPropagation();});
  h.addEventListener('keydown',function(e){e.stopPropagation();});
  h.addEventListener('pointerdown',function(e){
    e.preventDefault();e.stopPropagation();h.classList.add('on');
    if(h.setPointerCapture)try{h.setPointerCapture(e.pointerId);}catch(_){}
    var ci=+h.dataset.ci,startX=e.clientX,startW=ths[ci].getBoundingClientRect().width;
    function mv(ev){cols[ci].style.width=Math.max(56,startW+ev.clientX-startX)+'px';}
    function up(){document.removeEventListener('pointermove',mv);
      document.removeEventListener('pointerup',up);h.classList.remove('on');
      justRz=true;setTimeout(function(){justRz=false;},0);updSk();}
    document.addEventListener('pointermove',mv);
    document.addEventListener('pointerup',up);});});
window.addEventListener('resize',updSk);
updSk();
function toggle(r,e){if(e&&e.target&&e.target.closest('a'))return;
  var open=r.nextElementSibling.classList.toggle('open'); r.setAttribute('aria-expanded',open);}
R().forEach(function(r){
  r.addEventListener('click',function(e){toggle(r,e);});
  r.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle(r,e);}});});
var dir={};
function sortBy(th){var k=th.dataset.k;dir[k]=!dir[k];var m=dir[k]?1:-1;
  var ps=R().map(function(r){return [r,r.nextElementSibling];});
  ps.sort(function(a,b){
    if(k==='years'||k==='deg'){return ((+a[0].dataset[k]||0)-(+b[0].dataset[k]||0))*m;}
    var x=a[0].dataset[k]||'',y=b[0].dataset[k]||''; return x<y?-m:x>y?m:0;});
  ps.forEach(function(p){tb.appendChild(p[0]);tb.appendChild(p[1]);});
  [].slice.call(document.querySelectorAll('th[data-k]')).forEach(function(t){t.setAttribute('aria-sort','none');});
  th.setAttribute('aria-sort',dir[k]?'ascending':'descending');}
var justRz=false;
[].slice.call(document.querySelectorAll('th[data-k]')).forEach(function(th){
  th.addEventListener('click',function(){if(justRz){justRz=false;return;}sortBy(th);});
  th.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();sortBy(th);}});});
[].slice.call(document.querySelectorAll('[data-skill]')).forEach(function(b){
  b.addEventListener('click',function(){q.value=b.dataset.skill;filt();
    document.querySelector('.tw').scrollIntoView({behavior:'smooth',block:'start'});});});
var ds=document.getElementById('ds');
if(ds&&window.fetch){fetch('roles.csv.meta.json').then(function(r){if(!r.ok)throw 0;return r.json();}).then(function(d){
  var w=d.window||{},st=d.store||{};if(typeof d.rows!=='number'||!isFinite(d.rows)||d.rows<0||!w.start||!w.end)return;
  ds.textContent=d.rows+' roles, '+w.start+'..'+w.end+', open and closed'
    +(w.fully_covered?'':(st.earliest_first_seen?' — observations begin '+st.earliest_first_seen:''))
    +(d.run_date?'; regenerated '+d.run_date:'');}).catch(function(){});}
</script>"""

    head = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Israeli analytics jobs — {esc(run_date)}</title>' + css
            + '</head><body><div class="wrap">')
    top = (f'<h1><span id="cnt">{n}</span> ' + esc(heading) + '</h1>'
           # ONE string, rendered on the board AND the archive. It said "open roles,
           # refreshed daily" under the archive's own "<n> archived roles (no longer on the
           # employer's careers page)" — false for all 61 archived rows. Every clause here
           # must be true on both pages, which is why "open" moved up into the board's h1.
           '<div class="sub">Data / BI / analytics · any experience level · '
           'refreshed daily · click a row to expand, a header to sort</div>'
           '<input id="q" type="search" aria-label="Filter roles" '
           'placeholder="Filter by company, role, skill, or location…">'
           '<div id="fbar" hidden><span id="fbtxt"></span>'
           '<button id="fclear" type="button" title="Clear the filter">✕ clear filter</button></div>')
    empty_row = ('<tr id="nores" style="display:none"><td colspan="7" class="nores">'
                 'No roles match your filter.</td></tr>')
    rz = '<span class="rz" data-ci="{i}" title="Drag to resize column"></span>'
    table = ('<div class="tw"><table>'
             '<colgroup><col style="width:165px"><col><col style="width:250px">'
             '<col style="width:135px"><col style="width:72px"><col style="width:95px">'
             '<col style="width:105px"></colgroup>'
             '<thead><tr>'
             '<th data-k="company" tabindex="0" role="columnheader" aria-sort="none">Company' + rz.format(i=0) + '</th>'
             '<th data-k="role" tabindex="0" role="columnheader" aria-sort="none">Role' + rz.format(i=1) + '</th>'
             '<th data-k="skills" tabindex="0" role="columnheader" aria-sort="none" class="hskl">Skills' + rz.format(i=2) + '</th>'
             '<th data-k="loc" tabindex="0" role="columnheader" aria-sort="none" class="hloc">Location' + rz.format(i=3) + '</th>'
             '<th data-k="years" tabindex="0" role="columnheader" aria-sort="none" class="hyrs" '
             'title="Years of experience asked for">Years' + rz.format(i=4) + '</th>'
             '<th data-k="deg" tabindex="0" role="columnheader" aria-sort="none" class="hdeg">Degree' + rz.format(i=5) + '</th>'
             '<th data-k="date" tabindex="0" role="columnheader" aria-sort="none" class="hdate">Posted</th>'
             '</tr></thead><tbody id="tb">'
             + ("".join(rows) + empty_row if rows
                else '<tr><td colspan="7" class="nores">No open roles right now.</td></tr>')
             + '</tbody></table></div>')
    # ---- on-page documentation of the tagging system (kept in sync with the code) ----
    legend = ""
    if "archived" not in heading:
        tg = " · ".join(f"<b>{esc(l)}</b> ({esc(roleprofile.TASK_DESC.get(l, ''))})"
                        for l, _, _ in roleprofile.TASK_GROUPS)
        au = " · ".join(f"<b>{esc(l)}</b> ({esc(d)})" for l, d in roleprofile.AI_DESC.items())
        cl = ", ".join(l for _, l in roleprofile.CLUSTERS)
        legend = (
            '<details class="legend"><summary>ℹ️ How the tags on this board are computed</summary>'
            '<div class="lg">'
            '<p><b>Everything is extracted deterministically from the posting text</b> — a fixed '
            'keyword lexicon and header rules, no AI guessing. A tag can be missing simply because '
            'the posting never stated it; postings without a captured description show no tags at all.</p>'
            f'<p><b>Skills</b> are matched from a curated {len(roleprofile.SKILLS)}-term lexicon and grouped into '
            f'non-overlapping clusters: {esc(cl)}. Hover any tag for its meaning.</p>'
            '<p><b>MUST / PLUS badges</b> mirror the posting&#8217;s own wording (&#8220;a must&#8221;, '
            '&#8220;an advantage&#8221;, חובה / יתרון) — absence of a badge means the posting didn&#8217;t '
            'mark that line. <b>Years</b> is the experience figure stated nearest to '
            '&#8220;experience&#8221;. <b>Degree</b> shows the level and fields asked for; '
            '&#8220;plus&#8221; means the posting itself calls the degree an advantage.</p>'
            f'<p><b>Day-to-day groups</b> classify the responsibilities section: {tg}. '
            'A chip appears only when a group matches <b>multiple</b> responsibility bullets — '
            'it marks an emphasis of the role, not a passing mention — and chips are ordered '
            'by how dominant each theme is.</p>'
            f'<p><b>🤖 AI usage</b> classifies what the analyst is expected to do with AI, judged '
            f'from the words around each AI mention: {au}. WHERE the mention sits matters: in the '
            'requirements section it is <b>prior experience you must bring</b>; in the '
            'responsibilities it is <b>part of the job</b> — learnable, not a bar to entry. The '
            'dashboard and chips keep the two apart. Mentions of the company&#8217;s own AI '
            'product (&#8220;analyze our AI agents&#8221;) are deliberately NOT counted — that is '
            'product analysis, not AI usage.</p>'
            '<p><b>Soft skills</b> (dotted chips) are tagged from the requirements section only — '
            'the person the posting describes, separate from the toolbox: communication, ownership, '
            'business acumen, curiosity, and so on. Hover any chip for its meaning.</p>'
            '<p><b>reposted</b> marks a posting whose date was bumped 3+ days after this board first '
            'saw it, with the original date in the card.</p>'
            '</div></details>')
    foot = f'<div class="foot">{esc(audit)}{contact}</div>'
    page = (head + top + insights + table + legend + foot + '</div>' + js
            + analytics_html + '</body></html>')
    if isinstance(report, dict):        # only once the page exists: a raise above leaves it empty
        report.update(cards=cards, hidden=hidden, issues=issues, frag=frag, alarms=alarms)
    return page


def _path_label(path):
    return {
        "keyword": "keyword",
        "keyword_nollm": "keyword(no-llm)",
        "llm": "LLM",
        "llm_cache": "LLM(cached)",
        "llm_failed_fallback": "LLM-failed→fallback",
        "llm_skipped": "LLM-skipped→fallback",
    }.get(path, path or "?")


def build_digest(jobs, run_date, stats):
    """Return (subject, html, text).

    `jobs` are merged+new accepted jobs, each with keys: company, title, location, url,
    posted_date, sources (list), and `_class` (the classify() result dict).
    `stats` is a dict of run counters.
    """
    n = len(jobs)
    subject = f"[Israeli Jobs] {n} new senior analytics opening" + ("" if n == 1 else "s") + f" — {run_date}"

    # group by company (alphabetical), jobs within a company by posted_date desc
    by_company = {}
    for j in jobs:
        by_company.setdefault(j["company"], []).append(j)
    for c in by_company:
        by_company[c].sort(key=lambda j: str(j.get("posted_date") or ""), reverse=True)

    # ---------- plaintext ----------
    tl = [subject, "=" * len(subject), ""]
    if n == 0:
        tl.append("No new matching openings today.")
    for company in sorted(by_company):
        tl.append(f"\n{company}")
        tl.append("-" * len(company))
        for j in by_company[company]:
            src = "+".join(j.get("sources", [])) or j.get("ats_platform", "")
            path = _path_label(j.get("_class", {}).get("path"))
            tl.append(f"  • {j['title']}")
            tl.append(f"      {j.get('location') or '—'} | posted {_fmt_date(j.get('posted_date'))} | via {src} | match:{path}")
            tl.append(f"      {j.get('url') or ''}")
    tl.append("")
    tl.append(_text_audit(stats))
    text = "\n".join(tl)

    # ---------- HTML ----------
    def esc(s):
        return html.escape(str(s or ""))

    hb = [
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:720px;margin:0 auto;color:#1a1a1a;">',
        f'<h2 style="margin:0 0 4px;">{esc(str(n))} new senior analytics opening{"" if n==1 else "s"}</h2>',
        f'<div style="color:#666;font-size:13px;margin-bottom:16px;">Israeli high-tech ATS scan · {esc(run_date)}</div>',
    ]
    if n == 0:
        hb.append('<p style="color:#666;">No new matching openings today.</p>')
    for company in sorted(by_company):
        hb.append(f'<h3 style="margin:22px 0 6px;border-bottom:1px solid #eee;padding-bottom:4px;">{esc(company)}</h3>')
        for j in by_company[company]:
            src = "+".join(j.get("sources", [])) or j.get("ats_platform", "")
            path = _path_label(j.get("_class", {}).get("path"))
            url = esc(_safe_url(j.get("url")))
            title = esc(j.get("title"))
            title_html = f'<a href="{url}" style="color:#1a56db;text-decoration:none;">{title}</a>' if url else title
            hb.append(
                '<div style="margin:8px 0 12px;">'
                f'<div style="font-size:15px;font-weight:600;">{title_html}</div>'
                f'<div style="color:#555;font-size:13px;margin-top:2px;">'
                f'{esc(j.get("location") or "—")} &nbsp;·&nbsp; posted {esc(_fmt_date(j.get("posted_date")))} '
                f'&nbsp;·&nbsp; via {esc(src)} '
                f'&nbsp;·&nbsp; <span style="color:#888;">match: {esc(path)}</span>'
                '</div></div>'
            )
    hb.append(_html_audit(stats, esc))
    hb.append("</div>")
    return subject, "\n".join(hb), text


def _text_audit(s):
    paths = s.get("paths", {})
    lines = [
        "-" * 40,
        "RUN AUDIT",
        f"  companies scanned: {s.get('companies_scanned', 0)}  (failed: {s.get('companies_failed', 0)})",
        f"  jobs fetched: {s.get('jobs_fetched', 0)}  | Israel-matched: {s.get('israel_matched', 0)}",
        f"  accepted: {s.get('accepted', 0)}  | after merge: {s.get('after_merge', 0)}  | NEW (this digest): {s.get('new', 0)}",
        f"  decision paths: " + ", ".join(f"{k}={v}" for k, v in sorted(paths.items())),
        f"  LLM calls this run: {s.get('llm_calls', 0)}"
        + (f"  | JDs fetched inline: {s.get('jd_filled_inline', 0)}"
           if s.get("jd_filled_inline") else ""),
    ]
    if s.get("email_overflow"):
        lines.append(f"  held over (email cap): {s['email_overflow']}")
    if s.get("dead_sources"):
        lines.append("  SOURCES NOT PRODUCING: " + "; ".join(s["dead_sources"]))
    if s.get("registry_alarms"):
        lines.append("  REGISTRY: " + "; ".join(s["registry_alarms"]))
    if s.get("stage_alarms"):
        lines.append("  STAGES: " + "; ".join(s["stage_alarms"]))
    for _line in s.get("fetch_health") or []:
        lines.append("  BOARDS " + _line)
    if s.get("company_intel"):
        lines.append("  COMPANY INTEL: " + "; ".join(s["company_intel"]))
    if s.get("roles"):
        lines.append("  ROLES: " + "; ".join(s["roles"]))
    if s.get("render"):
        lines.append("  RENDER: " + " · ".join(s["render"]))
    if s.get("stages"):
        lines.append(f"  stage order: {s['stages']}")
    if s.get("failed_companies"):
        lines.append("  failed companies: " + _capped(s["failed_companies"]))
    return "\n".join(lines)


def _html_audit(s, esc):
    esc = (lambda x, _e=esc: _e(str(x or "")))          # a bare html.escape chokes on ints; 0 renders blank as before
    paths = s.get("paths", {})
    fc = _capped(s.get("failed_companies", []))
    return (
        '<div style="margin-top:28px;padding:12px 14px;background:#f7f7f8;border-radius:8px;'
        'font-size:12px;color:#666;">'
        '<div style="font-weight:600;color:#444;margin-bottom:6px;">Run audit</div>'
        f'Companies scanned: {esc(s.get("companies_scanned",0))} (failed: {esc(s.get("companies_failed",0))})<br>'
        f'Jobs fetched: {esc(s.get("jobs_fetched",0))} · Israel-matched: {esc(s.get("israel_matched",0))}<br>'
        f'Accepted: {esc(s.get("accepted",0))} · after merge: {esc(s.get("after_merge",0))} · '
        f'<b>NEW: {esc(s.get("new",0))}</b><br>'
        f'Decision paths: {esc(", ".join(f"{k}={v}" for k,v in sorted(paths.items())))}<br>'
        f'LLM calls this run: {esc(s.get("llm_calls",0))}'
        + (f' · JDs fetched inline: {esc(s.get("jd_filled_inline",0))}'
           if s.get("jd_filled_inline") else "")
        + (f' · held over (email cap): {esc(s.get("email_overflow",0))}'
           if s.get("email_overflow") else "")
        + (f'<br><b>Sources not producing:</b> {esc("; ".join(s.get("dead_sources") or []))}'
           if s.get("dead_sources") else "")
        + (f'<br><b>Registry:</b> {esc("; ".join(s.get("registry_alarms") or []))}'
           if s.get("registry_alarms") else "")
        + (f'<br><b>Stages:</b> {esc("; ".join(s.get("stage_alarms") or []))}'
           if s.get("stage_alarms") else "")
        + "".join(f'<br><b>Boards</b> {esc(_line)}' for _line in (s.get("fetch_health") or []))
        + (f'<br><b>Company intel:</b> {esc("; ".join(s.get("company_intel") or []))}'
           if s.get("company_intel") else "")
        + (f'<br><b>Roles:</b> {esc("; ".join(s.get("roles") or []))}'
           if s.get("roles") else "")
        + (f'<br><b>Render:</b> {esc(" · ".join(s.get("render") or []))}'
           if s.get("render") else "")
        + (f'<br>Stage order: {esc(s.get("stages",""))}' if s.get("stages") else "")
        + (f'<br>Failed companies: {esc(fc)}' if fc else "")
        + '</div>'
    )


# names other lanes' tests reach through this module
_firmo_facts = rolecard.firmo_facts


def render_all(email_jobs, board_jobs, arch_jobs, run_date, stats, company_info=None, *,
               firmographics=None, board_url="", analytics_html="", contact_url="", ledger=None):
    """Every product from one call, board and archive FIRST so their render report reaches
    the mail that is built last. Returns a dict:

        board_html, board_ok              -> docs/index.html (write only when ok)
        archive_html, archive_ok          -> docs/archive.html (write only when ok)
        md_title, md_body, email_ok       -> digests/latest.md (the email; a stub naming the failure when not ok)
        subject, html, text               -> the legacy digest (only `subject` is read)
        render_lines                      -> the `Render:` line's fragments, = the mail's (for the payload)
        warnings                          -> what run.py should print as ::warning::

    Never raises for a product's sake: a renderer that fails is reported (a warning, a bold
    line in the mail) and NOT written, so yesterday's board stays published; the other
    products still ship — an exception here would lose the morning's verdicts (they are
    saved before rendering, but the email and board would be blank).
    """
    ledger = ledger or {}
    out = {"render_lines": [], "warnings": []}
    issues = {"lines": [], "alarms": []}

    def _product(name, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            msg = f"{name} FAILED ({e.__class__.__name__}: {str(e)[:80]}) — yesterday's file kept"
            issues["alarms"].append(msg)
            return None

    rep_b, rep_a = {}, {}
    board = _product("board", lambda: build_board_html(
        board_jobs, run_date, stats, company_info, analytics_html=analytics_html,
        contact_url=contact_url, firmographics=firmographics, ledger=ledger, report=rep_b))
    archive = _product("archive", lambda: build_board_html(
        arch_jobs, run_date, stats, company_info=company_info,
        heading="archived roles (no longer on the employer's careers page)",
        firmographics=firmographics, ledger=ledger, report=rep_a))
    for label, rep in (("board", rep_b), ("archive", rep_a)):
        if rep:
            issues["lines"].append(f"{label} {rep['frag']}")
            issues["alarms"] += [a for a in rep["alarms"] if a not in issues["alarms"]]
    # a product that failed is NOT written: run.py keeps yesterday's file on disk, so the
    # public board never shows an apology page (the failure is in the mail and the log)
    out["board_ok"], out["archive_ok"] = board is not None, archive is not None
    out["board_html"], out["archive_html"] = board or "", archive or ""
    md = _product("email", lambda: build_markdown(
        email_jobs, run_date, stats, company_info, board_url=board_url,
        firmographics=firmographics, ledger=ledger, render_issues=issues))
    out["email_ok"] = md is not None
    if md is None:
        title = f"🎯 digest {run_date} — the email could not be rendered"
        md = (title, f"# {title}\n\n**Needs a look**\n\n- **Render:** "
              + "; ".join(_md_alarm(a) for a in issues["alarms"]) + "\n\n- **Render:** "
              + " · ".join(_md_line(x) for x in issues["lines"]))
    out["md_title"], out["md_body"] = md
    out["render_lines"] = list(issues["lines"])
    legacy = _product("legacy digest", lambda: build_digest(email_jobs, run_date,
                                                             {**stats, "render": out["render_lines"]}))
    out["subject"], out["html"], out["text"] = legacy if legacy else (
        f"[Israeli Jobs] digest — {run_date}", "", "")
    out["warnings"] = [f"render: {a}" for a in dict.fromkeys(issues["alarms"])]
    return out

