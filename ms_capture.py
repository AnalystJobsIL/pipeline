"""Capture the exact Microsoft careers pcsx/search request (method, url, post body) + a response sample."""
import json
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
reqs = []


def on_request(r):
    if "pcsx/search" in r.url:
        reqs.append((r.method, r.url, r.post_data))


sample = {}


def on_response(resp):
    if "pcsx/search" in resp.url:
        try:
            sample["body"] = resp.json()
        except Exception:
            pass


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(user_agent=UA)
    pg.on("request", on_request)
    pg.on("response", on_response)
    pg.goto("https://jobs.careers.microsoft.com/global/en/search?lc=Israel&l=en_us",
            wait_until="load", timeout=35000)
    pg.wait_for_timeout(7000)
    b.close()

for m, u, body in reqs[:3]:
    print("METHOD:", m)
    print("URL:", u)
    print("BODY:", body)
    print("---")
if sample.get("body"):
    d = sample["body"]
    res = d.get("operationResult", {}).get("result", {}) if isinstance(d, dict) else {}
    jobs = res.get("jobs", []) or (d.get("jobs", []) if isinstance(d, dict) else [])
    print("TOTAL:", res.get("totalJobs") or d.get("count"))
    for j in jobs[:6]:
        loc = j.get("properties", {}).get("locations") or j.get("properties", {}).get("primaryLocation")
        print(f"   - {j.get('title')} | {loc}")
    print("TOP-LEVEL KEYS:", list(d.keys())[:10])
