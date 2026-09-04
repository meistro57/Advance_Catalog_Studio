# app.py
import datetime
import os

from flask import (
    Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
)
from werkzeug.utils import secure_filename

import config
from utils import db, docker_ops, staging, metadata, bolt_sets, anchor_sets, fabrication
from utils.schema_templates import CATALOG_TEMPLATES

app = Flask(__name__)
app.config.from_object(config)

# Dimension formatting helpers for the fabrication sheet templates.
app.jinja_env.filters["fmm"] = fabrication.format_mm
app.jinja_env.filters["fin_fraction"] = fabrication.format_in
app.jinja_env.filters["f_dim"] = fabrication.format_dim_text

os.makedirs(config.UPLOAD_DIR, exist_ok=True)
os.makedirs(config.EXPORT_DIR, exist_ok=True)


# --------------------------------------------------------------------------
# Home: upload new mdf/ldf, see staged pairs, see attached databases
# --------------------------------------------------------------------------

@app.route("/")
def index():
    staged = staging.list_staged_pairs()
    try:
        attached = db.list_databases()
    except Exception as e:
        attached = []
        flash(f"Could not reach the scratch SQL Server container: {e}", "danger")
    exports = staging.list_exports()
    container_up = docker_ops.container_is_running()
    meta = metadata.all_meta()
    return render_template(
        "index.html",
        staged=staged,
        attached=attached,
        exports=exports,
        container_up=container_up,
        meta=meta,
        catalog_types=CATALOG_TEMPLATES,
        as_versions=sorted(config.SUPPORTED_AS_VERSIONS),
        default_as_version=config.ADVANCE_STEEL_VERSION,
    )


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
        docker_ops.copy_into_container(
            os.path.join(config.UPLOAD_DIR, mdf_filename), mdf_filename
        )
        docker_ops.copy_into_container(
            os.path.join(config.UPLOAD_DIR, ldf_filename), ldf_filename
        )
        db.attach_database(db_name, mdf_filename, ldf_filename)
        catalog_type = db.guess_catalog_type(db_name)
        metadata.set_meta(db_name, catalog_type=catalog_type, as_version=as_version)
        flash(f"Attached as database '{db_name}' (AS {as_version}, {catalog_type} catalog).", "success")
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
    return jsonify(view)


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
# Printable anchor fabrication detail sheet (issue #2)
# --------------------------------------------------------------------------

DIM_MODES = ("imperial", "metric", "dual")


@app.route("/db/<database>/fabrication-sheet")
def fabrication_sheet(database):
    """Dimensioned SVG fabrication detail for one anchor record (print/PDF)."""
    mode = request.args.get("mode", "imperial")
    if mode not in DIM_MODES:
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
                    f"Generated {total_new} records across {len(counts)} tables: {', '.join(summary_parts)}.",
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
            applied = db.apply_find_replace(database, find_text, replace_text)
            if applied:
                total = sum(applied.values())
                flash(
                    f"Replaced '{find_text}' → '{replace_text}' across "
                    f"{total} cell(s) in {len(applied)} column(s).",
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


@app.route("/db/<database>/detach", methods=["POST"])
def detach(database):
    mdf_filename = f"{database}.mdf"
    ldf_filename = f"{database}_log.ldf"
    try:
        db_meta = metadata.get(database)
        db.detach_database(database)
        docker_ops.copy_out_of_container(
            f"{database}.mdf", os.path.join(config.EXPORT_DIR, mdf_filename)
        )
        docker_ops.copy_out_of_container(
            f"{database}_log.ldf", os.path.join(config.EXPORT_DIR, ldf_filename)
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
    pk_col = db.guess_primary_key(database, table)

    filter_col = request.args.get("filter_col", "")
    filter_op = request.args.get("filter_op", "=")
    filter_val = request.args.get("filter_val", "")
    virtual_val = request.args.get("virtual_val", "")

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

    return render_template(
        "table.html",
        database=database,
        table=table,
        columns=columns,
        rows=rows,
        pk_col=pk_col,
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


@app.route("/db/<database>/<table>/<pk_val>/edit", methods=["GET", "POST"])
def edit_row(database, table, pk_val):
    if table not in db.list_tables(database):
        flash("Unknown table.", "danger")
        return redirect(url_for("show_database", database=database))

    pk_col = db.guess_primary_key(database, table)
    if not pk_col:
        flash("No primary key column found — can't edit rows in this table directly.", "warning")
        return redirect(url_for("show_table", database=database, table=table))

    columns = db.get_columns(database, table)

    if request.method == "POST":
        updates = {}
        for c in columns:
            name = c["COLUMN_NAME"]
            if name == pk_col:
                continue
            raw = request.form.get(name, "")
            updates[name] = db.coerce_value(raw, c["DATA_TYPE"])
        try:
            db.update_row(database, table, pk_col, pk_val, updates)
            flash("Row updated.", "success")
        except Exception as e:
            flash(f"Update failed: {e}", "danger")
        return redirect(url_for("show_table", database=database, table=table))

    row = db.get_row(database, table, pk_col, pk_val)
    return render_template(
        "row_form.html",
        database=database,
        table=table,
        columns=columns,
        row=row,
        mode="edit",
        pk_col=pk_col,
        pk_val=pk_val,
    )


@app.route("/db/<database>/<table>/<pk_val>/duplicate", methods=["POST"])
def duplicate_row_route(database, table, pk_val):
    pk_col = db.guess_primary_key(database, table)
    if not pk_col:
        flash("No primary key column found — can't duplicate rows in this table.", "warning")
        return redirect(url_for("show_table", database=database, table=table))
    try:
        new_id = db.duplicate_row(database, table, pk_col, pk_val)
        if new_id is not None:
            flash(f"Duplicated as new {pk_col}={new_id}. Edit it below.", "success")
            return redirect(url_for("edit_row", database=database, table=table, pk_val=new_id))
        flash("Duplicated. New row added to the bottom of the table.", "success")
    except Exception as e:
        flash(f"Duplicate failed: {e}", "danger")
    return redirect(url_for("show_table", database=database, table=table))


@app.route("/db/<database>/<table>/<pk_val>/delete", methods=["POST"])
def delete_row_route(database, table, pk_val):
    pk_col = db.guess_primary_key(database, table)
    if not pk_col:
        flash("No primary key column found — can't delete rows in this table.", "warning")
        return redirect(url_for("show_table", database=database, table=table))
    try:
        db.delete_row(database, table, pk_col, pk_val)
        flash("Row deleted.", "success")
    except Exception as e:
        flash(f"Delete failed: {e}", "danger")
    return redirect(url_for("show_table", database=database, table=table))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5050)
