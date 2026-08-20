"""Screenshot individual expanded job-detail blocks for visual QA of the description UI.

Expands each row whose index is given (default: a spread of role types) and captures
just that <tr.detail> block, so I can compare the description layout across roles.
"""
import sys
from playwright.sync_api import sync_playwright

path = sys.argv[1] if len(sys.argv) > 1 else "docs/index.html"
idxs = [int(x) for x in sys.argv[2:]] or [0, 4, 6, 10, 14, 20, 30, 45]
url = "file:///" + path.replace("\\", "/") if not path.startswith("http") else path

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 900, "height": 900}, device_scale_factor=2)
    pg.goto(url, wait_until="load")
    pg.wait_for_timeout(600)
    rows = pg.query_selector_all("tr.row")
    for i in idxs:
        if i >= len(rows):
            continue
        # collapse any open, open just this one
        pg.eval_on_selector_all("tr.row[aria-expanded=true]", "els=>els.forEach(e=>e.click())")
        pg.wait_for_timeout(120)
        rows[i].click()
        pg.wait_for_timeout(250)
        # the detail row is the next sibling
        detail = pg.evaluate_handle(
            "(i)=>document.querySelectorAll('tr.row')[i].nextElementSibling", i)
        el = detail.as_element()
        if el:
            company = (rows[i].inner_text() or "").split("\n")[0][:20].strip()
            fn = f"out/detail_{i:02d}.png"
            try:
                el.screenshot(path=fn)
                print(f"{fn}  row {i}  {company}")
            except Exception as e:
                print(f"row {i} shot err {e}")
    b.close()
print("done")
