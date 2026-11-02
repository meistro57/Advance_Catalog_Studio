# Verification log — Advance Steel 2026

Manual evidence for anything the repo treats as **verified**. Every write path
in `TODO.md` is gated on an entry here. Add a new section per test; never edit a
past entry except to correct it (note the correction).

Each entry records:

- Advance Steel build / service pack, and where it ran (test VM, never a live
  project database);
- the catalog or style file used (name, source, checksum if practical);
- the exact operation (tool page, wizard, SQL script) and the expected result;
- the observed result, with a log line, screenshot path, or import message;
- verdict: **pass**, **fail**, or **inconclusive**, plus what that unblocks.

## Template

```
### A0 — <short title>

- Date / operator:
- AS build:
- File(s):
- Operation:
- Expected:
- Observed:
- Evidence: <path to screenshot/log inside the repo, if publishable>
- Verdict: pass | fail | inconclusive
- Unblocks: <TODO item(s)>
```

## Pending

| ID | Item | Status |
| --- | --- | --- |
| A1 | Bolt `Position1..6` semantics | not started |
| A2 | Anchor `Position` semantics | not started |
| A3 | Shear-stud clone round trip and `ConnectorRelations.Key` | not started |
| A4 | Drawing-style edit round trip (same-name import) | not started |
| A5 | `AstorDetailsBase` enum labels in the AS UI | not started |
| A6 | Exported `.mdf` / `.ldf` pair imports cleanly | not started |

## Known results

Nothing has been verified against a live Advance Steel 2026 install in this
repository yet. The sample catalogs and exports were inspected at the SQL level
only; that is why the viewers are read-only and why the clone/usage/batch tools
report instead of applying.
