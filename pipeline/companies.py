"""Load companies.csv into row dicts."""
from __future__ import annotations

import csv
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(REPO_ROOT, "companies.csv")


def load_companies(path=CSV_PATH, active_only=True):
    """Return companies.csv as a list of row dicts."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if active_only and str(row.get("active", "")).strip().lower() != "true":
                continue
            rows.append(row)
    return rows
