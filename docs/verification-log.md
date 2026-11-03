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
| A5 | `AstorDetailsBase` enum labels in the AS UI | in progress — one drawing observation (A5.1), DSM list not read yet |
| A6 | Exported `.mdf` / `.ldf` pair imports cleanly | not started |

## Known results

Nothing has been verified against a live Advance Steel 2026 install in this
repository yet. The sample catalogs and exports were inspected at the SQL level
only; that is why the viewers are read-only and why the clone/usage/batch tools
report instead of applying.

### A5.1 — Dimension direction and type from a real railing detail

- Date / operator: 2026-11-03 / Mark Hubrich (drawing and export); export read
  at SQL level in the scratch container.
- AS build: Advance Steel 2026 (build not recorded).
- File(s): `Marks 6 - Railing (Mp is Handrail)` style export (`.mdf`/`.ldf`,
  not committed) and the detail it produced (front view, `MA1`, Pipe 1 1/4 Std,
  1 1/2" = 1'-0").
- Operation: compared each `DetViewDimRequestLinear` of the front view's
  strategy (`RAIL FRONT MINIMAL`, items 1-3, all `Type` 2) with the dimensions
  printed on the detail.
- Expected: one printed chain per request that finds points.
- Observed:
  - `X view - Railing Posts` (Direction 0, ArrangeAbove 0; points: post
    system lines "Bottom-Any" + `Assembly overall`) printed the bottom string
    8 13/16" · 3'-11" ×5 · 13/16", horizontal, below the view.
  - `X - Extremes - Top` (Direction **4**, ArrangeAbove 1; point
    `Mp | Extreme`) printed 19'-3 9/16" **parallel to the sloped handrail**
    (the main part), above the view.
  - `Y - Assembly overall - Top` (Direction **5**, ArrangeAbove 1; point
    `Assembly overall`) printed nothing visible.
  - Every printed chain shows segment values, not running totals
    (`DetViewDimStrategyItems.Type` = 2).
- Evidence: Mark's screenshot of the detail (not committed).
- Verdict: **inconclusive**. One drawing is consistent with Direction 4 =
  "along the main part's X axis" and Type 2 = a relative (chained) linear
  dimension, but neither number has been read from the DSM's own lists.
  The editor shows both as **observed**, never as verified. Direction 5 is
  unexplained; why its chain printed nothing is open.
- Unblocks: nothing yet. Next step for A5: open these requests in the DSM and
  record the direction and dimension-type names shown for 4, 5 and 2.
