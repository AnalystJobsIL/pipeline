"""Atomic file writes for the state files everything else depends on.

`open(path, "w")` truncates immediately. A process killed between the truncate and the end
of `writerows` leaves a SHORT companies.csv — and because most audit steps are
`continue-on-error: true`, the job then happily commits the truncated registry. Low
probability, total blast radius. Write to a temp file in the same directory and
`os.replace` it in (atomic on POSIX and Windows).

    from pipeline.atomic import write_csv_rows, write_json
    write_csv_rows("companies.csv", rows)
"""
from __future__ import annotations

import csv
import json
import os
import tempfile


def _swap(path, write_fn, newline=""):
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=os.path.basename(path))
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8", newline=newline) as f:
            write_fn(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_csv_rows(path, rows):
    """Atomically replace `path` with `rows` (list of lists)."""
    _swap(path, lambda f: csv.writer(f).writerows(rows))


def write_json(path, obj, **kw):
    """Atomically replace `path` with json(obj)."""
    kw.setdefault("ensure_ascii", False)
    kw.setdefault("indent", 1)
    _swap(path, lambda f: json.dump(obj, f, **kw), newline=None)
