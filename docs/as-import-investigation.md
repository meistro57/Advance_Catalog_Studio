# Why Advance Steel refused an export from Catalog Studio

Investigation report, 2026-11-03, **resolved**. Question: why does Advance Steel
2026 answer *"Source database is older than Release 5.1!"* when importing a
Catalog Studio export?

Companion evidence: `docs/verification-log.md` **A6** and **A6.1–A6.10** (the
chronological test log). This file is the consolidated summary.

## 1. Cause

The `.mdf` records the **physical file paths** of the database. Catalog Studio
attached every upload at `/var/opt/mssql/attach/...`, so exported files carried
Linux paths, and Advance Steel refuses such a file — reporting it as "older than
Release 5.1". An export of the *same database* whose recorded paths are Windows
paths imports normally.

Direct test (A6.10): one file, two unedited round trips, each imported under a
name never used before —

| | Attached as | Recorded path in the mdf | AS import |
|---|---|---|---|
| A | `/var/opt/mssql/attach/RT.mdf` | `/var/opt/mssql/attach/RT.mdf` | **refused** |
| B | `C:\var\opt\mssql\attach\W2.mdf` | `C:\var\opt\mssql\attach\W2.mdf` | **imported** |

Both are file version 904 and differ in 322 bytes. SQL Server on Linux maps
`C:\` onto its own root, so B opens the same file as A; the only difference is
what the file remembers about where it lives.

The original export from Advance Steel recorded a Windows path
(`S:\AS-Anchors\Marks 6 - Railing (Mp is Handrail).mdf`), which is why AS's own
files always imported.

## 2. Fix

- `db.attach_database` / `db.create_empty_database` now hand SQL Server
  `C:\var\opt\mssql\attach\...` paths, so new attachments record Windows paths.
- `db.ensure_windows_file_paths()` re-homes a database attached the old way
  (`MODIFY FILE` + offline/online); **Export a copy** and **Detach & Export**
  call it before writing the pair, so existing attachments are fixed on export
  rather than needing a re-upload.
- `db.get_physical_files()` converts the recorded `C:\...` path back to the
  Linux path that `docker cp` needs.

Verified live: a new attach stores `C:\...`; an old-style database is re-homed
and stays online; both survive detach. Covered by
`tests/test_windows_file_paths.py`.

## 3. Why the investigation took a while

Every symptom pointed at the database contents, and every content check said
the files were identical:

| Hypothesis | Measurement | Verdict |
|---|---|---|
| SQL file version (904 vs 957) | `DBCC CHECKPRIMARYFILE` = 904 for AS's file, an edited style and a stock style | ruled out |
| Schema release | `DbVersion`: `DetObjAnnotationStrategy` = 2, all others 1, in all three files | ruled out |
| Compatibility level | `dbi_cmptlevel` = 120 in all, same as `samples/A325TC.mdf` | ruled out |
| Style content | full row-by-row dump, all 45 tables: identical (pristine vs round trip) | ruled out |
| The `.ldf` (4 KB sectors) | AS imports an **mdf alone** and rebuilds the log | ruled out |
| Line endings / text mode | every file exactly 7,536,640 bytes, 4 `\r\n`, no `.gitattributes` | ruled out |
| Download corruption | SHA-256 of the file on disk equals the served bytes | ruled out |
| Boot page state | boot page restored byte-for-byte from AS's file: still refused | inconclusive |
| **Recorded file paths** | A/B test above; 322 bytes differ, only the path | **cause** |

The one misleading result was the boot-page patch (A6.8): it restored page 1
but the paths are recorded in more than that page — the two variants differ in
322 bytes, not the 18 seen on page 1 — so the patch never actually produced a
Windows-path file.

Two tests kept the investigation honest: an exact byte copy under a new name
imported (so the harness was reliable), and a single unedited attach/detach was
enough to be refused (so the editing path was never the problem).

## 4. Consequences for the tool

- "Export a copy" and "Detach & Export" are now safe for a Windows AS install,
  because the exported pair records Windows paths.
- Files attached before this fix do not need re-uploading: they are re-homed on
  the next export.
- Nothing about this changes the data. Row-for-row, an export is the database
  the user attached.

## 5. Still to confirm

One edited export made through the app, imported by Advance Steel. That is the
last step of A6; everything up to it is verified.

## 6. Environment state

- `hilti-scratch-sql` — SQL Server 2019 (file version 904), running.
- Attached: `mark_rail` (attached before the path fix, so it will be re-homed on
  its next export).
- Probe and comparison databases removed; the files placed for testing remain
  in the repo (`column.mdf`, `ladder.mdf`, `Marks_Ladder.mdf`, `as-import-test*`
  folders).
