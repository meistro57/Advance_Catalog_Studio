# CSRF audit

_Last reviewed: 2026-11-02, introduced in `a7bdf54`._

The Flask development server has no authentication, so a page from another site
open in the same browser could otherwise trigger a state change with a plain
`<form>` or `<img>` request. Every request that can write therefore needs a
session CSRF token.

## How the guard works

- `_csrf_token()` creates the per-session token; `_inject_csrf()` exposes it to
  every template as `csrf_token`.
- `_csrf_valid()` compares the submitted `csrf_token` form value with the
  session token.
- `_csrf_guard()` is an `app.before_request` hook: **every POST** is rejected
  with 400 before the route body runs unless the endpoint is exempted below.
  This is deliberately central, so a new POST route cannot forget the check.
- `tests/test_write_guards.py::test_every_writing_post_route_requires_csrf`
  walks the live URL map and fails if any non-exempt POST accepts a request with
  no token.
- The `/uploads/*` routes keep their original explicit `_csrf_valid()` check as
  well; it is redundant now but harmless, and the staging cleanup tests still
  exercise it directly.

## POST routes

| Route | Endpoint | Writes | Token |
| --- | --- | --- | --- |
| `/upload` | `upload` | stages uploaded mdf/ldf files | required |
| `/attach` | `attach` | ATTACH DATABASE in the container | required |
| `/create` | `create_catalog` | CREATE DATABASE + DDL/seed | required |
| `/uploads/remove` | `uploads_remove` | moves staged files to trash | required |
| `/uploads/flush` | `uploads_flush` | moves all staged files to trash | required |
| `/uploads/purge` | `uploads_purge` | deletes the staging trash | required |
| `/db/<db>/detach` | `detach` | detach + export mdf/ldf | required |
| `/db/<db>/snapshots/prune` | `prune_snapshots` | deletes old `.bak` snapshots | required |
| `/db/<db>/add-diameter` (`action=apply`) | `add_diameter` | snapshot + multi-table clone | required |
| `/db/<db>/find-replace` (`action=apply`) | `find_replace` | snapshot + database-wide replace | required |
| `/db/<db>/<table>/add` | `add_row` | INSERT | required |
| `/db/<db>/<table>/<pk>/edit` | `edit_row` | UPDATE | required |
| `/db/<db>/<table>/<pk>/duplicate` | `duplicate_row_route` | INSERT copy | required |
| `/db/<db>/<table>/<pk>/delete` | `delete_row_route` | DELETE | required |
| `/db/<db>/drawing-style/save` | `drawing_style_save` | UPDATE style fields | required |
| `/db/<db>/drawing-style/rule` | `drawing_style_rule` | rule copy/reorder/delete | required |
| `/db/<db>/drawing-style/diagram` | `drawing_style_diagram` | none (redraws a figure) | required anyway (htmx posts it) |
| `/detail-diff` | `detail_diff` | none (parses two uploaded DXFs in the request) | required anyway (a file upload is a POST) |

## Exempt POST routes (read-only)

These only render a preview from the submitted values. They never reach
`utils.db`, and they are listed in `READ_ONLY_POST_ENDPOINTS` in `app.py`:

| Route | Endpoint | Why it is token-free |
| --- | --- | --- |
| `/db/<db>/shear-stud-browser/clone-preview` | `shear_stud_clone_preview` | builds the preview-only clone proposal in memory (issue #4 has no apply route) |
| `/db/<db>/drawing-style/label-preview` | `drawing_style_label_preview` | parses a label formula string and returns HTML |
| `/db/<db>/bolt-set-viewer/sketch` | `bolt_set_viewer_sketch` | checks the token itself, because the payload is JSON (`csrf_token` in the body) |

`/db/<db>/add-diameter` and `/db/<db>/find-replace` accept `action=preview`
without a token (nothing is written); only `action=apply` requires it.

## Notes

- GET routes are all read-only. The table browser validates `filter_col` and
  `filter_op` before they reach SQL, so a crafted GET cannot inject identifiers.
- The health downloads (`/db/<db>/health.json`, `/db/<db>/health.csv`) are GET
  and read-only.
- Delivered-library attachments are additionally refused at the route level by
  `_blocked_write()`, independent of CSRF.
- Adding a new POST route means: rely on the central guard, and add a row to
  this table. If it is genuinely read-only, add it to
  `READ_ONLY_POST_ENDPOINTS` **and** explain it here.
