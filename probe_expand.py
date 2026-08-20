"""One-off: probe a big list of Israeli high-tech companies not yet in companies.csv,
across the guessable ATS platforms. Prints real hits for manual verification + add."""
import csv
from probe_ats import probe, slug_variants

have = {r["company_name"].lower() for r in csv.DictReader(open("companies.csv", encoding="utf-8"))}
NAMES = [
    # cybersecurity (batch 2)
    "Pentera", "Cynerio", "Sygnia", "Hunters", "Cyberint", "Argus Cyber Security", "Cylus",
    "Otorio", "Deep Instinct", "Morphisec", "Perception Point", "Cynet", "Medigate",
    "Cybersixgill", "Wiliot", "Karamba Security", "Sweet Security",
    # fintech (batch 2)
    "PayEm", "Trustmi", "Mesh Payments", "Sunbit", "Fairmarkit", "Finaloop", "Okoora",
    "Sedric", "Credorax",
    # data / AI / devtools (batch 2)
    "DagsHub", "Datagen", "Anecdotes", "Torii", "Firefly", "Silk", "Zesty", "Codefresh",
    "Logz.io", "Aquarium", "Anima", "Bit", "Placer.ai", "Verbit",
    # sales / martech
    "Walnut", "Demostack", "Syte", "Fast Simon",
    # health-tech
    "TytoCare", "Healthy.io", "K Health", "Nucleai", "Genoox", "Sight Diagnostics",
    # mobility / hardware
    "Hailo", "Innoviz", "REE Automotive", "Fabric",
]

seen = set()
for n in NAMES:
    if n.lower() in have or n.lower() in seen:
        continue
    seen.add(n.lower())
    probe(n, slug_variants(n))
print("DONE")
