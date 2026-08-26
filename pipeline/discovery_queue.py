"""`research_companies.json` — the names funnel's queue, read and written safely.

ABSENT and CORRUPT are different things, and collapsing them destroys the file. Both
discovery bridges used to do exactly that: `except Exception: research = []` in
`discovery_daily.main()` and `_load_json(path, [])` in `discovery_telegram.main()`, each
followed by a write. One half-written file — both steps are `continue-on-error` in the same
`daily-digest.yml` job, and runs do get cancelled — turned 1,606 queued names into whatever
that morning happened to find, with no error and exit 0 (BACKLOG 188).

Two failure shapes, and only the first is the obvious one:

  * unparseable bytes — a truncated `json.dump`;
  * VALID JSON of the wrong type (`{"Wix": {...}}`, what a hand-edit or a bad merge makes).
    `json.load` succeeds, `except Exception` never fires, and the crash lands one line later
    on `e.get(...)` over a dict's keys — which killed `main()` BEFORE `sources.record()`, so
    the day's source liveness went unrecorded and `sources.stale()` lied the next morning.
    That is why the guard here is `isinstance`, not `except`.

The write side is the other half of the same bug: `open(path, "w")` truncates immediately,
so a process killed mid-write IS the corrupt file the reader then has to survive.
`pipeline.atomic` exists for this and the queue was not using it.
"""
from __future__ import annotations

import json
import os

PATH = "research_companies.json"


class QueueUnreadable(Exception):
    """The queue exists and cannot be trusted — never overwrite it, never lose it."""


def load(path=PATH):
    """The queue as a list. ABSENT -> `[]`. CORRUPT -> `QueueUnreadable`."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError as e:
        raise QueueUnreadable(f"{path} exists but is not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise QueueUnreadable(f"{path} holds a {type(data).__name__}, expected a list")
    return data


def write(entries, path=PATH):
    """Replace the queue atomically — a killed write must not leave a short file."""
    from pipeline.atomic import write_json
    write_json(path, entries)
