"""What does a change to the Israel gate move? (lane: classifier)

`pipeline/israel.py`'s `is_israel_job` is the identical predicate at every fetch, activation,
zero-confirmation and resolver site, so a change to it moves every card in both caches at
once. This measures that movement BEFORE it ships: the gate at a git ref against the gate in
the working tree, over every card in `scraped_cache.json` + `discovered_cache.json`, and --
with `--texts` -- over every published role record joined to its stored description, which
is the only place an aggregator row's full text lives (the gate never sees it; the
classifier's head does, after the fill).

It spends nothing: no LLM, no network. It is a measurement tool, nothing imports it.

    python tools/measure_israel_rule.py --base origin/master
    python tools/measure_israel_rule.py --base origin/master --texts --out out/geo.json

Every flipped card is printed with the place that fired, then the per-company before/after
and the companies whose Israel count goes to zero. Read every flip before shipping a rule.
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import os
import subprocess
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import israel                                   # noqa: E402

PUBLISHED = ("open", "closed")


def _base_module(ref, root):
    """`pipeline/israel.py` as it was at `ref`, loaded as `pipeline._israel_base` so a
    relative import in it still resolves against today's package."""
    out = subprocess.run(["git", "show", "%s:pipeline/israel.py" % ref], cwd=root,
                         capture_output=True)
    if out.returncode != 0:
        raise SystemExit("git show %s:pipeline/israel.py failed: %s"
                         % (ref, out.stderr.decode(errors="replace")[:200]))
    mod = types.ModuleType("pipeline._israel_base")
    mod.__package__ = "pipeline"
    mod.__file__ = "<%s:pipeline/israel.py>" % ref
    exec(compile(out.stdout.decode("utf-8"), mod.__file__, "exec"), mod.__dict__)
    return mod


def _flatten(d):
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    return [v for vs in d.values() for v in (vs if isinstance(vs, list) else [vs])
            if isinstance(v, dict)]


def cards(root):
    """[(source, job)] over both caches."""
    out = []
    for name in ("scraped_cache.json", "discovered_cache.json"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            with io.open(p, encoding="utf-8") as f:
                out += [(name.split("_")[0], j) for j in _flatten(json.load(f))]
    return out


def ledger_jobs(root):
    """[(status, job)] for every published role record, carrying its stored description."""
    text = {}
    p = os.path.join(root, "cloud_state", "roles_text.jsonl")
    with io.open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                x = json.loads(line)
                text[x.get("role_id")] = x.get("description") or ""
    out = []
    with io.open(os.path.join(root, "cloud_state", "roles.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            out.append((r.get("status") or "", {
                "company": r.get("company") or "", "title": r.get("title") or "",
                "location": r.get("location") or "", "url": r.get("url") or "",
                "role_id": r.get("role_id"), "description": text.get(r.get("role_id"), "")}))
    return out


def compare(jobs, old, new):
    """(flips, before_by_company, after_by_company). A flip is (source, job, old, new, why)."""
    flips, before, after = [], collections.Counter(), collections.Counter()
    for src, j in jobs:
        o, n = bool(old.is_israel_job(j)), bool(new.is_israel_job(j))
        co = j.get("company") or "?"
        before[co] += o
        after[co] += n
        if o != n:
            flips.append((src, j, o, n, getattr(new, "stated_foreign_place", lambda _j: None)(j)))
    return flips, before, after


def _row(src, j, o, n, why):
    return {"source": src, "company": j.get("company"), "title": j.get("title"),
            "location": j.get("location"), "url": j.get("url"), "role_id": j.get("role_id"),
            "desc_len": len(j.get("description") or ""), "before": o, "after": n,
            "fired_on": why, "label": ""}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/master", help="git ref of the OLD gate")
    ap.add_argument("--root", default=ROOT, help="tree whose caches are read")
    ap.add_argument("--texts", action="store_true",
                    help="also run the classifier head's view: published records + stored text")
    ap.add_argument("--out", default=None, help="write every flip as JSON here")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    old = _base_module(a.base, a.root)
    jobs = cards(a.root)
    flips, before, after = compare(jobs, old, israel)
    print("cards %d; Israel before %d, after %d; flips %d"
          % (len(jobs), sum(before.values()), sum(after.values()), len(flips)))
    for src, j, o, n, why in flips:
        print("  %s  %-10s %-28.28s | %-58.58s | loc=%-24.24s | %s"
              % ("IN->OUT" if o else "OUT->IN", src, j.get("company"), j.get("title"),
                 j.get("location") or "", why))
    moved = sorted(c for c in before if before[c] != after[c])
    print("\ncompanies moved: %d" % len(moved))
    for c in moved:
        print("  %-36.36s %3d -> %3d%s" % (c, before[c], after[c],
                                            "   TO ZERO" if before[c] and not after[c] else ""))
    rows = [_row(*f) for f in flips]

    if a.texts:
        # the head's view: `stated_foreign_place` on the stored text, whatever the old gate did
        led = ledger_jobs(a.root)
        hits = [(s, j, israel.stated_foreign_place(j)) for s, j in led]
        hits = [(s, j, w) for s, j, w in hits if w]
        pub = [(s, j, w) for s, j, w in hits if s in PUBLISHED]
        print("\nledger records %d; the head would reject %d (published %d)"
              % (len(led), len(hits), len(pub)))
        for s, j, w in hits:
            print("  %-10s %-26.26s | %-50.50s | loc=%-22.22s | %s"
                  % (s, j["company"], j["title"], j["location"], w))
        rows += [dict(_row("ledger", j, True, False, w), status=s) for s, j, w in hits]

    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with io.open(a.out, "w", encoding="utf-8") as f:
            json.dump({"base": a.base, "flips": rows}, f, ensure_ascii=False, indent=1)
        print("\nwrote %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
