#!/usr/bin/env python3
"""Merge resolved ATS configs (out/resolved_configs.json) into companies.csv, safely.

LINE-BASED on purpose: only the changed rows are re-serialized; every other line is kept
byte-for-byte. A whole-file DictWriter/csv.writer round-trip re-quotes all 1000+ rows (noisy
diff) and — worse — earlier truncated the file when it hit a row with embedded commas. Here we
match a line by its first CSV field (company_name), rewrite just fields 2-4 of that one line,
and leave the rest untouched.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import os
import re
import sys

# One seam, called through the MODULE (never bound with `from ... import x as y`, which
# makes a separate global that patching the gate cannot reach).
from pipeline import identity_gate as _gate


def _parse(line):
    return next(csv.reader(io.StringIO(line)))


def _fmt(fields):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(fields)
    return buf.getvalue()


def main():
    src = os.environ.get("RESOLVED_OUT", "out/resolved_configs.json")
    if not os.path.exists(src):
        print(f"no {src}; nothing to apply")
        return 0
    resolved = json.load(open(src, encoding="utf-8"))
    with open("companies.csv", encoding="utf-8", newline="") as f:
        lines = f.readlines()
    changed = 0
    for i, line in enumerate(lines):
        if i == 0 or not line.strip():
            continue
        try:
            fields = _parse(line)
        except Exception:  # noqa: BLE001
            continue
        name = fields[0] if fields else ""
        # A verdict a human (or this morning's identity audit) wrote TODAY is newer
        # knowledge than a re-render of the public careers page. Moon Active's page does not
        # expose its Ashby widget, so the resolver reports "no working ATS" for a board we
        # just verified has 33 jobs — and on a lucky sniff it would overwrite it. Same rule
        # merge_csv_rows uses for repaired URLs: never revert to older knowledge.
        note = fields[5] if len(fields) >= 6 else ""
        if name in resolved and re.search(r"(platform-fix|identity|url-repaired|rebrand) "
                                          + _dt.date.today().isoformat(), note):
            print(f"  keep  {name[:28]:29} -> repaired by hand today; resolver output ignored")
            continue
        if name in resolved and len(fields) >= 4:
            plat, tok, api = resolved[name][0], resolved[name][1], resolved[name][2]
            if [fields[1], fields[2], fields[3]] != [plat, tok, api]:
                # This tool cannot ACTIVATE a row -- it never writes col 4 -- but it can
                # RE-POINT an already-active one at another company's board, and its gate is
                # upstream in `resolve_llm._verify`, not here. It was invisible to the
                # derived writer enumeration until 2026-08-24 because its write is a TUPLE
                # target (`fields[1], fields[2], fields[3] = ...`).
                #
                # A VETO on proven foreignness, never a demand for proof. `api` is usually a
                # machine endpoint, so requiring `page_names_company` here would refuse every
                # ATS re-point -- the same over-block measured at 358 rows in
                # docs/BACKLOG.md 33. `tenant_is_this_company` returns True when there is
                # nothing checkable, so this fires only on a real mismatch.
                if len(fields) >= 5 and fields[4] == "true" and (
                        _gate.is_foreign(name, api)
                        or not _gate.tenant_is_this_company(name, api)):
                    print(f"  [XX]  {name[:28]:29} -> resolver proposed {api[:44]}, which is "
                          f"not this company's board; active row left pointing where it was")
                    continue
                fields[1], fields[2], fields[3] = plat, tok, api
                if len(fields) >= 6:
                    # through the append-log: a bare concatenation has no cap, and the next
                    # writer's trim then cuts whatever segment happens to be at the boundary
                    from pipeline.notes import replace_own
                    fields[5] = replace_own(fields[5], "self-heal",
                                            f"self-heal {_dt.date.today().isoformat()}: "
                                            f"re-resolved to {plat}")
                eol = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
                lines[i] = _fmt(fields) + eol
                changed += 1
                print(f"  fixed {name[:28]:29} -> {plat} {api[:55]}")
    if not changed:
        print("no changes to apply")
        return 0
    if "--dry-run" in sys.argv:
        print(f"(dry-run) would update {changed} rows")
        return 0
    # atomic: a kill mid-write must not leave a truncated registry
    import os as _os
    import tempfile as _tf
    _fd, _tmp = _tf.mkstemp(dir=_os.path.dirname(_os.path.abspath("companies.csv")) or ".",
                            prefix=".tmp_")
    _os.close(_fd)
    with open(_tmp, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)
        f.flush()
        _os.fsync(f.fileno())
    _os.replace(_tmp, "companies.csv")
    print(f"=== applied {changed} config fixes to companies.csv ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
