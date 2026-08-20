#!/usr/bin/env python3
"""Generic Playwright careers-page scraper — works when there is NO public API.

Strategy per page:
  1. schema.org JobPosting JSON-LD (many career sites embed it for Google-for-Jobs) -> clean
     title / location / datePosted / url / description.
  2. Fallback: anchor-tag heuristic (links that look like individual job postings).

This is the reliable way to cover custom / server-rendered career sites (Google, Meta, Shopify,
and the hundreds of React-SPA startups) that expose no fetchable JSON API.
"""
from __future__ import annotations

import json
import sys

from pipeline import israel

_JSONLD = r"""() => {
  const out = [];
  const walk = (o) => {
    if (!o || typeof o !== 'object') return;
    if (Array.isArray(o)) { o.forEach(walk); return; }
    const t = o['@type'];
    if (t === 'JobPosting' || (Array.isArray(t) && t.includes('JobPosting'))) out.push(o);
    if (o['@graph']) walk(o['@graph']);
  };
  document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
    try { walk(JSON.parse(s.textContent)); } catch (e) {}
  });
  return out;
}"""

_LINKS = r"""() => {
  // Only links that look like an INDIVIDUAL job posting (a detail path with an id/slug segment),
  // whose text reads like a job title (has a role keyword), not nav chrome.
  const detail = /\/(job|jobs|position|positions|opening|openings|vacancy|role|roles|gh_jid|apply)[\/\-_=][A-Za-z0-9]/i;
  const roleword = /(engineer|developer|manager|analyst|scientist|designer|lead|architect|specialist|director|head|officer|consultant|researcher|marketing|sales|product|data|devops|qa|account|recruit|finance|legal|operations|support|success|counsel|controller|bi\b|analytics)/i;
  const nav = /^(careers?|jobs?|home|about|products?|platform|company|contact|blog|login|apply|search|menu|skip|consent|cookie|privacy|open positions|all jobs|view all)$/i;
  const seen = new Set(), out = [];
  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.href, txt = (a.textContent || '').trim().replace(/\s+/g, ' ');
    if (txt.length < 6 || txt.length > 120 || nav.test(txt) || seen.has(href)) return;
    if (detail.test(href) && roleword.test(txt)) { seen.add(href); out.push({title: txt, url: href}); }
  });
  return out.slice(0, 150);
}"""


def _loc(jp):
    loc = jp.get("jobLocation") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    addr = (loc or {}).get("address") or {}
    if isinstance(addr, str):
        return addr
    parts = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
    parts = [p.get("name") if isinstance(p, dict) else p for p in parts]
    return ", ".join(str(p) for p in parts if p)


def scrape(company, careers_url, timeout_ms=40000):
    from playwright.sync_api import sync_playwright
    jobs = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"))
        try:
            pg.goto(careers_url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                pg.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            pg.mouse.wheel(0, 2500)
            pg.wait_for_timeout(3000)
            ld = pg.evaluate(_JSONLD)
            links = pg.evaluate(_LINKS) if not ld else []
        except Exception:
            ld, links = [], []
        finally:
            b.close()
    for jp in ld:
        title = jp.get("title") or ""
        url = jp.get("url") or careers_url
        jobs.append({"company": company, "title": str(title)[:200], "location": _loc(jp),
                     "country_code": "", "url": url, "posted_date": (jp.get("datePosted") or "")[:10],
                     "ats_platform": "scrape", "job_id": str(url),
                     "description": str(jp.get("description") or "")[:2000]})
    if not ld:
        for l in links:
            jobs.append({"company": company, "title": l["title"], "location": "",
                         "country_code": "", "url": l["url"], "posted_date": "",
                         "ats_platform": "scrape-links", "job_id": l["url"], "description": ""})
    return jobs, bool(ld)


if __name__ == "__main__":
    tests = [
        ("Google", "https://www.google.com/about/careers/applications/jobs/results/?location=Israel"),
        ("Meta", "https://www.metacareers.com/jobs?offices[0]=Tel%20Aviv%2C%20Israel"),
        ("Shopify", "https://www.shopify.com/careers/search?location=Israel"),
        ("Snyk", "https://snyk.io/careers/"),
        ("Coralogix", "https://coralogix.com/careers/"),
        ("Tabnine", "https://www.tabnine.com/careers"),
        ("Cato Networks", "https://www.catonetworks.com/careers/"),
        ("Trax Retail", "https://traxretail.com/careers/"),
    ]
    if len(sys.argv) >= 3:
        tests = [(sys.argv[1], sys.argv[2])]
    for name, url in tests:
        try:
            js, had_ld = scrape(name, url)
            il = sum(1 for j in js if israel.is_israel_job(j))
            mode = "JSON-LD" if had_ld else ("links" if js else "none")
            print(f"{name:16} [{mode:7}] jobs={len(js):4} israel={il}")
            for j in js[:2]:
                print(f"     - {j['title'][:50]} | {j['location']} | {j['posted_date']}")
        except Exception as e:  # noqa: BLE001
            print(f"{name:16} ERR {type(e).__name__}: {str(e)[:60]}")
