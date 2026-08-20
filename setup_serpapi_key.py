#!/usr/bin/env python3
"""Paste-and-go setup for the SerpApi key. Robust replacement for the .cmd batch logic.

Run it (double-click the Desktop launcher, or `python setup_serpapi_key.py`), paste your
SerpApi key at the prompt. It writes the gitignored secrets.env, sets the GitHub Actions
secret, and verifies Israel coverage. Claude never sees the value — you type it here.
"""
from __future__ import annotations

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
GHREPO = "AnalystJobsIL/pipeline"
IS_WIN = os.name == "nt"


def main():
    print("\n  Get a FREE key (no card) at https://serpapi.com  ->  Dashboard  ->  "
          "'Your Private API Key'.\n")
    try:
        key = input("  Paste your SerpApi key and press Enter: ").strip()
    except EOFError:
        key = ""
    if not key:
        print("\n  No key entered. Nothing changed.\n")
        return 1

    # 1) local secrets.env (gitignored; the pipeline reads it every run)
    with open(os.path.join(REPO, "secrets.env"), "w", encoding="utf-8") as f:
        f.write(f"SERPAPI_KEY={key}\n")
    print("  [ok] wrote local secrets.env")

    # 2) GitHub Actions secret (for the cloud run)
    try:
        subprocess.run(["gh", "secret", "set", "SERPAPI_KEY", "--repo", GHREPO, "--body", key],
                       check=True, shell=IS_WIN)
        print("  [ok] set GitHub Actions secret SERPAPI_KEY")
    except Exception as e:  # noqa: BLE001
        print(f"  [!!] GitHub secret step failed ({e}). Add it manually in the repo:")
        print("       Settings > Secrets and variables > Actions > new secret SERPAPI_KEY")

    # 3) verify (prints only a count, never the key)
    print("\n  Verifying Israel coverage...\n")
    subprocess.run([sys.executable, "verify_jsearch.py"], cwd=REPO)
    print("\n  Done. If Israel jobs showed above, you're set (local + cloud).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
