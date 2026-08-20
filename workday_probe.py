"""Probe Workday tenants/sites for a company and report the first combo returning Israel jobs.

Workday api_url pattern: https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
(POST). {tenant}, {N}, {site} vary per company. This tries common combos with searchText=Israel.
"""
import sys

from pipeline import http as _http

# Most tenant/site combos are dead; keep probes snappy so failures can't stall the run.
_orig_req = _http._request
_http._request = lambda *a, **k: _orig_req(*a, **{**k, "retries": 1, "timeout": 6})

from pipeline import fetchers, israel

WD_N = [1, 3, 5, 12, 2, 103, 101]
SITES = ["External", "External_Career_Site", "ExternalCareerSite", "External_Careers",
         "External_Career", "careers", "Careers", "{t}careers", "{t}_careers", "jobs",
         "Ext", "Global", "External_Site", "External_Global", "en-US", "Professional"]


def try_company(name, tenants):
    for t in tenants:
        for n in WD_N:
            for s0 in SITES:
                s = s0.replace("{t}", t)
                url = f"https://{t}.wd{n}.myworkdayjobs.com/wday/cxs/{t}/{s}/jobs"
                row = {"company_name": name, "ats_platform": "workday",
                       "token": f"{t}/{s}", "api_url": url}
                try:
                    jobs = fetchers.fetch_workday(row)
                except Exception:
                    continue
                il = sum(1 for j in jobs if israel.is_israel_job(j))
                tag = "  <== ISRAEL" if il else "  (0 israel)"
                print(f"  HIT {name}: {t}.wd{n} / {s}  jobs={len(jobs)} israel={il}{tag}")
                print(f"       CSV: {name},workday,{t}/{s},\"{url}\",true,\"Global board - Workday\"")
                return True
    print(f"  {name}: no working Workday tenant/site found")
    return False


CANDIDATES = {
    "SAP": ["sap"], "ServiceNow": ["servicenow"], "Qualcomm": ["qualcomm"],
    "Synopsys": ["synopsys"], "Dell": ["dell"], "Amdocs": ["amdocs"], "Nokia": ["nokia"],
    "eBay": ["ebay"], "Snowflake": ["snowflake"], "Verint": ["verint"], "Elbit": ["elbitsystems"],
    "Siemens": ["siemens"], "Philips": ["philips"], "GE": ["ge", "generalelectric"],
    "Medtronic": ["medtronic"], "Nvidia2": ["nvidia"], "Cognyte": ["cognyte"],
    "Akamai": ["akamai"], "Zoominfo": ["zoominfo"], "Fortinet": ["fortinet"],
}

if __name__ == "__main__":
    items = ([(a, [a.lower()]) for a in sys.argv[1:]] if len(sys.argv) > 1
             else list(CANDIDATES.items()))
    for name, tenants in items:
        try_company(name, tenants)
    print("DONE")
