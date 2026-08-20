"""For a sample of still-unresolved companies, load the careers page and report which ATS host(s)
appear in its network traffic — to see whether adding more ATS fetchers would unlock more coverage."""
import json
import re
from collections import Counter
from playwright.sync_api import sync_playwright

from pipeline.companies import load_companies

ATS_HOSTS = {
    "greenhouse": r"greenhouse\.io", "lever": r"lever\.co", "ashby": r"ashbyhq",
    "smartrecruiters": r"smartrecruiters", "recruitee": r"recruitee", "workable": r"workable",
    "workday": r"myworkdayjobs|workday", "comeet": r"comeet", "breezy": r"breezy\.hr",
    "bamboohr": r"bamboohr", "teamtailor": r"teamtailor", "personio": r"personio",
    "jobvite": r"jobvite", "icims": r"icims", "eightfold": r"eightfold", "taleo": r"taleo",
    "successfactors": r"successfactors|sapsf", "oraclecloud": r"oraclecloud\.com|taleo",
    "rippling": r"rippling", "ripplingats": r"ats\.rippling", "pinpoint": r"pinpoint",
    "jazzhr": r"applytojob|jazz\.co", "recruitcrm": r"recruitcrm", "freshteam": r"freshteam",
    "zoho": r"zohorecruit", "gem": r"gem\.com", "wellfound": r"wellfound|angel\.co",
    "notion": r"notion\.site", "webflow": r"webflow", "wix": r"wixsite|parastorage",
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def detect(url):
    found = set()

    def on_req(r):
        for name, rx in ATS_HOSTS.items():
            if re.search(rx, r.url, re.I):
                found.add(name)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=UA)
        pg.on("request", on_req)
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(4000)
            pg.mouse.wheel(0, 2000)
            pg.wait_for_timeout(2500)
        except Exception:
            pass
        finally:
            b.close()
    return found


def main():
    have = {r["company_name"].strip().lower() for r in load_companies(active_only=False)}
    with open("research_companies.json", encoding="utf-8") as f:
        entries = json.load(f)
    todo = [e for e in entries if (e.get("name") or "").strip().lower() not in have
            and e.get("careers_url")]
    sample = todo[::max(1, len(todo) // 40)][:40]        # ~40 evenly-spaced unresolved
    print(f"sampling {len(sample)} of {len(todo)} unresolved ...")
    tally = Counter()
    for e in sample:
        f = detect(e["careers_url"])
        for a in f:
            tally[a] += 1
        print(f"  {e['name'][:24]:24} -> {sorted(f) or 'none'}")
    print("\n=== ATS seen across sample ===")
    for a, n in tally.most_common():
        print(f"  {a}: {n}")


if __name__ == "__main__":
    main()
