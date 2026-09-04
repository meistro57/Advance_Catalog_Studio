# Shear-stud (connector) catalog schema — Nelson H4L

Issue #4, Phase 1 investigation. Source: `raw_files/Nelson H4L.mdf` / `.ldf`,
attached to the scratch SQL Server as `NelsonH4L`.

> Status: OBSERVED, not yet round-trip verified through Advance Steel 2026.
> This note records what the exported catalog contains and the relationships
> that follow from it. Field meanings are labelled "observed" where they are
> inferred from consistent catalog values, not confirmed in the application.

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
