#!/usr/bin/env python3
"""Superseded shim — kept only so documents that name it stay true until the docs lane
retires it (docs/BACKLOG.md, scraper lane 2026-08-24).

It existed to scrape rows activated after the 00:00 refresh and merge them into
scraped_cache.json. No workflow ever ran it, and in the cloud the refresh always follows the
19:00 hunt (both share the `repo-state` concurrency group), so the gap it described does not
occur. The one useful behaviour — "scrape the active rows that have no cache entry and merge
the hits" — is now `python refresh_scrape_cache.py --only-missing --apply`.
"""
from __future__ import annotations

import sys


def main():
    print("cache_new_rows.py is superseded: delegating to "
          "`refresh_scrape_cache.py --only-missing` (add --apply to merge)", flush=True)
    passthrough = [a for a in sys.argv[1:] if a in ("--apply", "--dry-run")]
    from refresh_scrape_cache import run
    return run(["--only-missing", *passthrough])


if __name__ == "__main__":
    sys.exit(main())
