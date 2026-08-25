#!/usr/bin/env python3
"""Cross-validate 'validated-empty' companies — are they REALLY empty?

For each company marked "scanned; no open Israel roles now", fetch its careers page over plain
HTTP and look for CONTRADICTING signals the scraper may have missed:
  - an embedded ATS/Comeet/Workday signature  -> resolve via the ATS API and count Israel jobs
  - Israel city names near role-like words in the raw HTML -> flag as suspect (parse miss)

Promotes any company whose ATS turns out to have live Israel jobs; reports suspects. Updates
companies.csv in place. This is a deterministic audit — no LLM, no browser.
"""
from __future__ import annotations

import csv
import re
import time
import urllib.request

from wayback_rescue import extract_ats
from resolve_deep import _verify
from scrape_universal import ROLE, ISRAEL_LOC
from pipeline import identity_gate as _gate
from pipeline.atomic import write_csv_rows
from pipeline.notes import replace_own as _note_replace
from pipeline.recruiters import is_recruiter
from pipeline.verdicts import is_terminal


def in_validate_empty_pool(r):
    """This tool's OWN membership rule (Sun 04:00, ACTIVATES). Until 2026-08-25 the selector
    was the bare substring `no open israel roles` over EVERY row -- no `active` filter, no
    terminal filter -- so the day ten same-board twins were parked `alias-of` and a city
    name was parked `redundant`, three of them (Primis Tech, kornit, Tel Aviv) were still
    selected, and the promote branch would have re-activated them on Sunday with
    `check_invariants` green (wave-1 pools attacker, reproduced on the real `main()`).
    A row with no address cannot be cross-validated either."""
    return (len(r) >= 6 and r[4] == "false"
            and "no open israel roles" in (r[5] or "").lower()
            and (r[3] or "").startswith("http")
            and not is_terminal(r[5] or "") and not is_recruiter(r[0]))

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"


def _get(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(1_200_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def check(name, url):
    """Return ('promote', row) | ('suspect', reason) | ('confirmed', None)."""
    html = _get(url)
    if len(html) < 500:
        return ("confirmed", None)                 # can't re-check; leave as-is
    det = extract_ats(html, name)
    if det:
        plat, tok, api = det
        v = _verify(name, plat, tok, api)
        if v:
            n_all, il = v
            if il > 0 and (not _gate.activation_ok(name, api, il, html=html)
                           or not _gate.embedded_board_ok(name, tok, api)):
                # `extract_ats` returns whatever board the page embeds. This branch promoted
                # it to ACTIVE on a job count alone, so a careers page embedding a different
                # company's board promoted that board. The page is in hand; use it -- and
                # only to REFUSE: a page naming THIS company cannot vouch for a board it
                # merely embeds (Cogniteam's own page + a stale riskified embed promoted
                # Riskified's board -- wave-4 R1), so the promote also needs
                # `embedded_board_ok`: the board's own tenant token near-matches the name.
                #
                # Return `suspect`, NOT `confirmed`. `confirmed` is the tool's word for
                # "board exists, genuinely 0 Israel now" and for "could not re-check", and
                # `main()` handles it with `confirmed += 1` and nothing else -- no note, no
                # print, no row write. A refusal returned that way is indistinguishable from
                # a real empty, so the row re-enters the same Sunday pool and is refused
                # again, silently, forever. `suspect` writes an `empty-but-suspect` note the
                # next reader can see, and leaves the row's re-check token intact.
                return ("suspect", f"{il} IL but the board is not this company's")
            if il > 0:                              # scraper missed a live board with Israel jobs!
                return ("promote", [name, plat, tok, api, "true",
                                    f"cross-validated; {n_all}/{il} IL (was empty)"])
            return ("confirmed", None)              # board exists, genuinely 0 Israel now
    # textual contradiction: Israel city near a role word
    hits = 0
    for m in ISRAEL_LOC.finditer(html):
        ctx = html[max(0, m.start() - 300):m.end() + 300]
        if ROLE.search(ctx):
            hits += 1
        if hits >= 2:
            return ("suspect", f"{hits}+ role-near-Israel mentions in HTML")
    return ("confirmed", None)


_MODIFIED = set()   # names this run rewrote (single-writer merge)


def main():
    rows = list(csv.reader(open("companies.csv", encoding="utf-8")))
    idx = {r[0].strip(): (i, r[3]) for i, r in enumerate(rows) if in_validate_empty_pool(r)}
    print(f"cross-validating {len(idx)} validated-empty companies ...")
    promoted, suspects, confirmed = 0, [], 0
    for name, (rowi, url) in idx.items():
        try:
            kind, payload = check(name, url)
        except Exception:  # noqa: BLE001
            kind, payload = "confirmed", None
        if kind == "promote":
            # rule 3 at the write site: `check()` builds the row from the page, and the
            # row's OTHER segments (`dark-triage`, an `alias-of`, the hunt's stamp) live in
            # the registry, not in the page -- merge here rather than replace.
            payload[5] = _note_replace(rows[rowi][5] if len(rows[rowi]) > 5 else "",
                                       "cross-validated", payload[5])
            rows[rowi] = payload
            _MODIFIED.add(name)
            promoted += 1
            print(f"  [PROMOTE] {name}: {payload[5]}", flush=True)
        elif kind == "suspect":
            suspects.append((name, payload))
            # Through `pipeline.notes`, like every other note write in the repo. This was
            # the ONE exception: a bare concatenation with no cap, which is why the 220-char
            # limit did not apply to it and the cell grew to 324 chars. The next tool's
            # stamp then evicted whole segments to make room -- including this row's own
            # `no open Israel roles` token, which is `validate_empty`'s entire selector, so
            # the row left its own Sunday pool permanently. Measured on the real registry:
            # 28 of 54 rows lost that token by the next nightly hunt stamp (15 before this
            # branch existed; the longer payload took it to 28). `Kima` lost two tokens at
            # once, the second being `scanned via brightdata`, which `bd_rescue` owns and
            # no scheduled tool rewrites.
            # ...and even capped, this can cost the row its OWN selector. `no open Israel
            # roles` is by construction the OLDEST segment on these rows -- it is how they
            # entered this pool -- and `replace_own` evicts oldest-first to make room. So
            # the write is skipped when it would take the token with it: a note nobody reads
            # is worth less than a row that keeps being re-checked, and the row is still
            # visible in this run's `suspect:` summary either way. Measured on the real
            # registry: 22 of 54 rows would have lost the token; 0 do now.
            _new = _note_replace(rows[rowi][5] or "", "empty-but-suspect",
                                 "empty-but-suspect; " + payload)
            if "no open israel roles" in _new.lower():
                rows[rowi][5] = _new
                _MODIFIED.add(name)
            else:
                print(f"  [note skipped] {name}: the cell is full and the note would evict "
                      f"this row's own re-check token", flush=True)
        else:
            confirmed += 1
        time.sleep(0.1)
    # single-writer discipline: merge back only rows this run modified
    changed = {r[0]: r for r in rows if r and len(r) > 5 and r[0] in _MODIFIED}
    fresh = list(csv.reader(open("companies.csv", encoding="utf-8")))
    for _i, fr in enumerate(fresh):
        if fr and len(fr) > 5 and fr[0] in changed:
            fresh[_i] = changed[fr[0]]
    write_csv_rows("companies.csv", fresh)
    print(f"\n=== promoted {promoted} · suspects {len(suspects)} · confirmed-empty {confirmed} ===")
    for n, why in suspects[:25]:
        print(f"   suspect: {n} ({why})")


if __name__ == "__main__":
    main()
