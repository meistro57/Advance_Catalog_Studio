# app.py
import csv
import datetime
import io
import json
import os
import secrets

from flask import (
    Flask, render_template, request, redirect, url_for, flash, send_from_directory,
    send_file, jsonify, session, abort, Response,
)
from werkzeug.utils import secure_filename

import config
from utils import db, docker_ops, staging, metadata, bolt_sets, anchor_sets, fabrication
from utils import staging_cleanup, drawing_styles, style_diagrams, bolt_profile
from utils import shear_studs, health, style_usage, snapshots, compare, icons
from utils import dxf_compare
from utils.schema_templates import CATALOG_TEMPLATES

app = Flask(__name__)
app.config.from_object(config)

# Dimension formatting helpers for the fabrication sheet templates.
app.jinja_env.filters["fmm"] = fabrication.format_mm
app.jinja_env.filters["fin_fraction"] = fabrication.format_in
app.jinja_env.filters["f_dim"] = fabrication.format_dim_text
# Shear-stud browser dimensions: stored millimetres, displayed in mm or inches.
app.jinja_env.filters["sdim"] = shear_studs.format_dimension
# Inline SVG icons: templates say {{ icon('health') }} instead of emoji, so the
# chrome renders the same on hosts without a colour emoji font.
app.jinja_env.globals["icon"] = icons.icon
# The dimension plan and the chain cards share one palette, so the card's number
# is the colour of that chain's lane.
app.jinja_env.globals["lane_colour"] = style_diagrams.lane_colour


def _csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_hex(16)
        session["_csrf"] = token
    return token


def _csrf_valid() -> bool:
    return bool(session.get("_csrf")) and request.form.get("csrf_token", "") == session["_csrf"]


def _library_block(database):
    """Reason when this attachment came from a delivered Advance Steel library."""
    library = metadata.get(database).get("library")
    if not library:
        return None
    label = metadata.library_label(library) or f"{library}.mdf"
    return (
        f"'{database}' was attached from a delivered Advance Steel library ({label}). "
        f"Catalog Studio keeps that copy read-only; attach a copy under a new name "
        f"to edit it."
    )


def _blocked_write(database):
    """Redirect response when a delivered-library database must stay read-only."""
    blocked = _library_block(database)
    if not blocked:
        return None
    flash(blocked, "warning")
    return redirect(url_for("show_database", database=database))


@app.context_processor
def _inject_csrf():
    return {
        "csrf_token": _csrf_token(),
        "issues_url": config.ISSUES_URL,
        "app_version": config.APP_VERSION,
    }


# POST endpoints that only render a preview and never touch the database. They
# are listed here (and in docs/csrf-audit.md) instead of carrying a token.
READ_ONLY_POST_ENDPOINTS = {
    "shear_stud_clone_preview",
    "drawing_style_label_preview",
}


@app.before_request
def _csrf_guard():
    """Require a CSRF token for every POST that can write.

    A central guard runs before the route body, so a stale or missing token is
    rejected before any database work starts.
    """
    if request.method != "POST":
        return None
    endpoint = request.endpoint or ""
    if endpoint in READ_ONLY_POST_ENDPOINTS:
        return None
    if endpoint == "bolt_set_viewer_sketch":
        return None  # JSON payload: the route checks csrf_token from the body
    if endpoint in {"find_replace", "add_diameter"}:
        if request.form.get("action") != "apply":
            return None
    if not _csrf_valid():
        abort(400, description="Invalid CSRF token.")
    return None

os.makedirs(config.UPLOAD_DIR, exist_ok=True)
os.makedirs(config.EXPORT_DIR, exist_ok=True)


# --------------------------------------------------------------------------
# Home: upload new mdf/ldf, see staged pairs, see attached databases
# --------------------------------------------------------------------------

@app.route("/")
def index():
    staged_status = staging_cleanup.scan_upload_dir(config.UPLOAD_DIR)
    container_up = docker_ops.container_is_running()
    attached = []
    if not container_up:
        flash(
            f"SQL Server container '{config.CONTAINER_NAME}' is not running, so no "
            "catalogs can be attached or browsed. Start it with: "
            f"docker start {config.CONTAINER_NAME}",
            "danger",
        )
    else:
        try:
            attached = db.list_databases()
            problem = db.compatibility_problem(db.server_file_version())
            if problem:
                flash(problem, "danger")
        except Exception as e:
            flash(f"Could not reach the scratch SQL Server container: {e}", "danger")
    exports_status = staging_cleanup.scan_upload_dir(config.EXPORT_DIR)
    exports = staging_cleanup.list_catalog_files(config.EXPORT_DIR)
    meta = metadata.all_meta()
    fastener_dbs = []
    style_dbs = []
    for name in attached:
        m = dict(meta.get(name) or {})
        ctype = m.get("catalog_type")
        if not ctype and container_up:
            try:
                ctype = db.guess_catalog_type(name)
            except Exception:
                ctype = None
            if ctype:
                m["catalog_type"] = ctype
                meta[name] = m
        if ctype == "drawing style":
            style_dbs.append(name)
        else:
            fastener_dbs.append(name)

    return render_template(
        "index.html",
        staged=staged_status["pairs"],
        orphan_files=staged_status["orphans"],
        uploads_status=staged_status,
        attached=attached,
        fastener_dbs=fastener_dbs,
        style_dbs=style_dbs,
        exports=exports,
        exports_status=exports_status,
        container_up=container_up,
        meta=meta,
        catalog_types=CATALOG_TEMPLATES,
        as_versions=sorted(config.SUPPORTED_AS_VERSIONS),
        default_as_version=config.ADVANCE_STEEL_VERSION,
    )


# --------------------------------------------------------------------------
# Staged-upload cleanup (issue #3): remove / flush / purge
# --------------------------------------------------------------------------

def _known_staged_names() -> set:
    status = staging_cleanup.scan_upload_dir(config.UPLOAD_DIR)
    known = set()
    for pair in status["pairs"]:
        known.add(pair["mdf"])
        if pair.get("ldf"):
            known.add(pair["ldf"])
    known.update(status["orphans"])
    return known


@app.route("/uploads/status")
def uploads_status():
    """Read-only stats used to populate the flush confirmation dialog."""
    return jsonify(staging_cleanup.scan_upload_dir(config.UPLOAD_DIR))


@app.route("/uploads/remove", methods=["POST"])
def uploads_remove():
    if not _csrf_valid():
        abort(400, description="Invalid CSRF token.")
    names = request.form.getlist("names")
    # derive targets server-side from the known staged list only
    known = _known_staged_names()
    safe = []
    for name in names:
        if name in known:
            safe.append(name)
    if not safe:
        flash("Nothing to remove (no matching staged file).", "warning")
        return redirect(url_for("index"))
    result = staging_cleanup.move_to_trash(config.UPLOAD_DIR, safe)
    _report_cleanup(result)
    if result["moved"]:
        flash(f"Remove: moved {len(result['moved'])} staged file(s) to the staging trash. "
              f"Attached databases and exports are unaffected.", "success")
    return redirect(url_for("index"))


@app.route("/uploads/flush", methods=["POST"])
def uploads_flush():
    if not _csrf_valid():
        abort(400, description="Invalid CSRF token.")
    files = staging_cleanup.list_catalog_files(config.UPLOAD_DIR)
    if not files:
        flash("Staging area is already empty.", "info")
        return redirect(url_for("index"))
    pre_sizes = {
        n: os.path.getsize(os.path.join(config.UPLOAD_DIR, n))
        for n in files
        if os.path.exists(os.path.join(config.UPLOAD_DIR, n))
    }
    result = staging_cleanup.move_to_trash(config.UPLOAD_DIR, files)
    _report_cleanup(result)
    reclaimed = sum(pre_sizes.get(n, 0) for n in result["moved"]) / 1024.0
    flash(
        f"Cleared {len(result['moved'])} staged file(s) "
        f"({reclaimed / 1024:.2f} MiB) into the staging trash. "
        f"Attached databases and exports are unaffected.",
        "success",
    )
    return redirect(url_for("index"))


@app.route("/uploads/purge", methods=["POST"])
def uploads_purge():
    if not _csrf_valid():
        abort(400, description="Invalid CSRF token.")
    try:
        result = staging_cleanup.purge_trash(config.UPLOAD_DIR)
    except staging_cleanup.StagingCleanupError as e:
        flash(f"Purge failed: {e}", "danger")
        return redirect(url_for("index"))
    flash(
        f"Purged {result['purged']} item(s) from the staging trash "
        f"({result['bytes'] / 1024:.2f} KiB reclaimed).", "success"
    )
    return redirect(url_for("index"))


@app.route("/exports/clear", methods=["POST"])
def exports_clear():
    """Move every finished export into exports/.trash (recoverable).

    The targets are re-derived from the export directory on the server, never
    taken from the browser. Attached databases and the staging area are
    untouched: the files here are finished copies for Advance Steel's import.
    """
    if not _csrf_valid():
        abort(400, description="Invalid CSRF token.")
    files = staging_cleanup.list_catalog_files(config.EXPORT_DIR)
    if not files:
        flash("There are no exports to clear.", "info")
        return redirect(url_for("index"))
    result = staging_cleanup.move_to_trash(config.EXPORT_DIR, files)
    _report_cleanup(result)
    status = staging_cleanup.scan_upload_dir(config.EXPORT_DIR)
    flash(
        f"Cleared {len(result['moved'])} export file(s) into exports/.trash "
        f"({status['trash']['bytes'] / 1048576:.2f} MiB held). Nothing attached "
        f"was touched; purge the trash to reclaim the space.",
        "success",
    )
    return redirect(url_for("index"))


@app.route("/exports/purge", methods=["POST"])
def exports_purge():
    """Permanently delete exports/.trash. The point of no return for exports."""
    if not _csrf_valid():
        abort(400, description="Invalid CSRF token.")
    try:
        result = staging_cleanup.purge_trash(config.EXPORT_DIR)
    except staging_cleanup.StagingCleanupError as e:
        flash(f"Purge failed: {e}", "danger")
        return redirect(url_for("index"))
    flash(
        f"Purged {result['purged']} item(s) from the export trash "
        f"({result['bytes'] / 1048576:.2f} MiB reclaimed).", "success"
    )
    return redirect(url_for("index"))


def _report_cleanup(result):
    """Flash warnings for missing/rejected files (success is reported by the
    individual routes with their precise moved counts)."""
    missing = result.get("missing") or []
    rejected = result.get("rejected") or []
    if missing:
        flash(f"{len(missing)} file(s) were already missing ({', '.join(missing)}).", "warning")
    if rejected:
        flash(f"{len(rejected)} target(s) were not removed "
              f"({', '.join(r['name'] for r in rejected)}).", "danger")


@app.route("/upload", methods=["POST"])
def upload():
    saved = []
    for field in ("mdf_file", "ldf_file"):
        f = request.files.get(field)
        if f and f.filename:
            filename = secure_filename(f.filename)
            f.save(os.path.join(config.UPLOAD_DIR, filename))
            saved.append(filename)
    if saved:
        flash(f"Uploaded: {', '.join(saved)}", "success")
    else:
        flash("No files received.", "warning")
    return redirect(url_for("index"))


@app.route("/attach", methods=["POST"])
def attach():
    base = request.form["base"]
    mdf_filename = request.form["mdf"]
    ldf_filename = request.form["ldf"]
    db_name = request.form.get("db_name") or staging.suggest_db_name(base)
    as_version = int(request.form.get("as_version") or config.ADVANCE_STEEL_VERSION)

    try:
        if not db.valid_identifier(db_name):
            raise RuntimeError(
                f"'{db_name}' isn't a valid database name — letters, numbers, "
                f"and underscores only (no spaces or hyphens)."
            )
        # Copy into the container under the DATABASE name, never the uploaded
        # file name: attaching the same upload twice under two names used to
        # point both databases at one physical mdf, which SQL Server then refuses
        # to open ("Access is denied") because the files must belong to one
        # database at a time.
        container_mdf = f"{db_name}.mdf"
        container_ldf = f"{db_name}_log.ldf"
        docker_ops.copy_into_container(
            os.path.join(config.UPLOAD_DIR, mdf_filename), container_mdf
        )
        docker_ops.copy_into_container(
            os.path.join(config.UPLOAD_DIR, ldf_filename), container_ldf
        )
        db.attach_database(db_name, container_mdf, container_ldf)
        catalog_type = db.guess_catalog_type(db_name)
        library = metadata.library_kind(mdf_filename) or ""
        metadata.set_meta(db_name, catalog_type=catalog_type, as_version=as_version,
                          library=library)
        message = f"Attached as database '{db_name}' (AS {as_version}, {catalog_type} catalog)."
        if library:
            message += (f" It came from a delivered Advance Steel library"
                        f" ({metadata.library_label(library)}), so this copy is"
                        f" read-only in Catalog Studio.")
        flash(message, "success")
    except Exception as e:
        flash(f"Attach failed: {e}", "danger")

    return redirect(url_for("index"))


@app.route("/create", methods=["POST"])
def create_catalog():
    db_name = request.form.get("db_name", "").strip()
    catalog_type = request.form.get("catalog_type")
    as_version = int(request.form.get("as_version") or config.ADVANCE_STEEL_VERSION)

    if catalog_type not in CATALOG_TEMPLATES:
        flash("Unknown catalog type.", "danger")
        return redirect(url_for("index"))

    if not db.valid_identifier(db_name):
        flash(
            f"'{db_name}' isn't a valid database name — letters, numbers, "
            f"and underscores only (no spaces or hyphens).",
            "danger",
        )
        return redirect(url_for("index"))

    template = CATALOG_TEMPLATES[catalog_type]

    try:
        db.create_empty_database(db_name)
        db.run_script(db_name, template["tables"])
        db.run_script(db_name, template["seed"])
        metadata.set_meta(db_name, catalog_type=catalog_type, as_version=as_version)
        flash(
            f"Created '{db_name}' as a new {template['label']} (AS {as_version}), "
            f"seeded with baseline lookup data.",
            "success",
        )
        return redirect(url_for("show_database", database=db_name))
    except Exception as e:
        flash(f"Create failed: {e}", "danger")
        return redirect(url_for("index"))


# --------------------------------------------------------------------------
# Database / table browsing
# --------------------------------------------------------------------------

@app.route("/db/<database>")
def show_database(database):
    tables = db.list_tables(database)
    counts = {t: db.get_row_count(database, t) for t in tables}
    meta = metadata.get(database)
    catalog_type = meta.get("catalog_type") or db.guess_catalog_type(database)
    diameters = db.get_catalog_diameters(database)
    return render_template(
        "database.html", database=database, tables=tables, counts=counts, meta=meta,
        diameters=diameters, catalog_type=catalog_type,
        snapshot_list=snapshots.snapshot_files(database),
        snapshot_keep=snapshots.DEFAULT_KEEP,
        library_label=metadata.library_label(meta.get("library")),
        write_blocked=_library_block(database),
    )


@app.route("/db/<database>/snapshots/prune", methods=["POST"])
def prune_snapshots(database):
    """Keep the newest N pre-change snapshots and delete the rest."""
    if not _csrf_valid():
        abort(400, description="Invalid CSRF token.")
    try:
        keep = int(request.form.get("keep") or snapshots.DEFAULT_KEEP)
    except ValueError:
        keep = snapshots.DEFAULT_KEEP
    keep = max(1, min(keep, 50))
    try:
        result = snapshots.prune_snapshots(database, keep)
    except Exception as e:
        flash(f"Snapshot cleanup failed: {e}", "danger")
    else:
        if result["removed"]:
            flash(
                f"Kept the newest {result['kept']} snapshot(s) for '{database}' and "
                f"removed {len(result['removed'])} ({result['bytes_freed']} bytes).",
                "success",
            )
        else:
            flash(f"Nothing to prune: {result['kept']} snapshot(s) kept.", "info")
    return redirect(url_for("show_database", database=database))


@app.route("/db/<database>/health")
def catalog_health(database):
    """Read-only health report for the detected catalog type.

    Aggregates the checks that already live in the per-type modules (bolt
    diameter coverage, anchor pairing/hardware, shear-stud completeness,
    drawing-style references). It reports; it never repairs.
    """
    try:
        report = health.build_report(database)
    except Exception as e:
        flash(f"Could not build the health report: {e}", "danger")
        return redirect(url_for("show_database", database=database))
    return render_template("catalog_health.html", database=database, report=report)


def _health_report_or_400(database):
    if not db.valid_identifier(database):
        abort(400, description="Invalid database name.")
    try:
        return health.build_report(database)
    except Exception as e:
        abort(503, description=f"Could not build the health report: {e}")


@app.route("/db/<database>/health.json")
def catalog_health_json(database):
    """Download the health report as JSON (read-only, same checks as the page)."""
    report = _health_report_or_400(database)
    payload = json.dumps(report, indent=2, sort_keys=False)
    return Response(
        payload,
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{database}-health.json"',
        },
    )


@app.route("/db/<database>/health.csv")
def catalog_health_csv(database):
    """Download the findings as CSV (one row per finding)."""
    report = _health_report_or_400(database)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["severity", "area", "code", "table", "message"])
    for item in report["findings"]:
        writer.writerow([
            item["severity"], item["area"], item["code"],
            item.get("table") or "", item["message"],
        ])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{database}-health.csv"',
        },
    )


# --------------------------------------------------------------------------
# Catalog comparison (read-only)
# --------------------------------------------------------------------------

@app.route("/compare")
def compare_catalogs():
    """Side-by-side table/diameter comparison of two attached databases."""
    name_a = request.args.get("a", "").strip()
    name_b = request.args.get("b", "").strip()
    try:
        attached = sorted(db.list_databases())
    except Exception as e:
        flash(f"Could not list the attached databases: {e}", "danger")
        attached = []

    result = None
    if name_a and name_b:
        if name_a not in attached or name_b not in attached:
            flash("Pick two attached databases to compare.", "warning")
        elif name_a == name_b:
            flash("Pick two different databases.", "warning")
        else:
            try:
                result = compare.build_comparison(name_a, name_b)
            except Exception as e:
                flash(f"Comparison failed: {e}", "danger")

    return render_template(
        "compare.html", attached=attached, name_a=name_a, name_b=name_b,
        result=result, meta=metadata.all_meta(),
    )


# --------------------------------------------------------------------------
# Detail diff (issue #15, Phase 1: read-only hand-edit report)
# --------------------------------------------------------------------------

def _style_databases():
    """Attached databases that look like drawing-style exports."""
    if not docker_ops.container_is_running():
        return []
    try:
        return sorted(name for name in db.list_databases()
                      if db.guess_catalog_type(name) == "drawing style")
    except Exception:
        return []


@app.route("/detail-diff", methods=["GET", "POST"])
def detail_diff():
    """Compare two DXF exports of one detail and report the hand edits."""
    style_databases = _style_databases()
    report = None
    error = None
    selected = ""
    if request.method == "POST":
        before_file = request.files.get("before")
        after_file = request.files.get("after")
        selected = request.form.get("style_db", "").strip()
        try:
            if (not before_file or not after_file
                    or not before_file.filename or not after_file.filename):
                raise dxf_compare.DxfError("Choose a before DXF and an after DXF.")
            for upload in (before_file, after_file):
                if not upload.filename.lower().endswith(".dxf"):
                    raise dxf_compare.DxfError(
                        f"'{upload.filename}' is not a .dxf file. Export an ASCII DXF.")
            before_data = before_file.read(dxf_compare.MAX_DXF_BYTES + 1)
            after_data = after_file.read(dxf_compare.MAX_DXF_BYTES + 1)
            for upload, data in ((before_file, before_data), (after_file, after_data)):
                if len(data) > dxf_compare.MAX_DXF_BYTES:
                    raise dxf_compare.DxfError(
                        f"'{upload.filename}' is larger than 64 MB.")
            style_model = None
            style_graph = None
            index = []
            if selected:
                if selected not in style_databases:
                    flash("That style database is not attached; the DXFs were "
                          "compared without it.", "warning")
                    selected = ""
                else:
                    try:
                        style_model = drawing_styles.style_tree(selected)
                        index.extend(dxf_compare.load_request_library(selected))
                        style_graph = style_usage.load_graph(selected)
                    except Exception as exc:
                        flash(f"Could not read the style export '{selected}': {exc}",
                              "warning")
                        style_model = None
                        style_graph = None
                        selected = ""
            report = dxf_compare.build_report(
                before_data, after_data, request_index=index,
                style_model=style_model, style_database=selected or None,
                style_graph=style_graph)
            if request.form.get("format") == "json":
                return jsonify(report)
        except dxf_compare.DxfError as exc:
            error = str(exc)
        except Exception as exc:
            error = f"Could not compare the files: {exc}"
    if request.method == "POST" and request.form.get("format") == "json" and error:
        return jsonify({"error": error}), 400
    return render_template(
        "detail_diff.html", style_databases=style_databases, selected=selected,
        report=report, error=error,
        report_json=json.dumps(report, indent=2, default=str) if report else None,
    )


# --------------------------------------------------------------------------
# Bolt-set viewer (issue #1, Phase 1: read-only graphical visualizer)
# --------------------------------------------------------------------------

@app.route("/db/<database>/bolt-set-viewer")
def bolt_set_viewer(database):
    """Page hosting the Three.js bolt-set visualizer (bolt catalogs only)."""
    if db.guess_catalog_type(database) != "bolt":
        flash("The bolt-set viewer only supports bolt catalogs.", "warning")
        return redirect(url_for("show_database", database=database))
    combos = bolt_sets.get_bolt_combos(database)
    if not combos:
        flash("No bolt sets found in SetOfBolts for this database.", "warning")
    return render_template(
        "bolt_set_viewer.html", database=database, combos=combos,
    )


@app.route("/db/<database>/bolt-set-viewer/payload")
def bolt_set_viewer_payload(database):
    """JSON view model for one (standard, set, material, diameter, length)."""
    try:
        diameter = float(request.args.get("diameter", ""))
        length_arg = request.args.get("length", "")
        length = float(length_arg) if length_arg else None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "diameter/length must be numbers."}), 400

    standard = request.args.get("standard", "")
    set_name = request.args.get("set", "")
    material = request.args.get("material", "")
    if not (standard and set_name and material):
        return jsonify({"ok": False, "error": "standard, set, and material are required."}), 400

    try:
        lengths = bolt_sets.get_bolt_lengths(database, standard, material, diameter)
        if length is None or length not in lengths:
            length = lengths[0] if lengths else None
        if length is None:
            return jsonify({
                "ok": False,
                "error": f"No SetBolts lengths found for {standard} / {material} / {diameter} mm.",
            })
        view = bolt_sets.bolt_set_view(
            database, standard, set_name, material, diameter, length
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    if view.get("ok"):
        view["profile_svg"] = bolt_profile.profile_svg(view)
    return jsonify(view)


@app.route("/db/<database>/bolt-set-viewer/sketch", methods=["POST"])
def bolt_set_viewer_sketch(database):
    """Re-draw the 2D profile for the browser's current (unsaved) layout."""
    payload = request.get_json(silent=True) or {}
    token = str(payload.get("csrf_token") or "")
    if not token or token != session.get("_csrf"):
        abort(400, description="Invalid CSRF token.")
    return Response(
        bolt_profile.profile_svg(bolt_profile.sanitize_layout(payload)),
        mimetype="image/svg+xml",
    )


# --------------------------------------------------------------------------
# Anchor configurator (graphical viewer, same patterns as the bolt viewer)
# --------------------------------------------------------------------------

@app.route("/db/<database>/anchor-configurator")
def anchor_configurator(database):
    """Page hosting the graphical anchor viewer (anchor catalogs only)."""
    if db.guess_catalog_type(database) != "anchor":
        flash("The anchor configurator only supports anchor catalogs.", "warning")
        return redirect(url_for("show_database", database=database))
    options = anchor_sets.get_anchor_options(database)
    if not options:
        flash("No anchors found in AnchorsName for this database.", "warning")
    return render_template(
        "anchor_configurator.html", database=database, options=options,
    )


@app.route("/db/<database>/anchor-configurator/payload")
def anchor_configurator_payload(database):
    """JSON view model for one (anchor, definition/length) selection."""
    try:
        anchor_id = int(request.args.get("anchor_id", ""))
        def_id = int(request.args.get("def_id", ""))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "anchor_id and def_id must be integers."}), 400
    try:
        lengths = anchor_sets.get_anchor_lengths(database, anchor_id)
        if not lengths:
            return jsonify({
                "ok": False,
                "error": "No AnchorsDefinition length variants found for that anchor.",
            })
        if def_id not in [l["def_id"] for l in lengths]:
            def_id = lengths[0]["def_id"]
        view = anchor_sets.anchor_view(database, anchor_id, def_id)
        view["available_lengths"] = lengths
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify(view)


# --------------------------------------------------------------------------
# Shear-stud (connector) browser (issue #4, read-only first slice)
# --------------------------------------------------------------------------


@app.route("/db/<database>/shear-stud-browser")
def shear_stud_browser(database):
    """Family / grade / diameter / length browser for connector catalogs.

    Read-only: the page only reads the Connector* tables plus SetBolts. The
    observed schema is not yet verified against a live Advance Steel install,
    so no editing or cloning is offered here.
    """
    if db.guess_catalog_type(database) != "shear stud":
        flash("The shear-stud browser only supports shear-stud (connector) catalogs.", "warning")
        return redirect(url_for("show_database", database=database))

    try:
        model = shear_studs.get_browser_model(database)
    except Exception as e:
        flash(f"Could not read the connector tables: {e}", "danger")
        return redirect(url_for("show_database", database=database))

    selections = {
        "standard": request.args.get("standard", "").strip(),
        "material": request.args.get("material", "").strip(),
        "diameter": request.args.get("diameter", "").strip(),
        "length": request.args.get("length", "").strip(),
    }
    units = shear_studs.normalize_units(request.args.get("units"))
    filters = {}
    for name in ("diameter", "length"):
        raw = selections[name]
        if not raw:
            filters[name] = None
            continue
        value = shear_studs.to_float(raw)
        if value is None:
            flash(f"Ignored {name} filter {raw!r}: not a number.", "warning")
            selections[name] = ""
        filters[name] = value

    groups = shear_studs.filter_groups(
        model["groups"],
        standard=selections["standard"] or None,
        material=selections["material"] or None,
        diameter=filters["diameter"],
        length=filters["length"],
    )
    issues = shear_studs.collect_issues(groups, model["global_issues"])

    return render_template(
        "shear_stud_browser.html",
        database=database,
        families=model["families"],
        groups=groups,
        issues=issues,
        summary=shear_studs.summarize(groups, issues),
        options=model["options"],
        selections=selections,
        units=units,
        number_text=shear_studs.number_text,
    )


@app.route("/db/<database>/shear-stud-browser/clone-preview", methods=["POST"])
def shear_stud_clone_preview(database):
    """Preview the rows an "add stud diameter" clone would need.

    Preview only: the plan is generated in memory and rendered with the issues
    that block it. No SQL is written and there is no apply action, because the
    connector schema is not yet verified against a live Advance Steel install.
    """
    if db.guess_catalog_type(database) != "shear stud":
        flash("The shear-stud browser only supports shear-stud (connector) catalogs.", "warning")
        return redirect(url_for("show_database", database=database))

    try:
        model = shear_studs.get_browser_model(database)
    except Exception as e:
        flash(f"Could not read the connector tables: {e}", "danger")
        return redirect(url_for("show_database", database=database))

    form = {
        "standard": request.form.get("standard", "").strip(),
        "material": request.form.get("material", "").strip(),
        "source_diameter": request.form.get("source_diameter", "").strip(),
        "target_diameter": request.form.get("target_diameter", "").strip(),
        "lengths": request.form.get("lengths", "").strip(),
        "along": request.form.get("along", "").strip(),
        "across": request.form.get("across", "").strip(),
        "hole_tolerance": request.form.get("hole_tolerance", "").strip(),
    }
    plan = shear_studs.plan_clone(
        model["groups"],
        model["relation_keys"],
        model["diameter_keys"],
        standard=form["standard"],
        material=form["material"],
        source_diameter=form["source_diameter"],
        target_diameter=form["target_diameter"],
        lengths=form["lengths"],
        scale_geometry="scale_geometry" in request.form,
        along=form["along"],
        across=form["across"],
        hole_tolerance=form["hole_tolerance"],
    )
    return render_template(
        "shear_stud_clone.html",
        database=database,
        plan=plan,
        form=form,
        options=model["options"],
        units=shear_studs.normalize_units(request.form.get("units")),
        number_text=shear_studs.number_text,
    )


# --------------------------------------------------------------------------
# Printable anchor fabrication detail sheet (issue #2)
# --------------------------------------------------------------------------


@app.route("/db/<database>/fabrication-sheet")
def fabrication_sheet(database):
    """Dimensioned SVG fabrication detail for one anchor record (print/PDF).

    The sheet always displays dimensions in imperial inches; metric/dual
    formatting helpers stay available in utils/fabrication.py for later use.
    """
    mode = "imperial"
    page = request.args.get("page", "letter")
    if page not in fabrication.SHEET_SIZES:
        page = "letter"
    try:
        anchor_id = int(request.args.get("anchor_id", ""))
        def_id = int(request.args.get("def_id", ""))
    except (TypeError, ValueError):
        flash("Select an anchor and a length to open its detail sheet.", "warning")
        return redirect(url_for("anchor_configurator", database=database))

    view = anchor_sets.anchor_view(database, anchor_id, def_id)
    if not view.get("ok"):
        flash(view.get("error", "Could not load that anchor record."), "danger")
        return redirect(url_for("anchor_configurator", database=database))

    issues = fabrication.validate_sheet(view)
    errors = [i for i in issues if i["level"] == "error"]
    status = "draft" if errors else "released"

    title_fields = {
        "project": request.args.get("project", ""),
        "job": request.args.get("job", ""),
        "mark": request.args.get("mark", ""),
        "quantity": request.args.get("quantity", "1"),
        "prepared": request.args.get("prepared", ""),
        "checked": request.args.get("checked", ""),
        "revision": request.args.get("revision", ""),
        "sheet_no": request.args.get("sheet_no", ""),
    }

    now = datetime.datetime.now(datetime.timezone.utc)
    geo = view.get("geometry") or {}
    sel = view.get("selection") or {}
    db_meta = metadata.get(database)
    filename = fabrication.sheet_filename(
        job=title_fields["job"],
        anchor_mark=title_fields["mark"],
        standard=sel.get("standard"),
        length_mm=geo.get("length_mm"),
        diameter_mm=(view.get("anchor") or {}).get("diameter"),
        revision=title_fields["revision"] or "0",
        draft=status == "draft",
    )

    return render_template(
        "fabrication_sheet.html",
        database=database,
        mode=mode,
        page=page,
        view=view,
        issues=issues,
        status=status,
        schedule=fabrication.hardware_schedule(view),
        svg=fabrication.generate_elevation_svg(view, mode),
        title_fields=title_fields,
        provenance={
            "database": database,
            "source": f"AnchorsName.ID={sel.get('anchor_id')}, "
                      f"AnchorsDefinition.ID={sel.get('def_id')}",
            "as_version": db_meta.get("as_version"),
            "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
            "part_name": sel.get("part_name"),
        },
        filename=filename,
        sheet_sizes=fabrication.SHEET_SIZES,
    )


@app.route("/db/<database>/add-diameter", methods=["GET", "POST"])
def add_diameter(database):
    catalog_type = db.guess_catalog_type(database)
    # Shear-stud catalogs have no BoltsDiameters/SetOfBolts chain for the clone
    # engine to copy (issue #4); their write path is still unverified.
    if catalog_type == "shear stud":
        flash(
            "Bolt-diameter cloning does not apply to shear-stud catalogs yet; "
            "use the read-only shear-stud browser instead.",
            "warning",
        )
        return redirect(url_for("show_database", database=database))
    existing_diameters = db.get_catalog_diameters(database)
    meta = metadata.get(database)
    presets = db.STANDARD_DIAMETERS
    preview = None

    form_data = {
        "preset": request.values.get("preset", '3/8"'),
        "source_dia": request.values.get("source_dia", ""),
        "target_dia": request.values.get("target_dia", ""),
        "target_name": request.values.get("target_name", ""),
        "replace_from": request.values.get("replace_from", ""),
        "replace_to": request.values.get("replace_to", ""),
        "scale_dimensions": "scale_dimensions" in request.values or request.method == "GET",
        "scale_along_across": "scale_along_across" in request.values or request.method == "GET",
        "cleanup_keys": request.form.getlist("cleanup_keys") if request.method == "POST" else [],
    }

    # Default preset values on initial GET
    if request.method == "GET" and not form_data["target_dia"]:
        matched_preset = next((p for p in presets if p["fraction"] == form_data["preset"]), None)
        if matched_preset:
            form_data["target_dia"] = str(matched_preset["mm"])
            form_data["target_name"] = matched_preset["run_name"]
            form_data["replace_to"] = matched_preset["token"]

    # Default source_dia to first non-orphan diameter if empty
    if not form_data["source_dia"]:
        for d in existing_diameters:
            if not d["is_orphan"]:
                form_data["source_dia"] = str(d["key"])
                form_data["replace_from"] = d["token"]
                break

    if request.method == "POST":
        action = request.form.get("action")
        try:
            source_dia = float(form_data["source_dia"])
            target_dia = float(form_data["target_dia"])
            target_name = form_data["target_name"]
            replace_from = form_data["replace_from"].strip()
            replace_to = form_data["replace_to"].strip()
            scale_dims = form_data["scale_dimensions"]
            scale_along = form_data["scale_along_across"]
            cleanup_keys = [float(k) for k in form_data["cleanup_keys"] if k]

            include_tables = request.form.getlist("include_tables")
            if not include_tables:
                include_tables = None

            if action == "preview":
                preview = db.preview_clone_diameter(
                    database=database,
                    source_dia=source_dia,
                    target_dia=target_dia,
                    target_name=target_name,
                    replace_from=replace_from,
                    replace_to=replace_to,
                    scale_dimensions=scale_dims,
                    scale_along_across=scale_along,
                    include_tables=include_tables,
                )
            elif action == "apply":
                blocked = _blocked_write(database)
                if blocked:
                    return blocked
                try:
                    snapshot = snapshots.create_snapshot(
                        database, f"add diameter {target_dia:g} mm")
                except Exception as e:
                    flash(
                        f"Pre-change snapshot failed, so nothing was added: {e}",
                        "danger",
                    )
                    return render_template(
                        "add_diameter.html",
                        database=database,
                        catalog_type=catalog_type,
                        existing_diameters=existing_diameters,
                        presets=presets,
                        form_data=form_data,
                        preview=None,
                        meta=meta,
                    )
                counts = db.apply_clone_diameter(
                    database=database,
                    source_dia=source_dia,
                    target_dia=target_dia,
                    target_name=target_name,
                    replace_from=replace_from,
                    replace_to=replace_to,
                    scale_dimensions=scale_dims,
                    scale_along_across=scale_along,
                    include_tables=include_tables,
                    cleanup_keys=cleanup_keys,
                )
                total_new = sum(counts.values())
                summary_parts = [f"{t} ({cnt})" for t, cnt in counts.items()]
                flash(
                    f"Successfully added diameter '{target_name}' ({target_dia} mm) to {database}! "
                    f"Generated {total_new} records across {len(counts)} tables: {', '.join(summary_parts)}. "
                    f"Snapshot: {snapshot['filename']}.",
                    "success",
                )
                return redirect(url_for("show_database", database=database))
        except Exception as e:
            flash(f"Diameter operation failed: {e}", "danger")

    return render_template(
        "add_diameter.html",
        database=database,
        catalog_type=catalog_type,
        existing_diameters=existing_diameters,
        presets=presets,
        form_data=form_data,
        preview=preview,
        meta=meta,
    )


@app.route("/db/<database>/remove-diameter", methods=["GET", "POST"])
def remove_diameter(database):
    """Preview and apply removal of an existing diameter across bolt/anchor tables."""
    catalog_type = db.guess_catalog_type(database)
    if catalog_type not in ("bolt", "anchor"):
        flash(
            f"Diameter removal is only supported for bolt and anchor catalogs "
            f"(not '{catalog_type}').",
            "warning",
        )
        return redirect(url_for("show_database", database=database))

    existing_diameters = db.get_catalog_diameters(database)
    meta = metadata.get(database)
    library_label = metadata.library_label(meta.get("library"))
    selected_dia = request.values.get("diameter", "").strip()
    if not selected_dia and existing_diameters:
        selected_dia = str(existing_diameters[0]["key"])

    preview = None
    if request.method == "POST":
        action = request.form.get("action", "preview")
        try:
            dia_val = float(selected_dia)
            if action == "apply":
                blocked = _blocked_write(database)
                if blocked:
                    return blocked
                try:
                    snapshot = snapshots.create_snapshot(
                        database, f"remove diameter {dia_val:g} mm"
                    )
                except Exception as e:
                    flash(
                        f"Pre-change snapshot failed, so nothing was removed: {e}",
                        "danger",
                    )
                    try:
                        preview = db.preview_remove_diameter(database, dia_val)
                    except Exception:
                        preview = None
                    return render_template(
                        "remove_diameter.html",
                        database=database,
                        catalog_type=catalog_type,
                        existing_diameters=existing_diameters,
                        selected_dia=selected_dia,
                        preview=preview,
                        meta=meta,
                        library_label=library_label,
                    )
                counts = db.apply_remove_diameter(database, dia_val)
                total_deleted = sum(counts.values())
                non_zero = [f"{t} ({cnt})" for t, cnt in counts.items() if cnt]
                summary_str = ", ".join(non_zero) if non_zero else "0 rows"
                flash(
                    f"Removed diameter {dia_val:g} mm from {database}: "
                    f"deleted {total_deleted} row(s) ({summary_str}). "
                    f"Snapshot: {snapshot['filename']}.",
                    "success",
                )
                return redirect(url_for("show_database", database=database))
            else:
                preview = db.preview_remove_diameter(database, dia_val)
        except Exception as e:
            flash(f"Diameter removal failed: {e}", "danger")
    elif selected_dia:
        try:
            preview = db.preview_remove_diameter(database, float(selected_dia))
        except Exception as e:
            flash(f"Could not preview diameter removal: {e}", "danger")

    return render_template(
        "remove_diameter.html",
        database=database,
        catalog_type=catalog_type,
        existing_diameters=existing_diameters,
        selected_dia=selected_dia,
        preview=preview,
        meta=meta,
        library_label=library_label,
    )


@app.route("/db/<database>/find-replace", methods=["GET", "POST"])
def find_replace(database):
    find_text = request.values.get("find", "")
    replace_text = request.values.get("replace", "")
    return_to = request.values.get("return_to")
    preview = None

    if request.method == "POST":
        action = request.form.get("action")
        if find_text and action == "preview":
            preview = db.preview_find_replace(database, find_text)
            if not preview:
                flash(f"No matches found for '{find_text}'.", "warning")
            elif return_to:
                summary = "; ".join(f"{label} ({count})" for label, count in preview.items())
                flash(f"Matches for '{find_text}': {summary}", "info")
            if return_to:
                return redirect(return_to)
        elif find_text and action == "apply":
            blocked = _blocked_write(database)
            if blocked:
                return blocked
            try:
                snapshot = snapshots.create_snapshot(
                    database, f"find-replace {find_text[:20]}")
            except Exception as e:
                flash(
                    f"Pre-change snapshot failed, so nothing was replaced: {e}",
                    "danger",
                )
                return render_template(
                    "find_replace.html", database=database,
                    find_text=find_text, replace_text=replace_text, preview=None,
                )
            applied = db.apply_find_replace(database, find_text, replace_text)
            if applied:
                total = sum(applied.values())
                flash(
                    f"Replaced '{find_text}' → '{replace_text}' across "
                    f"{total} cell(s) in {len(applied)} column(s). "
                    f"Snapshot: {snapshot['filename']}.",
                    "success",
                )
            else:
                flash(f"No matches found for '{find_text}'.", "warning")
            if return_to:
                return redirect(return_to)
            find_text, replace_text = "", ""

    return render_template(
        "find_replace.html",
        database=database,
        find_text=find_text,
        replace_text=replace_text,
        preview=preview,
    )


@app.route("/db/<database>/export-copy", methods=["POST"])
def export_copy(database):
    """Write the mdf/ldf into exports/ and send the mdf to the browser.

    Detaching ends the editing session, which is wrong for the iterate loop
    (export -> import into Advance Steel -> change something -> export again).
    Taking the database offline for the copy flushes and closes its files the
    same way a detach does, so the pair is just as clean, and the database comes
    back online in a ``finally`` even when the copy fails.

    Advance Steel imports the ``.mdf`` and rebuilds the log itself, so the
    download is the mdf alone. The matching ``.ldf`` is still written to
    ``exports/`` so the dashboard can hand over the complete pair.
    """
    try:
        db.ensure_windows_file_paths(database)  # Advance Steel refuses Linux paths
        files = db.get_physical_files(database)
        if not files.get("mdf") or not files.get("ldf"):
            raise RuntimeError(f"Couldn't find the physical mdf/ldf for '{database}'.")
        mdf_name = f"{database}.mdf"
        ldf_name = f"{database}_log.ldf"
        with db.offline_database(database):
            docker_ops.copy_out_of_container(
                files["mdf"], os.path.join(config.EXPORT_DIR, mdf_name)
            )
            docker_ops.copy_out_of_container(
                files["ldf"], os.path.join(config.EXPORT_DIR, ldf_name)
            )
    except Exception as e:
        flash(f"Export failed: {e}", "danger")
        target = request.form.get("return_to", "")
        if not target.startswith(f"/db/{database}"):
            target = url_for("show_database", database=database)
        return redirect(target)

    return send_file(
        os.path.join(config.EXPORT_DIR, mdf_name),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=mdf_name,
    )


@app.route("/db/<database>/detach", methods=["POST"])
def detach(database):
    mdf_filename = f"{database}.mdf"
    ldf_filename = f"{database}_log.ldf"
    try:
        db_meta = metadata.get(database)
        # Ask SQL Server where the files really live BEFORE detaching -- the
        # physical names needn't match the database name, and docker cp needs
        # an absolute in-container path.
        db.ensure_windows_file_paths(database)  # Advance Steel refuses Linux paths
        files = db.get_physical_files(database)
        if not files.get("mdf") or not files.get("ldf"):
            raise RuntimeError(f"Couldn't find the physical mdf/ldf for '{database}'.")
        db.detach_database(database)
        docker_ops.copy_out_of_container(
            files["mdf"], os.path.join(config.EXPORT_DIR, mdf_filename)
        )
        docker_ops.copy_out_of_container(
            files["ldf"], os.path.join(config.EXPORT_DIR, ldf_filename)
        )
        as_version = db_meta.get("as_version", config.ADVANCE_STEEL_VERSION)
        flash(
            f"Detached and exported '{database}' (targeting AS {as_version}) — "
            f"ready to download and import back into Advance Steel.",
            "success",
        )
    except Exception as e:
        flash(f"Detach/export failed: {e}", "danger")
    return redirect(url_for("index"))


@app.route("/exports/<path:filename>")
def download_export(filename):
    return send_from_directory(config.EXPORT_DIR, filename, as_attachment=True)


@app.route("/db/<database>/<table>")
def show_table(database, table):
    if table not in db.list_tables(database):
        flash("Unknown table.", "danger")
        return redirect(url_for("show_database", database=database))

    columns = [c["COLUMN_NAME"] for c in db.get_columns(database, table)]
    pk_cols = db.get_primary_key_columns(database, table)

    filter_col = request.args.get("filter_col", "")
    filter_op = request.args.get("filter_op", "=")
    filter_val = request.args.get("filter_val", "")
    virtual_val = request.args.get("virtual_val", "")

    if filter_col and filter_col not in columns:
        abort(400)
    if filter_op not in ("=", "contains"):
        abort(400)

    virtual = db.VIRTUAL_FILTERS.get(table)
    virtual_values = None

    if virtual:
        virtual_values = db.get_column_values(database, virtual["join_table"], virtual["join_column"])

    if virtual and virtual_val:
        rows = db.get_rows_joined_filter(
            database, table, virtual["join_table"], virtual["local_col"],
            virtual["foreign_col"], virtual["join_column"], virtual_val,
        )
    elif filter_col and filter_val:
        rows = db.get_rows_filtered(database, table, filter_col, filter_op, filter_val)
    else:
        rows = db.get_rows(database, table)

    row_tokens = [db.make_row_token(r, pk_cols) for r in rows] if pk_cols else []

    return render_template(
        "table.html",
        database=database,
        table=table,
        columns=columns,
        rows=rows,
        row_tokens=row_tokens,
        pk_cols=pk_cols,
        style_relations=_style_relations_or_none(database),
        filter_col=filter_col,
        filter_op=filter_op,
        filter_val=filter_val,
        virtual=virtual,
        virtual_val=virtual_val,
        virtual_values=virtual_values,
    )


# --------------------------------------------------------------------------
# Row editing: add / edit / duplicate / delete
# --------------------------------------------------------------------------

@app.route("/db/<database>/<table>/add", methods=["GET", "POST"])
def add_row(database, table):
    if table not in db.list_tables(database):
        flash("Unknown table.", "danger")
        return redirect(url_for("show_database", database=database))

    columns = db.get_columns(database, table)

    if request.method == "POST":
        blocked = _blocked_write(database)
        if blocked:
            return blocked
        values = {}
        for c in columns:
            name = c["COLUMN_NAME"]
            raw = request.form.get(name, "")
            values[name] = db.coerce_value(raw, c["DATA_TYPE"])
        try:
            db.insert_row(database, table, values)
            flash("Row added.", "success")
            return redirect(url_for("show_table", database=database, table=table))
        except Exception as e:
            flash(f"Insert failed: {e}", "danger")

    return render_template(
        "row_form.html",
        database=database,
        table=table,
        columns=columns,
        row=None,
        mode="add",
    )


# --------------------------------------------------------------------------
# Drawing styles (Drawing Style Manager exports)
# --------------------------------------------------------------------------

def _style_relations_or_none(database):
    """Relations map when this db is a drawing-style export, else None."""
    try:
        if drawing_styles.is_drawing_style(database):
            return drawing_styles.load_relations(database)
    except Exception:
        pass
    return None


def _relation_options_for(database, table):
    rels = _style_relations_or_none(database)
    if not rels:
        return {}
    try:
        return drawing_styles.options_for_table(database, table, rels)
    except Exception:
        return {}


@app.route("/db/<database>/drawing-style/usage")
def drawing_style_usage(database):
    """Read-only "used by" and orphan scan for a drawing-style export.

    The analysis follows the export's own InfoTableRelations map; it invents no
    table names and never deletes or compacts anything.
    """
    if db.guess_catalog_type(database) != "drawing style":
        flash("This database isn't a drawing-style export.", "warning")
        return redirect(url_for("show_database", database=database))
    table = request.args.get("table", "").strip() or None
    token = request.args.get("token", "").strip() or None
    try:
        model = style_usage.build_page_model(database, table=table, token=token)
    except Exception as e:
        flash(f"Could not build the usage report: {e}", "danger")
        return redirect(url_for("drawing_style", database=database))
    return render_template(
        "drawing_style_usage.html", database=database, model=model,
    )


@app.route("/db/<database>/drawing-style/rename-copies", methods=["GET", "POST"])
def drawing_style_rename_copies(database):
    """Preview and rename 'Copy of ' / 'Copy (n) ' prefixes from Deep Copy (issue #16)."""
    if db.guess_catalog_type(database) != "drawing style":
        flash("This database isn't a drawing-style export.", "warning")
        return redirect(url_for("show_database", database=database))

    replacement_prefix = request.values.get("replacement_prefix", "")
    if request.method == "POST" and "table_filter_submitted" in request.form:
        include_tables = request.form.getlist("include_tables")
    else:
        include_tables = None

    lib_label = metadata.library_label(metadata.get(database).get("library"))

    if request.method == "POST" and request.form.get("action") == "apply":
        blocked = _blocked_write(database)
        if blocked:
            return blocked
        try:
            plan = drawing_styles.preview_deep_copy_rename(
                database,
                replacement_prefix=replacement_prefix,
                include_tables=include_tables,
            )
        except Exception as e:
            flash(f"Could not build the rename plan: {e}", "danger")
            return redirect(url_for("drawing_style", database=database))

        if not plan["total_rows"]:
            flash("No deep-copy prefixes matched in the selected tables.", "warning")
            return render_template(
                "drawing_style_rename.html",
                database=database,
                plan=plan,
                replacement_prefix=replacement_prefix,
                library_label=lib_label,
            )

        reason_tag = replacement_prefix.strip() or "strip"
        try:
            snapshot = snapshots.create_snapshot(
                database, f"rename deep copies ({reason_tag[:20]})"
            )
        except Exception as e:
            flash(
                f"Pre-change snapshot failed, so nothing was renamed: {e}",
                "danger",
            )
            return render_template(
                "drawing_style_rename.html",
                database=database,
                plan=plan,
                replacement_prefix=replacement_prefix,
                library_label=lib_label,
            )

        try:
            counts = drawing_styles.apply_deep_copy_rename(
                database,
                replacement_prefix=replacement_prefix,
                include_tables=include_tables,
            )
            total = sum(counts.values())
            summary_parts = [f"{t} ({cnt})" for t, cnt in counts.items()]
            action_desc = (
                f"replaced deep-copy prefixes with '{replacement_prefix.strip()}'"
                if replacement_prefix.strip()
                else "stripped deep-copy prefixes"
            )
            flash(
                f"Renamed {total} record(s) across {len(counts)} table(s) ({action_desc}): "
                f"{', '.join(summary_parts)}. Snapshot: {snapshot['filename']}.",
                "success",
            )
            return redirect(url_for("drawing_style", database=database))
        except Exception as e:
            flash(f"Deep-copy rename failed: {e}", "danger")

    try:
        plan = drawing_styles.preview_deep_copy_rename(
            database,
            replacement_prefix=replacement_prefix,
            include_tables=include_tables,
        )
    except Exception as e:
        flash(f"Could not build the rename preview: {e}", "danger")
        return redirect(url_for("drawing_style", database=database))

    return render_template(
        "drawing_style_rename.html",
        database=database,
        plan=plan,
        replacement_prefix=replacement_prefix,
        library_label=lib_label,
    )


@app.route("/db/<database>/drawing-style")
def drawing_style(database):
    if db.guess_catalog_type(database) != "drawing style":
        flash("This database isn't a drawing-style export.", "warning")
        return redirect(url_for("show_database", database=database))
    rels = drawing_styles.load_relations(database)
    tree = style_diagrams.decorate_tree(drawing_styles.style_tree(database))
    from collections import defaultdict
    options = defaultdict(lambda: defaultdict(list))
    for t, cols in drawing_styles.all_relation_options(database, rels).items():
        options[t].update(cols)
    report = drawing_styles.integrity_report(database, rels)
    scale_choices = [
        (1.0 / n, drawing_styles.scale_label(1.0 / n))
        for n in drawing_styles.STANDARD_SCALE_DENOMINATORS
    ]
    return render_template(
        "drawing_style.html", database=database, tree=tree, options=options,
        report=report, meta=metadata.get(database), scale_choices=scale_choices,
        length_cols=drawing_styles.LENGTH_COLUMNS, ftin=drawing_styles.format_ft_in,
        scale_denom=drawing_styles.scale_denominator,
        label_tokens=sorted(drawing_styles.KNOWN_FIELDS),
        label_escapes=list(drawing_styles.SYMBOL_ESCAPES),
        label_commands=["#Newline", "#Height(6.40)", "#Bold(1)", "#Underline(1)",
                        "#Color(2)", "#Italic(1)", "#Rounded", "#End"],
    )


@app.route("/db/<database>/drawing-style/save", methods=["POST"])
def drawing_style_save(database):
    blocked = _blocked_write(database)
    if blocked:
        return blocked
    edits = []
    for name, value in request.form.items():
        if not name.startswith("f::"):
            continue
        parts = name.split("::")
        if len(parts) != 4:
            continue
        _, table, token, col = parts
        original = request.form.get("o::" + "::".join(parts[1:]))
        if original is not None and original == value:
            continue  # untouched; don't round-trip floats/text needlessly
        edits.append((table, token, col, value))
    if not edits:
        flash("No changes.", "info")
    else:
        n, errors = drawing_styles.apply_field_edits(database, edits)
        if n:
            flash(f"Saved {len(edits) - len(errors)} field(s) across {n} record(s).", "success")
        for e in errors:
            flash(e, "danger")
    if request.headers.get("HX-Request"):
        return Response(render_template("_flash_oob.html"), mimetype="text/html")
    anchor = request.form.get("anchor", "")
    return redirect(url_for("drawing_style", database=database) + (f"#{anchor}" if anchor else ""))


@app.route("/db/<database>/drawing-style/rule", methods=["POST"])
def drawing_style_rule(database):
    """Representation-rule actions. Buttons post op='action:key:order'.

    An htmx request gets just that map's rules block back, so reordering or
    copying a rule keeps the page (and scroll position) intact; a plain form
    post still redirects to the rebuilt page.

    `uid` ("<view key>-<map key>") comes back with the action so the returned
    fragment keeps the same element ids: one representation map can be shared by
    several views, and each one renders its own copy of the block.
    """
    blocked = _blocked_write(database)
    if blocked:
        return blocked
    raw_op = request.form.get("op", "")
    parts = raw_op.split(":")
    map_key = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    # View key first, map key second; anything else is ignored, never echoed.
    uid = request.form.get("uid", "")
    if not uid or not all(part.isdigit() for part in uid.split("-")) or len(uid.split("-")) > 2:
        uid = None
    error = None
    try:
        action, key, order = parts
        key, order = int(key), int(order)
        if action in ("up", "down"):
            drawing_styles.move_repr_item(database, key, order, -1 if action == "up" else 1)
        elif action == "copy":
            new_order = drawing_styles.insert_repr_item_after(database, key, order)
            flash(f"Rule copied to position {new_order}.", "success")
        elif action == "delete":
            db.delete_row(database, "DetObjReprMapItems", {"Key": key, "Order": order})
            drawing_styles.compact_repr_orders(database, key)
            flash("Rule deleted.", "success")
        elif action == "renumber":
            drawing_styles.compact_repr_orders(database, key)
            flash("Rule order renumbered.", "success")
        else:
            raise ValueError(f"unknown action {action!r}")
    except Exception as e:
        error = f"Rule change failed: {e}"
        flash(error, "danger")

    if request.headers.get("HX-Request"):
        flash_html = render_template("_flash_oob.html")
        if map_key is None:
            return Response(flash_html, mimetype="text/html")
        block = drawing_styles.repr_block(
            database, map_key, _style_relations_or_none(database), uid=uid)
        rules_html = render_template(
            "_drawing_rules.html", database=database, block=block,
            options=block["options"], rule_error=error,
            ftin=drawing_styles.format_ft_in,
        )
        return Response(rules_html + flash_html, mimetype="text/html")
    # No-JS fallback: land on the rules screen of the view that sent the action.
    view_key = uid.split("-")[0] if uid and "-" in uid else None
    anchor = f"#pane-rules-{view_key}" if view_key else f"#pane-rules-{map_key or ''}"
    return redirect(url_for("drawing_style", database=database) + anchor)


@app.route("/db/<database>/drawing-style/label-preview", methods=["POST"])
def drawing_style_label_preview(database):
    content = request.form.get("content", "")
    return render_template("_label_preview.html", p=drawing_styles.parse_label_format(content))


@app.route("/db/<database>/drawing-style/diagram", methods=["POST"])
def drawing_style_diagram(database):
    """Re-draw one schematic figure from the form's current (unsaved) values."""
    if not _csrf_valid():
        abort(400, description="Invalid CSRF token.")
    table = request.form.get("table", "")
    points = [p for p in request.form.get("points", "").split("\n") if p]
    try:
        svg = style_diagrams.diagram(
            request.form.get("kind", ""),
            style_diagrams.row_from_form(table, request.form.items()),
            points,
        )
    except ValueError as e:
        return Response(f'<div class="sd-note">{e}</div>', mimetype="text/html")
    return Response(svg, mimetype="text/html")


def _resolve_row(database, table, pk_val):
    """(pk_cols, pk dict) for a row token, or (None, error message)."""
    pk_cols = db.get_primary_key_columns(database, table)
    if not pk_cols:
        return None, "No primary key column found — this table is read only here."
    try:
        return pk_cols, db.parse_row_token(pk_val, pk_cols)
    except ValueError as e:
        return None, str(e)


@app.route("/db/<database>/<table>/<pk_val>/edit", methods=["GET", "POST"])
def edit_row(database, table, pk_val):
    if table not in db.list_tables(database):
        flash("Unknown table.", "danger")
        return redirect(url_for("show_database", database=database))

    pk_cols, pk = _resolve_row(database, table, pk_val)
    if pk_cols is None:
        flash(pk, "warning")
        return redirect(url_for("show_table", database=database, table=table))

    columns = db.get_columns(database, table)

    if request.method == "POST":
        blocked = _blocked_write(database)
        if blocked:
            return blocked
        updates = {}
        for c in columns:
            name = c["COLUMN_NAME"]
            if name in pk_cols:
                continue
            raw = request.form.get(name, "")
            updates[name] = db.coerce_value(raw, c["DATA_TYPE"])
        try:
            db.update_row(database, table, pk, updates)
            flash("Row updated.", "success")
        except Exception as e:
            flash(f"Update failed: {e}", "danger")
        return redirect(request.form.get("return_to") or url_for("show_table", database=database, table=table))

    row = db.get_row(database, table, pk)
    if row is None:
        flash("Row not found (or key matched more than one row).", "warning")
        return redirect(url_for("show_table", database=database, table=table))
    return render_template(
        "row_form.html",
        database=database,
        table=table,
        columns=columns,
        row=row,
        mode="edit",
        pk_cols=pk_cols,
        relation_options=_relation_options_for(database, table),
        return_to=request.args.get("return_to", ""),
    )


@app.route("/db/<database>/<table>/<pk_val>/duplicate", methods=["POST"])
def duplicate_row_route(database, table, pk_val):
    blocked = _blocked_write(database)
    if blocked:
        return blocked
    pk_cols, pk = _resolve_row(database, table, pk_val)
    if pk_cols is None:
        flash(pk, "warning")
        return redirect(url_for("show_table", database=database, table=table))
    try:
        new_pk = db.duplicate_row(database, table, pk_cols, pk)
        if new_pk is not None:
            label = ", ".join(f"{k}={v}" for k, v in new_pk.items())
            flash(f"Duplicated as {label}. Edit it below.", "success")
            return redirect(url_for(
                "edit_row", database=database, table=table,
                pk_val=db.make_row_token(new_pk, pk_cols),
            ))
        flash("Duplicated. New row added to the bottom of the table.", "success")
    except Exception as e:
        flash(f"Duplicate failed: {e}", "danger")
    return redirect(url_for("show_table", database=database, table=table))


@app.route("/db/<database>/<table>/<pk_val>/delete", methods=["POST"])
def delete_row_route(database, table, pk_val):
    blocked = _blocked_write(database)
    if blocked:
        return blocked
    pk_cols, pk = _resolve_row(database, table, pk_val)
    if pk_cols is None:
        flash(pk, "warning")
        return redirect(url_for("show_table", database=database, table=table))
    try:
        db.delete_row(database, table, pk)
        flash("Row deleted.", "success")
    except Exception as e:
        flash(f"Delete failed: {e}", "danger")
    return redirect(request.form.get("return_to") or url_for("show_table", database=database, table=table))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5050)
