#!/usr/bin/env python3
"""Fill missing employee counts from LinkedIn company pages via Bright Data Web Unlocker.

Targets ONLY firmographics records with null employees_global (the researcher's honest
"couldn't find a published number" cases — mostly small privates and acquired subsidiaries).
For each, guesses the LinkedIn company slug from the name, fetches the public page through
the Unlocker (1 credit/page), and extracts:
  - the member-linked employee count (JSON-LD numberOfEmployees / "N employees" text)
  - the self-reported size bucket ("51-200 employees") -> confirms/fills size_band

Updates the store in place (employees_source: "linkedin", employees_as_of stamped); a page
that can't be fetched or doesn't clearly match the company name is skipped, never guessed.

Needs BRIGHTDATA_API_KEY + BRIGHTDATA_ZONE in the environment or secrets.env. Never prints
the key. Cap per run with BD_LIMIT (default 60 — a full null-employee pass is ~49 credits).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

from pipeline.firmographics import band_for, identity_key, is_division_name
from pipeline.store import SeenStore

# LinkedIn soft blocks come back as HTTP 200 with an authwall/challenge body — that is
# infrastructure pushing back, not evidence about the company name
_BLOCKED = re.compile(r"authwall|checkpoint/challenge|captcha|please verify|unusual activity", re.I)

# chain redirects stdout to a file -> cp1252 on Windows -> Hebrew names crash prints
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
RETRY_MISS_DAYS = 30  # a name both passes failed on is retried monthly, not every 6h


def _load_secrets():
    p = os.path.join(ROOT, "secrets.env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)


def unlock(url, timeout=90):
    """Fetch url through Web Unlocker.

    Returns the HTML body, or None on INFRASTRUCTURE failure (expired key -> HTTPError,
    network down, quota exhausted). None must never be treated as "page not found":
    stamping per-name misses during an outage gates the whole cohort for a month."""
    body = json.dumps({"zone": os.environ["BRIGHTDATA_ZONE"], "url": url,
                       "format": "raw"}).encode()
    req = urllib.request.Request("https://api.brightdata.com/request", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['BRIGHTDATA_API_KEY']}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(2_000_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None


_SUFFIX = re.compile(r"\s+(ltd|inc|llc|corp|co|gmbh|group|technologies|solutions)\.?$", re.I)


def slug_candidates(name):
    """Best-guess LinkedIn /company/ slugs for a display name, most likely first."""
    base = re.sub(r"\([^)]*\)", "", name).strip()          # "Habana Labs (Intel)" -> "Habana Labs"
    base = _SUFFIX.sub("", base)
    cands = []
    for form in (base, base.replace(".", " "), base.replace(".", "")):
        s = re.sub(r"[^0-9a-z]+", "-", form.lower().replace("&", " and ")).strip("-")
        s = re.sub(r"-+", "-", s)
        if s and s not in cands:
            cands.append(s)
    return cands[:3]


# size_band derivation lives in pipeline.firmographics.band_for (canonical)


def parse_page(html, name):
    """Return (count|None, range_str|None, strong_match) if the page matches, else None.

    strong_match: the FULL normalized name appears in the page title. A single generic
    name word ("Bounce", "AWS") matching some other company's title produced wrong fills
    that were internally consistent (count inside the wrong page's own bucket) — so weak
    matches are still returned but the caller marks them for LLM re-verification.
    """
    title = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    if not title:
        return None
    norm = lambda s: " ".join(re.sub(r"[^0-9a-z]+", " ", s.lower()).split())
    t, full = norm(title.group(1)), norm(re.sub(r"\([^)]*\)", "", name))
    words = full.split()
    if full and full in t:
        strong = True
    elif words and words[0] in t.split():
        strong = False  # only a name fragment matched — could be a namesake company
    else:
        return None
    count = None
    m = re.search(r'"numberOfEmployees"\s*:\s*\{[^}]*"value"\s*:\s*(\d+)', html)
    if m:
        count = int(m.group(1))
    else:
        m = re.search(r'>([\d,]{1,7})\s+employees<', html)
        if m:
            count = int(m.group(1).replace(",", ""))
    rng = None
    m = re.search(r'([\d,]+)\s*-\s*([\d,]+)\s+employees|([\d,]+)\+\s+employees', html)
    if m:
        rng = m.group(0).replace(" employees", "").replace(",", "").strip()
    if count is not None and not (1 <= count <= 5_000_000):
        count = None
    return (count, rng, strong) if (count or rng) else None


def main():
    _load_secrets()
    if not (os.environ.get("BRIGHTDATA_API_KEY") and os.environ.get("BRIGHTDATA_ZONE")):
        print("BRIGHTDATA_API_KEY / BRIGHTDATA_ZONE not set — run setup_brightdata.py first")
        return
    limit = int(os.environ.get("BD_LIMIT", "60"))
    st = SeenStore()
    recs = st.load_firmographics()
    retry_cutoff = (dt.date.today() - dt.timedelta(days=RETRY_MISS_DAYS)).isoformat()
    targets = sorted(c for c, r in recs.items()
                     if not r.get("employees_global")
                     and not (r.get("employees_lookup_miss") or "") > retry_cutoff
                     and not (r.get("employees_linkedin_miss") or "") > retry_cutoff)
    # one lookup per identity per run — two name-forms of one company must not both pay
    seen_ids, deduped = set(), []
    for c in targets:
        ik = identity_key(c)
        if ik not in seen_ids:
            seen_ids.add(ik)
            deduped.append(c)
    targets = deduped[:limit]
    today = dt.date.today().isoformat()
    print(f"linkedin employee lookup for {len(targets)} companies ...")
    got = rng_only = miss = infra_streak = 0
    for name in targets:
        found, got_body = None, False
        for slug in slug_candidates(name):
            html = unlock(f"https://www.linkedin.com/company/{slug}")
            if html is None:
                continue  # transport failure — proves nothing about this company
            if len(html) < 1000 or _BLOCKED.search(html[:4000]):
                continue  # error stub / authwall: soft block, still not name evidence
            got_body = True
            found = parse_page(html, name)
            if found:
                break
        time.sleep(1)
        if not found:
            if not got_body:
                # every fetch failed at the transport layer: outage, not a page miss —
                # no stamp, and 3 in a row means the rest of the run would be the same
                infra_streak += 1
                print(f"  UNAVAILABLE {name}: unlocker unreachable (no miss recorded)", flush=True)
                if infra_streak >= 3:
                    print("3 consecutive unlocker failures — aborting; nothing was gated")
                    break
                continue
            infra_streak = 0
            miss += 1
            rec = recs[name]
            rec["employees_linkedin_miss"] = today  # don't re-spend unlocker credits every 6h
            st.save_firmographics({name: rec}, today)
            print(f"  miss {name} (monthly retry)", flush=True)
            continue
        infra_streak = 0
        count, rng, strong = found
        # a division record ("Sony (PlayStation)") strong-matches the PARENT's page by
        # construction (slug and title both drop the parenthetical) — force weak so the
        # LLM pass re-verifies instead of inheriting the parent's global headcount
        if is_division_name(name):
            strong = False
        rec = recs[name]
        # weak (name-fragment) title matches are exactly how generic names land on a
        # namesake's page — mark them so the LLM verify pass ALWAYS re-checks them
        rec["employees_source"] = "linkedin" if strong else "linkedin-weakmatch"
        rec["employees_as_of"] = today
        if rng:
            rec["employees_range"] = rng
        if count:
            rec["employees_global"] = count
            rec["size_band"] = band_for(count)  # ALWAYS re-derive — a stale band contradicts the count
            got += 1
            print(f"  ok   {name}: {count} employees" + (f" (bucket {rng})" if rng else ""), flush=True)
        else:
            # bucket only: keep count null (honest), but use the bucket's floor for size_band
            if not rec.get("size_band"):
                floor = int(re.split(r"[-+]", rng)[0] or 0)
                rec["size_band"] = band_for(max(floor, 1))
            rng_only += 1
            print(f"  rng  {name}: bucket {rng}, no member count", flush=True)
        st.save_firmographics({name: rec}, today)
    print(f"=== counts {got} · bucket-only {rng_only} · miss {miss} ===")


if __name__ == "__main__":
    main()
