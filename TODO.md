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

Baseline: `main` green at 344 tests; read-only bolt/anchor/stud/style views and
the health report exist; writes are the bolt diameter clone, raw row CRUD, find
& replace, and drawing-style field/rule edits.

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

## F. Data safety (prompted by the co-developer brief)

- [x] **F0 — Pre-change snapshots.** `copy_only` `.bak` + manifest for the bolt
  diameter clone and find & replace, fail-closed.
- [ ] **F0a — Snapshot the remaining batch paths.** Wire `create_snapshot()`
  into selective deep copy, batch presentation replace and any future purge, and
  decide whether single-row style edits need one (probably not, but state it).
- [ ] **F0b — Snapshot retention.** Keep the newest N per database and prune the
  rest with an explicit action (snapshots can be hundreds of MB).
- [ ] **F0c — Restore helper.** Document (and optionally automate) restoring a
  snapshot with `RESTORE DATABASE` inside the container, then detaching.
- [ ] **F0d — Read-only library guard.** Track which attached databases came from
  a delivered library (`AstorDetails`) and refuse batch writes there, even
  though everything is a copy in this tool.

## G. Cross-cutting features

- [ ] **G1 — Catalog comparison.** `GET /compare?a=&b=` showing table presence,
  row counts and per-type summaries (diameters/families/stud lengths); pure diff
  helpers plus tests; no writes.
- [ ] **G2 — Health report exports.** Download the findings as JSON/CSV, and add
  checks that are cheap and verified (e.g. `ScrewNew` grip gaps, duplicate stud
  names, anchor hardware material mismatches).
- [ ] **G3 — CI.** GitHub Actions running `pytest`, `python -m compileall`, and
  a docs link check on push/PR (repo currently has no CI).
- [ ] **G4 — Lint/format.** Decide on `ruff` (and a formatting policy) or
  explicitly stay unformatted; do not reformat unrelated code in one commit.
- [ ] **G5 — Docs refresh.** Screenshot for the usage page, refresh
  `catalog-studio-dashboard.png`, and re-check the README status table after
  every milestone.
- [ ] **G6 — CSRF review.** Audit every POST route; destructive ones must use
  `_csrf_valid()`, read-only previews may stay token-free but must say so.

## H. Housekeeping

- [ ] **G1 — Metadata sidecar.** `catalog_studio/catalog_metadata.json` is dirty
  from live attaches (`Mark_Column`, `HILTI_HY_200`); decide whether the file is
  runtime state (git-ignore it) or committed examples.
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
