# Detail diff: reading hand edits back to a drawing style

Issue #15 describes a practical problem. Editing a drawing style's dimensions
and layout in the Drawing Style Manager is slow, so the useful workflow is to
hand-edit a generated detail until it looks right and then work out which style
settings would have produced it. This is the Phase 1, read-only half of that
idea: two DXF exports of the same detail plus, optionally, the style export that
produced the first one.

The page is **Detail diff** (`/detail-diff`) in the navigation bar. The same
POST accepts `format=json` and returns the report as JSON, which is the
agent-facing surface an MCP server can wrap later. The MCP server itself is not
built yet; the operations behind the issue's tools (read, explain, search,
propose) are the module's functions plus the JSON report. The JSON POST is still
a POST, so it needs the session `csrf_token` (get the page first and send the
token with the two files).

Nothing here writes. There is no apply route, no database change and no export.
Phase 2 (apply the plan to a copy, regenerate, diff again) stays blocked until
verification A4 in `docs/verification-log.md` passes and a real before/after
pair has been checked under A7.

## Inputs

| Input | Required | Notes |
| --- | --- | --- |
| Before DXF | yes | The detail as the style generated it. ASCII DXF, not binary. |
| After DXF | yes | The same detail after the hand edits, same assembly and coordinates. |
| Style export | no | An attached drawing-style database. Adds existing requests, shared-style warnings and scale proposals. |

The two files are parsed in the request and never stored. Each may be up to 64 MB.
The page refuses binary DXF, non-`.dxf` names and a missing file.

Part marks, m-numbers and dimension values are compared only as geometry (where
a dimension sits and which way it runs). Text content and measured values are
never reported as edits.

## Reading the DXF

`utils/dxf_compare.py` is a small ASCII DXF reader, not an AutoCAD engine. It
reads the HEADER variables `$ACADVER`, `$INSUNITS` and `$MEASUREMENT`, the LAYER
and DIMSTYLE tables, block names and the ENTITIES section. Supported geometry:
LINE, LWPOLYLINE/POLYLINE + VERTEX, CIRCLE, ARC, ELLIPSE, INSERT, DIMENSION and
its subclasses, TEXT/MTEXT/ATTRIB, HATCH, LEADER/MLEADER, SOLID/3DFACE, SPLINE
and POINT. Anything else is kept as an `other` entity if it has coordinates.

Each entity gets:

- `kind`: dimension, label, title, contour, axis, hatch or other;
- `origin`: generated (Advance Steel), hand or unknown;
- an anchor, bounding box, length and orientation.

Entity kinds come from the DXF entity type first, then the layer name refines
it (a LINE on a `CENTER` layer is an axis; TEXT on a `TITLE` layer is title
text; a HATCH is a hatch). The role table is in `LAYER_ROLE_HINTS`.

Origin is inferred, and the inference is named in the report:

| Rule | Origin | Basis |
| --- | --- | --- |
| XDATA application id starts with AS, ASTOR or ADVANCE | generated | AS XDATA |
| Layer starts with `AS_`, `AS-`, `ADVANCE` or `ASTOR` | generated | AS layer prefix |
| Proxy entity | generated | proxy entity |
| Layer `0` or blank and no AS marker | unknown | no AS marker on layer 0 |
| Plain AutoCAD dimension/text on a non-AS layer | hand | plain AutoCAD object on a non-AS layer |
| Any other entity on a non-AS layer | hand | non-AS layer |

The layer-prefix rule is an inference from the sample drawings, not a verified
list. The report shows the raw layer for every entity, and the page warns when
the before file has no AS-marked entity at all.

## The diff

- Tolerance is 0.5% of the drawing diagonal unless overridden.
- First pass pairs entities of the same kind and origin whose anchors are within
  tolerance. Attribute differences on a pair are reported as changes.
- Second pass pairs the leftovers within 25% of the diagonal, with a stricter
  shape test (same dimension subtype and span within 10%, same label height and
  rotation, same contour direction and length). Those are moves.
- Unpaired after-entities are added; unpaired before-entities are removed.
- Dimensions are paired by subtype, direction and span, but a change in the
  measured value is not reported. Text content is not read. A dimension that
  the DXF exploded into lines or text on a dimension layer is classified as
  "dimension geometry" and still maps to the view's dimension strategy.
- Matched entities are grouped into readable edits. A dimension group with more
  than one segment is a chain; the group carries the side and offset of its
  chain.
- When a uniform size change is found, the after file is normalised to the
  before scale before diffing, so the scale change is not reported as every
  entity moving. The scale is detected from contour length totals per layer and
  cross-checked with the outline bounding box; one layer is only accepted when
  the bounding box agrees.

## Intent

Each edit is described with the vocabulary the dimension cards already use
(`utils/dim_explain.py`), without guessing Advance Steel enum labels:

- **feature**: the assembly extreme when the landing point is on the outline's
  extreme, a system line (centerline) when it lands on an axis layer, otherwise
  a generated contour and its layer name. The DXF does not carry the Advance
  Steel object, so no part name (post, rail) is invented.
- **direction**: runs horizontally, vertically, along the main part, square to
  it, or at an angle. The main part is the longest generated contour segment;
  the report states that basis.
- **side**: above/below/left/right of the view outline, or above/below the
  sloped main part. The offset from the nearest existing chain (or the view
  edge) is reported with the file's units.
- **what**: single dimension, or a chain of N segments.

For labels the text content is explicitly ignored and the text height is
reported as a drawing default, not a style value.

## Mapping an edit to the style

| On the sheet | Style surface | Tables |
| --- | --- | --- |
| Scale | `DetViewRequest.Scale` | `DetViewRequest` |
| Views, order, spacing | `DetailStyle.Request1..10`, `DetViewArrangeStrategy` | `DetailStyle`, `DetViewArrangeStrategy` |
| Solid, hidden, centerline, simplified | representation rules | `DetObjReprMapItems`, `DetObjAppearance`, `Linetypes` |
| Part labels | label strategies and formulas | `DetObjReprMapItems`, `DetObjAnnotationStrategy`, `DetAnnotationType`, `DetArrangerStrategy` |
| Dimensions and slope triangles | dimension strategy, request and point rules | `DetViewDimStrategyItems`, `DetViewDimRequestLinear`, `DetViewDimPointSelection` |
| Title text and position | `DetailStyle.TitleFormat` / `TitlePosition` | `DetailStyle` |
| Depth, view box, break lines | `DetViewSystemAndBox`, `DetViewLengthClip` | `DetViewSystemAndBox`, `DetViewLengthClip` |

Reported as **not a style change**: text height, layer/entity colours, the
AutoCAD dimension style (arrowheads, text style, extension gaps), the title
frame/border and anything else that belongs to the drawing defaults or the DWG
prototype. The DIMSTYLE and LAYER tables are compared directly, so an arrow-size
or layer-colour change is reported even when no entity moved.

A dimension edit is matched against existing requests indexed by their explained
sentence. The index contains the selected style's requests plus every
`DetViewDimRequestLinear` row in the attached export (the library). Matching
prefers the same axis, side, feature and dimension type; the score is shown, not
hidden. The point-selection rules inside those requests are indexed separately,
so the report also lists a reusable point rule whose sentence matches the
feature (for example "the assembly extreme"). Each edit carries a suggested
style change in one sentence, using the best match when there is one and saying
"add a request" when there is not. When a matched record is used by more than
one style, the report flags it through the read-only `style_usage` walk, because
editing it changes every one of those styles.

## What the report does not claim

- It does not name Advance Steel part or object sets.
- It does not guess enum numbers for direction, point position or title
  position; those labels are not in the export.
- It does not read paper-space layout or the DWG prototype. A scale change or
  layer colour made there is invisible.
- A whole view moved on the sheet is reported as many moved entities. The style
  stores arrangement order and spacing, not exact coordinates.
- It does not apply anything.

## Verification (A7)

The parser and diff are unit-tested against synthetic ASCII DXF files
(`tests/test_dxf_compare.py`): classification, polylines, binary refusal,
add/remove/move/change, dimension chains, scale, style matching, shared-style
flags and the route. None of that is evidence about a real Advance Steel
export.

To close A7, use a real pair from the same assembly:

1. Generate a detail from a style and export it as DXF.
2. Hand-edit a copy and export it as DXF.
3. Run both through Detail diff with the style export attached.
4. Confirm the generated entities are on AS layers (or add the observed prefix
   to `AS_LAYER_PREFIXES`), that added hand dimensions are reported as hand, and
   that the chains and sides match what was edited.
5. Record the AS build, files, result and any correction in
   `docs/verification-log.md` under A7.

Until that entry passes, every reading here is an inference and the page says
so.
