# Drawing-style exports (Drawing Style Manager → Export)

Reverse engineered from an Advance Steel 2026 export of
**"3 - Elevation SECTION View - Full"** (one style, 45 tables, ~7 MB mdf).
The logical file name inside the mdf is `AstorDetailProcessesBLANK`.

## Detection

`db.guess_catalog_type()` returns `"drawing style"` when both `DetailStyle` and
`DetObjReprMapItems` exist.

## The tree

```
DetailMasterTable            what appears in the style picker (RunName, HelpText, ExamplePicture)
 └─ StyleKey → DetailStyle    title formulas, "Number of items", Request1..Request10
     └─ RequestN → DetViewRequest          one per generated view
         ├─ Scale                          float, 1/N (0.0625 = 1:16 = 3/4" = 1'-0")
         ├─ SystemAndBox → DetViewSystemAndBox   view CS + depth box (zDeltaFront/Rear in mm)
         ├─ LengthclipXY → DetViewLengthClip     break-line clipping
         ├─ ObjReprMap   → DetObjReprMapsNew
         │                   └─ DetObjReprMapItems (Key, Order)   ← representation rules
         │                        ObjQualifier       → DetObjQualifierSet ("Beams", "Holes", …)
         │                        GeometricRestrictions  AS built-in enum (not in file)
         │                        Appearance         → DetObjAppearance
         │                        AnnotationStrategy → DetObjAnnotationStrategy
         │                                               └─ AnnotationType → DetAnnotationType.Content (label formula)
         │                        LineType           → Linetypes
         │                        SimplifiedGap      mm
         └─ DimStrategy  → DetViewDimStrategyNew
                             └─ DetViewDimStrategyItems (Key, Order)
                                  └─ RequestLinear → DetViewDimRequestLinear
                                       └─ Point1..15 → DetViewDimPointSelection
```

Keys in an export are renumbered into the `22001+` range.

## Autodesk's relation map

Every export ships `InfoTableRelations`. Rows with `TypeProperty = 'Relations'`
give `TableName.ColumnName → ReferToDB.ReferToTable.ReferToBindedColumn`
with a display column. `ReferToDB` blank = inside this file; `AstorBase` /
`AstorDetailsBase` = Autodesk's built-in databases, which are **not** in the
export (those values are shown as raw numbers; no labels are invented).

Gaps/bugs in Autodesk's map, patched in `drawing_styles.SUPPLEMENTARY_RELATIONS`
(each confirmed by the values falling exactly inside the target's key range):

| Column | Map says | Actually |
| --- | --- | --- |
| `DetObjReprMapItems.ObjQualifier/Appearance/AnnotationStrategy/LineType` | (missing) | QualifierSet / Appearance / AnnotationStrategy / Linetypes |
| `DetObjAnnotationStrategy.AnnotationType/ArrangerStrategy/Group` | (missing) | AnnotationType / ArrangerStrategy / AnnotationGroup |
| `DetObjAppearance.HatchVisible/HatchHidden` | table `Detail` (doesn't exist) | `DetHatchSettings` |
| `DetViewDimRequestLinear.Point1..15` | (missing) | `DetViewDimPointSelection` |
| `DetViewRequestCategories.Key` | `DetBaseCategories` | the row's own id — ignored |

## Reverse references ("used by") and orphan scan

`InfoTableRelations` gives every in-file reference as
`Child.Column -> Parent.Bind`, but it never says which side contains which. The
direction was settled from the data and is encoded in
`utils/style_usage.py: ASCENT_EDGES` as
`(child_table, child_column, parent_table, parent_column)`: a child row is
reached from a parent row whose `parent_column` equals the child's
`child_column`. Two shapes appear:

| Shape | Example | Meaning |
| --- | --- | --- |
| child column holds the parent's key | `DetObjReprMapItems.Key -> DetObjReprMapsNew.Key` | rules share their map's `Key`; `Order` is their position |
| child column holds a foreign key | `DetObjReprMapsNew.Key -> DetViewRequest.ObjReprMap` | the view request owns its representation map |

The verified upward chains are:

```
DetObjAppearance.Key          -> DetObjReprMapItems.Appearance
DetObjAnnotationStrategy.Key  -> DetObjReprMapItems.AnnotationStrategy
DetAnnotationType.Key         -> DetObjAnnotationStrategy.AnnotationType
DetObjQualifierSet.Key        -> DetObjReprMapItems.ObjQualifier
Linetypes.Key                 -> DetObjReprMapItems.LineType
DetObjReprMapItems.Key        -> DetObjReprMapsNew.Key
DetObjReprMapsNew.Key         -> DetViewRequest.ObjReprMap
DetViewRequest.Key            -> DetailStyle.Request1..Request10
DetViewDimStrategyItems.Key   -> DetViewDimStrategyNew.Key
DetViewDimRequestLinear.Key   -> DetViewDimStrategyItems.RequestLinear
DetViewDimPointSelection.Key  -> DetViewDimRequestLinear.Point1..Point15
DetViewDimStrategyNew.Key     -> DetViewRequest.DimStrategy
```

Walking those edges from a shared row reaches every `DetailStyle` that depends
on it; walking them in reverse from each `DetailStyle` marks every reachable
row, so rows left over are unreachable from any style. Across the three
checked-in style exports exactly one row is unreachable (an unused
`DetGridReferenceSettings` "Default" entry), which is the expected noise floor.

The feature request names `DetStyle`, `DetStyleViews`, `DetView`,
`DetDimStrategy`, `DetObjectsSet`, `DetDimDefinition` and `DetDimPoints`; none
of those tables exist in an AS 2026 export. Equivalents in this schema:
`DetailStyle`, `DetailStyle.Request1..10` (+ `DetViewRequest`),
`DetViewRequest`, `DetViewDimStrategyNew`, `DetObjReprMapsNew` +
`DetObjReprMapItems`, `DetObjAppearance`/`DetObjAnnotationStrategy`,
`DetViewDimStrategyNew`, `DetViewDimPointSelection`.

## What the Autodesk guides confirm

Five Autodesk/partner documents were used to check the terminology and the
manager's behaviour (kept locally in `docs/references/`, not committed):

- *Advance Steel Drawing Style Manager Guide* (2016, `advance-steel-2016-...`),
- *Drawing Style Manager Guide 6.1* (`AS-DSM guide-6.1-EN-051028`),
- AU handouts `MSF9970-L` (Drawing Styles customization), `FAB22624` (Drawings)
  and `FAB196818` (presentations).

They describe the manager, not the SQL schema, and they predate the 2026
export, so they confirm concepts and workflows only. What each contributes:

| Document | Confirms |
| --- | --- |
| *Advance Steel Drawing Style Manager Guide* (2016) | full manager UI, Copy vs Deep copy, optional shared-item warning, Compact database, label token table |
| *Drawing Style Manager Guide 6.1* (2005) | sub-style reuse model, `.mdb` export/import, Advance vs User libraries |
| AU `MSF9970-L` (Drawing Styles customization) | Copy shares sub-styles, Deep copy duplicates all levels and prefixes them `Copy of` |
| AU `FAB22624` (Drawings) | token-based labelling on sheets, style selection workflow |
| AU `FAB196818` (presentations) | practical presentation/token tips |

| Guide term | Observed table(s) |
| --- | --- |
| Drawing style | `DetailStyle` (+ picker record `DetailMasterTable`) |
| View / view request | `DetViewRequest` (+ `DetViewSystemAndBox`, `DetViewLengthClip`) |
| Object presentation set / rules | `DetObjReprMapsNew` / `DetObjReprMapItems` |
| Model objects | `DetObjQualifierSet` (+ `DetObjQualifierSetItem`, `...Group`) |
| Labeling strategy | `DetObjAnnotationStrategy` |
| Label content | `DetAnnotationType.Content` |
| Dimension strategy | `DetViewDimStrategyNew` / `DetViewDimStrategyItems` ("dimension definitions") |
| Dimension chain / request | `DetViewDimRequestLinear` |
| Point selection rules | `DetViewDimPointSelection` |

Behaviour confirmed by the guides:

- **Copy shares, Deep copy duplicates.** The guide: *"The Copy function will
  create a new DS, but referring (sharing) the same sub-styles with the original
  DS"*; deep copy duplicates the full structure and prefixes every copied level
  with `Copy of`. The handout adds that copied sub-style rows are *"all new
  records in the database"*. This is the hazard the sub-style usage page exists
  to expose.
- **The manager can warn about shared edits.** *"Modifying a sub-style modifies
  all drawing styles that use that sub-style. The Drawing Style Manager can be
  set up to display a warning when a shared item ... is modified."* So the
  sharing is not always silent; it is an option in DSM.
- **DSM already has the deduplication feature.** The `Compact database` button
  *"searches for equal records inside all detail tables ... combines the records
  and updates all records that have a relationship to the current combined
  object"* (control tables such as `DetRole` excluded). Catalog Studio therefore
  reports unreachable rows instead of re-implementing compaction; use DSM's
  Compact on a copy after reviewing the report.
- **Advance vs User is a library, not a row.** Styles live under the delivered
  `Advance` category or the editable `User` library (`_astm4CommDetailing User
  <base> <sub>`). An export is one library file, so provenance is the source
  database (`AstorDetails` = delivered, `AstorAddIn` = user overrides), not a
  column; the usage page shows the database name and `OwnerText` instead.
- **Label tokens.** The guide lists the token table now mirrored in
  `drawing_styles.KNOWN_FIELDS` (`%ProfName`, `%Thickness`, `%UserAttr1..10`,
  ...) and the AutoCAD-style symbol escapes `%%c` (Ø), `%%d` (°), `%%p` (±) and
  `%%%` (%), which `parse_label_format` renders as symbols.

## Composite keys

`DetObjReprMapItems`, `DetViewDimStrategyItems`, `DetailStyleMapItems`,
`DetProcessesSuiteItems` are keyed `(Key, Order)`; `DetailMasterTable` is keyed
`(Key, BaseCategory, SubCategory, StyleKey)`. Addressing these by `Key` alone hits
every rule in the map. All row operations go through full-key row tokens and an
exactly-one-row transaction guard (`db.update_row` / `db.delete_row`).

## Representation rules

Rules are evaluated top to bottom by `Order`. The same object set can appear
several times with different `GeometricRestrictions` (seen: 0, 5, 6) — specific
cases first, catch-all after. The editor can reorder (swap through a temp
`Order`), copy-below (shifts the rest down), delete (then renumbers 0..n-1).

## Placement (where views, titles and labels go)

**No coordinates are stored.** A style export carries the *rules* Advance Steel
uses to lay a drawing out; the positions themselves are computed at drawing
time. Verified across the three checked-in exports: there is no x/y column on
`DetViewRequest`, `DetailStyle` or `DetViewSystemAndBox`, and `DetArrangerControl`
(which does hold angles) is empty in the sample.

Placement is therefore four groups of stored inputs:

| Where | Column | Meaning |
| --- | --- | --- |
| `DetailStyle.ViewArrangeStrategy` | -> `DetViewArrangeStrategy.Key` | shared arrangement sub-style |
| `DetViewArrangeStrategy` | `ViewDistance` | spacing between views, **millimetres** (displayed as ft-in, accepts either) |
| `DetViewArrangeStrategy` | `ArrangeCutsInChains` | boolean |
| `DetailStyle` | `DetailOrientation`, `ObjectSelectionStrategy` | AS enums; the relation points at `AstorBase` tables that are not in the export, so only the number is available |
| `DetailStyle` | `ObjectPosition`, `TitlePosition`, `CutViewTitlePosition`, `FrameAppearance`, `AutomaticClipping` | AS enums with **no relation at all** in `InfoTableRelations`; numbers only |
| `DetViewRequest` | `ArrangeDir`, `CompassLocation`, `CompassLocationInOverviews` | per-view direction/compass enums; numbers only |
| `DetArrangerStrategy` | `TerminateOnFirstFit`, `ArrangeGlobally`, `ArrangeInCenter` + `SearchArea1..10` / `AreaPercent` / `MinDistance` / `MaxDistance` | where an **object label** is placed (10 search areas, distances in mm) |
| `DetArrangerControl` | `Angle1..16`, `PreferredDistance`, `MaxDistance`, `AllowOppositeAngles`, `ArrangeInCentre` | where a **dimension text** may sit (angle search); empty in every sample |

The editor shows these in two places rather than inventing positions:

- **Style pane -> Placement** — the arrangement strategy as a select, the three
  arrangement fields editable inline (shared sub-style, so it says so), and the
  seven style-level placement numbers;
- **each view pane -> Placement in this view** — the three per-view numbers,
  linking back to the style's arrangement strategy.

Unverified: what each placement enum number means. They are shown as
`(AS enum)` and never labelled, and the page states that positions are computed
rather than stored. `DetArrangerStrategy` is already loaded into the editor tree
and editable through the raw table view; giving it a dedicated pane is the next
step, not a rewrite.

## Label formulas (`DetAnnotationType.Content`, `DetailStyle.TitleFormat`)

| Token | Meaning |
| --- | --- |
| `%Field` | model property (`%Position`, `%Name`, `%MainPartPosNum`, `%BoltCount`, `%Diameter`, `%Length`, `%Norm`, `%UserAttr1`, `%Note`, `%ViewNumber`, `%Scale`, …) |
| `#Newline` | line break |
| `#Height(mm)` | text height (6.40 ≈ 1/4") |
| `#Bold(0/1)`, `#Underline(0/1)`, `#Italic(0/1)` | styling |
| `#Color(n)` | AutoCAD ACI colour (1 red … 7 white/black; 257 seen = default) |
| `#Rounded` … `#End` | framed text |

Field names are matched greedily; `%BoltCountx` is `%BoltCount` + `x`.

## Editor figures

`catalog_studio/utils/style_diagrams.py` draws the editor's pictures from these
same row values, so the geometry always follows the columns:

- **style overview** — one row per `DetViewRequest`, bar length = paper width
  for 1 ft of model (`12/N`), plus that view's rule and dimension counts.
- **print scale** — `Scale` is a reciprocal: 1 ft of model drawn as paper
  inches (`Σ 12/N`), with a 3-inch tick bar.
- **view box** — `xDelta`/`yDelta` as reach around the view's coordinate
  system, `zDeltaFront`/`zDeltaRear` as depth in front of and behind the view
  plane, with the mode numbers printed unchanged.
- **length clipping** — the member is drawn once and each column is placed on
  it as a measured distance (`MinRemainingLength`, `MinClipIntervalLength`,
  `Extension`, `ClippingGap`). The figure shows *which distance carries which
  name*, not what AS does with it.
- **dimension chain** — `Direction` (0 = X, 1 = Y), `ArrangeAbove` and the
  point count decide the sketch; point names come from
  `DetViewDimPointSelection.RunName`.
- **dimension plan** — every chain of one view at once: X chains stack above
  or below the part, Y chains beside it, numbered into a legend that repeats
  direction, Above and point count. Lanes follow
  `DetViewDimStrategyItems.Order`; beyond the lane cap the figure reports how
  many were left out.
- **chain anatomy** — a static explainer for one chain (line, ticks, Above,
  Direction), shown once per style.
- **vertical chains** — `ArrangeAbove` on a Y chain is drawn on the **left**.
  The DSM guide (2016, p.72): *"In the vertical detail views above is left and
  below is right."* Earlier figures put it on the right.
- **dimension setup flags** — `ArrangeGlobally`, `GroupRelatedDimensions`,
  `OneChainPerObjectInPoints1`, `AllowCombine`, `AutomaticallySeparate`,
  `Group` and `LabelContents` are surfaced as badges in the editor table; their
  exact AS behaviour is not verified, so they are labelled as AS switches.
- **hatch swatch** — parallel lines at the preset's own `Angle` and a spacing
  proportional to its `Scale`, labelled with `PatternName`. Real AutoCAD
  pattern shapes are not reproduced.

Two readings above are interpretation, not source data: the box extents as
"front/behind around a plane", and the clipping columns as the distances drawn.
Both are called out in the figure footers.

## Dimension request explainer

`catalog_studio/utils/dim_explain.py` turns one `DetViewDimRequestLinear` row
and its `DetViewDimPointSelection` rows into sentences, shown as one card per
chain on the view's **Dimensions** screen. It follows the DSM's own three
questions (guide 2016, ch. 6): what is measured (point selection rules), which
way the chain runs (direction), where it goes (arrangement switches).

Every line carries a basis tag so a reading is never presented as fact:

| Tag | Source |
| --- | --- |
| DSM guide | Meaning from the Drawing Style Manager guide; switch columns matched to the DSM option by name |
| stored | Read straight from the row (object set name, point count, Direction 0/1) |
| from name | Parsed from a rule's `RunName` (`Holes - All`, `Main Part - Extreme as reference`) |
| AS number | A built-in enum value whose label is not in the export; shown unchanged |
| observed | Seen in Advance Steel output for a real export (verification log A5.1), not yet read from the DSM list |

Column ↔ DSM option matches (by name, cross-checked by the name code):

| Column | DSM option | Name code |
| --- | --- | --- |
| `ArrangeGlobally` | Dimension line must not overlap the total geometry | G / L |
| `ArrangeAbove` | Arrange dimension line above and not below (left/right in vertical views) | T / B |
| `OneChainPerObjectInPoints1` | Create a separate dimension chain for each item marked with * | S / A |
| `GroupRelatedDimensions` | Group only related dimensions | — |
| `AllowCombine` | inverse of "Do not combine with other dimensions" | — |
| `AutomaticallySeparate` | not described in the guides | — |

The DSM writes the arrangement into the request name (`Mp X - Extreme GTA`).
The explainer decodes that suffix and warns when it disagrees with the stored
switches. Across real exports, agreement is evidence that the column matches
above are right (feeds TODO A5). It also warns when `Number of Points`
disagrees with the filled `Point1..15`, when a chain has no points, and when
every point rule is "as reference" (the guide: reference points only appear
when the chain already has something to measure).

Real exports (the railing style, A5.1) also showed:

- point rule names in the form `Objects | Point kind | Position`
  (`Railings - Posts Landing | System | Bottom-Any`); the explainer reads the
  position part against the DSM's position list ("Bottom-Any" = bottom points
  of the object, any on the main part);
- `DetViewDimStrategyItems.Type` (→ `AstorDetailsBase.DetRequestTypes`, the
  DSM dimension type) and `DetViewDimRequestLinear.Group`
  (→ `DetViewDimRequestLinearGroup`, the DSM folder: Mp / Railings / Others);
- `DetViewDimStrategyNew.Items`, which names the strategy's item list (equal to
  its own `Key` in every export seen; the tree follows `Items` when set);
- `Direction` values 4 and 5 in addition to 0/1.

Not decoded: the point type, position-on-object and visibility columns of
`DetViewDimPointSelection`, and `Direction` values other than 0/1. The guide
lists the options (≈20 directions, 27 point types, 15 positions, 3 visibility
states) but the number → option table is in `AstorDetailsBase`. Those columns
are listed raw on each card.

## Editor layout

The editor is one form split into screens by a left-hand menu: the style, then
each view as **View** (setup, scale, box, clipping), **Representation rules**
and **Dimensions**, then the four libraries and a help screen on reading a
dimension request. Only one screen shows at a time (`#pane-…` in the URL);
hidden screens still submit, so one **Save changes** covers every screen and
menu items with unsaved edits get an orange dot. Old anchors (`#req-<view>`,
`#rules-<map>`, `#lib`) still resolve to the screen that contains them.

## Editor behaviour (htmx)

The editor page edits rules in place. Rule buttons post `op=action:map:order`
to `/db/<db>/drawing-style/rule`; an `HX-Request` post gets back just that
map's rules block (`templates/_drawing_rules.html`, built from
`drawing_styles.repr_block`), so reordering never reloads the page. Flashes
come back as out-of-band swaps into `#flashHost`, and plain form posts still
redirect to `#rules-<map>` for the no-JavaScript path. htmx is vendored at
`static/vendor/htmx/htmx.min.js` (no CDN, no build step). Field saves post the
whole form and answer with flashes only.

## Not verified yet

The guides above describe the 2016 manager and its `.mdb` libraries; the 2026
export is a SQL Server pair, so none of the following is settled by them.

- How the Drawing Style Manager import handles a style whose name already
  exists. Renaming before import sidesteps it.
- Labels for `AstorDetailsBase` enums (geometric restrictions, object
  qualifiers, display-type numbers on appearances, xy/z box modes).
- Units of `DetViewLengthClip.ClippingGap` (5.0 — doesn't look like mm).
- Whether deleting rows that the usage scan reports as unreachable produces an
  importable export. The scan is read-only for that reason, and no purge,
  deduplication, shrink or `.ldf` cleanup is implemented.
- How a selectively deep-copied style branch (new keys, rewired references)
  survives import. The reported keys are renumbered into the `22001+` range, so
  a copy must allocate keys that Advance Steel accepts; that is unverified.
