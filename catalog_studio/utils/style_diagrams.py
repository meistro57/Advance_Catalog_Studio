# utils/style_diagrams.py
"""Schematic SVG figures for the drawing-style editor.

The editor's numbers are hard to picture: a view box is a handful of
millimetres, a scale is a reciprocal, and dimension requests are a direction
plus point names. Each figure draws *what the settings mean* using the row's
own values, and every unverified reading is called out in the figure footer.
Nothing here is Advance Steel's own rendering, so captions say "schematic".
"""

import html

from utils.drawing_styles import (
    LENGTH_COLUMNS,
    format_ft_in,
    parse_length,
    scale_denominator,
)

INK = "#212529"
MUTED = "#6c757d"
ACCENT = "#0d6efd"
PART = "#dee2e6"
KEEP = "#dbe9ff"


def _esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def _esc_text(value):
    return html.escape("" if value is None else str(value), quote=False)


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _num(value):
    """909.6, 0.0625, -1; '—' when absent, the raw text when unreadable."""
    if value is None or value == "":
        return "—"
    f = _to_float(value)
    if f is None:
        return _esc(value)
    if f == int(f):
        return str(int(f))
    return f"{f:.4g}"


def _len_text(value):
    """'609.6 mm (2'-0\")' — imperial part only when it lands on 1/16 inch."""
    f = _to_float(value)
    if f is None:
        return "—"
    text = f"{_num(f)} mm"
    ftin = format_ft_in(f)
    if ftin:
        approx = ftin.startswith("≈")
        text += f" ({'≈' if approx else ''}{ftin.lstrip('≈ ').strip()})"
    return text


def _figure(width, height, label, body):
    return (
        f'<svg class="sd-svg" viewBox="0 0 {width:g} {height:g}" role="img" '
        f'aria-label="{_esc(label)}" xmlns="http://www.w3.org/2000/svg">{body}</svg>'
    )


def _text(x, y, content, cls="sd-label", anchor="start", raw=False):
    body = content if raw else _esc_text(content)
    return (
        f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">'
        f"{body}</text>"
    )


def _line(x1, y1, x2, y2, cls="sd-rule"):
    return (
        f'<line class="{cls}" x1="{x1:.1f}" y1="{y1:.1f}" '
        f'x2="{x2:.1f}" y2="{y2:.1f}"/>'
    )


def _rect(x, y, width, height, cls="sd-part"):
    return (
        f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" '
        f'width="{width:.1f}" height="{height:.1f}"/>'
    )


def _bracket(x1, x2, y, label, cls="sd-dim"):
    return [
        _line(x1, y - 4, x1, y + 4, cls),
        _line(x2, y - 4, x2, y + 4, cls),
        _line(x1, y, x2, y, cls),
        _text((x1 + x2) / 2, y + 15, label, "sd-label-sm", "middle"),
    ]


def _short_point(name, limit=20):
    """'Grid | BottomExtreme-BottomExtreme' -> 'BottomExtreme-BottomExtr…'."""
    text = str(name or "").split(" | ")[-1].strip() or "point"
    if len(text) <= limit:
        return _esc_text(text)
    return _esc_text(text[: limit - 1].rstrip() + "…")


def scale_bar_svg(value, width=300.0, height=86.0):
    """Ruler answering "how big does this print?": one foot of model, drawn
    as paper inches at the row's 1:N scale."""
    n = scale_denominator(value)
    if not n:
        return _figure(
            width,
            height,
            "Print scale",
            _text(4, 28, f"Scale {_num(value)} is not a clean 1:N — nothing to draw.", "sd-label"),
        )
    paper_mm = 12.0 * 25.4 / n
    paper_txt = format_ft_in(paper_mm) or f"{_num(round(paper_mm / 25.4, 3))}\""
    parts = [
        _text(4, 16, f"One foot of model prints {paper_txt} wide at 1:{n}", "sd-label"),
        f'<rect class="sd-scale-bed" x="24" y="28" width="{width - 48:.1f}" height="12"/>',
    ]
    seg = (width - 48.0) / 4
    for i in range(4):
        parts.append(
            f'<rect x="{24 + i * seg:.1f}" y="28" width="{seg:.1f}" height="12" '
            f'fill="{INK if i % 2 == 0 else "#fff"}" stroke="{INK}" stroke-width="0.8"/>'
        )
    labels = ["0", '3"', '6"', '9"', "1'-0\""]
    for i, lab in enumerate(labels):
        anchor = "start" if i == 0 else ("end" if i == 4 else "middle")
        parts.append(_text(24 + i * seg, 56, lab, "sd-label-sm", anchor))
    parts.append(_text(4, 76, f"Scale 1:{n} — paper units are {n}× smaller than model", "sd-note"))
    return _figure(width, height, f"Scale bar for 1:{n}", "".join(parts))


def style_overview_svg(views, width=720.0):
    """One row per view: how large it prints, plus its rule and dimension counts."""
    views = [v for v in (views or []) if v.get("name")]
    if not views:
        return _figure(
            width,
            60,
            "Style overview",
            _text(4, 28, "This style has no view requests.", "sd-label"),
        )
    papers = []
    for v in views:
        n = scale_denominator(v.get("scale"))
        papers.append((12.0 / n) if n else 0.0)
    widest = max(papers) if papers else 0.0
    row_h = 38.0
    top = 22.0
    height = top + row_h * len(views) + 26
    parts = [
        _text(4, 12, "View", "sd-head"),
        _text(232, 12, "Paper width per foot of model", "sd-head"),
        _text(width - 92, 12, "Rules", "sd-head", "end"),
        _text(width - 4, 12, "Dims", "sd-head", "end"),
    ]
    track = 230.0
    for i, (view, paper) in enumerate(zip(views, papers)):
        y = top + i * row_h
        name = str(view["name"])
        shown = name if len(name) <= 30 else name[:29].rstrip() + "…"
        parts.append(_text(4, y + 14, shown, "sd-label"))
        parts.append(_rect(232, y + 4, track, 12, "sd-scale-bed"))
        if paper and widest:
            bar = max(6.0, track * paper / widest)
            parts.append(_rect(232, y + 4, bar, 12, "sd-overview-bar"))
            n = scale_denominator(view.get("scale"))
            paper_txt = format_ft_in(paper * 25.4) or _num(round(paper, 2))
            parts.append(_text(232 + bar + 6, y + 14, f"1:{n} · {paper_txt}", "sd-label-sm"))
        else:
            parts.append(_text(232 + 6, y + 14, "scale not a clean 1:N", "sd-label-sm"))
        parts.append(_text(width - 92, y + 14, str(view.get("rules", 0)), "sd-label-sm", "end"))
        parts.append(_text(width - 4, y + 14, str(view.get("dims", 0)), "sd-label-sm", "end"))
    parts.append(
        _text(4, height - 8, "Longer bar = that view prints larger. Rule and dimension counts are this view's own.", "sd-note")
    )
    return _figure(width, height, "Style overview", "".join(parts))


def view_box_svg(box):
    """Plan footprint (X/Y extend) beside a section through the view depth."""
    box = box or {}
    x = _to_float(box.get("xDelta"))
    y = _to_float(box.get("yDelta"))
    front = _to_float(box.get("zDeltaFront"))
    rear = _to_float(box.get("zDeltaRear"))
    parts = [
        _text(4, 14, "Plan — sideways reach", "sd-head"),
        _text(280, 14, "Depth — front / behind", "sd-head"),
    ]

    draw_x = x if x and x > 0 else 0.0
    draw_y = y if y and y > 0 else 0.0
    scale = None
    if draw_x:
        scale = 150.0 / draw_x
    if draw_y:
        sy = 96.0 / draw_y
        scale = sy if scale is None else min(scale, sy)
    if scale:
        w_px, h_px = draw_x * scale, draw_y * scale
        left, top = 120.0 - w_px / 2, 92.0 - h_px / 2
        parts += [
            _line(120 - max(w_px, 20) / 2 - 16, 92, 120 + max(w_px, 20) / 2 + 16, 92, "sd-center"),
            _line(120, 92 - max(h_px, 20) / 2 - 14, 120, 92 + max(h_px, 20) / 2 + 14, "sd-center"),
            _rect(left, top, max(w_px, 2.0), max(h_px, 2.0), "sd-box"),
            _rect(104, 83, 32, 18, "sd-part"),
            _text(120, 96, "part", "sd-label-sm", "middle"),
            _text(120, top - 18, f"X extend {_len_text(x)}", "sd-label", "middle"),
            _text(120, top + max(h_px, 2.0) + 24, f"Y extend {_len_text(y)}", "sd-label", "middle"),
        ]
    else:
        parts.append(_text(120, 96, "no XY extents (both 0)", "sd-label-sm", "middle"))

    plane = 390.0
    if (front and front > 0) or (rear and rear > 0):
        depth_scale = None
        if front and front > 0:
            depth_scale = 100.0 / front
        if rear and rear > 0:
            sr = 128.0 / rear
            depth_scale = sr if depth_scale is None else min(depth_scale, sr)
        fw = max(front * depth_scale, 3.0) if front and front > 0 else 0.0
        rw = max(rear * depth_scale, 3.0) if rear and rear > 0 else 0.0
        parts += [
            _rect(plane - fw, 78, fw + rw, 26, "sd-part"),
            f'<rect class="sd-part-dark" x="{plane - 5:.1f}" y="66" width="10" height="50"/>',
            _line(plane, 58, plane, 126, "sd-plane"),
            _text(plane, 52, "view plane", "sd-label-sm", "middle"),
        ]
        legend = []
        if fw and fw >= 90:
            parts += [
                _text(plane - fw / 2, 142, "in front", "sd-label-sm", "middle"),
                _text(plane - fw / 2, 155, _len_text(front), "sd-label", "middle"),
            ]
        elif fw:
            legend.append(f"in front {_len_text(front)}")
        if rw and rw >= 90:
            parts += [
                _text(plane + rw / 2, 142, "behind", "sd-label-sm", "middle"),
                _text(plane + rw / 2, 155, _len_text(rear), "sd-label", "middle"),
            ]
        elif rw:
            legend.append(f"behind {_len_text(rear)}")
        for i, entry in enumerate(legend):
            parts.append(_text(280, 142 + 13 * i, entry, "sd-label"))
    else:
        parts.append(_text(plane, 100, "no depth on either side (both 0)", "sd-label-sm", "middle"))

    modes = (
        f"xy mode {_num(box.get('xyMode'))} · z mode {_num(box.get('zMode'))} "
        "(AS enum numbers, labels not in this file)"
    )
    parts.append(_text(4, 180, modes, "sd-note"))
    if _truthy(box.get("EnlargeByEnv")):
        parts.append(
            _text(4, 192, f"enlarged to minimum size {_len_text(box.get('MinSizeEnv'))}", "sd-note")
        )
    else:
        parts.append(_text(4, 192, "not enlarged to a minimum size", "sd-note"))
    return _figure(520, 200, "View box schematic", "".join(parts))


def length_clip_svg(clip):
    """Where each clipping distance sits on a member."""
    clip = clip or {}
    x_on = _truthy(clip.get("X Clip"))
    y_on = _truthy(clip.get("Y Clip"))
    remaining = clip.get("MinRemainingLength")
    interval = clip.get("MinClipIntervalLength")
    extension = clip.get("Extension")
    gap = clip.get("ClippingGap")
    parts = [_text(4, 14, "What the clip distances measure", "sd-head")]
    left, right, top, height = 70.0, 460.0, 56.0, 20.0
    parts.append(_rect(left, top, right - left, height, "sd-part"))
    parts.append(_text((left + right) / 2, top + 13.5, "member", "sd-label-sm", "middle"))

    if not x_on:
        parts.append(
            _text(4, 100, "X clip is off — no break lines in X, so these distances never apply.", "sd-label")
        )
    else:
        c0, c1 = 170.0, 370.0
        parts += [
            _rect(c0, top, c1 - c0, height, "sd-keep"),
            _line(c0, top - 14, c0, top + height + 14, "sd-plane"),
            _line(c1, top - 14, c1, top + height + 14, "sd-plane"),
            _text(c0, top - 18, "clip line", "sd-label-sm", "middle"),
            _text(c1, top - 18, "clip line", "sd-label-sm", "middle"),
            *_bracket(c0, c1, 104, f"MinClipIntervalLength {_len_text(interval)}"),
            *_bracket(left, c0, 138, f"MinRemainingLength {_len_text(remaining)}"),
        ]

    ext = _to_float(extension)
    if ext is None:
        ext_note = "Extension —"
    elif ext < 0:
        ext_note = f"Extension {_num(ext)} — negative sentinel, meaning unconfirmed"
    else:
        ext_note = f"Extension {_len_text(ext)}"
    parts.append(
        _text(
            4,
            168,
            f"X clip {'on' if x_on else 'off'} · Y clip {'on' if y_on else 'off'} · "
            f"ClippingGap {_num(gap)} (units unverified) · {ext_note}",
            "sd-note",
        )
    )
    parts.append(
        _text(4, 181, "Which distance AS applies at a member end is unverified; the bar just shows where each column sits.", "sd-note")
    )
    return _figure(520, 190, "Length clipping schematic", "".join(parts))


def dimension_svg(linear, points=()):
    """The dimension chain: which axis it runs along, above or below, and how
    many points get chained."""
    linear = linear or {}
    direction = 1 if str(linear.get("Direction", "0")).strip() == "1" else 0
    above = _truthy(linear.get("ArrangeAbove"))
    count = int(_to_float(linear.get("Number of Points")) or len(points) or 0)
    names = list(points or ())
    label_names = count <= 4 and len(names) >= count

    parts = [
        _text(
            4,
            14,
            f"{'X' if direction == 0 else 'Y'}-direction chain, {count} point(s), "
            f"{'above' if above else 'below'} the part",
            "sd-head",
        )
    ]

    def tick_label(index, x, y, anchor):
        if label_names and index < len(names):
            return (
                f'<text class="sd-label-sm" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">'
                f"<title>{_esc(names[index])}</title>{_short_point(names[index], 18)}</text>"
            )
        return _text(x, y, str(index + 1), "sd-label-sm", anchor)

    if direction == 0:
        px0, px1, py0 = 70.0, 450.0, 80.0
        parts.append(_rect(px0, py0, px1 - px0, 26, "sd-part"))
        chain_y = 54.0 if above else 134.0
        parts.append(_line(px0 - 6, chain_y, px1 + 6, chain_y, "sd-dim"))
        xs = [px0] if count < 2 else [px0 + i * (px1 - px0) / (count - 1) for i in range(count)]
        for i, tx in enumerate(xs):
            parts.append(_line(tx, chain_y - 6, tx, chain_y + 6, "sd-dim"))
            anchor = "start" if i == 0 else ("end" if i == count - 1 else "middle")
            ty = chain_y - 10 if above else chain_y + 18
            parts.append(tick_label(i, tx, ty, anchor))
    else:
        py0, py1, px0 = 40.0, 128.0, 220.0
        parts.append(_rect(px0, py0, 34, py1 - py0, "sd-part"))
        chain_x = 300.0 if above else 160.0
        parts.append(_line(chain_x, py0 - 6, chain_x, py1 + 6, "sd-dim"))
        ys = [py0] if count < 2 else [py0 + i * (py1 - py0) / (count - 1) for i in range(count)]
        for i, ty in enumerate(ys):
            parts.append(_line(chain_x - 6, ty, chain_x + 6, ty, "sd-dim"))
            anchor = "start" if above else "end"
            parts.append(tick_label(i, chain_x + (10 if above else -10), ty + 4, anchor))

    parts.append(
        _text(4, 154, "Direction 0 = X, 1 = Y (file values). Point names come from DetViewDimPointSelection.", "sd-note")
    )
    parts.append(
        _text(4, 166, "Whether AS calls the far side 'above' for a Y request is unverified.", "sd-note")
    )
    return _figure(520, 174, "Dimension chain schematic", "".join(parts))


def hatch_swatch_svg(settings, size=54.0):
    """Hatch sample using the preset's own angle and scale (spacing is
    relative, so two presets can be compared side by side)."""
    settings = settings or {}
    pattern = (settings.get("PatternName") or "").strip()
    angle = _to_float(settings.get("Angle")) or 0.0
    scale = _to_float(settings.get("Scale")) or 1.0
    if not pattern:
        body = (
            f'<rect x="0.5" y="0.5" width="{size - 1:g}" height="{size - 1:g}" fill="#fff" '
            f'stroke="{MUTED}" stroke-dasharray="3 2"/>'
            + _text(size / 2, size / 2 + 3, "none", "sd-label-sm", "middle")
        )
        return _figure(size, size, "No hatch", body)
    spacing = max(3.0, min(11.0, 5.0 * abs(scale)))
    pid = f"sd-hatch-{int(abs(angle) * 10)}-{int(abs(scale) * 100)}"
    body = (
        f'<defs><pattern id="{pid}" width="{spacing:.1f}" height="{spacing:.1f}" '
        f'patternUnits="userSpaceOnUse" patternTransform="rotate({-angle:.2f})">'
        f'<line x1="0" y1="0" x2="0" y2="{spacing:.1f}" stroke="{INK}" stroke-width="0.9"/>'
        f"</pattern></defs>"
        f'<rect x="0.5" y="0.5" width="{size - 1:g}" height="{size - 1:g}" '
        f'fill="url(#{pid})" stroke="{INK}" stroke-width="0.8"/>'
    )
    return _figure(size, size, f"Hatch {pattern}", body)


def row_from_form(table, items):
    """Build a pseudo row from posted form fields (`f::<table>::<token>::<col>`)."""
    lengths = LENGTH_COLUMNS.get(table, set())
    row = {}
    for name, value in items:
        if not name.startswith("f::"):
            continue
        parts = name.split("::")
        if len(parts) != 4 or parts[1] != table:
            continue
        column = parts[3]
        if column in lengths:
            try:
                row[column] = parse_length(value)
            except ValueError:
                row[column] = value
        else:
            row[column] = value
    return row


def diagram(kind, row, points=()):
    if kind == "viewbox":
        return view_box_svg(row)
    if kind == "clip":
        return length_clip_svg(row)
    if kind == "dims":
        return dimension_svg(row, points)
    if kind == "scale":
        return scale_bar_svg((row or {}).get("Scale"))
    raise ValueError(f"unknown diagram {kind!r}")


def request_diagrams(request):
    """Every figure for one view request, ready to drop into the template."""
    row = request.get("row") or {}
    sysbox = (request.get("sysbox") or {}).get("row")
    clip = (request.get("clip") or {}).get("row")
    dims = []
    for d in request.get("dims") or []:
        linear = (d.get("linear") or {}).get("row")
        if linear:
            dims.append({
                "name": linear.get("RunName") or f"request #{linear.get('Key')}",
                "points": d.get("points") or [],
                "svg": dimension_svg(linear, d.get("points") or ()),
            })
    return {
        "scale": scale_bar_svg(row.get("Scale")),
        "viewbox": view_box_svg(sysbox) if sysbox else None,
        "clip": length_clip_svg(clip) if clip else None,
        "dims": dims,
    }


def decorate_tree(tree):
    """Attach figures to a style_tree() result in place; returns the tree."""
    hatches = {e["row"].get("Key"): e["row"] for e in tree.get("libraries", {}).get("DetHatchSettings", [])}
    for master in tree.get("masters", []):
        style = master.get("style")
        if not style:
            continue
        for request in style.get("requests", []):
            if request.get("missing"):
                continue
            request["diagrams"] = request_diagrams(request)
        style["overview_svg"] = style_overview_svg([
            {
                "name": request["row"].get("RunName") or f"view {request['row'].get('Key')}",
                "scale": request["row"].get("Scale"),
                "rules": len(request.get("repr_items") or ()),
                "dims": len(request.get("dims") or ()),
            }
            for request in style.get("requests", [])
            if not request.get("missing")
        ])
    for entry in tree.get("libraries", {}).get("DetObjAppearance", []):
        row = entry["row"]
        entry["hatch_visible_svg"] = hatch_swatch_svg(hatches.get(row.get("HatchVisible")))
        entry["hatch_hidden_svg"] = hatch_swatch_svg(hatches.get(row.get("HatchHidden")))
    return tree
