# Shear-stud (connector) catalog schema — Nelson H4L & Nelson H4L-Inch

Issue #4 investigation and verification (`A3.1` in `docs/verification-log.md`).
Sources: `raw_files/Nelson H4L.mdf` / `.ldf` (metric) and `NELSON_STUDS`
(`Nelson H4L-Inch`, imperial), exported from Advance Steel 2026 (file version 904).

> Status: VERIFIED across both metric (`Nelson H4L`) and imperial
> (`Nelson H4L-Inch`) Advance Steel 2026 exports (`docs/verification-log.md`
> A3.1).

## Shape

Nelson H4L is a **shear-stud (headed-stud) connector catalog**. It does NOT
use the bolt schema's `BoltsDiameters`/`ScrewNew`/`SetOfBolts`/... tables and
does NOT use the anchor `Anchors*` tables. It reuses **`SetBolts`** to hold
the stud records themselves. It must therefore be detected by its own
`Connector*` tables before the generic "has SetBolts -> bolt" rule
(`utils/db.py: guess_catalog_type` returns `"shear stud"`).

## Tables and keys (observed)

| Table | Columns | Key |
| --- | --- | --- |
| `ConnectorStandard` | `Key`, `RunName`, `OwnerText` | PK `Key` ("Nelson H4L") |
| `ConnectorMaterial` | `Key`, `RunName`, `weight`, `OwnerText` | PK `Key` ("Mild Steel") |
| `ConnectorDiameters` | `Key` (float mm), `RunName`, `Description` | PK `Key` (6.0, 10.0, 13.0, 16.0) |
| `ConnectorDistances` | `Key`, `HoleTolerance`, `along`, `across`, `Description` | PK (`Key`, `HoleTolerance`) — same role as `BoltsDistances` |
| `ConnectorRelations` | `Key` (int), `ConnectorStandard`, `ConnectorMaterial`, `ConnectorDiameter` | PK `Key`; one row per (Standard, Material, Diameter) triple |
| `SetBolts` | bolt-shape columns, reused for studs | PK (`Standard`, `Material`, `Diameter`, `Length`) |
| `Sources` | `Short`, `Long` | PK `Short` |

The minimum complete record set for a stud diameter to exist and list lengths
in Advance Steel is therefore believed to be:

1. `ConnectorStandard` row (family) and `ConnectorMaterial` row (grade);
2. `ConnectorDiameters` row for the diameter (mm `Key`, `RunName`);
3. `ConnectorDistances` row(s) for the diameter (hole/spacing rules);
4. `ConnectorRelations` row linking Standard + Material + Diameter;
5. one or more `SetBolts` stud rows for that (Standard, Material, Diameter)
   with positive `Length` values.

## Field semantics observed in Nelson H4L

- `SetBolts.Standard` / `Material` echo the connector family and material
  ("Nelson H4L", "Mild Steel"); `Source` = "Nelson H4L", `OwnerText` = "DSC".
- `SetBolts.Diameter` (mm) and `Length` (mm) are the stud shank diameter and
  overall length; 31 studs across 4 diameters, lengths 10–65 mm in 5 mm steps.
- `ScrewHeadOuterDiameter` / `HeadHeight` / `NumberOfCorners` describe the
  stud head: for H4L all studs have `NumberOfCorners = 0` (round head) with
  head diameter ~2× shank diameter and head height ~½ × shank diameter
  (e.g. Ø16 stud: head Ø31.8 × 7.9; Ø6 stud: head Ø12.7 × 4.7).
- `SetBolts.Type = 2` for every stud row. In the bolt catalogs (A325TC,
  Grade5) `SetBolts.Type = 1`; whether `Type` is the bolt-vs-connector
  discriminator is **unconfirmed** — treat as observed, verify in AS 2026.
- `Name` = `"<family> <dia> x <length>"`, e.g. `Nelson H4L 16 x 40`
  (mm values, no unit suffix). No imperial fractions in this catalog.
- `ConnectorDiameters.RunName` is the metric display string, e.g.
  ` 10.00 mm`, `   6.00 mm` — single-digit values carry extra leading spaces.
  Preserve `RunName` strings verbatim; generate metric names with the same
  fixed-width alignment convention, never from `Name` text.
- `ConnectorDistances` mirrors `BoltsDistances` (along/across spacing for the
  hole), with `HoleTolerance = 0.0` in this export.
- Units are millimetres throughout; weights in kg (`SetBolts.Weight`,
  `ConnectorMaterial.weight`).

## Open verification items (before any write path)

- Confirm `SetBolts.Type` semantics and that shear studs are distinguishable
  from bolts by schema/tables rather than by `Type`.
- Confirm the `ConnectorRelations` role and whether its `Key` must be
  identity-managed when adding a diameter.
- Confirm which tables are required for a new stud family/diameter to appear
  in AS 2026 Management Tools (record the dependency graph from a successful
  round trip).
- ISO 13918-style studs previously observed in `SetBolts` in other catalogs
  may share this `Connector*` shape or differ; do not assume.

## Consumers in Catalog Studio

- `utils/db.py: guess_catalog_type` labels the shape `shear stud` by table
  presence; `get_catalog_diameters` has a connector branch so the dashboard
  lists `ConnectorDiameters` with counts from `ConnectorRelations`,
  `ConnectorDistances` and `SetBolts`, and flags diameters with no references
  as orphans.
- `utils/schema_templates.py: CATALOG_TEMPLATES["shear stud"]` (`D2`) creates a
  fresh 7-table Shear Stud Catalog (`ConnectorStandard`, `ConnectorMaterial`,
  `ConnectorDiameters`, `ConnectorDistances`, `ConnectorRelations`, `SetBolts`,
  `Sources`) seeded with a complete starter family (`Nelson H4L` / `Mild Steel` /
  `16.0 mm`).
- `utils/shear_studs.py` builds a per-(standard, material, diameter) model and
  treats the minimum record set above as the completeness rule. Both metric
  (`' 10.00 mm'`, `'Nelson H4L 16 x 40'`) and imperial (`'   1/4 inch'`,
  `'Nelson H4L 1/4 x 1 1/8'`) `RunName` and `SetBolts.Name` conventions are
  recognized.
- `/db/<db>/shear-stud-browser` renders family → grade → diameter cards with
  the authored `RunName`, the hole rule, length chips, the stud table and the
  validation findings, links every value back to its raw table, and opens a
  per-record **Stud Record Detail** panel (`stud_detail` / `stud_svg`, `D3`) with
  a 2D schematic SVG elevation, source table/column traceability, and a
  composite-PK raw-row link (`/db/<db>/SetBolts/edit/<token>`) when a stud
  length is selected.
- `POST /db/<db>/shear-stud-browser/clone-preview` proposes the rows for a new
  diameter (`ConnectorDiameters`, `ConnectorDistances`, `ConnectorRelations` with
  `Key = max(Key)+1`, and `SetBolts`), and when `plan.ok` is true,
  `POST /db/<db>/shear-stud-browser/clone-apply` (`shear_studs.apply_clone`, `D1`)
  takes a pre-change backup snapshot (`snapshots.create_snapshot`, fail-closed)
  and inserts all rows in parent-before-child order inside a single transaction.
- `/db/<db>/health#exportChecklist` (`D5`) provides the pre-export readiness
  checklist (table/row counts, open findings, and Detach & Export reminder).
