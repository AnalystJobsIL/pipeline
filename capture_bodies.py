"""Capture the actual RESPONSE BODIES of a careers page's internal calls, find the ones carrying
job data, and dump their request (method/url/post_data) + a body snippet so we can build a parser."""
import json
import re
import sys
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
KW = re.compile(r"tel[\s-]?aviv|herzliya|\bisrael\b|jobPosting|job_id|requisition|postingTitle|"
                r"\"title\"|jobTitle|locations?", re.I)


def run(name, url, save_prefix):
    caught = []

    def on_resp(resp):
        u = resp.url
        rt = resp.request.resource_type
        if rt not in ("xhr", "fetch", "document", "other"):
            return
        try:
            body = resp.text()
        except Exception:
            return
        if len(body) < 200:
            return
        hits = len(KW.findall(body))
        if hits >= 5:
            caught.append((hits, resp.request.method, u, resp.request.post_data, body))

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=UA)
        pg.on("response", on_resp)
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(6000)
            pg.mouse.wheel(0, 3000)
            pg.wait_for_timeout(5000)
        except Exception as e:
            print(f"  nav {type(e).__name__}: {str(e)[:80]}")
        finally:
            b.close()

    caught.sort(reverse=True)
    print(f"=== {name}: {len(caught)} job-ish responses ===")
    for i, (hits, method, u, post, body) in enumerate(caught[:4]):
        fn = f"{save_prefix}_{i}.json"
        with open(fn, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"  [{hits:4} kw] {method} {u[:90]}")
        if post:
            print(f"        POST: {post[:160]}")
        print(f"        saved -> {fn} ({len(body)} bytes)")


if __name__ == "__main__":
    name, url, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
    run(name, url, prefix)
