"""The secrethunter.io company catalog, read from its sitemap — names and candidate handles.

WHAT THIS IS. secrethunter.io publishes a sitemap of 2,703 company pages. The slug of each
`/companies/<slug>` URL is, usually, the company's LinkedIn handle. That handle is the one
thing `auto_expand`'s free rung can turn into the company's OWN domain
(`auto_expand._site_from_guess`: guess `<handle>.<tld>`, then REFUSE it unless the page names
the company AND links back to `linkedin.com/company/<handle>`). 514 of the 517 queue entries
carry an aggregator posting URL instead of a domain, which is why `resolve_llm._verify` can
confirm almost nothing; a handle is the cheapest evidence that changes that.

WHAT THIS DELIBERATELY IS NOT. It does not read the company PAGES. Measured 2026-08-27, the
schema.org JSON-LD on those pages — which carries `Organization.sameAs`, the company's real
domain, and an `ItemList` of every open job title — is served ONLY to an allowlist of named
search-engine crawlers:

    curl · Chrome · no UA · an honest `AnalystJobsIL/1.0` UA · `Claude-User` ·
    `?_escaped_fragment_=`     -> 34,181 bytes, 2 ld+json blocks, no company data at all.
                                  That size is CONSTANT: byte-identical across 26 different
                                  companies, which is the tell -- a real page varies.
    Googlebot · bingbot · ClaudeBot -> the Organization and the ItemList. This body is NOT a
                                  constant size (it contains the job list): 38,649 bytes / 5
                                  blocks for `ness-technologies`, 12,207 / 5 for `1global`,
                                  11,284 / 4 for `amdocs`, which has no open roles at all.

There is no honest User-Agent that reaches it, so reading those pages at scale would mean
claiming to be a crawler we are not. That is refused. The sitemap itself is NOT gated — it
answers in full to an honest UA — and that is what this module reads.
`docs/decisions/2026-08-27-secrethunter-company-catalog.md` has the full workings and every
alternative rejected.

THE SEED IS NOT A VERDICT. Output is queue entries only. `careers_url` is deliberately the
secrethunter company page, whose host is already on `aggregators.HOSTS` — that is what makes
`auto_expand` treat it as an aggregator seed and reach for the slug rungs (`auto_expand.py`
:449 requires a non-empty `careers_url`; :503 calls `_site_from_guess` only when the seed is
an aggregator URL). Nothing here can activate a `companies.csv` row; that is the registry
lane's write and it goes through `identity_gate` plus its own page read.

    python -c "from pipeline import secrethunter as s; print(len(s.sitemap_slugs()))"
"""
import datetime
import os
import re
import urllib.parse

SITEMAP_INDEX_URL = "https://secrethunter.io/sitemap.xml"
SITEMAP_URL = "https://secrethunter.io/sitemap.xml?type=companies&page=1"
COMPANY_URL = "https://secrethunter.io/companies/%s"

# We say who we are. `pipeline/http.py`'s default UA deliberately carries no identifying
# token (it must not fingerprint this scanner to ATS providers); here the opposite is right —
# this is a bulk read of one small publisher's catalog and they are entitled to see who it is.
UA = "AnalystJobsIL/1.0 (+https://github.com/AnalystJobsIL/pipeline)"

# How many names one run may add to research_companies.json.
#
# THE CAP IS SET FROM THE REGISTRY'S THROUGHPUT, NOT FROM WHAT THIS SOURCE COULD SUPPLY.
# The resolver queue IS the bottleneck (ARCHITECTURE.md 1a): `LLM_RESOLVE_CAP` is 10 against
# 250-name batches, and the 2026-08-27 auto-expand run resolved 11 rows from a batch of 250
# on the free rung — call it ~22/day over two runs. The registry lane had just drained this
# queue 1,693 -> 517 precisely because depth buries the good leads.
#
# 40 was the throughput-matched value and reached the whole 2,002 in ~50 days. The operator
# raised it to 150 on 2026-08-27 to front-load the initial seeding: ~14 days instead of ~50.
# Measured cost, dry-run against sandbox copies of the real state files: **+138 net per run**
# (150 queued, 12 drained), so the queue deepens rather than holding flat.
#
# WHAT THIS DOES AND DOES NOT BUY. It does not make anything resolve faster: `auto_expand`'s
# free rung is bounded by `AUTO_EXPAND_SITE_MAX` (25/run, twice daily) and that number cannot
# safely rise — a successful guess clears `agg_seed` and the next statement runs a full
# `resolve_deep` at ~342 s per name with no deadline check, so 25 is already ~142 min of a
# 330-min job timeout (`auto_expand.py:635-647`). What it DOES buy is that catalog names
# reach the front of that rung's queue sooner, because an unseen name sorts first
# (`auto_expand.py:455`) — at the cost of displacing older, job-backed leads. `docs/BACKLOG.md` 339.
#
# The window is day-ROTATED rather than a prefix, so every slug is reached rather than the
# same 150 being offered forever — the fix `_targeted_inputs` needed when `unresolved[:20]`
# over a stably-sorted list meant the other 90 of 110 were never searched once (1a rule 3).
QUEUE_CAP = int(os.environ.get("SECRETHUNTER_QUEUE_CAP", "150"))

# `auto_expand._site_from_guess` requires `[a-z0-9-]+` before it will guess a domain, and a
# LinkedIn handle has the same shape. A slug that cannot be either is not refused silently.
_SLUG_OK = re.compile(r"[a-z0-9][a-z0-9-]*")

# Deliberately loose. The first cut of this module refused any slug that was not already
# handle-shaped and threw away 98 names, among them `Harmonya%20Technologies`,
# `Valence%20Security`, `Zafran%20Security` and `Innoviz%20Technologies` — Israeli tech
# companies whose only sin was a space in the URL. This repo has already paid 36 legitimate
# acquisitions and 358 path-tenant rows for rules tightened without measuring the cost, so
# the rule NORMALISES first and refuses only what is left with nothing usable.
_MAX_TOKENS = 8
_MIN_CHARS = 2

_HEBREW = re.compile(r"[֐-׿]+")

# Path segments under /companies/ that are navigation, not employers. None is in
# today's sitemap; they cost nothing and they are what a regenerated sitemap would add
# first. `Page 2` and `All` were real queue entries before the host anchor landed.
_RESERVED = {"all", "search", "page", "index", "list", "browse", "new", "top",
             "popular", "category", "categories", "jobs", "companies", "a-z", "null",
             "undefined", "none"}


def handle_from_slug(slug):
    """The LinkedIn-handle-shaped form of a catalog slug, or "" if nothing usable survives.

    `Harmonya%20Technologies` -> `harmonya-technologies` (a space is not a reason to lose a
    company). `alvarez-&-marsal` -> `alvarez-and-marsal`. `costello'sacehardware` ->
    `costellosacehardware`. And a MIXED slug keeps its Latin half:
    `אוניפארם-קריירה-unipharm-career` -> `unipharm-career`, which is a real handle for a real
    company that the first cut of this rule discarded as "non-latin".
    """
    if not isinstance(slug, str):
        return ""                       # str(b"wix") is "b'wix'", which is slug-shaped
    s = slug
    # `sitemap_slugs` decodes, but this is a public entry point and a caller holding a raw
    # `Harmonya%20Technologies` must not silently get `harmonya-20technologies` — a handle
    # that is wrong in a way nothing downstream can detect, because it is still slug-shaped.
    # Decode until STABLE, not a fixed two passes: `%252520` needs three, and a fixed count
    # makes the guarantee accidental rather than structural.
    for _ in range(6):
        if not re.search(r"%[0-9A-Fa-f]{2}", s):
            break
        nxt = urllib.parse.unquote(s)
        if nxt == s:
            break
        s = nxt
    if re.search(r"%[0-9A-Fa-f]{2}", s):
        return ""                       # still escaped after 6 passes: refuse, never guess
    s = s.lower()
    s = _HEBREW.sub(" ", s)                     # a Hebrew run is not a handle; its Latin
    s = s.replace("&", " and ")                 # neighbours may still be one
    # An apostrophe is INTRA-word, not a separator: `costello's ace hardware` is
    # `costellos-ace-hardware`, never `costello-s-ace-hardware`. Everything else that is not
    # alphanumeric genuinely does separate words.
    s = re.sub(r"[’']", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-{2,}", "-", s).strip("-")

# Tokens that a blind .title() would mangle. Not exhaustive and does not need to be: the name
# is evidence for a case-insensitive match, not a display string. See `name_from_slug`.
_UPPER = {"ai", "ml", "bi", "it", "hr", "io", "tv", "us", "uk", "usa", "crm", "erp", "sap",
          "iot", "vr", "ar", "api", "sdk", "cnc", "led", "rnd", "hls", "3d"}


def sitemap_slugs(timeout=90):
    """Every `/companies/<slug>` in the catalog, decoded. One GET, keyless, honest UA.

    The sitemap lists each company twice (plain and `?lang=en`); the `?lang=en` half is
    dropped. 26 of the slugs are DOUBLE percent-encoded -- 16 Hebrew, the other 10 European
    (`bäckerei-bergmann-&-sohn-gmbh`, `slezáská-diakonie`, `loréal`) -- so one
    `unquote` leaves `%D7%90...`, a string that still looks like a slug and silently is not.
    Both passes are applied.

    PAGINATION IS FOLLOWED, NOT ASSUMED. `?type=companies&page=2` is empty today, but an
    earlier cut hardcoded page 1 and reasoned "so there is no pagination loop to get wrong" --
    which silently returns a PREFIX the day the catalog outgrows one page, and the count still
    looks healthy. The INDEX is what `robots.txt` actually publishes, so it is read and every
    `type=companies` child followed.
    """
    from pipeline import http
    hdrs = {"User-Agent": UA, "Accept": "application/xml,text/xml,*/*"}
    pages = []
    try:
        index = http.get_text(SITEMAP_INDEX_URL, timeout=timeout, headers=hdrs)
        pages = [u for u in re.findall(r"<loc>(.*?)</loc>", index) if "type=companies" in u]
    except Exception as e:  # noqa: BLE001
        print(f"[secrethunter] sitemap index unreadable ({e}); falling back to page 1",
              flush=True)
    out, seen = [], set()
    locs = []
    for u in (pages or [SITEMAP_URL]):
        xml = http.get_text(u.replace("&amp;", "&"), timeout=timeout, headers=hdrs)
        locs.extend(re.findall(r"<loc>(.*?)</loc>", xml))
    for loc in locs:
        if "lang=en" in loc:
            continue
        # ANCHOR ON THE HOST, and stop the slug at the first `/`, `#` or `?`. The first cut
        # used `([^?<]+)` with no host check, so `/companies/page/2`, `/companies/all` and a
        # cross-domain `<loc>` all became queue entries named `Page 2`, `All` and whatever the
        # other host said -- each one burning a slot in the queue the cap exists to protect.
        if not re.match(r"https?://(www\.)?secrethunter\.io/companies/", loc):
            continue
        m = re.search(r"/companies/([^/?#<]+)/?(?:[?#]|$)", loc)
        if not m:
            continue
        slug = urllib.parse.unquote(urllib.parse.unquote(m.group(1))).strip()
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def name_from_slug(slug):
    """A display name reconstructed from the URL slug, via its normalised handle.

    LOSSY, AND KNOWN TO BE. The catalog's real names live in the JSON-LD on the company pages,
    behind the crawler-UA gate this module refuses to defeat, so a slug is all we have:
    `majestic-labs-ai` -> `Majestic Labs AI` is right, `ide-technologies-ltd.` -> `Ide
    Technologies Ltd` is not quite. This costs YIELD, not correctness — `_site_from_guess`
    demands `page_mentions_company(name, html, strict=True)` before it believes a domain, so
    a mangled name fails closed and produces nothing rather than something wrong.
    """
    s = re.sub(r"[-_]+", " ", handle_from_slug(slug)).strip()
    words = []
    for w in s.split():
        lw = w.lower().strip(".")
        words.append(lw.upper() if lw in _UPPER else w[:1].upper() + w[1:])
    return " ".join(words).strip()


def slug_refusal(handle, name):
    """Why this slug may not become a queue entry, or None to accept.

    Takes the NORMALISED handle, not the raw slug: normalisation is what stops a `%20` or an
    `&` from costing a real employer. Returns a short grep-able token, never a sentence — the
    reason is written to the intake ledger and `grep -c agency` has to mean something.
    """
    h = str(handle or "").strip()
    if not h:
        # Nothing Latin survived: a wholly Hebrew slug is neither a LinkedIn handle nor a
        # domain stem, so it can reach no rung we have. Recorded rather than dropped, so the
        # day someone builds a Hebrew rung the names are all still here.
        return "non-latin-slug"
    if not _SLUG_OK.fullmatch(h):
        return "unsafe-slug"
    if len(h) < _MIN_CHARS:
        return "slug-too-short"
    if len(h.split("-")) > _MAX_TOKENS:
        return "slug-too-long"
    if h in _RESERVED:
        return "reserved-path"
    from pipeline.firmographics import looks_like_junk
    if looks_like_junk(name):
        return "junk-name"
    from pipeline.recruiters import is_recruiter
    if is_recruiter(name, h):
        return "agency"
    return None


# `israel` and `il` are deliberately NOT here. In an Israel-scoped registry they are a
# DISAMBIGUATOR, not a legal suffix: stripping them collides `Access` with `Access Israel`
# and `Applied Materials` with `Applied Materials Israel`, and a false "already known"
# silently loses a real employer -- the more expensive of the two mistakes, as the docstring
# below says. An adversarial pass found 8 such collisions in the live catalog.
_LEGAL = re.compile(r"[\s-]+(ltd|ltd\.|inc|inc\.|llc|l\.l\.c|corp|corp\.|plc|gmbh)$")
_ZERO_WIDTH = re.compile(r"[​-‏‪-‮﻿]")


def alias_keys(name):
    """The forms of a company name that mean the same registry row.

    The queue matches names EXACTLY, lower-cased — that is what `auto_expand.py:450` and both
    bridges' drain blocks do, so this module must not invent a looser rule and queue names
    they will not recognise. But exact matching alone offered ~100 companies we already hold
    under a trailing `Ltd` or a stray hyphen, and each of those burns a resolver slot in the
    queue that IS the bottleneck. So: exact, minus a trailing legal suffix, and alphanumeric
    only. Deliberately NOT the aggressive stop-word strip used for one-off overlap counts —
    dropping `technologies`/`group`/`labs` merges genuinely different firms, and a false
    "already known" silently loses a real employer, which is the more expensive mistake.
    """
    n = _ZERO_WIDTH.sub("", str(name or ""))
    n = " ".join(n.strip().lower().split())[:200]     # bound: `_LEGAL` scans every start
    if not n:
        return set()
    out = {n}
    stripped = _LEGAL.sub("", n).strip()
    if stripped:
        out.add(stripped)
    for v in list(out):
        alnum = re.sub(r"[^a-z0-9]+", "", v)
        if alnum:
            out.add(alnum)
    return out


def handle_index(slugs):
    """alias-key -> handle, dropping any key that two DIFFERENT handles both claim.

    An ambiguous key is skipped rather than resolved: writing the wrong handle onto a queue
    entry is worse than leaving it empty, because `_site_from_guess` would then probe another
    company's domain and `page_mentions_company` is the only thing standing between that and
    a wrong row.
    """
    idx, ambiguous = {}, set()
    for slug in slugs:
        h = handle_from_slug(slug)
        if not h:
            continue
        for k in alias_keys(name_from_slug(slug)):
            if idx.get(k, h) != h:
                ambiguous.add(k)
            idx.setdefault(k, h)
    for k in ambiguous:
        idx.pop(k, None)
    return idx


def backfill_handles(entries, slugs):
    """Fill an EMPTY `slug` on queue entries we ALREADY hold, in place. (filled, mismatches).

    The catalog's value is not only the names it adds. 135 of the 517 queue entries carry no
    handle at all — including all 91 that this same source queued as `secrethunter.io/jobz/`
    postings before there was a catalog reader — and a handle is the ONE thing
    `auto_expand._site_from_guess` needs. Without it those entries are the subset of the queue
    that no rung can even attempt: an aggregator seed with nothing to guess a domain from.

    NEVER overwrites a handle we already hold. Roughly 10% genuinely differ (`Grain` /
    `grainfinance`, `Wayve` / `wayve-technologies`), and the one we hold has PROVENANCE — a
    LinkedIn card that named the company — while the catalog's is a directory's slug. The
    disagreement is recorded to the intake ledger and ours is kept.

    Additive to the queue's existing four-key shape, so no other lane changes.
    """
    idx = handle_index(slugs)
    filled, mismatches = 0, []
    for e in entries:
        h = next((idx[k] for k in alias_keys(e.get("name")) if k in idx), None)
        if not h:
            continue
        cur = (e.get("slug") or "").strip()
        if not cur:
            e["slug"] = h
            filled += 1
        elif cur.lower() != h:
            mismatches.append((e.get("name") or h, "handle-mismatch"))
    return filled, mismatches


def _window(pool, cap, day=None):
    """A day-rotated window of `cap` entries over `pool`, wrapping at the end.

    A fixed prefix over a stable list is not a sample, it is a blind spot: the same names
    would be offered every morning and the tail would never be reached at all.
    """
    if cap <= 0 or not pool:
        return []
    if cap >= len(pool):
        return list(pool)
    doy = (day or datetime.date.today()).timetuple().tm_yday
    start = (doy * cap) % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(cap)]


def queue_entries(slugs, have, queued, cap=None, day=None):
    """(entries, rejections, stats) — queue entries for names we do not already hold.

    `have`    lower-cased company names already in companies.csv
    `queued`  lower-cased names already in research_companies.json
    Entries use the queue's existing four-key shape; nothing else in the repo has to change.
    """
    cap = QUEUE_CAP if cap is None else cap
    rejections, stats = [], {"slugs": len(slugs), "known": 0, "queued_already": 0,
                             "refused": 0, "offered": 0, "dup_in_catalog": 0}
    seen_keys = set()
    have_keys = set()
    for n in have:
        have_keys |= alias_keys(n)
    queued_keys = set()
    for n in queued:
        queued_keys |= alias_keys(n)
    fresh = []
    for slug in slugs:
        handle = handle_from_slug(slug)
        name = name_from_slug(slug)
        keys = alias_keys(name)
        if keys & have_keys:
            stats["known"] += 1
            continue
        if keys & queued_keys:
            stats["queued_already"] += 1
            continue
        why = slug_refusal(handle, name)
        if why:
            stats["refused"] += 1
            rejections.append((name or slug, why))
            continue
        # `careers_url` re-encodes the DECODED slug, so for the 26 double-encoded entries it
        # is single-encoded where the sitemap's loc was double (`%D7%90...` vs `%25D7%2590...`).
        # Both reach the same page and neither is ever fetched by us — an aggregator seed is
        # refused before any GET — but the distinction is written down because the first
        # version of this comment claimed it "keeps the ORIGINAL slug", which is not true.
        # `slug` carries the normalised handle, which is what the rungs actually consume.
        # ...and not twice in the same run. `NeuReality`/`neureality` and
        # `Aqua Security`/`Aquasecurity` are each one company listed under two slugs; without
        # this they were two entries, each burning a slot in the queue the cap exists to
        # protect. `new_cos.setdefault` downstream collapses only EXACT name twins.
        if keys & seen_keys:
            stats["dup_in_catalog"] += 1
            continue
        seen_keys |= keys
        fresh.append({"name": name, "careers_url": COMPANY_URL % urllib.parse.quote(slug),
                      "ats": "unknown", "slug": handle})
    # Refusals are recorded for the WHOLE catalog, not just the window: the ledger's value is
    # that a wrong rejection is appealable, and a name refused outside today's window is
    # exactly as wrongly refused as one inside it.
    entries = _window(fresh, cap, day=day)
    stats["fresh"] = len(fresh)
    stats["offered"] = len(entries)
    return entries, rejections, stats
