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
  suite with `venv/bin/python -m pytest tests/`. All tests are unit/route tests
  (bolt-set view model and profile drawing, drawing-style label parsing,
  figures and htmx rule partials, drawing-style sub-style usage walk and orphan
  scan, catalog health report, fabrication sheet model, shear-stud browser
  model and clone plan, staging cleanup, connection timeouts, the diameter
  clone's replace-before-insert order, find & replace's single transaction and
  legacy-type casts, detach/backup connection recovery, the light/dark theme
  hooks and shared design layer, and the inline SVG icon set / offline asset
  rule) — no database needed. The clone and find/replace tests stub the
  cursor, so they assert statement order and commit/rollback rather than SQL
  Server behaviour.
- **No configured linter, no Makefile, no packaging config exist.** CI exists:
  `.github/workflows/ci.yml` runs `compileall`, `pytest tests/` and
  `pyflakes catalog_studio tests *.py` on every push/PR. Verification of real
  catalogs is still manual against the Docker SQL Server; the suite itself needs
  no database. The tree is kept pyflakes-clean, but pyflakes is not a pinned
  dependency and no formatting policy is applied.
- The backlog is `TODO.md`; live-Advance-Steel evidence goes in
  `docs/verification-log.md`. Write paths stay blocked until their verification
  entry passes.
- A Docker container named `hilti-scratch-sql` on `127.0.0.1:1433` must exist
  and be running (`docker start hilti-scratch-sql`; it is configured with
  `--restart unless-stopped`). SQL Server `sa` password is hardcoded in
  `catalog_studio/config.py` (`Scratch2026!Pw`) and duplicated in every
  root-level CLI script.
- Start the web app (port **5050**): `python catalog_studio/app.py`
- Attach existing catalog pairs through the web UI (upload → attach). The
  checked-in example pairs live in `samples/`; copy one into the runtime
  staging dir first, e.g. `cp samples/A325TC.mdf catalog_studio/uploads/`
  (and its `_log.ldf`), or run one-off inspection/export scripts against an
  already-attached database, e.g.:
  ```bash
  python db_inspect.py A325TC_mark
  python export_bolts.py A325TC_mark out.csv
  python export_catalog.py HiltiHY200 out.csv
  ```
- Checked-in sample data lives in `samples/` (A325TC, Grade5, US_Headed/
  US_Hooked/US_Threaded_Anchors, plus Nelson/raw_files).
  `catalog_studio/uploads/` is a RUNTIME staging area: uploads are
  git-ignored and can be cleaned with the dashboard's Remove / Clear staged
  uploads actions (issue #3). `catalog_studio/exports/` is the export dir.

## Code layout

- `catalog_studio/app.py` — all Flask routes; entry point.
- `catalog_studio/config.py` — paths, SQL connection, container name, AS version
  (2026 only; `SUPPORTED_AS_VERSIONS = {2026}`), plus `DB_LOGIN_TIMEOUT` (5 s).
- `catalog_studio/utils/db.py` — every SQL Server operation, generic table
  browsing/editing, find & replace, and the diameter clone engine. All
  pymssql connections go through `_open_connection()` so a stopped container
  fails in seconds instead of pymssql's 60 s default; never add a raw
  `pymssql.connect` elsewhere. The dashboard checks the container first and
  skips the database query when it is down.
- `catalog_studio/utils/docker_ops.py` — shells out to `docker cp`/`exec`/
  `inspect` to move files in/out of the container.
- `catalog_studio/utils/metadata.py` — per-database `catalog_type`, `library` and
  `as_version`, stored in a local JSON sidecar
  (`catalog_studio/catalog_metadata.json`), deliberately **not** written into
  the mdf (extra tables would break Advance Steel import). `library_kind()`
  recognises an attachment made from `AstorDetails` / `AstorAddIn` /
  `AstorBase` / `AstorSettings` and the attach route stores it; `app._blocked_write()`
  then refuses every write route for that database (delivered libraries are
  read-only). Detach/export and all reads stay allowed.
- `catalog_studio/utils/staging.py` — pairs `.mdf` with `_log.ldf` in uploads/,
  suggests DB names from filenames, lists exports/.
- `catalog_studio/utils/staging_cleanup.py` — safe cleanup of the runtime
  upload staging area (issue #3): strict path containment (plain basenames
  with `.mdf`/`.ldf` only, no traversal/absolute paths/symlinks escaping the
  canonical upload dir), scan stats for the confirmation dialogs, and
  recoverable removal — files move into `uploads/.trash` and only an explicit
  purge deletes them. Fully unit-tested.
- `catalog_studio/utils/drawing_styles.py` — Drawing Style Manager exports
  (`catalog_type == "drawing style"`). Reads the export's own
  `InfoTableRelations` map (+ `SUPPLEMENTARY_RELATIONS` fixes), builds the
  style tree for `templates/drawing_style.html`, parses label formulas
  (`parse_label_format`), converts mm <-> ft-in (`format_ft_in`/`parse_length`),
  reorders representation rules (`(Key, Order)` swaps through a temp Order),
  and runs `integrity_report`. Pure helpers are unit-tested in
  `tests/test_drawing_styles.py`; schema notes in `docs/drawing-style-schema.md`.
  Never invent labels for AstorBase/AstorDetailsBase enums — they aren't in the export.
  Do not reimplement compaction: the Style Manager's own **Compact database**
  merges equal records and rewires references; the tool only reports.
  Feature requests sometimes name `DetStyle`, `DetStyleViews`, `DetView`,
  `DetDimStrategy`, `DetObjectsSet`, `DetDimDefinition`, `DetDimPoints`,
  `DetObjects` or `DetPresentation`: none of those exist in an AS 2026 export.
  Map them via `docs/drawing-style-schema.md` before writing code, and never
  introduce a second schema guess. Label formulas also support the `%%c` / `%%d`
  / `%%p` / `%%%` symbol escapes and the token set documented in Autodesk's
  Drawing Style Manager guide (see `KNOWN_FIELDS`); keep samples preview-only.
  The vendor PDFs live in `docs/references/` and are git-ignored (copyrighted,
  large); they describe the AS 2016 / DSM 6.1 manager, not the SQL schema.
- Drawing-style rule actions are htmx-enhanced: `templates/_drawing_rules.html`
  is the single rules block (included by the page **and** returned by
  `drawing_style_rule` for `HX-Request` posts), `drawing_styles.repr_block()`
  loads just that map instead of the whole tree, and `_flash_oob.html` appends
  flashed messages into `#flashHost`. Keep the plain `form="ruleForm"` submit
  path working as the no-JS fallback, and keep `fld` in
  `_drawing_macros.html` (imported `with context`). htmx 2.0.4 is vendored at
  `static/vendor/htmx/htmx.min.js` so the tool stays offline. The libraries card
  at the bottom of the page uses Bootstrap **collapse** (`data-bs-parent="#libPanes"`),
  not `data-bs-toggle="tab"`: one library pane is open at a time and clicking the
  open tab closes it. Keep `aria-expanded`/`aria-controls` in sync, and keep the
  panes' content unconditional (they are hidden, never server-gated).
- `catalog_studio/utils/style_diagrams.py` — the drawing-style editor's
  schematic SVG figures (style overview, print-scale ruler, view box, length
  clipping, dimension-chain anatomy, per-view dimension plan, single chain,
  hatch swatches) plus the page-level `decorate_tree()` helper. The dimension
  plan caps lanes per side (`MAX_PLAN_LANES`) and says how many it left out;
  the anatomy figure is attached to the first view with dimensions only. Builders are pure and unit-tested; the page embeds them and redraws
  live through `POST /db/<db>/drawing-style/diagram`, which reuses the same
  builders so there is one geometry implementation (no JS twin). Keep the
  "unverified" notes in the figures when touching them.
- `catalog_studio/utils/shear_studs.py` — read-only shear-stud (connector)
  browser model: metric display parsing/formatting, stud name convention,
  per-record geometry checks, per-(standard, material, diameter) grouping with
  the documented completeness rules, filtering and summaries. Pure helpers are
  unit-tested; `get_browser_model()` is the only SQL (reads `Connector*` +
  `SetBolts`). Nothing here writes. Display units are presentation-only:
  `normalize_units()` / `format_dimension()` keep storage in millimetres and
  render inches through `fabrication.format_in` (nearest 1/16 in, reduced
  fraction, `≈` marker); the templates call it as the `sdim` Jinja filter and
  carry `units` through filter links and the clone form. Never convert values
  before they reach SQL or the clone proposal.
- `catalog_studio/utils/style_usage.py` — read-only "used by" walk and orphan
  scan for drawing-style exports (`/db/<db>/drawing-style/usage`, template
  `drawing_style_usage.html`, "Sub-style usage" button on the editor page).
  Containment direction is declared in `ASCENT_EDGES` (child table/column ->
  parent table/column) because `InfoTableRelations` states references but not
  which side contains which; keep it in sync with
  `docs/drawing-style-schema.md`. The walk (`usage`), the reachability scan
  (`orphan_report`) and the pure helpers are unit-tested; unreachable rows are
  reported only. `DetStyle`/`DetStyleViews`/`DetView`/`DetDimStrategy`/
  `DetObjectsSet`/`DetDimDefinition`/`DetDimPoints` from the feature request do
  NOT exist in an AS 2026 export — the observed names are in the module
  docstring. No purge, compaction, LDF deletion or clone lives here.
- `catalog_studio/utils/snapshots.py` — data-safety net for batch writes:
  `create_snapshot()` runs `BACKUP DATABASE ... WITH COPY_ONLY` inside the
  scratch container, copies the `.bak` to `catalog_studio/snapshots/<db>/` and
  writes a JSON manifest. `add-diameter` (apply) and `find-replace` (apply) call
  it first and abort when it fails; any new batch mutation must do the same
  (fail closed, never "warn and continue"). Snapshots are runtime files
  (git-ignored); the exported mdf/ldf pair remains the deliverable. Tests patch
  `db.backup_database` / `docker_ops.copy_out_of_container`, so no DB is needed.
  Retention is explicit: `snapshot_files()` lists the `.bak` files (newest
  first, manifest optional), `prune_snapshots(keep=5)` deletes the surplus and
  backs the database page's **Prune older** button
  (`POST /db/<db>/snapshots/prune`, CSRF-checked), and `restore_plan()` returns
  the `docker cp` + `RESTORE DATABASE ... WITH REPLACE` commands for a manual
  restore. Nothing here executes a restore.
- `catalog_studio/utils/compare.py` — read-only side-by-side comparison of two
  attached databases (`/compare`, template `compare.html`, **Compare** button in
  the nav bar): table presence, per-table row counts with deltas, and diameter
  keys/names/related-row counts/orphan flags for bolt, anchor and shear-stud
  catalogs. Pure helpers (`table_diff`, `count_diff`, `diameter_diff`,
  `summary`) are unit-tested; `build_comparison()` is the only SQL. It never
  writes and refuses a database with itself.
- `catalog_studio/utils/health.py` — read-only catalog health report
  (`/db/<db>/health`, template `catalog_health.html`, "Health Report" button on
  the database page; the same findings download as `/db/<db>/health.json` and
  `/db/<db>/health.csv`). It adds no new catalog semantics: `build_report()`
  dispatches on `db.guess_catalog_type` and reuses `db.get_catalog_diameters`
  (bolt diameter coverage against the documented six-table relationship),
  `bolt_sets.parse_component_slots`/`annotate_components` (anchor hardware
  slots), `shear_studs.get_browser_model` (stud findings) and
  `drawing_styles.integrity_report` (dangling references). Pure collectors,
  sorting, summary and section grouping are unit-tested; keep new rules in the
  owning module and only aggregate here. It never repairs; a clean report is
  not a claim of Advance Steel validity.
- `catalog_studio/utils/schema_templates.py` — reverse-engineered DDL + seed
  data for freshly created anchor/bolt catalogs.
- `catalog_studio/utils/bolt_profile.py` — dimensioned 2D elevation of the
  same assembly (head/shank/hardware/clamped material, numbered balloons, part
  legend, inch dimensions). Pure and unit-tested; the browser posts its current
  layout to `POST /db/<db>/bolt-set-viewer/sketch` so the drawing always matches
  the 3D preview, and the payload embeds the initial profile. Keep it schematic
  and keep the "unverified" footer wording.
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
- `templates/base.html` + `static/css/theme.css` + `static/js/theme.js` — the
  light/dark switch and the **Issues** button. The button URL comes from
  `config.ISSUES_URL` via the context processor (`issues_url`), not from the
  template. `base.html` sets `data-bs-theme` on `<html>` from
  `localStorage` (`catalogStudioTheme`) before first paint, falling back to
  `prefers-color-scheme`, and renders the navbar toggle; `theme.js` only wires
  the switch, icons and cross-tab sync. `theme.css` owns the tokens **and** the
  dark remaps for the light-only utilities the templates use (`bg-white`,
  `bg-light`, `text-dark` scoped to `bg-light`). Keep pages extending
  `base.html` so they inherit the theme, and keep SVG/drawing surfaces on light
  "paper" (`.cs-paper`, `.bp-host`, `.label-preview`, the Three.js canvas, the
  printable fabrication sheet) — their strokes and dimension text assume it.
- `catalog_studio/utils/icons.py` — the chrome's inline SVG icon set, exposed
  to templates as the `icon('name')` Jinja global (registered in `app.py`).
  Icons are 24x24 stroke paths that inherit `currentColor`, so no icon font and
  no colour-emoji font is needed (a missing emoji font renders tofu boxes on
  minimal Linux and in headless browsers). `tests/test_icons.py` fails on an
  unknown icon name, on colour emoji in a template, or on a CDN asset reference
  in `base.html`. Add new glyphs to `ICONS`, never inline `<svg>` in a template.
- `catalog_studio/static/vendor/bootstrap/` — **pinned local** Bootstrap 5.3.3
  (`bootstrap.min.css`, `bootstrap.bundle.min.js`), loaded by `base.html` so the
  workbench works offline like htmx and Three.js. `static/img/` holds the
  navbar brand mark and the SVG favicon. Never switch either back to a CDN.
- `catalog_studio/static/vendor/three/` — **pinned local** Three.js r160
  (`three.module.js`, `OrbitControls.js`) so the workshop works offline. The
  viewer template loads it via an import map (`three` and `three/addons/`
  keys); never switch to a CDN.
- `catalog_studio/static/js/bolt-set-viewer.js`, `static/js/bolt-set-layout.js`,
  `static/css/bolt-set-viewer.css`, `templates/bolt_set_viewer.html` — the
  Three.js viewer (Phase 1) + client-side assembly editor (Phase 2). The page
  is organised as 3D schematic / dimensioned profile / component table, with
  perspective-orthographic toggle, part labels, an exploded slider, and
  hover/selection sync between the 3D scene and the table (table↔3D sync lives
  in `highlightSlot`/`selectSlot`).
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

## Primary keys (critical)

Advance Steel tables frequently have COMPOSITE primary keys (bolt: `SetBolts`,
`ScrewNew`, `SetNutsBolts`, `BoltsDistances`; style: `DetObjReprMapItems`,
`DetViewDimStrategyItems`, `DetailMasterTable`). Always address rows with
`db.get_primary_key_columns()` + a full pk dict; URLs carry
`db.make_row_token()` (raw value for single keys, `pk~<base64 json>` for
composite). `db.update_row`/`db.delete_row` roll back unless exactly one row
changes. `db.guess_primary_key()` now returns None for composite keys.

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
database-wide find & replace over all text columns. Every POST that can write
passes the central CSRF guard first, and write routes additionally call
`_blocked_write()` so an attachment recorded as a delivered library cannot be
modified. Two read-only views sit on top: `/db/<db>/health(.json|.csv)` and
`/compare?a=&b=`.

Bolt-set viewer flow (issue #1): `/db/<db>/bolt-set-viewer` (page, bolt
catalogs only) → the page's JS calls
`/db/<db>/bolt-set-viewer/payload?standard=&set=&material=&diameter=&length=`
which returns the normalized view model: bolt record, component stacks with
server-computed y positions, side ("head"/"nut") and layer tags, schematic
grip, screw rules, warnings, plus `catalog_parts` (every deduplicated
SetNutsBolts record, keyed by Standard/Material/Diameter, for editor
dropdowns) and `profile_svg`. The page always shows a component table as an
accessibility fallback; WebGL is optional. The dimensioned profile is redrawn
from the browser's draft layout through
`POST /db/<db>/bolt-set-viewer/sketch` (CSRF-checked JSON, values clamped by
`bolt_profile.sanitize_layout`), so the drawing has one implementation.

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
shear-stud writing UI; adding one must start from that schema note.

`catalog_studio/utils/shear_studs.py` is the read-only slice: pure functions
build a per-(standard, material, diameter) model from the connector rows plus
`SetBolts`, apply the documented completeness rules (lookup rows, diameter
row, distance rule, relation row, at least one stud length) and emit
error/warning/note issues. `get_browser_model()` only reads. The page is
`/db/<db>/shear-stud-browser` (`shear_stud_browser` route, template
`shear_stud_browser.html`, linked from the dashboard for `shear stud`
catalogs) and `db.get_catalog_diameters()` has its own connector branch so
`ConnectorDiameters` show up on the dashboard with orphan detection. The
bolt-diameter clone route redirects for these catalogs (its engine copies
tables they do not have), and the dashboard hides that button. The pure
model, validation, filtering and the route are unit-tested; nothing writes to
a connector catalog.

`plan_clone()` in the same module is the **preview-only** clone proposal
(`POST /db/<db>/shear-stud-browser/clone-preview`, template
`shear_stud_clone.html`): it returns INSERT-shaped rows for
`ConnectorDiameters`, `ConnectorDistances`, `ConnectorRelations` and
`SetBolts` plus the issues that block them (existing diameter/group/length/
name, duplicate or non-numeric lengths, incomplete or missing source, tight
spacing). Geometry, weight and the hole rule scale by `target/source` only
when asked, are labelled as estimates, and weight is left empty when no source
stud of that length exists. There is deliberately no apply route — the
proposal is the review artifact for the unverified write path, and
`ConnectorRelations.Key` is proposed as `max(Key)+1` (not an identity column
in the export).

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
    is not corrupted. Free text (`BoltsDistances.Description`) goes through
    `db.replace_diameter_in_text`, which matches whole numbers only.
  - Re-applying a clone replaces the target diameter instead of duplicating it:
    the bolt tables are deleted first and the anchor branch deletes
    `AnchorsHoleDefinition`/`AnchorsDefinition`/`AnchorsName` children before
    parents in the same transaction. Applying with target == source raises.
  - The bolt branch copies every column, so it refuses to run (fail closed) when
    one of the copied tables has an identity column — that shape is unverified.
- `preview_find_replace` / `apply_find_replace` each use one connection for the
  whole scan. `apply_find_replace` runs every column update in one transaction
  and rolls back on the first failure; legacy `text`/`ntext` columns are cast to
  `nvarchar(max)` because SQL Server's `REPLACE()` rejects them.
- Every POST is CSRF-checked by the central `_csrf_guard()` (`before_request`)
  before the route body runs; only `READ_ONLY_POST_ENDPOINTS` (clone preview,
  label preview) and `action=preview` on add-diameter/find-replace are exempt.
  The bolt-set sketch route checks the JSON `csrf_token` itself. Any new POST
  route must either rely on that guard or be added to the exemption set **and**
  to `docs/csrf-audit.md`; `test_every_writing_post_route_requires_csrf` walks
  the URL map and fails otherwise. Staging targets are always re-derived
  server-side from the scanned staged list, never trusted from the browser.
- `.gitignore` excludes `venv/`, `__pycache__/`, `.pytest_cache/`, `.crush/`,
  everything in `catalog_studio/uploads/` (kept via `.gitkeep`) and generated
  files in `catalog_studio/exports/`. Example `.mdf`/`.ldf` pairs are tracked
  under `samples/` (and `raw_files/`), never in the runtime upload dir.
- Only Advance Steel **2026** is validated; schema shapes are known to differ
  across versions (comments reference a FastenSuite `integrity_check.py`
  expecting a different bolt schema). Treat any new schema as unverified.

## Stack, database roles and naming policy

- **Stack:** this tool is Python 3.12 + Flask (see `requirements.txt`). Requests
  to re-platform it to C#/.NET/EF are out of scope; the Python modules already
  encode the verified schema knowledge and the test suite.
- **Database roles (documented by Autodesk, not re-verified here):**
  `AstorDetails.mdf` = delivered templates/styles (treat as read-only),
  `AstorAddIn.mdf` = user overrides and cloned styles, `AstorBase.mdf` =
  fasteners/bolts/anchors/studs/materials, `AstorSettings.mdf` = global defaults.
  The tool only ever sees copies attached to the scratch container; record
  provenance per file (`catalog_metadata.json`), never write to a delivered
  library, and prefer authoring into a copy of the user library.
- **Naming:** generated names follow the observed conventions (` 10.00 mm`,
  `1/2 inch`, `<family> <dia> x <length>`) and are token-safe; never emit
  recursive `Copy (1) of ...` names. Deep-copy naming is a project decision to
  make when that write path is verified.
- **Performance:** catalog tables can hold tens of thousands of rows. Prefer one
  connection per operation, parameterised batch statements and indexed lookups.
  `preview_find_replace` / `apply_find_replace` still run one `COUNT`/`UPDATE`
  per text column and are the known slow path on very large catalogs.

## Known inconsistencies (not yet bugs to "fix" blindly)

- `docker_ops.copy_out_of_container` and `db.get_physical_files` document that
  physical mdf/ldf filenames in the container need not match the database name,
  but the detach route in `app.py` guesses `{database}.mdf` /
  `{database}_log.ldf` anyway (`get_physical_files` is defined but unused by
  the app).

## Gotchas for safe changes

- Adding a POST route: the central `_csrf_guard()` already requires a token, so
  the form needs `csrf_token`. If the route only renders a preview, add it to
  `READ_ONLY_POST_ENDPOINTS` **and** `docs/csrf-audit.md`
  (`test_every_writing_post_route_requires_csrf` enforces the split).

- Never point the tool at live Advance Steel databases; keep untouched source
  copies. The Flask dev server (port 5050, debug on) has no auth.
- Editing `catalog_metadata.json` while the app runs: writes are guarded by a
  process-local lock only, so don't hand-edit it mid-session.
- `MAX_CONTENT_LENGTH` is 500 MB; catalogs can approach that.
