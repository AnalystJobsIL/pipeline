"""Diagnostic: how does a Comeet careers page expose its jobs? Render with Playwright,
capture every comeet-related request + JSON response, and any embedded job links / iframe."""
import sys
from playwright.sync_api import sync_playwright


def probe(url):
    reqs, jsons, err = [], [], None
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36")

        def on_req(r):
            if "comeet" in r.url.lower():
                reqs.append((r.method, r.url[:170]))

        def on_resp(r):
            u = r.url.lower()
            if "comeet" in u and ("careers-api" in u or "position" in u or "/company/" in u):
                try:
                    ct = r.headers.get("content-type", "")
                    if "json" in ct:
                        data = r.json()
                        jsons.append((r.url[:110], type(data).__name__,
                                      len(data) if isinstance(data, list) else list(data)[:6]))
                except Exception:
                    pass

        pg.on("request", on_req)
        pg.on("response", on_resp)
        try:
            pg.goto(url, wait_until="load", timeout=35000)
            pg.wait_for_timeout(9000)
            joblinks = pg.eval_on_selector_all(
                "a[href*='comeet.com/jobs'], a[href*='comeet.co/jobs']",
                "els=>els.slice(0,3).map(function(e){return e.href})")
            iframes = [f.get_attribute("src") for f in pg.query_selector_all("iframe")
                       if (f.get_attribute("src") or "").lower().find("comeet") > -1]
            # scan page HTML for an embedded uid/token config
            htmlbits = pg.evaluate(
                "()=>{var h=document.documentElement.innerHTML;"
                "var m=h.match(/[A-Z0-9]{2}\\.[A-Z0-9]{3}/g)||[];"
                "return {uids:[...new Set(m)].slice(0,6)};}")
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:120]}"
            joblinks, iframes, htmlbits = [], [], {}
        finally:
            b.close()
    print(f"\n=== {url} ===")
    if err:
        print("  ERR:", err)
    print("  comeet requests:")
    for m, u in reqs[:12]:
        print(f"    {m} {u}")
    print("  comeet JSON responses:")
    for u, t, keys in jsons[:6]:
        print(f"    {u}  ->  {t} {keys}")
    print("  job links in DOM:", joblinks)
    print("  comeet iframes:", iframes)
    print("  uid candidates in HTML:", htmlbits.get("uids"))


if __name__ == "__main__":
    for u in sys.argv[1:]:
        probe(u)
