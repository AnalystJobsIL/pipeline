"""Load each big-tech Israel careers search in Playwright and capture the JSON API call it fires
(URL + whether the response carries job records) so we can judge if it's wireable into the pipeline."""
from playwright.sync_api import sync_playwright

TARGETS = {
    "Microsoft": "https://jobs.careers.microsoft.com/global/en/search?lc=Israel",
    "Google": "https://www.google.com/about/careers/applications/jobs/results/?location=Israel",
    "Apple": "https://jobs.apple.com/en-us/search?location=israel-ISRC",
    "Meta": "https://www.metacareers.com/jobs?offices[0]=Tel%20Aviv%2C%20Israel",
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def capture(name, url):
    hits = []

    def on_response(resp):
        u = resp.url
        ct = (resp.headers or {}).get("content-type", "")
        if "json" in ct and any(k in u.lower() for k in ("search", "job", "role", "graphql", "api")):
            try:
                body = resp.text()
            except Exception:
                return
            n = body.count('"title"') + body.count('"postingTitle"') + body.count('"jobTitle"')
            if n or "job" in u.lower():
                hits.append((u.split("?")[0], resp.status, n, len(body)))

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=UA)
        pg.on("response", on_response)
        try:
            pg.goto(url, wait_until="load", timeout=35000)
            pg.wait_for_timeout(6000)
            pg.mouse.wheel(0, 2000)
            pg.wait_for_timeout(4000)
        except Exception as e:
            print(f"{name}: nav err {type(e).__name__}: {str(e)[:80]}")
        finally:
            b.close()
    print(f"=== {name} ===")
    seen = set()
    for u, st, n, ln in hits:
        if u in seen:
            continue
        seen.add(u)
        print(f"   [{st}] titles~{n:3} len={ln:7} {u}")
    if not hits:
        print("   (no JSON job API captured)")


for name, url in TARGETS.items():
    try:
        capture(name, url)
    except Exception as e:  # noqa: BLE001
        print(f"{name}: ERR {type(e).__name__}: {str(e)[:100]}")
    print()
