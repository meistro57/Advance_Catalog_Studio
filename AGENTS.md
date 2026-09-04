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
- `catalog_studio/utils/anchor_sets.py` — anchor view model for the graphical
  anchor configurator. Pure mapping functions (termination classification,
  end splitting, anchor layout) are unit-tested and shared slot/matching code
  is reused from `bolt_sets.py` (anchor component columns are `DiameterN`
  without the bolt schema's " (mm)" suffix).
- `catalog_studio/utils/fabrication.py` — printable fabrication detail sheet
  (issue #2). Owns the documented US_Hooked_Anchors field mapping, inch
  fraction / metric / dual dimension formatting (nearest 1/16 in with an
  `≈` marker for inexact conversions), validation, safe sheet filenames, the
  hardware schedule, and the dimensioned SVG elevation renderer. All of it is
  unit-tested; the template never invents numbers.
- `catalog_studio/static/vendor/three/` — **pinned local** Three.js r160
  (`three.module.js`, `OrbitControls.js`) so the workshop works offline. The
  viewer template loads it via an import map (`three` and `three/addons/`
  keys); never switch to a CDN.
- `catalog_studio/static/js/bolt-set-viewer.js`, `static/js/bolt-set-layout.js`,
  `static/css/bolt-set-viewer.css`, `templates/bolt_set_viewer.html` — the
  Three.js viewer (Phase 1) + client-side assembly editor (Phase 2).
- `catalog_studio/static/js/anchor-configurator.js`,
  `templates/anchor_configurator.html` — the graphical anchor viewer
  (read-only; shares the bolt viewer CSS/import-map/Three.js vendor files).
- `templates/fabrication_sheet.html`, `static/css/fabrication-sheet.css`,
  route `/db/<db>/fabrication-sheet` — the printable fabrication detail
  (issue #2). A standalone page (no nav chrome) whose SVG elevation is
  generated server-side by `fabrication.generate_elevation_svg`; title-block
  fields are mirrored into the sheet by inline JS before printing. The
  anchor configurator links each selection to its sheet via the "Detail
  Sheet" button.
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

Display units: the viewer/editor shows **all dimensions in inches** (`fin()`
in bolt-set-viewer.js converts mm→in at display time; `in2()` formats layout
warning text). Storage and every layout computation stay in millimetres —
never change the engine to inches, only the presentation layer. The editor's
grip input is inches and is converted back to mm before layout.

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

## Anchor configurator: verified vs assumed

Anchor catalogs (all sample DBs share one 10-table schema: `AnchorsName`,
`AnchorsDefinition`, `AnchorsHoleDefinition`, `SetNutsBolts`, ...) are served
by `/db/<db>/anchor-configurator` (page, anchor catalogs only) and its payload
endpoint (`anchor_id` = an `AnchorsName.ID`, `def_id` = an
`AnchorsDefinition.ID` length variant; the payload also lists
`available_lengths` for the dropdown). Four bottom terminations appear in the
samples, classified from `AnchorsDefinition` fields:
- plain rod (HiltiHY200 adhesive, US Threaded);
- hex head at the rod bottom (`HeadDiameter`/`HeadHeight`/`NumberOfHeadEdges`);
- L-shaped 90° hook below the rod (`HookRadius` bend + `DistanceA` tail).

**Assumed and flagged to the user** (module docstring of `anchor_sets.py`
owns the interpretation; none of it is verified against a live Advance Steel
install): `Length` is the overall rod length drawn from y=0 (bottom) to the
tip; the concrete/surface plane is drawn at `Length - TopDistance` when that
fits inside the rod; `ThreadLength` is drawn from the rod tip downward; the
bottom termination sits at the embedded end. Hardware slots keep catalog
authoring order (no re-ordering by `Position` magnitude, whose meaning is
unconfirmed) and are split by sign: `Position < 0` → embedded end, otherwise
top end. With a head present, embedded-end hardware is stacked above the head
height. Two-sided sets (e.g. US `2Na2W`) render nuts/washers at both ends and
raise an interpretation note.

## Shear-stud (connector) catalogs (issue #4)

Nelson H4L (`raw_files/Nelson H4L.mdf`, attached as `NelsonH4L`) introduced a
third catalog shape: shear-stud connector catalogs that REUSE `SetBolts` for
the stud records and add `ConnectorStandard` / `ConnectorMaterial` /
`ConnectorDiameters` / `ConnectorDistances` / `ConnectorRelations`.
`guess_catalog_type` therefore checks for the `Connector*` tables BEFORE the
generic "has SetBolts -> bolt" rule, or shear-stud catalogs misclassify as
bolts (see `docs/shear-stud-schema.md` for the full observed schema, keys,
minimum record set, and naming conventions). Field meanings such as
`SetBolts.Type` are recorded as OBSERVED only — nothing in the connector
shape is verified against a live AS 2026 install yet, so there is no
shear-stud editing UI and adding one must start from that schema note.

## Fabrication detail sheet (issue #2)

The fabrication sheet renders the same verified anchor fields as the
configurator as a dimensioned SVG for print ("Print / Save as PDF" in the
browser; server-side PDF generation is a later phase). Field mapping is
documented in the `fabrication.py` module docstring (verified against
`US_Hooked_Anchors`). Conventions shared with the anchor viewer — overall rod
length, thread at the top, concrete plane from `TopDistance`, hook drawn from
`HookRadius` — are repeated on the sheet itself, and a prominent
"NTS — USE WRITTEN DIMENSIONS" note is always shown. `DistanceA` is
interpreted as the L-hook horizontal tail (it equals the part-name tail token
across every sample diameter) and is drawn; the remaining distance fields
(`DistanceF/E/O/C`, `BottomDistance`) are reported in the fabrication table
with their source-column labels but are NEVER drawn as geometry. Values
without a numeric source (coating, thread designation) are shown as absent
rather than inferred.

Dimension formatting rules (tested in `tests/test_fabrication.py`): metric
display preserves source precision (trailing zeros trimmed); imperial display
rounds to the nearest 1/16 in and reduces the fraction, prefixing `≈` when
the mm value is not exactly representable at that denominator. The printed
detail sheet always renders dimensions in **imperial inches**; the metric and
dual formatting helpers remain in `fabrication.py` (with tests) for later
phases. The sheet status is `draft` whenever validation raises an
error-level issue (missing/zero required fields, thread longer than the rod,
missing hook radius, unmatched SetNutsBolts references) — drafts show a
DRAFT / INCOMPLETE watermark and get a `DRAFT_` filename prefix. All geometry
numbers on the sheet come from the server model; the template contains no
dimension logic of its own.

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
