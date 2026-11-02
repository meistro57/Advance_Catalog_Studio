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
