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
| A6 | Exported `.mdf` / `.ldf` pair imports cleanly | failed on SQL 2022 (A6.1); fix in place, re-test pending |

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

### A6.1 — Export from a SQL Server 2022 scratch container fails to import

- Date / operator: 2026-11-03 / Mark Hubrich (import), file versions read in
  a scratch container.
- AS build: Advance Steel 2026 (build not recorded).
- File(s): `Marks 6 - Railing (Mp is Handrail)` style export.
- Operation: Drawing Style Manager → Import Drawing Styles on a file exported
  by Catalog Studio.
- Expected: the style list fills.
- Observed: "Import/Export error — Source database is older than Release
  5.1!". `DBCC CHECKPRIMARYFILE`: the original AS export is file version
  **904** (SQL Server 2019); after attaching to `mssql/server:2022` it is
  **957**. The same file attached, edited and detached on
  `mssql/server:2019-latest` stays **904**. All sample catalogs in
  `samples/` and `raw_files/` are 904.
- Verdict: **fail** on 2022, cause found. Attach and create now refuse when the
  server or the file is newer than 904 (`db.require_as_compatible`).
- Unblocks: re-run this import with a file exported from a 2019 container to
  close A6.
### A6.2 — Scratch container rebuilt on 2019; attach path re-verified

- Date / operator: 2026-11-03 / repair of the local scratch environment.
- Why: the `hilti-scratch-sql` container had been created from
  `mssql/server:2022-latest` (file version 957). After A6.1's guard landed,
  every attach was refused, so detached databases could not be brought back.
- Done: the 2022 container and its files were removed, and the container was
  recreated from `mcr.microsoft.com/mssql/server:2019-latest` on
  `127.0.0.1:1433` (same name, `--restart unless-stopped`, configured SA
  password). Only 904 files were kept behind.
- Second defect found during the rebuild: copying a file into
  `/var/opt/mssql/attach` chowned it to `mssql:mssql`, but the 2019 image has
  no `mssql` group (user `mssql` runs with gid 0), so the copy step failed with
  "invalid group" before SQL Server saw the file. `docker_ops` now sets the
  owner only (`chown mssql`), which works on both images.
- Verified end to end on the rebuilt server: `server_file_version()` reports
  **904** and `compatibility_problem()` returns `None`; `samples/A325TC.mdf`
  (904) attaches, `guess_catalog_type` reports **bolt**, 10 tables are listed,
  the database detaches cleanly, and `DBCC CHECKPRIMARYFILE` on the same file
  afterwards still reads **904**. The temporary copy was removed, leaving the
  container with no attached databases.
- Verdict: **pass** for the environment (2019 server, attach/detach, file
  version preserved). A6 stays open: the Advance Steel import itself has not
  been re-run.
