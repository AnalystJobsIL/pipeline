"""Second Comeet probe: scroll to trigger lazy-load, wait long, and dump the widget config
(window globals + the embed element's data-* attributes) plus any careers-api call captured."""
import sys
from playwright.sync_api import sync_playwright


def probe(url):
    hits = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36")
        pg.on("request", lambda r: hits.append(r.url) if ("careers-api/2.0" in r.url or
              ("comeet" in r.url and "position" in r.url.lower())) else None)
        try:
            pg.goto(url, wait_until="load", timeout=35000)
            for _ in range(6):                       # scroll in steps to trigger lazy widgets
                pg.mouse.wheel(0, 1400)
                pg.wait_for_timeout(1500)
            pg.wait_for_timeout(4000)
            cfg = pg.evaluate("""()=>{
                var out={globals:[],embed:null,anyIframeSrc:[]};
                for(var k in window){ if(/comeet/i.test(k)) out.globals.push(k); }
                var el=document.querySelector('[data-comeet-uid],[data-uid],[class*=comeet],[id*=comeet],[data-comeet]');
                if(el){out.embed=el.outerHTML.slice(0,400);}
                out.anyIframeSrc=[].slice.call(document.querySelectorAll('iframe')).map(f=>f.src).slice(0,5);
                if(window.Comeet){try{out.comeetKeys=Object.keys(window.Comeet).slice(0,15);}catch(e){}}
                return out;}""")
        except Exception as e:
            cfg = {"err": f"{type(e).__name__}: {str(e)[:120]}"}
        finally:
            b.close()
    print(f"\n=== {url} ===")
    print("  careers-api/positions requests:", hits[:5] or "NONE")
    print("  comeet globals:", cfg.get("globals"))
    print("  window.Comeet keys:", cfg.get("comeetKeys"))
    print("  embed element:", (cfg.get("embed") or "none")[:300])
    print("  iframes:", cfg.get("anyIframeSrc"))
    if cfg.get("err"):
        print("  ERR:", cfg["err"])


if __name__ == "__main__":
    for u in sys.argv[1:]:
        probe(u)
