# AGENTS.md

Guidance for AI agents working in this repository.

## What this project is

**Advance Steel Catalog Studio** is a local, browser-based (Flask) workbench for
inspecting, repairing, creating, and exporting Autodesk Advance Steel component
catalogs stored as SQL Server `.mdf`/`.ldf` database pairs (bolt and anchor
catalogs). It is a **research-driven, early-stage tool**: schemas were reverse
engineered from real Advance Steel 2026 exports, and all database work happens
against a **disposable Docker SQL Server container** — never a live Advance
Steel install.

Two different catalog shapes are supported, selected per-database by table
presence (see `guess_catalog_type` in `catalog_studio/utils/db.py`):

- **bolt** catalogs: `BoltsDiameters`, `BoltsDistances`, `ScrewNew`,
  `SetOfBolts`, `SetBolts`, `SetNutsBolts`, plus lookup tables (`Sets`,
  `Sources`, `Standard`, `StrengthClass`).
- **anchor** catalogs: `AnchorsName`, `AnchorsDefinition`,
  `AnchorsHoleDefinition`, `AnchorsStandard`, `BoltsDiameters`,
  `BoltsDistances`, `SetNutsBolts`, plus lookup tables.

The core "diameter clone" engine (`db.preview_clone_diameter` /
`db.apply_clone_diameter`) copies a working source diameter across all related
tables to create a new target diameter, with optional geometry/weight scaling
and display-name token replacement.

## Running the project

- Python 3.12 venv already exists at repo root (`venv/`); deps are
  `catalog_studio/requirements.txt` (only `Flask` and `pymssql`).
- Dev-only test dependency (`pytest`) is in `requirements-dev.txt`; run the
  suite with `venv/bin/python -m pytest tests/`. Tests are pure unit tests for
  the bolt-set view-model mapping plus route smoke tests — no database needed.
- **No linter, no CI, no Makefile, no packaging config exist.** Verification
  is manual against the Docker SQL Server (plus the pytest suite).
- A Docker container named `hilti-scratch-sql` on `127.0.0.1:1433` must exist
  and be running. SQL Server `sa` password is hardcoded in
  `catalog_studio/config.py` (`Scratch2026!Pw`) and duplicated in every
  root-level CLI script.
- Start the web app (port **5050**): `python catalog_studio/app.py`
- Attach existing catalog pairs (`catalog_studio/uploads/*.mdf`) through the
  web UI (upload → attach), or run one-off inspection/export scripts against an
  already-attached database, e.g.:
  ```bash
  python db_inspect.py A325TC_mark
  python export_bolts.py A325TC_mark out.csv
  python export_catalog.py HiltiHY200 out.csv
  ```
- Checked-in sample data lives in `catalog_studio/uploads/` (A325TC, Grade5,
  US_Hooked_Anchors) and `raw_files/`. `catalog_studio/exports/` and
  `catalog_studio/uploads/` are also the runtime working dirs of the app.

## Code layout

- `catalog_studio/app.py` — all Flask routes; entry point.
- `catalog_studio/config.py` — paths, SQL connection, container name, AS version
  (2026 only; `SUPPORTED_AS_VERSIONS = {2026}`).
- `catalog_studio/utils/db.py` — every SQL Server operation, generic table
  browsing/editing, find & replace, and the diameter clone engine.
- `catalog_studio/utils/docker_ops.py` — shells out to `docker cp`/`exec`/
  `inspect` to move files in/out of the container.
- `catalog_studio/utils/metadata.py` — per-database `catalog_type` and
  `as_version`, stored in a local JSON sidecar
  (`catalog_studio/catalog_metadata.json`), deliberately **not** written into
  the mdf (extra tables would break Advance Steel import).
- `catalog_studio/utils/staging.py` — pairs `.mdf` with `_log.ldf` in uploads/,
  suggests DB names from filenames, lists exports/.
- `catalog_studio/utils/schema_templates.py` — reverse-engineered DDL + seed
  data for freshly created anchor/bolt catalogs.
- `catalog_studio/utils/bolt_sets.py` — bolt-set view model for the graphical
  bolt-set viewer (issue #1). Pure mapping functions (slot parsing,
  SetNutsBolts matching, Position interpretation, stack/grip layout, screw-rule
  normalization) are unit-tested; SQL gathering functions sit at the bottom.
- `catalog_studio/static/vendor/three/` — **pinned local** Three.js r160
  (`three.module.js`, `OrbitControls.js`) so the workshop works offline. The
  viewer template loads it via an import map (`three` and `three/addons/`
  keys); never switch to a CDN.
- `catalog_studio/static/js/bolt-set-viewer.js`, `static/js/bolt-set-layout.js`,
  `static/css/bolt-set-viewer.css`, `templates/bolt_set_viewer.html` — the
  Three.js viewer (Phase 1) + client-side assembly editor (Phase 2).
- `tests/` — pytest suite (conftest puts `catalog_studio/` on sys.path).
- `catalog_studio/templates/*.html` — Jinja2 + Bootstrap 5.3.3 (CDN).
- Root-level `*.py` (`db_inspect.py`, `export_catalog.py`, etc.) — one-off
  diagnostic/export scripts. They do **not** import from `catalog_studio`;
  each hardcodes its own connection settings, target database, and SQL.

## Import convention (critical)

All modules under `catalog_studio/` import siblings as top-level packages:
`from config import ...` and `from utils import db, docker_ops, ...`. These work
only because the script's own directory is prepended to `sys.path` when running
`python catalog_studio/app.py`. Keep this flat-import style in new modules;
never switch to relative imports. Root-level scripts cannot reuse `utils/`
without path hacks and currently don't try.

## Web/data flow

Upload → attach: file copied into the container's `/var/opt/mssql/attach`,
then `CREATE DATABASE ... FOR ATTACH` (docker_ops + `db.attach_database`), then
catalog type is guessed and recorded in the metadata sidecar. Edit flows call
`preview_*` functions to show samples/counts, then `apply_*` functions that
repeat the same logic inside an explicit transaction
(`autocommit=False` + `commit()`/`rollback()`). Export/detach runs
`sp_detach_db`, then `docker cp`s the files back to `exports/` for download.
Also available per table: browse/filter/add/edit/duplicate/delete rows, and a
database-wide find & replace over all text columns.

Bolt-set viewer flow (issue #1): `/db/<db>/bolt-set-viewer` (page, bolt
catalogs only) → the page's JS calls
`/db/<db>/bolt-set-viewer/payload?standard=&set=&material=&diameter=&length=`
which returns the normalized view model: bolt record, component stacks with
server-computed y positions, side ("head"/"nut") and layer tags, schematic
grip, screw rules, warnings, plus `catalog_parts` (every deduplicated
SetNutsBolts record, keyed by Standard/Material/Diameter, for editor
dropdowns). The page always shows a component table as an accessibility
fallback; WebGL is optional.

Phase 2 (assembly editor) is a client-side preview layer: the viewer keeps a
draft copy of the assembly and lets the user swap the component in each
position, move components between head/nut sides, reorder the stack, and
override the schematic grip thickness. Drafts are laid out in the browser by
`static/js/bolt-set-layout.js`, which **mirrors `build_layout()` in
bolt_sets.py** (grip override included) — keep the two files in sync. The
editor never writes SQL; Phase 3 will hand proposals to a server-side
preview/transaction flow.

## Bolt-set viewer: verified vs assumed (issue #1)

Verified from the sample catalogs (A325TC_mark, Grade5) and encoded in
`bolt_sets.py`:
- `SetNutsBolts.Type`: 1 = nut, 2 = washer. Reliable classifier.
- `SetOfBolts` stores components in 6 repeated slots
  `DINn` / `[Diametern (mm)]` / `Materialn` / `Positionn`; the row's
  `Length` INT column is the component count, not a bolt length. Empty slots
  use `'-'` with `0.0` diameter or NULLs.
- `ScrewNew` rows carry up to 7 grip bands (`GripLengthMin/Max` +
  `ScrewLengthBase/Delta`); auto bolt length = base + k·delta to cover the grip.
- Bolt `Length` is the under-head shank length; `SetBolts.NumberOfCorners` is
  unreliable for heads (A325TC records 0 for a hex head) so 6 sides are assumed
  and flagged.

**Assumed, NOT yet verified against a live Advance Steel install** (do not
write positions back to a catalog until confirmed):
- `Position` sign splits head-side (positive) vs nut-side (negative)
  components; magnitude = layer count from the clamped material. Fallback when
  signs don't split (e.g., Grade5 10.0 mm): order by component type, nut
  outermost. The module docstring and the rendered page flag this.
- `ScrewHeadOuterDiameter` / `OutsideDiameter` on polygonal parts are treated
  as across-flats (hex corner radius = (flat/2)/cos(π/n)); washers are round.
- The "grip zone" drawn is schematic: shank length minus hardware stacks; it
  is not a stored catalog value.

## SQL conventions and gotchas

- Values are always parameterized (`%s`); identifiers (table/column/db names)
  are interpolated inside brackets `[...]` and must only ever come from trusted
  sources (validated form input, or names read back from
  `INFORMATION_SCHEMA`/`sys.*`). `db.valid_identifier` (letters/digits/
  underscores) is enforced for DB names; table/column names from URLs are
  checked against `db.list_tables` before use. Keep this discipline in new SQL.
- `db.duplicate_row` handles identity PKs and computes `MAX(pk)+1` otherwise.
- Row CRUD is disabled for tables where `db.guess_primary_key` finds neither a
  real PK nor a column named `ID`.
- `db.VIRTUAL_FILTERS` (db.py) declares per-table "filter by a column on a
  related table" joins; only `AnchorsDefinition` has one today.
- **Schema knowledge from reverse engineering** (see README "Why bolt
  diameters are difficult"):
  - Imperial diameters are stored in **millimetres** (`9.525`, `12.7`, ...).
  - `RunName` strings carry a **deliberate leading space** (`' 3/8 inch'`);
    metric names use zero-padded strings like `' 10.00 mm'`. Preserve this
    when generating or editing display names.
  - A usable bolt diameter needs coordinated rows across up to six tables; a
    row in `BoltsDiameters` alone is an orphan label. Scaling uses
    `target/source` for linear dims and `(target/source)²` for weights.
    Scaled values are starting estimates, never certified product data.
  - The bolt `SetOfBolts` schema repeats six component slots with column names
    like `[Diameter1 (mm)]` (space and parentheses — always bracket these);
    anchors use `Diameter1`..`Diameter6` and `DIN1`..`DIN6` on `AnchorsName`.
  - Names in cloned rows are rewritten via `db.smart_replace_name`, which only
    substitutes a token when it is preceded by whitespace and followed by
    ` x ` (bolt names) or at end-of-string/boundary — so `1/4` in `1 1/4`
    is not corrupted.
- `preview_find_replace` / `apply_find_replace` open a fresh connection per
  table/column; fine for small catalogs, slow on large ones.
- `.gitignore` excludes `venv/`, `__pycache__/`, `.pytest_cache/`, `.crush/`,
  and generated files in `catalog_studio/exports/`. Sample catalog `.mdf` /
  `.ldf` pairs under `catalog_studio/uploads/` are intentionally tracked.
- Only Advance Steel **2026** is validated; schema shapes are known to differ
  across versions (comments reference a FastenSuite `integrity_check.py`
  expecting a different bolt schema). Treat any new schema as unverified.

## Known inconsistencies (not yet bugs to "fix" blindly)

- `docker_ops.copy_out_of_container` and `db.get_physical_files` document that
  physical mdf/ldf filenames in the container need not match the database name,
  but the detach route in `app.py` guesses `{database}.mdf` /
  `{database}_log.ldf` anyway (`get_physical_files` is defined but unused by
  the app).

## Gotchas for safe changes

- Never point the tool at live Advance Steel databases; keep untouched source
  copies. The Flask dev server (port 5050, debug on) has no auth.
- Editing `catalog_metadata.json` while the app runs: writes are guarded by a
  process-local lock only, so don't hand-edit it mid-session.
- `MAX_CONTENT_LENGTH` is 500 MB; catalogs can approach that.
