"""Screenshot the local board at desktop + mobile widths for visual review."""
import sys
from playwright.sync_api import sync_playwright

path = sys.argv[1] if len(sys.argv) > 1 else "docs/index.html"
url = "file:///" + path.replace("\\", "/") if not path.startswith("http") else path

with sync_playwright() as p:
    b = p.chromium.launch()
    # desktop
    pg = b.new_page(viewport={"width": 1200, "height": 900})
    pg.goto(url, wait_until="load")
    pg.wait_for_timeout(800)
    pg.screenshot(path="out/board_desktop.png", full_page=False)
    # expand first row to show detail
    try:
        pg.eval_on_selector("tr.row", "el=>el.click()")
        pg.wait_for_timeout(400)
        pg.screenshot(path="out/board_desktop_expanded.png", full_page=False)
    except Exception as e:
        print("expand desktop err", e)
    pg.close()
    # mobile
    m = b.new_page(viewport={"width": 390, "height": 780}, is_mobile=True)
    m.goto(url, wait_until="load")
    m.wait_for_timeout(800)
    m.screenshot(path="out/board_mobile.png", full_page=False)
    try:
        m.eval_on_selector("tr.row", "el=>el.click()")
        m.wait_for_timeout(400)
        m.screenshot(path="out/board_mobile_expanded.png", full_page=False)
    except Exception as e:
        print("expand mobile err", e)
    m.close()
    b.close()
print("shots written to out/board_*.png")
