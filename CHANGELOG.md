# Changelog

All notable changes to **Advance Steel Catalog Studio** are documented in this file.
Versioning follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`); the canonical version string lives in [`VERSION`](VERSION) and is exposed in the application via `config.APP_VERSION`.

## [0.6.0] - 2026-11-10

### Added
- **Decoded Dimension Point-Selection, Direction, and Request-Type Enums (`#11` — `E1b` / `A5.2`)**: Decoded `DetViewDimPointSelection` (`PointType` including `+1000` for `"as reference"`, `PointGeometricRestrictions`, `MpGeomRestriction`, `VisibilityStatus`, `GeometricRestrictions`, `ParentRelativePositonRestriction`), `DetViewDimRequestLinear.Direction`, and `DetViewDimStrategyItems.Type` across delivered `AstorDetails.mdf` (`docs/verification-log.md` `A5.2`) and wired verified label tables into `utils/dim_explain.py` and `templates/drawing_style.html`.
- **Dimension Point Selection Editing & Validation (`E1`)**: Added inline `Number of Points` and `Point1..15` dropdowns on each dimension chain card in `/db/<db>/drawing-style` along with `drawing_styles.validate_dim_request_points()` to validate point counts and `DetViewDimPointSelection.Objects` references on save and in `integrity_report()`.

## [0.5.1] - 2026-11-10

### Added
- **Shear-Stud Per-Record Detail Panel & Deeper Validation (`#4` — `D3`, `D4`)**: Added `shear_studs.stud_detail()` and `stud_svg()` so selecting a stud length in `/db/<db>/shear-stud-browser` renders a 2D schematic elevation SVG, source table/column traceability table, and composite-PK raw-row links (`/db/<db>/SetBolts/edit/<token>`), plus validation checks for cross-catalog duplicate names (`duplicate_stud_name`), implausible steel weights (`weight_implausible`), non-monotonic weights vs length (`weight_non_monotonic`), and invalid/orphan distance rules (`invalid_distance_rule`, `orphan_distance`).

## [0.5.0] - 2026-11-10

### Added
- **Fractional-Inch / `mm` Dimension Toggle (`#18`)**: Added **Fractional in** (`1/16"` reduced fractions with `≈` markers) and **`mm`** toggle buttons in both the **Bolt-Set Viewer** (`/db/<db>/bolt-set-viewer`) and **Anchor Configurator** (`/db/<db>/anchor-configurator`), switching 3D dimension callouts, 2D profile sketches (`utils/bolt_profile.py`), dropdown labels, and component/geometry tables between imperial fractions and millimetres.
- **Interactive Anchor Bolt Projection Control (`#19`)**: Added a live **Bolt projection from concrete** input, a **`4″ Typical`** (`101.6 mm`) preset button, and a **Catalog default** reset in the Anchor Configurator (plus `projection_mm` pass-through to the printable Fabrication Detail Sheet) to preview custom projections and resulting concrete embedment depth.

### Changed
- **Renamed `"Top distance"` to `"Bolt projection from concrete"` (`#21`)**: Updated the display label for `AnchorsDefinition.TopDistance` across `utils/anchor_sets.py`, the Anchor Configurator geometry panel and 3D callouts, and `templates/fabrication_sheet.html`.

## [0.4.0] - 2026-11-10

### Added
- **Split Home Workspace (`#20`)**: Divided the home dashboard into **Fastener Management** (`#fastenerManagementZone`, industrial cobalt/steel palette) and **Drawing Style Management** (`#drawingStyleManagementZone`, drafting-studio teal palette) above a shared ingest/staging/export dock, and applied `body.cs-style-workspace` across drawing-style pages.
- **Remove Diameter Wizard (`#17`)**: Added `/db/<db>/remove-diameter` (`db.preview_remove_diameter` / `db.apply_remove_diameter`) to preview and cascade-delete an existing bolt or anchor diameter in child-before-parent order inside a single transaction after taking a fail-closed `COPY_ONLY` snapshot.
- **Batch Rename for Deep-Copy Prefixes (`#16`)**: Added `/db/<db>/drawing-style/rename-copies` (`drawing_styles.plan_deep_copy_rename` / `preview_deep_copy_rename` / `apply_deep_copy_rename`) to strip or replace `Copy of `, `Copy (n) of `, and `Copy (n) ` prefixes across all Drawing Style `RunName` tables in a single snapshot-backed transaction.
- **DXF Hand-Edit Diff — Phase 1 (`#15`)**: Added `/detail-diff` (`utils/dxf_compare.py`) to compare before/after ASCII DXF exports of a detail and map hand-made dimensions, labels, scales, and representations back to Drawing Style settings.
- **Application Versioning**: Added root `VERSION` file, `config.APP_VERSION`, navbar version badge, and CI checks.

## [0.3.0] - 2026-11-04

### Added
- **Export a Copy & Windows File Paths (`#14`)**: Added `/db/<db>/export-copy` for non-destructive `.mdf` downloads and `db.ensure_windows_file_paths()` so Advance Steel 2026 imports never fail with `"Source database is older than Release 5.1!"`.
- **SQL Server 2019 Version Guard**: Added `db.require_as_compatible()` to verify internal SQL file version `904` before attaching or creating databases.
- **Pre-change Snapshots & Delivered-Library Guard**: Added `utils/snapshots.py` (`COPY_ONLY` `.bak` + JSON manifest + retention pruning), read-only protection for delivered `Astor*` libraries, central CSRF guard (`docs/csrf-audit.md`), `/compare` side-by-side catalog comparison, and GitHub Actions CI.
- **Light/Dark Theme & Offline Vendor Assets**: Added `static/css/theme.css`, `static/js/theme.js`, inline SVG icons (`utils/icons.py`), and vendored Bootstrap 5.3.3, htmx 2.0.4, and Three.js r160.

## [0.2.0] - 2026-10-15

### Added
- **Drawing Style Editor, Schematic Figures & Sub-Style Usage**: Menu-driven editor (`/db/<db>/drawing-style`), htmx rule actions, SVG schematics (`utils/style_diagrams.py`), plain-language dimension cards (`utils/dim_explain.py`), and reverse-reference / orphan scan (`utils/style_usage.py`).
- **Shear-Stud Browser (`#4` Phase 1) & Catalog Health Report**: Read-only connector catalog browser (`/db/<db>/shear-stud-browser`) with inch/mm toggle and clone preview, plus cross-catalog `/db/<db>/health` report with JSON/CSV export.
- **Transactional Safety Fixes (`#7`, `#8`, `#9`, `#10`)**: Single-transaction find & replace with `text`/`ntext` cast, replace-before-insert anchor diameter cloning, validated table filters, and detach recovery.

## [0.1.0] - 2026-09-15

### Added
- **Initial Workbench (`#1`, `#2`, `#3`)**: Upload/attach/detach `.mdf`+`.ldf` pairs against disposable Docker SQL Server, guided bolt/anchor diameter cloning, Three.js Bolt-Set Viewer + 2D profile sketch + Phase 2 client assembly editor, graphical Anchor Configurator, printable SVG Fabrication Detail Sheets, and recoverable staging/export cleanup.
