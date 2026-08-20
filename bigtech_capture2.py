"""Load each big-company Israel careers search, INTERACT (scroll + wait for XHR), and capture every
JSON API response that looks like job data — reporting the endpoint + whether it carries jobs."""
import json
import re
import sys
from playwright.sync_api import sync_playwright

TARGETS = {
    "Google": "https://www.google.com/about/careers/applications/jobs/results/?location=Israel",
    "Meta": "https://www.metacareers.com/jobs?offices[0]=Tel%20Aviv%2C%20Israel",
    "Apple": "https://jobs.apple.com/en-us/search?location=israel-ISRC",
    "Shopify": "https://www.shopify.com/careers/search?location=Israel",
    "Booking.com": "https://careers.booking.com/search?location=Israel",
    "Intuit": "https://www.intuit.com/careers/teams/technology/",
    "eBay": "https://careers.ebayinc.com/us/en/search-results?keywords=Israel",
    "Uber": "https://www.uber.com/us/en/careers/list/?location=ISR-Tel-Aviv",
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def capture(name, url):
    hits = {}

    def on_resp(resp):
        u = resp.url
        ct = (resp.headers or {}).get("content-type", "")
        if "json" not in ct:
            return
        if not re.search(r"job|search|role|position|career|graphql|api", u, re.I):
            return
        try:
            body = resp.text()
        except Exception:
            return
        n = len(re.findall(r'"(title|jobTitle|postingTitle|name)"\s*:', body))
        il = len(re.findall(r"israel|tel aviv|herzliya|haifa|yokneam", body, re.I))
        if n >= 3:
            base = u.split("?")[0]
            if base not in hits or n > hits[base][0]:
                hits[base] = (n, il, resp.status)

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=UA)
        pg.on("response", on_resp)
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=40000)
            for _ in range(4):
                pg.wait_for_timeout(2500)
                pg.mouse.wheel(0, 2000)
            pg.wait_for_timeout(3000)
        except Exception as e:
            print(f"  {name}: nav {type(e).__name__}: {str(e)[:70]}")
        finally:
            b.close()
    print(f"=== {name} ===")
    if not hits:
        print("   (no JSON job API captured — server-rendered or auth-gated)")
    for base, (n, il, st) in sorted(hits.items(), key=lambda x: -x[1][0])[:4]:
        tag = "  <-- has Israel terms" if il else ""
        print(f"   [{st}] titles~{n:3} israelterms={il:3} {base}{tag}")


if __name__ == "__main__":
    names = sys.argv[1:] or list(TARGETS)
    for nm in names:
        try:
            capture(nm, TARGETS[nm])
        except Exception as e:  # noqa: BLE001
            print(f"{nm}: ERR {type(e).__name__}: {str(e)[:80]}")
