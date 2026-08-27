"""What intake REFUSED, and why — the appeal trail for a name this layer threw away.

`docs/BACKLOG.md` 70: both discovery bridges apply `looks_like_junk` and `is_recruiter` on
every run and keep only a COUNT. `looks_like_junk` does not even print. So a wrongly-rejected
employer is invisible forever and un-appealable: nothing anywhere records that the name was
ever seen, and the source that offered it will not necessarily offer it again — a LinkedIn
card expires, a Telegram post scrolls off the preview. The count told you 32 names died on
2026-08-24 and could not tell you one of them.

This is a merge-only ledger: a name rejected once keeps the date it was FIRST refused, so
"has this ever been refused, and on what grounds?" is answerable offline by one grep. It is
NOT permanent -- `TTL_DAYS` (90) drops a name that has not been re-offered in three months,
because an un-pruned ledger only grows. So the guarantee is precise: any name the sources are
STILL offering is answerable indefinitely, and one refused once and never seen again is
answerable for 90 days. Raise `TTL_DAYS` if that trade is ever wrong.

    from pipeline import intake_ledger
    intake_ledger.record([("Jobgether", "agency"), ("AppSec", "junk-name")])
    python -c "from pipeline import intake_ledger; print(intake_ledger.summary())"

THREE rules this file follows because §1a rule 5 cost the queue 1,606 names:
  * ABSENT is not CORRUPT. A missing file is an empty ledger; a file that parses to the
    wrong TYPE is a refusal to write, never a silent truncation over someone's data.
  * The check is `isinstance`, not `except` — `json.load` accepts `{"Wix": {...}}` happily
    and the failure then lands somewhere unrelated.
  * The write is atomic (`pipeline.atomic`), because `open(path, "w")` truncating is what
    MAKES the corrupt file the next reader has to survive.

Never a gate. Nothing reads this to decide anything; it only records what the gates in
`pipeline/recruiters.py` and `pipeline/firmographics.py` already decided.
"""
import datetime
import io
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "cloud_state", "intake_rejects.json")

# A rejection is evidence, not a verdict, so it expires: a name refused once and never seen
# again is noise after a while, and an un-pruned ledger is a file that only grows. A name
# still being offered daily keeps its `first_seen` and never ages out.
TTL_DAYS = 90


class LedgerUnreadable(Exception):
    """The file exists and is not a ledger. Refuse to write; do not guess."""


def _today():
    return datetime.date.today().isoformat()


def load(path=None):
    """The ledger as {key: record}. Absent -> {}. Present-but-wrong-shape -> raises."""
    p = path or PATH
    if not os.path.exists(p):
        return {}
    try:
        raw = io.open(p, encoding="utf-8").read()
    except OSError as e:
        raise LedgerUnreadable("%s cannot be read (%s)" % (p, e))
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise LedgerUnreadable("%s is not valid JSON (%s)" % (p, e))
    if not isinstance(data, dict):
        raise LedgerUnreadable("%s parsed as %s, not a ledger dict"
                               % (p, type(data).__name__))
    return data


def _key(name):
    return " ".join(str(name or "").strip().lower().split())


def record(rejections, path=None, ttl_days=TTL_DAYS, today=None):
    """Merge `rejections` into the ledger. Returns (n_new, n_seen_again, n_pruned).

    `rejections` is an iterable of (name, reason) pairs or a {name: reason} dict. A reason is
    a short grep-able token (`agency`, `junk-name`, `non-latin-slug`), never a sentence —
    `grep -c agency` has to mean something.

    Returns (0, 0, 0) and prints, rather than raising, when the file is unreadable: this is
    a diagnostic, and a diagnostic must never be able to take down the run it documents.
    """
    p = path or PATH
    day = today or _today()
    try:
        datetime.date.fromisoformat(day)        # a bad `today` must not become a first_seen
    except (TypeError, ValueError):
        day = _today()
    items = rejections.items() if isinstance(rejections, dict) else list(rejections)
    try:
        data = load(p)
    except LedgerUnreadable as e:
        print("::error::intake ledger: %s — not overwriting it; this run's %d rejections "
              "are un-recorded (the names are in the step log)." % (e, len(items)), flush=True)
        return (0, 0, 0)

    new = seen = 0
    for name, reason in items:
        k = _key(name)
        if not k:
            continue
        rec = data.get(k)
        if isinstance(rec, dict):
            rec["last_seen"] = day
            rec["reason"] = str(reason)      # the newest gate to fire wins
            rec.setdefault("name", str(name))
            rec.setdefault("first_seen", day)
            seen += 1
        else:
            data[k] = {"name": str(name), "reason": str(reason),
                       "first_seen": day, "last_seen": day}
            new += 1

    pruned = 0
    if ttl_days:
        try:
            cutoff = (datetime.date.fromisoformat(day)
                      - datetime.timedelta(days=int(ttl_days))).isoformat()
        except (TypeError, ValueError):
            cutoff = None       # an unparseable `today` must not decide what to delete
        # A record with NO `last_seen` is not old, it is INCOMPLETE: `"" < cutoff` is True, so
        # the first cut deleted it and reported it under "aged out" -- silent data loss in the
        # one file whose whole promise is merge-only. Repair it instead. A non-dict value is
        # not prunable at all by the old test, so it was immortal; it is repaired too.
        for k, v in list(data.items()):
            if not isinstance(v, dict):
                data[k] = {"name": str(k), "reason": str(v), "first_seen": day,
                           "last_seen": day}
                continue
            if not v.get("last_seen"):
                v["last_seen"] = v.get("first_seen") or day
        if cutoff:
            for k in [k for k, v in data.items()
                      if str(v.get("last_seen", "")) < cutoff]:
                del data[k]
                pruned += 1

    from pipeline.atomic import write_json
    write_json(p, data)
    return (new, seen, pruned)


def summary(path=None):
    """One line for the step log: how many names this layer is currently refusing, by reason."""
    try:
        data = load(path)
    except LedgerUnreadable as e:
        return "intake-rejects: unreadable (%s)" % e
    if not data:
        return "intake-rejects: 0 names"
    counts = {}
    for v in data.values():
        if isinstance(v, dict):
            counts[str(v.get("reason", "?"))] = counts.get(str(v.get("reason", "?")), 0) + 1
    by = " ".join("%s=%d" % (r, n) for r, n in sorted(counts.items()))
    return "intake-rejects: %d names (%s)" % (len(data), by)
