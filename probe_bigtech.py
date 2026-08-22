"""Probe big-tech public job-search APIs for Israel roles."""
import json
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json",
                                               **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def post(url, body, headers=None):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"User-Agent": UA, "Content-Type": "application/json",
                                          "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def try_microsoft():
    url = ("https://gcsservices.careers.microsoft.com/search/api/v1/search"
           "?lc=Israel&l=en_us&pg=1&pgSz=20&o=Relevance&flt=true")
    d = get(url)
    res = d.get("operationResult", {}).get("result", {})
    jobs = res.get("jobs", [])
    print(f"MICROSOFT: total={res.get('totalJobs')} sample:")
    for j in jobs[:5]:
        print(f"   - {j.get('title')} | {j.get('properties',{}).get('locations') or j.get('properties',{}).get('primaryLocation')}")


def try_google():
    url = ("https://careers.google.com/api/v3/search/?location=Israel&page_size=20")
    d = get(url)
    jobs = d.get("jobs", [])
    print(f"GOOGLE: count={d.get('count')} returned={len(jobs)} sample:")
    for j in jobs[:5]:
        locs = ", ".join(x.get("display") for x in j.get("locations", [])[:2])
        print(f"   - {j.get('title')} | {locs}")


def try_apple():
    url = "https://jobs.apple.com/api/v1/search"
    body = {"query": "", "filters": {"range": {"standardWeeklyHours": {"start": None, "end": None}}},
            "page": 1, "locale": "en-us", "sort": "relevance",
            "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"}}
    # Apple location filter needs office IDs; try postLocation search param instead
    d = post("https://jobs.apple.com/api/role/search",
             {"filters": {"locations": ["ISRC"]}, "page": 1})
    print("APPLE (locations=ISRC):", d.get("totalRecords"), "records")
    for j in (d.get("searchResults") or [])[:5]:
        print(f"   - {j.get('postingTitle')} | {j.get('locations')}")


def try_meta():
    # Meta careers uses a GraphQL endpoint with a persisted doc_id (fragile). Try the public REST-ish.
    url = "https://www.metacareers.com/graphql"
    body = {"doc_id": "9114524511922157",
            "variables": {"search_input": {"offices": ["Tel Aviv, Israel"], "results_per_page": 20}}}
    d = post(url, body, headers={"X-FB-Friendly-Name": "CareersJobSearchResultsQuery"})
    print("META:", json.dumps(d)[:200])


for name, fn in [("microsoft", try_microsoft), ("google", try_google),
                 ("apple", try_apple), ("meta", try_meta)]:
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        print(f"{name.upper()}: ERR {type(e).__name__}: {str(e)[:120]}")
    print()
