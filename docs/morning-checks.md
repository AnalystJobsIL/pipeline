# Morning checks — the archive

Append-only. `HANDOFF.md`'s `## Morning checks` table holds rows that are due soon or were
answered in the last week; once a row is older than that it moves here **verbatim**, so the
repo keeps a record of how often its own predictions came true.

That record is worth keeping for one reason: on 2026-08-27 the `docs` lane found **fourteen**
`Morning check <date>:` sentences buried in `HANDOFF.md`'s prose and **not one of them had
ever been answered**. When they were finally answered in a batch, **8 of the 17 clauses
failed** — including two that had shipped to subscribers twice (`### Tel Aviv` and
`### Jobgether` both appeared as employer headings in the 2026-08-26 email against checks
that said neither would). A prediction nobody checks is not a safety net; it is a note.

`docs/check_docs.py::check_morning_checks` warns on a row past its date with an empty
verdict, and errors on a verdict the reader cannot check. An unanswered check is deliberately
a **warning** — the session that wrote it is rarely the session that is pushing when it comes
due, and the cheapest way to make an error go green would be to delete the check.

## 2026-08

*(Nothing has aged out yet. The first rows will arrive from `HANDOFF.md` on or after
2026-09-02, seven days after the batch answered on 2026-08-27.)*
