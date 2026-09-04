# Advance Steel Catalog Studio & Database Tool

A specialized database workbench and automation tool for reverse-engineering, inspecting, modifying, and generating **Autodesk Advance Steel** component catalogs (`.mdf` / `.ldf` SQL Server LocalDB databases).

---

## Table of Contents

1. [Overview](#overview)
2. [Why Advance Steel Catalogs are Difficult](#why-advance-steel-catalogs-are-difficult)
3. [The Relational Architecture of Advance Steel Bolt Databases](#the-relational-architecture-of-advance-steel-bolt-databases)
   - [The Metric Storage Rule](#the-metric-storage-rule)
   - [The 6 Core Interconnected Tables](#the-6-core-interconnected-tables)
   - [Relational Diagram](#relational-diagram)
4. [The Problem: Why Adding a Diameter in One Table Fails](#the-problem-why-adding-a-diameter-in-one-table-fails)
5. [The Solution: Web App Cascading Diameter Engine](#the-solution-web-app-cascading-diameter-engine)
   - [Pre-configured Standard Presets](#pre-configured-standard-presets)
   - [Proportional Scaling Formulas](#proportional-scaling-formulas)
   - [Context-Aware Name Replacement](#context-aware-name-replacement)
   - [Orphan Detection & Cleanup](#orphan-detection--cleanup)
   - [Atomic Transactions](#atomic-transactions)
6. [Web App Interface & Features](#web-app-interface--features)
   - [Database Overview Page](#database-overview-page)
   - [Add / Clone Diameter Wizard](#add--clone-diameter-wizard)
   - [Database-Wide Find & Replace](#database-wide-find--replace)
   - [Raw Table Editor & Filtering](#raw-table-editor--filtering)
7. [Getting Started & Setup](#getting-started--setup)
   - [Prerequisites](#prerequisites)
   - [Starting the Scratch SQL Server](#starting-the-scratch-sql-server)
   - [Running Catalog Studio](#running-catalog-studio)
8. [Typical Workflow: From Ingest to Advance Steel Import](#typical-workflow-from-ingest-to-advance-steel-import)
9. [Command-Line Utilities Reference](#command-line-utilities-reference)

---

## Overview

Advance Steel stores all hardware catalogs (bolts, anchors, shear studs, special parts) inside Microsoft SQL Server `.mdf` and `.ldf` database files. Modifying catalogs directly inside Autodesk Advance Steel Management Tools is notoriously slow, fragile, and prone to missing relational dependencies.

**Catalog Studio** isolates catalog development inside a lightweight Docker SQL Server container (`hilti-scratch-sql`). It provides:
- Safe, non-destructive editing outside your live Advance Steel installation.
- A web UI for browsing, filtering, and mass-editing database tables.
- A **Cascading Diameter Generator** that automatically builds and links the complete cluster of tables required when adding a new bolt diameter.
- One-click detach and download ready for re-import into Advance Steel.

---

## Why Advance Steel Catalogs are Difficult

Unlike general engineering spreadsheets, Advance Steel catalogs are **strictly relational SQL databases** with hidden dependencies:
1. **No Single "Diameter List"**: A bolt diameter does not live in a single table. It is spread across **6 distinct tables** that must all agree on keys, tolerances, and assembly sets.
2. **Hidden Units Convention**: Advance Steel converts imperial fractions to millimeters internally. If a diameter is keyed improperly, joints in Advance Steel fail silently or throw cryptic calculation errors.
3. **Composite Keys**: Tables like `SetBolts`, `SetOfBolts`, and `ScrewNew` use composite primary keys (combining Standard, Set, Material, Diameter, and Length) rather than simple auto-incrementing IDs.
4. **Assembly Sets**: A single diameter must account for every hardware set variation (`MuS` = Nut + 1 Washer, `Mu2S` = Nut + 2 Washers, `MuKS` = Nut + Round Washer, etc.).

---

## The Relational Architecture of Advance Steel Bolt Databases

### The Metric Storage Rule
Advance Steel **always** stores internal geometric values (diameters, lengths, head dimensions, edge distances) in **millimeters (`FLOAT`)**, regardless of whether your Advance Steel project is Imperial or Metric:

| Nominal Size | Millimeter Value Stored in Database (`FLOAT`) | Advance Steel Display Format (`RunName`) |
| :--- | :--- | :--- |
| **1/4"** | `6.35` | `' 1/4 inch'` |
| **5/16"** | `7.9375` | `' 5/16 inch'` |
| **3/8"** | `9.525` | `' 3/8 inch'` |
| **1/2"** | `12.7` | `' 1/2 inch'` |
| **5/8"** | `15.875` | `' 5/8 inch'` |
| **3/4"** | `19.05` | `' 3/4 inch'` |
| **7/8"** | `22.225` | `' 7/8 inch'` |
| **1"** | `25.4` | `' 1 inch'` |
| **1 1/4"** | `31.75` | `' 1 1/4 inch'` |
| **1 3/8"** | `34.925` | `' 1 3/8 inch'` |
| **1 1/2"** | `38.1` | `' 1 1/2 inch'` |

*(Note the leading space in Advance Steel's standard `' 3/8 inch'` display strings).*

---

### The 6 Core Interconnected Tables

When an Advance Steel bolt catalog (such as `A325TC_mark`) is loaded, a complete diameter is distributed across 6 tables:

```
                  ┌────────────────────┐
                  │   BoltsDiameters   │
                  │ (Key = 9.525 mm)   │
                  └─────────┬──────────┘
                            │
        ┌───────────────────┼────────────────────┐
        ▼                   ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ BoltsDistances│   │   ScrewNew    │   │   SetOfBolts    │
│ (Tolerances)  │   │(Grip & Rules) │   │ (Hardware Sets) │
└───────────────┘   └───────────────┘   └────────┬────────┘
                                                 │
                            ┌────────────────────┴────────┐
                            ▼                             ▼
                    ┌───────────────┐             ┌───────────────┐
                    │   SetBolts    │             │ SetNutsBolts  │
                    │(Bolt Lengths) │             │(Nuts & Washers│
                    └───────────────┘             └───────────────┘
```

#### 1. `BoltsDiameters`
- **Purpose**: Global lookup table for available nominal diameters in the catalog.
- **Key Columns**:
  - `[Key]` (`FLOAT`, PK): The nominal diameter in millimeters (e.g., `9.525`).
  - `RunName` (`NVARCHAR(64)`): The UI label displayed in Advance Steel dropdowns (e.g., `' 3/8 inch'`).
  - `Description` (`NVARCHAR(64)`): Optional description.

#### 2. `BoltsDistances`
- **Purpose**: Defines minimum structural edge distances and bolt pitch distances for Advance Steel joint macros.
- **Key Columns**:
  - `Diameter` (`FLOAT`): Diameter in mm.
  - `HoleTolerance` (`FLOAT`): Extra hole clearance (`0.0`, `1.0`, `2.0` mm).
  - `along` (`FLOAT`): Distance along the line of force.
  - `across` (`FLOAT`): Distance across the line of force.
  - `Description` (`NVARCHAR(64)`): Label (e.g. `'dl=9,525'`).

#### 3. `ScrewNew`
- **Purpose**: Length calculation rules for each assembly set. Controls how Advance Steel calculates the required bolt length from the total grip thickness.
- **Key Columns**:
  - `Standard` (`NVARCHAR(32)`): Bolt standard (e.g. `'ASTM A325TC'`).
  - `Set` (`NVARCHAR(32)`): Assembly code (e.g. `'MuS'`, `'Mu2S'`, `'MuKS'`).
  - `Material` (`NVARCHAR(16)`): Strength grade (e.g. `'10.9'`).
  - `Diameter` (`FLOAT`): Diameter in mm.
  - `GripLengthMin1..7` / `GripLengthMax1..7`: Grip thickness bands.
  - `ScrewLengthBase1..7` / `ScrewLengthDelta1..7`: Base lengths and incremental steps.

#### 4. `SetOfBolts`
- **Purpose**: The "recipe" for bolt hardware assemblies. Tells Advance Steel which nut and washers belong to this bolt diameter.
- **Key Columns**:
  - `Standard`, `Set`, `Material`, `Diameter`: Identifies the parent bolt.
  - `DIN1`, `[Diameter1 (mm)]`, `Material1`, `Position1`: Nut specification (e.g. `ASTM A563`, `9.525 mm`, position `-2`).
  - `DIN2`, `[Diameter2 (mm)]`, `Material2`, `Position2`: Washer 1 specification (e.g. `ASTM F436`, `9.525 mm`).
  - `DIN3`, `[Diameter3 (mm)]`, `Material3`, `Position3`: Washer 2 specification (e.g. `ASTM F436`, `9.525 mm`).

#### 5. `SetNutsBolts`
- **Purpose**: The physical dimensions and part records for matching nuts and washers.
- **Key Columns**:
  - `Standard`, `Material`, `Diameter`: Identifies the component.
  - `Height`: Thickness / height of the nut or washer (mm).
  - `OutsideDiameter`: Outer boundary / hex size (mm).
  - `NumberOfCorners`: `6` for hex nuts, `0` for round washers, `4` for square/plate washers.
  - `Name`: Display name (e.g. `'A563 Nut 3/8'`, `'Washer F436 - 3/8'`).
  - `Weight`: Mass in kg.
  - `Type`: `1` = Nut, `2` = Washer.

#### 6. `SetBolts`
- **Purpose**: The catalog of physical bolt lengths available for purchase. Advance Steel selects rows from this table to place 3D bolts in the model.
- **Key Columns**:
  - `Standard`, `Material`, `Diameter`: Parent bolt specs.
  - `Length`: Shank length in mm (e.g., `25.4`, `31.75`, `38.1` ... up to `254.0`).
  - `ScrewHeadOuterDiameter`: Outer head diameter in mm.
  - `HeadHeight`: Head thickness in mm.
  - `Name`: Part description (e.g. `'A325TC 3/8 x 1'`, `'A325TC 3/8 x 1 1/4'`).
  - `Weight`: Bolt weight in kg.

---

## The Problem: Why Adding a Diameter in One Table Fails

When users open a database editor or standard CRUD UI and go to `BoltsDiameters` to add a new size:
1. **Single Table Insertion**: The UI executes `INSERT INTO BoltsDiameters ([Key], RunName) VALUES (39.1, ' 3/8 inch')`.
2. **Missing Relational Children**: Advance Steel now knows a label called `' 3/8 inch'`, but:
   - `SetBolts` has **0** bolt lengths for that diameter.
   - `SetNutsBolts` has **0** matching nuts and washers.
   - `SetOfBolts` has **0** assembly definitions.
   - `ScrewNew` has **0** calculation rules.
   - `BoltsDistances` has **0** tolerance spacing rules.
3. **Advance Steel Fails**: Inside Advance Steel, the user selects 3/8" in the bolt properties dialog, and the bolt disappears, fails length calculation, or causes connection joints to error out.
4. **Key Error**: Furthermore, if `Key = 39.1` was entered instead of `9.525` (3/8" * 25.4 = 9.525 mm), Advance Steel treats the diameter as ~1.54 inches, breaking all metric and imperial geometry.

---

## The Solution: Web App Cascading Diameter Engine

Catalog Studio includes a dedicated **Cascading Diameter Engine** accessible directly from the browser.

### 1. Pre-configured Standard Presets
Eliminates manual math and formatting errors. Choosing a preset from the dropdown instantly populates:
- The exact millimeter value (e.g. `9.525`).
- The Advance Steel UI format string (e.g. `' 3/8 inch'`).
- The find-and-replace token for part naming (e.g. `'3/8'`).

### 2. Proportional Scaling Formulas
When cloning from an existing diameter (such as cloning from `1/2"` / `12.7 mm` down to `3/8"` / `9.525 mm`), the engine computes a scale factor:
$$\text{Scale Ratio} = \frac{D_{\text{target}}}{D_{\text{source}}} = \frac{9.525}{12.7} = 0.75$$

- **Linear Dimensions** (Head Outer Diameter, Head Height, Nut Height, Washer Thickness):
  $$\text{Dimension}_{\text{target}} = \text{Dimension}_{\text{source}} \times 0.75$$
- **Edge & Pitch Spacing** (`along`, `across` in `BoltsDistances`):
  $$\text{Spacing}_{\text{target}} = \text{Spacing}_{\text{source}} \times 0.75$$
- **Component Mass** (`Weight` in kg for bolts, nuts, and washers):
  $$\text{Weight}_{\text{target}} = \text{Weight}_{\text{source}} \times (0.75)^2$$

### 3. Context-Aware Name Replacement
Simple string replacement often corrupts bolt names (for example, replacing `'1'` when cloning from 1" diameter bolts would turn `'A325TC 1 x 1 1/4'` into `'A325TC 3/8 x 3/8 1/4'`).

Catalog Studio uses context-aware regex:
- **Bolt Names**: Replaces the diameter token *immediately preceding* `' x '`:
  `A325TC 1/2 x 1 1/4` $\rightarrow$ `A325TC 3/8 x 1 1/4`
- **Nut & Washer Names**: Replaces the diameter token trailing after a space or hyphen:
  `A563 Nut 1/2` $\rightarrow$ `A563 Nut 3/8`
  `Washer F436 - 1/2` $\rightarrow$ `Washer F436 - 3/8`

### 4. Orphan Detection & Cleanup
The engine audits `BoltsDiameters` against all related tables:
- Any diameter entry with **0** corresponding rows in `SetBolts`, `SetOfBolts`, or `ScrewNew` is automatically flagged in the UI as:
  `⚠️ Orphan (0 records)`
- When adding the true diameter, a one-click checkbox cleanly purges the broken/miskeyed orphan row.

### 5. Atomic Transactions
All operations across all 6 tables run within a single SQL Server transaction (`autocommit=False`). If any insert or constraint fails, the entire transaction rolls back cleanly, preventing database corruption.

---

## Web App Interface & Features

### Database Overview Page (`/db/<database>`)
- Displays catalog metadata (Advance Steel version, catalog type).
- **Catalog Diameters Bar**: Visual badges showing every diameter present in the database, its total related record count, and warning badges for any detected orphans.
- Quick buttons for **Add / Clone Diameter** and **Find & Replace**.
- List of all tables with live row counts.

### Add / Clone Diameter Wizard (`/db/<database>/add-diameter`)
1. **Target Diameter**: Select from standard Imperial/Metric presets or enter custom dimensions.
2. **Source Template**: Choose which existing, functioning diameter to use as the template.
3. **Name Tokens**: Specify search and replace tokens for part naming.
4. **Options**: Toggle proportional head dimension scaling, edge distance scaling, and orphan cleanup.
5. **Live Preview**: Inspect table-by-table row counts and preview actual sample rows of `SetBolts` and `SetNutsBolts` before committing changes.

### Database-Wide Find & Replace (`/db/<database>/find-replace`)
- Scans every `NVARCHAR`, `VARCHAR`, and text column across all tables in the database.
- Safe Preview mode shows match counts per table and column before executing.

### Raw Table Editor (`/db/<database>/<table>`)
- Live table browsing with pagination.
- Column filtering and quick text search.
- In-place row editing, duplicating, and deleting.
- Guidance banner on `BoltsDiameters` pointing users to the cascading wizard.

---

## Getting Started & Setup

### Prerequisites
- **Linux** (or macOS / Windows with WSL2).
- **Docker** (for running the scratch SQL Server container).
- **Python 3.12+** with the provided virtual environment.

### Starting the Scratch SQL Server
The tool uses a container named `hilti-scratch-sql`:
```bash
# Check if container is running
docker ps -a | grep hilti-scratch-sql

# If stopped, start it:
docker start hilti-scratch-sql
```
*(Container port 1433 is mapped to `127.0.0.1:1433` with user `sa` and password `Scratch2026!Pw`).*

### Running Catalog Studio
Activate the virtual environment and start Flask:
```bash
cd /home/mark/Advance_Steel_DB_Tool_Dev
source venv/bin/activate
python catalog_studio/app.py
```
Open your browser to:
```
http://localhost:5050
```

---

## Typical Workflow: From Ingest to Advance Steel Import

```
┌─────────────────────────┐
│ Live Advance Steel (.mdf│
└────────────┬────────────┘
             │ 1. Copy out of Advance Steel / Steel / Data
             ▼
┌─────────────────────────┐
│   Catalog Studio Web    │  Upload .mdf / .ldf pair at http://localhost:5050
│       (/upload)         │
└────────────┬────────────┘
             │ 2. Attach into Docker SQL Server
             ▼
┌─────────────────────────┐
│ Add / Clone Diameter    │  Run cascading wizard:
│   (/add-diameter)       │  - Pick preset (e.g. 3/8")
└────────────┬────────────┘  - Auto-generate 50+ linked records
             │ 3. Detach & Export
             ▼
┌─────────────────────────┐
│ Download from /exports  │  Clean .mdf / .ldf ready to drop back into
└────────────┬────────────┘  Advance Steel
             │ 4. Re-import in Advance Steel Management Tools
             ▼
┌─────────────────────────┐
│ Functioning 3D Bolts in │
│ Advance Steel Model     │
└─────────────────────────┘
```

---

## Command-Line Utilities Reference

For automated scripts or headless workflows, several CLI tools are available in the repository root:

### 1. `db_inspect.py`
Inspects all tables, column types, and sample rows in an attached database:
```bash
python db_inspect.py A325TC_mark
```

### 2. `export_bolts.py`
Performs the full Advance Steel relational join (`SetBolts` + `SetOfBolts` + `SetNutsBolts`) and exports a consolidated CSV of all bolt assemblies. Also flags any bolts with missing nut records:
```bash
python export_bolts.py A325TC_mark output_catalog.csv
```

### 3. `diagnose_sets.py`
Inspects assembly set configurations (`MuS`, `Mu2S`, `MuKS`) and their washer/nut bindings for a specific diameter:
```bash
python diagnose_sets.py
```

---

## Summary of Completed Updates on `A325TC_mark`

In the current workspace, the `A325TC_mark` database has been fully repaired and upgraded:
- **Cleaned Up**: Removed the orphan entry `Key = 39.1` from `BoltsDiameters`.
- **Created 3/8" (9.525 mm)**:
  - `BoltsDiameters`: `Key = 9.525`, `RunName = ' 3/8 inch'`.
  - `BoltsDistances`: 3 tolerance rows (0.0, 1.0, 2.0 mm) with scaled `along` and `across` distances.
  - `ScrewNew`: 3 assembly calculation rows for `Mu2S`, `MuKS`, and `MuS`.
  - `SetOfBolts`: 3 assembly composition rows linking 9.525 mm bolts to 9.525 mm nuts and washers.
  - `SetNutsBolts`: 3 component rows (`A563 Nut 3/8`, `Washer F436 - 3/8`, `Washer F436R - 3/8`) with scaled dimensions.
  - `SetBolts`: 37 bolt length rows (1" to 10") with scaled head dimensions and weights.
- **Verification**: `export_bolts.py` confirmed 1,071 bolt assembly records joined with 100% complete nut and washer records.
