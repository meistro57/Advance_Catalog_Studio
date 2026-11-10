# TODO — Advance Steel Catalog Studio

Working backlog for this repository. Keep it current: move finished items to the
"Done" log at the bottom and delete nothing else without a reason.

Status key: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

Rules that apply to every item:

- No write path ships without a **documented Advance Steel 2026 round trip**
  (edit → export → import into a controlled AS install → verify). Record the
  version and result in `docs/verification-log.md`.
- Every new check/rule is labelled **verified** or **assumed** where it lives,
  and assumed rules never enable a write.
- New SQL follows `AGENTS.md`: parameterised values, validated identifiers,
  `_open_connection()` only, preview before apply, CSRF on destructive routes.
- Any behavioural change needs pytest coverage; docs (`README.md`, `AGENTS.md`,
  `docs/*.md`) are updated in the same commit.

Baseline: `main` green at 547 tests; read-only bolt/anchor/stud/style views,
the health report and the DXF hand-edit diff (issue #15 Phase 1) exist; the
home dashboard is split into Fastener Management and Drawing Style Management
realms with distinct colour palettes (issue #20); both the Bolt-Set Viewer and
Anchor Configurator include fractional-inch / `mm` dimension toggles (issue #18),
and the Anchor Configurator has an interactive Bolt projection from concrete
control with a 4" typical preset (issues #19, #21); writes are the bolt/anchor
diameter clone and removal (issue #17), raw row CRUD, find & replace,
drawing-style field/rule edits, and deep-copy `RunName` prefix renaming
(issue #16).

---

## A. Verification programme (unblocks most `[!]` items)

Each task produces a section in `docs/verification-log.md` with: AS build,
catalog file, operation, expected vs observed, screenshot/log, verdict.

- [ ] **A1 — Bolt `Position1..6` semantics.** Use a working set
  (`MuS`, `Mu2S`, `MuKS`) plus a live AS 2026 connection; confirm sign and
  magnitude meaning (head vs nut side, layer order), and whether
  `SetBolts.NumberOfCorners` is usable for head geometry. Unblocks #1 Phase 3.
- [ ] **A2 — Anchor `Position` semantics.** Same method on `US_Headed_Anchors`,
  `US_Hooked_Anchors`, `US_Threaded_Anchors`; confirm top/bottom split and
  ordering. Unblocks the anchor editing UI.
- [ ] **A3 — Shear-stud round trip.** Attach Nelson H4L, apply one planned clone
  by hand (or via a throwaway script), detach/export, import into AS 2026,
  confirm the new diameter lists its lengths with correct name/geometry/weight.
  Also confirm `ConnectorRelations.Key` allocation (identity vs manual) and
  `SetBolts.Type` meaning. Unblocks #4 write path.
- [ ] **A4 — Drawing-style round trip.** Edit a rule and a field, export,
  import through Drawing Style Manager; confirm the style still loads, how a
  same-name style is handled, and whether `Copy of` naming matters. Unblocks
  selective deep copy, batch replacement, and any purge.
- [ ] **A5 — Enum labels.** Check whether any AS 2026 UI surface lists
  `AstorDetailsBase` values (geometric restrictions, object qualifiers, box
  modes, display types) with numbers. Only document a mapping that is read
  directly from the UI/build; never infer from ordering.
- [ ] **A6 — Export/detach integrity.** Confirm the exported `.mdf`/`.ldf` pair
  from the scratch container imports without the `ASSettings_User.xml` /
  log-file problems described in the compaction request.
- [ ] **A7 — DXF hand-edit diff against a real pair.** Generate a detail from a
  style, export DXF, hand-edit a copy, export again, and run both through
  `/detail-diff` with the style export. Confirm the AS layer/XData rule, the
  added hand dimensions, the chains and the sides match the edits; record the
  result in `docs/verification-log.md`. Unblocks issue #15 Phase 2.

## B. Bolt-set viewer/editor (issue #1)

- [ ] **B1 (`[!]` A1) — Phase 3 preview + transaction.** Server-side
  `preview_assembly_change()` / `apply_assembly_change()` that map a draft
  (component per slot, side, order, grip) to `SetOfBolts` / `SetBolts` /
  `SetNutsBolts` deltas; table-by-table preview, explicit confirm, one
  transaction, rollback on any mismatch. Tests with synthetic rows.
- [ ] **B2 — Draft validation pass in the browser.** Flag unmatched components,
  duplicate slots, hardware stacks that exceed the shank, and lengths the
  `ScrewNew` rules cannot cover; surface them next to the 3D view and in the
  profile (reuse `bolt_sets` warnings instead of new rules).
- [ ] **B3 — Python/JS layout parity.** Extract the browser layout into a JSON
  fixture and assert `bolt-set-layout.js` and `bolt_sets.build_layout()` agree
  (grip override included).
- [ ] **B4 — Record traceability.** Link every part row and 3D selection to its
  raw `SetNutsBolts` / `SetBolts` row (row token URLs), like the stud browser.
- [ ] **B5 — Accessibility.** Keyboard navigation for the component table,
  focus states, `aria-label`s on the explode/perspective toggles.
- [x] **B6 — Dimension unit toggle (issue #18).** Added fractional-inch (`1/16"`)
  / `mm` toggle buttons in the Bolt-Set Viewer (`bolt_set_viewer.html`,
  `bolt-set-viewer.js`, `bolt_profile.py`) and Anchor Configurator
  (`anchor_configurator.html`, `anchor-configurator.js`).

## C. Anchor configurator and fabrication sheets

- [ ] **C1 (`[!]` A2) — Purpose-built anchor editing.** Guided fields for
  identity/material/geometry/holes/hardware with relationship checks and a
  "what AS receives" preview; depends on verified `Position` semantics.
- [ ] **C2 — Fabrication sheet coverage.** Validate the sheet against
  `US_Headed_Anchors` and `US_Threaded_Anchors` (current mapping is verified for
  `US_Hooked_Anchors` only); document any family-specific rules.
- [ ] **C3 — Server-side PDF.** Decide whether browser Print stays the only
  output; if not, add a dependency and a test that the PDF contains every drawn
  dimension. Keep "NTS — USE WRITTEN DIMENSIONS".
- [ ] **C4 — Hole definition table.** Show `AnchorsHoleDefinition` on the
  configurator with its source rows; currently only the elevation is visualised.
- [x] **C5 — Anchor projection control & label (issues #19, #21).** Renamed
  `TopDistance` display label to `"Bolt projection from concrete"` and added an
  interactive projection control in the Anchor Configurator (with a quick 4"
  typical preset, catalog reset, embedment readout, and `projection_mm`
  pass-through to the fabrication detail sheet).

## D. Shear studs (issue #4)

- [ ] **D1 (`[!]` A3) — Transactional clone apply.** Reuse `plan_clone()` rows,
  insert inside one transaction with duplicate/name/relationship re-checks,
  return row counts; no apply button until A3 passes.
- [ ] **D2 (`[!]` A3) — New-catalog scaffolding.** Add a `shear stud` entry to
  `CATALOG_TEMPLATES` only when the schema template is verified; include seed
  lookups and the minimum record set from `docs/shear-stud-schema.md`.
- [ ] **D3 — Per-record detail.** Open one stud from the browser as a detail
  panel (like the anchor viewer) with raw-row links and its issue list.
- [ ] **D4 — Validation depth.** Duplicate names across families, distance-rule
  coverage per diameter, weight sanity vs `(d²·l)` ratio, and a warning when a
  family has no `ConnectorDistances` row.
- [ ] **D5 — Export checklist page.** One page per catalog: counts, open
  findings, "detach & export" reminder; reuse the health report data.

## E. Drawing styles

- [ ] **E1 — Dimension point selection editing.** Edit
  `DetViewDimRequestLinear.Point1..15` (and `NumberOfPoints`) with the existing
  relation dropdowns; validate that the point count matches the populated
  points and that `DetViewDimPointSelection.Objects` resolves.
- [ ] **E1b — Decode point-selection enums.** With a live AS 2026 DSM open
  next to an export, record which `DetViewDimPointSelection` column/value is
  each "Point type", "Point position on object/main part" and "Visibility"
  option, and which `Direction` values are which chain directions. Only then
  replace the raw columns on the dimension cards with labels (feeds A5).
- [ ] **E2 — Arranger strategy editing.** Expose `ArrangerStrategy`,
  `ArrangerControl` and the merge distance on annotation strategies, with the
  same shared-record warning as other library edits.
- [ ] **E3 — Usage page polish.** Record search/filter, deep links to raw rows,
  and a "used by N styles" badge in the editor next to shared sub-style fields
  (reuse `style_usage.usage()`; cache per request).
- [ ] **E4 — Multi-style fixture.** Add a sanitised synthetic export with two
  styles sharing one appearance to prove the usage walk reports both and the
  orphan scan stays empty.
- [ ] **E5 (`[!]` A4) — Selective deep copy.** Preview which branches would be
  duplicated per checkbox (view definitions, object presentation, dimension
  strategy, label strategy), propose new keys and names (no `Copy of`
  prefixing), then apply in one transaction.
- [ ] **E6 (`[!]` A4) — Batch presentation replace.** Criteria builder
  (object set / model role / geometric restriction) → preview diff by style and
  view → apply; block or auto-branch shared targets using the usage graph.
- [ ] **E7 — Token palette grouping.** Group tokens by object type (label,
  dimension, title) and keep the escape buttons.
- [ ] **E8 — Health rows for styles.** When an export has more than one style,
  report shared sub-styles in the health report, with counts per table.
- [x] **E10 — Rename deep-copy prefixes (issue #16).** Preview and transactional
  rename (`/db/<db>/drawing-style/rename-copies`) for the `Copy of ` and
  `Copy (n) ` `RunName` prefixes Advance Steel's Deep copy leaves on sub-style
  records across the style tables, with optional replacement prefix, table
  filtering, duplicate-name warnings, delivered-library guard and fail-closed
  pre-change snapshot (536 tests).
- [x] **E9 — Detail diff (issue #15, Phase 1).** Read-only `/detail-diff`: two
  ASCII DXFs plus an optional style export become a report of added, removed,
  moved and changed entities, with the feature, direction, side and chain
  intent, the owning style surface, existing request matches, shared sub-style
  warnings and a scale proposal. Text content and dimension values are ignored;
  text height, colours and the AutoCAD dimension style are reported as not a
  style change. Pure parser/diff/style matcher unit-tested; assumptions and the
  A7 procedure in `docs/dxf-diff.md`.
- [!] **E9b (blocked by A4, A7) — Apply the hand-edit plan.** Turn the Phase 1
  report into a reviewable table that writes a copy of the style (snapshot
  first), regenerates the detail, diffs it against the hand-edited target and
  repeats until only "style can't" edits remain.

## F. Data safety (prompted by the co-developer brief)

- [x] **F0 — Pre-change snapshots.** `copy_only` `.bak` + manifest for the bolt
  diameter clone and find & replace, fail-closed.
- [ ] **F0a — Snapshot the remaining batch paths.** Wire `create_snapshot()`
  into selective deep copy, batch presentation replace and any future purge, and
  decide whether single-row style edits need one (probably not, but state it).
- [x] **F0b — Snapshot retention.** `snapshot_files()` / `prune_snapshots()` and
  the database page's **Prune older** button keep the newest N (default 5);
  deletion is only ever an explicit, CSRF-checked action.
- [x] **F0c — Restore helper.** `snapshots.restore_plan()` returns the
  `docker cp` + `RESTORE DATABASE ... WITH REPLACE` command set (unit-tested);
  the README documents the manual procedure. Nothing executes a restore.
- [x] **F0d — Read-only library guard.** The attach route records an `Astor*`
  library origin in the metadata sidecar and `app._blocked_write()` refuses
  every write route for that database; reads, detach and export still work.

## G. Cross-cutting features

- [x] **G1 — Catalog comparison.** `GET /compare?a=&b=` shows table presence,
  row-count deltas and diameter keys/names/related rows/orphans; pure helpers in
  `utils/compare.py`; no writes.
- [~] **G2 — Health report exports.** JSON and CSV downloads exist
  (`/db/<db>/health.json`, `/db/<db>/health.csv`). Still open: extra cheap checks
  (`ScrewNew` grip gaps, duplicate stud names, anchor hardware material
  mismatches).
- [~] **G3 — CI.** `.github/workflows/ci.yml` runs `compileall`, `pytest tests/`
  and `pyflakes` on push/PR. A docs/markdown link check is still open.
- [~] **G4 — Lint/format.** `pyflakes catalog_studio tests *.py` is clean and
  is now the documented convenience check; still decide whether to pin `ruff`
  (and a formatting policy) or explicitly stay unformatted. Do not reformat
  unrelated code in one commit.
- [ ] **G5 — Docs refresh.** Screenshot for the usage page, refresh
  `catalog-studio-dashboard.png`, and re-check the README status table after
  every milestone.
- [x] **G6 — CSRF review.** Every POST now goes through the central
  `_csrf_guard()`; read-only previews are listed in `READ_ONLY_POST_ENDPOINTS`
  and `docs/csrf-audit.md`, and a URL-map test enforces the rule.

## H. Housekeeping

- [ ] **G1 — Metadata sidecar.** `catalog_studio/catalog_metadata.json` is dirty
  from live attaches (`Mark_Column`, `HILTI_HY_200`); decide whether the file is
  runtime state (git-ignore it) or committed examples. It now also carries the
  `library` flag that makes delivered Astor* attachments read-only, so a stale
  entry can silently block (or unblock) writes — worth settling.
- [ ] **G2 — Reference PDFs.** `docs/references/` holds the Autodesk guides and
  is git-ignored; keep a one-line note in the docs on what each is used for.
- [ ] **G3 — Test gaps.** No automated coverage for: `add-diameter` apply,
  detach/export, staging purge confirmation, drawing-style save/rule POST
  permutations, JS layout.
- [ ] **G4 — Sample data.** A multi-style drawing-style export and a second
  shear-stud catalog would strengthen the read-only features; only add files that
  are safe to publish.

## I. Open questions

- Should the health report become the default landing page for an attached
  database (instead of the raw table list)?
- Is `DBCC SHRINKDATABASE` ever worth offering on the scratch copy, or does the
  detach/export path already produce a small enough pair?
- Does AS 2026 read the `.ldf` on import, or only the `.mdf`? (Affects any future
  log cleanup; default answer: never split the pair.)

## Done log

- [x] Read-only shear-stud browser, completeness checks, preview-only clone plan.
- [x] Inches display for stud dimensions (nearest 1/16, `≈` marker).
- [x] Sub-style usage ("referenced by") and orphan scan for style exports.
- [x] Catalog health report across bolt, anchor, shear-stud and style catalogs.
- [x] Label preview tokens/escapes from Autodesk's DSM guide; docs mapping.
- [x] Branch cleanup and README/docs alignment.
- [x] Pre-change `COPY_ONLY` snapshots for the bolt diameter clone and find &
  replace, with fail-closed routes and manifests (329 tests).
- [x] Find & replace runs in one transaction, cascading legacy `text`/`ntext`
  to `nvarchar(max)` and rolling back on the first failure (issue #7).
- [x] Anchor diameter clone replaces an existing target diameter instead of
  duplicating it; the preview reports the rows that will be replaced (issue #8).
- [x] Table browser validates `filter_col` against the table's columns and
  limits `filter_op` to equals / contains (issue #9).
- [x] Detach restores `MULTI_USER` when `sp_detach_db` fails, snapshots close
  their connection on error, add-diameter names the snapshot failure, the bolt
  clone refuses identity-keyed tables, `BoltsDistances.Description` uses a
  token-boundary replace, and the tree is pyflakes-clean (issue #10).
- [x] Light/dark theme: navbar toggle, `localStorage` + `prefers-color-scheme`,
  Bootstrap `data-bs-theme` tokens in `static/css/theme.css`, drawing surfaces
  kept on light paper (348 tests).
- [x] Snapshot retention (`prune` keeps newest N) and a documented restore plan
  (F0b/F0c).
- [x] Delivered-library attachments (Astor*) are read-only for every write route
  (F0d).
- [x] Catalog comparison page `/compare` (G1); health report JSON/CSV downloads
  (G2 part 1).
- [x] Central CSRF guard for all POST routes plus `docs/csrf-audit.md` and a
  URL-map test (G6).
- [x] GitHub Actions CI: `compileall`, pytest and pyflakes (G3 part 1).
- [x] DXF hand-edit diff, Phase 1 of issue #15: read-only parser, entity
  classification, diff, chain intent, style mapping, request matching, shared
  sub-style flags, scale detection and the `/detail-diff` page/JSON (521 tests).
- [x] Deep-copy prefix rename (`/db/<db>/drawing-style/rename-copies`, issue #16):
  matches `Copy of `, `Copy (n) of ` and `Copy (n) ` across drawing-style
  `RunName` tables, previews before/after and same-table collisions, snapshots
  first, and updates in one transaction (536 tests).
- [x] Remove diameter (`/db/<db>/remove-diameter`, issue #17): previews and
  cascades deletion of a bolt or anchor diameter in child-before-parent order
  inside one transaction after taking a pre-change snapshot (541 tests).
- [x] Split home interface into Fastener Management and Drawing Style Management
  realms with distinct cobalt-steel vs drafting-teal themes across the home page
  and drawing-style workspace pages (issue #20, 543 tests).
- [x] Renamed `"Top distance"` to `"Bolt projection from concrete"` (issue #21),
  added interactive anchor bolt projection control with a `4"` typical preset
  (issue #19), and added fractional-inch / `mm` dimension display toggles across
  both the Bolt-Set Viewer and Anchor Configurator (issue #18, 547 tests).
