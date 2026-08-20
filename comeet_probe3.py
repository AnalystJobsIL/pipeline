"""Dump the Comeet widget config globals (window.comeetvar / window.COMEET / comeetInit args)
which should hold the company uid + token needed to build the careers-api URL."""
import json
import sys
from playwright.sync_api import sync_playwright


def probe(url):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36")
        try:
            pg.goto(url, wait_until="load", timeout=35000)
            pg.wait_for_timeout(6000)
            out = pg.evaluate("""()=>{
                function safe(o){try{return JSON.parse(JSON.stringify(o));}catch(e){return String(o);}}
                var r={};
                if(typeof comeetvar!=='undefined') r.comeetvar=safe(comeetvar);
                if(typeof COMEET!=='undefined') r.COMEET=safe(COMEET);
                if(window.comeetvar) r.win_comeetvar=safe(window.comeetvar);
                if(window.COMEET) r.win_COMEET=safe(window.COMEET);
                // scan inline scripts for comeetInit(...) args and any uid/token
                var s=[].slice.call(document.scripts).map(x=>x.textContent||'').join('\\n');
                var init=s.match(/comeet[A-Za-z]*\\s*=\\s*\\{[^}]{0,400}\\}/i);
                r.inlineConfig = init? init[0].slice(0,400): null;
                var tok=s.match(/token['"\\s:=]{1,4}[A-F0-9]{16,}/i);
                r.tokenHint = tok? tok[0]: null;
                return r;}""")
        except Exception as e:
            out = {"err": f"{type(e).__name__}: {str(e)[:150]}"}
        finally:
            b.close()
    print(f"\n=== {url} ===")
    print(json.dumps(out, indent=1)[:1600])


if __name__ == "__main__":
    for u in sys.argv[1:]:
        probe(u)
