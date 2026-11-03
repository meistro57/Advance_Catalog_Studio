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
| A6 | Exported `.mdf` / `.ldf` pair imports cleanly | **pass** with Windows-form file paths (A6.10); confirm with an edited export through the app |

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
### A6.3 — A 904 export is refused too, so the SQL file version is not the whole story

- Date / operator: 2026-11-03 / same railing style, after the scratch container
  was rebuilt on SQL Server 2019 (A6.2).
- What was imported: `marks_rail.mdf` + `marks_rail_log.ldf`, exported by
  Catalog Studio from the 2019 container at 2026-11-03 09:59.
- Observed: Advance Steel reports the same *"Source database is older than
  Release 5.1!"* it gave for the 2022 (957) export in A6.1. The file itself is
  **904**: `DBCC CHECKPRIMARYFILE` reads version 904, it attaches and detaches
  cleanly on the scratch 2019 server, `compatibility_level` is 120 (identical
  to the working `samples/A325TC.mdf`), and its `DbVersion` table lists schema
  versions per detail table (`DetObjAnnotationStrategy` = 2, the rest = 1).
- Reading: A6.1's conclusion covered only one cause. A file that is 904 can be
  refused as well, so the message is not a reliable statement about SQL Server
  file version — Advance Steel compares something else (most likely the
  per-table schema release in `DbVersion`) and words every mismatch as
  "older". Do not treat 904 as proof that an export will import.
- Next experiment: export the same style (and one stock style) **directly from
  Advance Steel 2026's Drawing Style Manager**, then compare that file's
  `DbVersion` and table list with ours. That isolates "our export is wrong"
  from "this style library predates AS 2026".
- Verdict: **open**. A6.1's fix (2019 container) removes one real hazard but
  does not close A6.
- Follow-up (same day): a second style export attached for comparison
  (`Beam`) has the same 45 tables and identical `DbVersion` rows as both the
  railing style and our re-export of it, and `compatibility_level`, state and
  page-verify options match. Catalog Studio's export is therefore a faithful
  round trip of what Advance Steel produced — the refusal is not caused by
  anything this tool writes. The remaining split is "this style library predates
  what AS 2026 accepts" versus "AS refuses re-imports of its own export here";
  importing an AS-produced file straight into AS still decides it.

### A6.4 — Two databases were attached on one physical file

- Date / operator: 2026-11-03 / found while exporting a copy of `mark_rail`.
- Observed: `sys.master_files` showed `Beam` and `mark_rail` both pointing at
  `/var/opt/mssql/attach/Marks_6_-_Railing_Mp_is_Handrail.mdf` (with different
  log files). Taking one online failed with `FCB::Open ... OS error 5 (Access is
  denied)` and left it `RECOVERY_PENDING`, undetachable (`5173`: files do not
  match the primary file).
- Cause: attach copied the staged upload into the container under its uploaded
  filename, so attaching the same file twice under two database names gave both
  databases the same `mdf`. SQL Server can only open a database file for one
  database at a time; the second one gets the access error.
- Fixed: attach copies in as `<db>.mdf` / `<db>_log.ldf`, so every database owns
  its files (`tests/test_attach_files.py`).
- Repair: the wedged duplicate was dropped, and one copy was re-attached from
  its own export pair (its own files, 45 tables, ONLINE). No user data was lost;
  the style database had been exported minutes earlier.
- Verdict: **fixed** (code + tests). This also explains the 16:16 export
  failure that A6.3 was investigating.

### A6.5 — The scratch container rewrites the log to 4 KB sectors

- Date / operator: 2026-11-03 / after A6.4.
- Observed: importing `column.mdf`, exported by Advance Steel itself and never
  opened by Catalog Studio, gives **no error**. The same style exported through
  the scratch container is refused.
- Difference found: every log file attached to the container is rewritten
  ("The tail of the log ... rewritten to match the new sector size of 4096
  bytes") — confirmed for `Marks_6_-_Railing`, `ladder`, `zz_off`,
  `zz_root_ladder`, `zz_i` and `column` itself. Advance Steel's own logs are
  512-byte-sector files; the container's disk is 4 KB, so any `.ldf` that has
  been attached here leaves as a 4 KB-sector log. The `.mdf` differs only in
  SQL bookkeeping (12 720 bytes across 71 of 920 pages, no row or schema change).
- Reading: the rewritten `.ldf` is the one artefact a round trip creates that
  Advance Steel never produces itself, and a mismatched log is enough to make an
  attach fail — which AS reports with the same generic "Source database is older
  than Release 5.1!" message it used for the 2022 files.
- Next experiment: import the exported `.mdf` **without any `_log.ldf` beside
  it**, so the target instance rebuilds the log at its own sector size. If that
  imports, `Export a copy` should stop shipping the log (or ship it with a
  warning).
- Verdict: **open**, prime suspect identified.

### A6.6 — The log is not the cause; the round-tripped mdf is

- Date / operator: 2026-11-03, after A6.5.
- Observed: Advance Steel imports `column.mdf` **with no log file beside it**
  without error — so it rebuilds the log itself, and the 4 KB-sector `.ldf` the
  scratch container writes cannot be what it rejects. The same test with
  `mark_rail.mdf` (a file that has been through the container) fails with the
  usual "older than Release 5.1".
- Difference now isolated to the `.mdf` written by the container. A round trip
  of the known-good file changes 12 720 bytes over 71 of 920 pages: 40 data
  pages (3 826 body bytes), 29 index pages (7 975 body bytes), the boot page and
  one PFS page. Attaching a database created by SQL Server 2014
  (`dbi_createVersion` 782) to this 2019 instance lets SQL upgrade/reorganise
  catalog pages, which is the kind of change Advance Steel may read as an
  unexpected release.
- Next experiment: import a round-tripped **but unedited** copy of
  `5 - Column` (`as-import-test-roundtrip/column.mdf`). Accepting it means the
  edit path is at fault; rejecting it means no file that passes through this
  container can be imported, whatever was edited.
- Verdict: **open**, narrowed to the mdf.

### A6.7 — Content survives; the container's page bookkeeping does not

- Date / operator: 2026-11-03, after A6.6.
- Observed: a round-tripped **unedited** copy of `5 - Column` is refused by
  Advance Steel, while the same database exported by AS is accepted. Data is
  untouched by the round trip: `CHECKSUM_AGG(BINARY_CHECKSUM(*))` and row
  counts are identical for **all 45 tables** between a pristine attach and a
  round-tripped attach of the same file.
- What does differ: 71 of 920 pages (40 data pages, 29 index pages, boot page,
  one PFS page) and, on the boot page, **18 bytes** — page-header LSN/checksum
  plus a handful of DBINFO fields. `dbi_version`, `dbi_createVersion`,
  `dbi_status`, `dbi_dbccFlags`, `dbi_cmptlevel` and the collation are all
  unchanged.
- Reading: the exported file is semantically the same database, but it carries
  bookkeeping (recovery/LSN state) written by this container's SQL Server that
  AS's own export never has. That is the only remaining explanation for the
  refusal, and it means any file that passes through the scratch server is
  suspect regardless of what was edited.
- Next step to test: have the **user's** SQL Server attach and detach the
  exported file, so the bookkeeping is written by the instance AS trusts, then
  import. If that works, the round trip has to hand over a `.bak` plus a
  documented restore-and-detach instead of raw mdf/ldf.
- Verdict: **open**; export format (raw files) is the problem, not the data.

### A6.8 — The control works, so the bytes are decisive

- Date / operator: 2026-11-03, after A6.7.
- Control: an exact byte copy of the known-good export (different filename,
  `cmp`-verified) imports without error, so the earlier accept/reject results
  are reproducible and the difference really is in the file bytes.
- Since all 45 tables are value-identical either way, the candidate is the boot
  page: a round-tripped file whose boot page (page 1) is restored byte-for-byte
  from Advance Steel's own export attaches cleanly here
  (`FOR ATTACH_REBUILD_LOG`, state ONLINE), so the patch is structurally valid.
- Next experiment: hand that patched file to Advance Steel. Accepting it pins
  the refusal to boot-page state, and the fix is to re-apply the original boot
  page on export (capture it when the file is attached, restore it when the
  copy is written). Rejecting it means the difference lies in data/index page
  bookkeeping and the export has to be rebuilt another way.
- Verdict: **open**, narrowed to the boot page.

### A6.9 — Boot page cleared; the difference is page bookkeeping

- Date / operator: 2026-11-03, after A6.8.
- Observed: the round-tripped file with Advance Steel's own boot page restored
  is still refused. The boot page is therefore not what AS reads.
- What is left: 40 data pages and 29 index pages rewritten by this container's
  SQL Server (page checksums, LSNs, row slot layout) while every one of the 45
  user tables holds identical values. No SQL command restores those pages to
  the shape a Windows instance writes, and hand-patching them would mean
  recomputing page checksums.
- Consequence: exports from the Docker/WSL scratch server cannot be imported by
  Advance Steel on this machine, whatever was edited. A Windows SQL Server for
  the scratch instance (separate from AS's own) is the only path left that
  keeps AS's database untouched.
- Verdict: **open, blocked on environment**. A6 stays open until an export from
  a Windows-hosted scratch instance is imported.

### A6.10 — Advance Steel refuses Linux file paths stored in the mdf

(Numbered after A6.5–A6.9 in the local investigation log, which established
that data, schema release, compatibility level, boot page, line endings and
the `.ldf` were all identical or irrelevant, and that one unedited
attach/detach cycle was enough to be refused.)

- Date / operator: 2026-11-03 / Mark Hubrich (imports); files built in a
  `mssql/server:2019-latest` scratch container.
- AS build: Advance Steel 2026 (build not recorded).
- File(s): `Marks 6 - Railing (Mp is Handrail)` style export, original pair.
- Operation: two unedited round trips of the same file, each under a name
  never imported before, then Drawing Style Manager → Import:
  - **A** attached as `/var/opt/mssql/attach/RT.mdf` (how the app attached
    until now);
  - **B** attached as `C:\var\opt\mssql\attach\W2.mdf` (SQL Server on Linux
    maps `C:\` to its root, so it is the same file).
- Expected: if the stored file path is the cause, A refused and B accepted.
- Observed: the paths the mdf records (`DBCC CHECKPRIMARYFILE (file, 3)`):
  original `S:\AS-Anchors\Marks 6 - Railing (Mp is Handrail).mdf`, A
  `/var/opt/mssql/attach/RT.mdf`, B `C:\var\opt\mssql\attach\W2.mdf`; both
  904; A and B differ in 322 bytes. **B imported; A did not.**
- Verdict: **pass** for B. Advance Steel rejects a file whose stored paths are
  not Windows paths and reports it as "Source database is older than Release
  5.1!". Fresh names alone (A) did not help, so reused names were not the cause.
- Change: `db.attach_database` / `create_empty_database` give SQL Server
  `C:\...` paths; `db.ensure_windows_file_paths` re-homes databases attached
  the old way (MODIFY FILE + offline/online) before **Export a copy** and
  **Detach & Export**; `get_physical_files` converts back for `docker cp`.
  Checked live: a new attach stores `C:\...`, an old-style database is re-homed
  and stays online, both survive detach.
- Unblocks: A6 once an *edited* export made through the app imports.
