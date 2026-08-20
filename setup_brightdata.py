#!/usr/bin/env python3
"""One-time Bright Data setup. Prompts for your API token + Web Unlocker zone name, stores them in
secrets.env (git-ignored) and as GitHub Actions secrets, then verifies with ONE request. The values
are never printed and never shown to Claude.

Get them from https://brightdata.com/cp:  create a "Web Unlocker API" zone (free tier: 5,000
requests/month), then copy the zone name (Overview tab) and your account API token (Settings ->
API tokens).
"""
import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(ROOT, "secrets.env")


def upsert_env(key, val):
    lines = []
    if os.path.exists(ENV):
        with open(ENV, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip() and not l.startswith(key + "=")]
    lines.append(f"{key}={val}")
    with open(ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    print("Bright Data setup (values stay on your machine + GitHub secrets)")
    token = input("Paste your Bright Data API token: ").strip()
    zone = input("Paste your Web Unlocker zone name (e.g. web_unlocker1): ").strip()
    if not token or not zone:
        print("empty input — aborting")
        return 1
    upsert_env("BRIGHTDATA_API_KEY", token)
    upsert_env("BRIGHTDATA_ZONE", zone)
    print("saved to secrets.env")
    for name, val in (("BRIGHTDATA_API_KEY", token), ("BRIGHTDATA_ZONE", zone)):
        try:
            subprocess.run(["gh", "secret", "set", name, "--body", val],
                           cwd=ROOT, check=True, capture_output=True)
            print(f"GitHub secret {name}: set")
        except Exception:  # noqa: BLE001
            print(f"GitHub secret {name}: FAILED (run: gh secret set {name})")
    # verify with one request (prints only byte count, never the key)
    body = json.dumps({"zone": zone, "url": "https://www.superplay.com/careers",
                       "format": "raw"}).encode()
    req = urllib.request.Request("https://api.brightdata.com/request", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = r.read()
        print(f"VERIFY OK: unlocked a Cloudflare-blocked page, {len(data)} bytes returned")
    except Exception as e:  # noqa: BLE001
        print(f"VERIFY FAILED: {type(e).__name__} — check token/zone in your dashboard")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
