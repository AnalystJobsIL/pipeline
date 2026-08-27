#!/usr/bin/env python3
"""Did today's digest actually reach the mail? A tripwire that does NOT run on GitHub.

    python digest_watchdog.py                 # check; alert if today's mail did not happen
    python digest_watchdog.py --dry-run       # say the verdict, write nothing
    python digest_watchdog.py --deadline 11:00 --alert ~/Desktop/DIGEST-ALERT.txt

WHY IT IS NOT A CRON (2026-08-27). Every "the run broke" path in this repo fires from inside
a digest, so a run that never starts is silent. The obvious fix is a watchdog cron -- and on
2026-08-27 that would have produced nothing, because **9 scheduled dispatches were due across
the two repositories and 1 fired**: pipeline 1 of 5 (00:00 arrived at 05:41; 02:30, 05:00,
06:00, 08:00 dropped) and the private relay 0 of 4. GitHub's scheduler failed as one thing.
Anything hosted on it fails with it, including a watchdog, including the relay repo's clock.

So this runs on the OPERATOR'S MACHINE, and it is the narrowest thing that can:

  * it does NO production work -- the standing position is that production belongs in the
    cloud, and the local firmographics chain was disabled for doing work here, not for
    checking. This writes one alert file and never touches the checkout;
  * it needs NO credential and no `gh`. It reads two files over plain HTTPS from the PUBLIC
    repo, so it cannot leak the identity the public repos are kept clear of
    (`CLAUDE.local.md`), and it works with no auth configured at all;
  * it cannot dispatch anything. Triggering a workflow from here would put the operator's
    account on a public run page, which `CLAUDE.local.md` section 3 forbids -- so this
    NOTICES, and a human decides.

Its one real limitation, stated plainly: **if the machine is asleep, there is no alarm.**
That is the price of the operator having declined an outbound dead-man's switch, which is
the only mechanism that needs neither this machine nor GitHub's scheduler (BACKLOG 308).

To install it (operator action -- deliberately not automated):

    Register-ScheduledTask -TaskName 'AnalystJobsIL-DigestWatchdog' -Trigger `
      (New-ScheduledTaskTrigger -Daily -At 14:30) -Action `
      (New-ScheduledTaskAction -Execute 'python' `
         -Argument 'digest_watchdog.py' -WorkingDirectory '<repo>')

14:30 local (UTC+3) is 11:30 UTC -- after the relay's last poll at 10:17 plus the 35-53 min
of scheduler lag measured on 2026-08-26, so a merely-late morning has finished being late.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

RAW = "https://raw.githubusercontent.com/AnalystJobsIL/pipeline/master/"
RECEIPT = "cloud_state/last_delivered.json"
DIGEST = "digests/latest.md"
DEFAULT_ALERT = os.path.join(os.path.expanduser("~"), "Desktop", "DIGEST-ALERT.txt")


def fetch(path, timeout=20):
    """(bytes, None) or (None, why). A network failure is NOT evidence of a missed digest."""
    try:
        req = urllib.request.Request(RAW + path, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:                              # noqa: BLE001 -- offline, DNS, TLS
        return None, f"{e.__class__.__name__}: {str(e)[:80]}"


def verdict(today, receipt_bytes, digest_bytes, why_receipt, why_digest):
    """(ok, headline, detail). `ok` False only when we can PROVE the mail did not happen."""
    if receipt_bytes is None and digest_bytes is None:
        return True, "could not reach GitHub", (
            f"receipt: {why_receipt}; digest: {why_digest}. Not treated as a missed digest -- "
            f"a watchdog that cries wolf when the wifi drops is a watchdog that gets ignored.")
    head = ""
    if digest_bytes is not None:
        lines = digest_bytes.decode("utf-8", "replace").lstrip().splitlines()
        head = lines[0] if lines else ""
    rec = {}
    if receipt_bytes is not None:
        try:
            loaded = json.loads(receipt_bytes.decode("utf-8", "replace"))
            rec = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            rec = {}
    when, past_cutoff = str(rec.get("date") or "?"), bool(rec.get("past_cutoff"))

    if head.startswith("# ⚠️ No digest"):
        return False, f"the run FAILED and said so ({today})", (
            f"origin's digests/latest.md is a failure notice: {head[:120]}. The mail you got "
            f"is that notice. Check the run log it links to.")
    if when == today and not past_cutoff:
        return True, f"delivered for {today}", f"receipt: {json.dumps(rec, ensure_ascii=False)[:200]}"
    if when == today and past_cutoff:
        return False, f"written for {today} but AFTER the relay's last poll", (
            "so it was probably never mailed, and tomorrow's run overwrites it before "
            "tomorrow's first poll. Roles were NOT marked sent, so nothing is burned.")
    try:
        age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(when)).days
    except ValueError:
        age = None
    return False, f"NO digest delivered for {today}", (
        f"the last delivery on origin is {when}"
        + (f", {age} day(s) ago" if age is not None else "")
        + f". digests/latest.md still reads: {head[:100]!r}. "
        f"Nothing in this pipeline will say so on its own -- every alarm it has fires from "
        f"inside a run that did not happen (BACKLOG 292).")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alert", default=DEFAULT_ALERT, help="where to write the alert file")
    ap.add_argument("--deadline", default="11:00",
                    help="UTC HH:MM before which a missing digest is merely late (default 11:00, "
                         "after the relay's last poll at 10:17 plus the measured lag)")
    ap.add_argument("--date", help="pretend it is this date (testing)")
    ap.add_argument("--dry-run", action="store_true", help="print the verdict, write nothing")
    a = ap.parse_args(argv)

    now = dt.datetime.now(dt.timezone.utc)
    today = a.date or now.date().isoformat()
    try:
        hh, mm = (int(x) for x in a.deadline.split(":"))
    except ValueError:
        print(f"--deadline {a.deadline!r} is not HH:MM; using 11:00", flush=True)
        hh, mm = 11, 0
    if not a.date and (now.hour * 60 + now.minute) < (hh * 60 + mm):
        print(f"watchdog: {now:%H:%M}Z is before the {a.deadline}Z deadline; too early to judge",
              flush=True)
        return 0

    rb, wr = fetch(RECEIPT)
    db, wd = fetch(DIGEST)
    ok, headline, detail = verdict(today, rb, db, wr, wd)
    print(f"watchdog: {'OK' if ok else 'ALARM'} -- {headline}", flush=True)
    print(f"  {detail}", flush=True)
    if a.dry_run:
        return 0 if ok else 1
    if ok:
        if os.path.exists(a.alert):
            os.unlink(a.alert)                          # clear a stale alarm on a good day
            print(f"  cleared {a.alert}", flush=True)
        return 0
    try:
        os.makedirs(os.path.dirname(os.path.abspath(a.alert)) or ".", exist_ok=True)
        with open(a.alert, "w", encoding="utf-8") as f:
            f.write(f"{headline}\n\n{detail}\n\nchecked {now:%Y-%m-%dT%H:%MZ} by "
                    f"digest_watchdog.py\nhttps://github.com/AnalystJobsIL/pipeline/actions\n")
        print(f"  wrote {a.alert}", flush=True)
    except OSError as e:
        print(f"  could not write {a.alert}: {e}", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
