/* static/js/bolt-set-viewer.js
 * Read-only base Three.js visualizer + Phase 2 client-side "assembly editor"
 * for an Advance Steel bolt set (issue #1).
 *
 * The Flask payload endpoint supplies a normalized view model plus every
 * candidate SetNutsBolts record (catalog_parts). The editor lets the user
 * swap components, move them between the head side and nut side, reorder the
 * stack, and override the schematic clamped-material thickness. All edits
 * update a client-side draft rendered through static/js/bolt-set-layout.js
 * (a mirror of utils/bolt_sets.py build_layout) - nothing is written to SQL.
 *
 * Component y positions come from the shared dimension contract; this module
 * turns that into primitives without re-deriving geometry placement.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { layoutAssembly } from './bolt-set-layout.js';

const COLORS = {
    head: 0x5c6f83,
    shank: 0x9fb0c0,
    bolt: 0x8fa3b8,
    nut: 0x5b6ee1,
    washer: 0xe8a13c,
    part: 0xb48be0,
    unmatched: 0xe05d5d,
    grip: 0x38bdf8,
    centerline: 0x94a3b8,
    dimline: 0x64748b,
    highlight: 0xffe08a,
};

const DATABASE = window.BOLT_DATABASE;
const LABEL_WORLD_H = 6;           // mm height of canvas text sprites
const DIM_RIGHT_MARGIN = 46;       // world mm reserved right of the bolt axis
const DIA_TOLERANCE = 1e-6;

const $ = (id) => document.getElementById(id);
const els = {
    combo: $('comboSelect'),
    length: $('lengthSelect'),
    mode: $('modeSelect'),
    resetView: $('resetViewBtn'),
    fitView: $('fitViewBtn'),
    caption: $('sceneCaption'),
    canvasHost: $('viewer3d'),
    fallback: $('webglFallback'),
    loading: $('loadingOverlay'),
    boltInfo: $('boltInfoPanel'),
    detail: $('detailPanel'),
    rules: $('screwRulesPanel'),
    warnings: $('warningsPanel'),
    tableBody: document.querySelector('#componentTable tbody'),
    editorRows: $('editorRows'),
    editorBadge: $('editorBadge'),
    resetDraft: $('resetDraftBtn'),
    gripAuto: $('gripAutoToggle'),
    gripValue: $('gripValueInput'),
    gripResult: $('gripResultText'),
    draftNotice: $('draftNotice'),
};

let serverView = null;   // last payload from the server (original catalog state)
let draft = null;        // client-side editable copy
let display = null;      // draft run through layoutAssembly (what is rendered)
let scene, camera, renderer, controls;
let assemblyGroup;
let partMeshes = [];
let gripMesh = null;
let raycaster = new THREE.Raycaster();
let pointer = new THREE.Vector2(1e4, 1e4);
let hovered = null;
let fitNeeded = true;
const clock = new THREE.Clock();

/* ------------------------------------------------------------------ helpers */

function fmt(n) {
    if (n === null || n === undefined || Number.isNaN(Number(n))) return '\u2013';
    const v = Number(n);
    if (Math.abs(v) < 0.0001) return '0';
    return String(Math.round(v * 10000) / 10000);
}

// The catalog stores dimensions in millimetres, but the viewer displays
// inches (visible dimensions). Conversion happens here at display time only;
// every layout computation stays in mm.
const MM_PER_IN = 25.4;

function fin(mm) {
    if (mm === null || mm === undefined || Number.isNaN(Number(mm))) return '\u2013';
    return fmt(Number(mm) / MM_PER_IN);
}

function hexRadius(acrossFlats, sides = 6) {
    return acrossFlats / 2 / Math.cos(Math.PI / sides);
}

function makeLabel(text, color = '#1e293b', bg = 'rgba(255,255,255,0.92)') {
    const cw = 512, ch = 128;
    const canvas = document.createElement('canvas');
    canvas.width = cw; canvas.height = ch;
    const ctx = canvas.getContext('2d');
    ctx.font = '700 64px system-ui, sans-serif';
    const tw = ctx.measureText(text).width;
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, cw, ch);
    ctx.fillStyle = color;
    ctx.textBaseline = 'middle';
    ctx.fillText(text, (cw - tw) / 2, ch / 2 + 4);
    const tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearFilter;
    tex.colorSpace = THREE.SRGBColorSpace;
    const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true });
    const sprite = new THREE.Sprite(mat);
    const aspect = cw / ch;
    sprite.scale.set(LABEL_WORLD_H * aspect, LABEL_WORLD_H, 1);
    sprite.renderOrder = 10;
    return sprite;
}

function dimensionLine(yA, yB, x, text, group) {
    const mat = new THREE.LineBasicMaterial({ color: COLORS.dimline });
    const span = Math.abs(yB - yA);
    const tick = Math.max(2, Math.min(6, span * 0.04));
    const pts = [new THREE.Vector3(x, yA, 0), new THREE.Vector3(x, yB, 0)];
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat);
    const mkTick = (y) => {
        const p = [new THREE.Vector3(x - tick, y, 0), new THREE.Vector3(x + tick, y, 0)];
        return new THREE.Line(new THREE.BufferGeometry().setFromPoints(p), mat);
    };
    group.add(line, mkTick(yA), mkTick(yB));
    const label = makeLabel(text);
    label.position.set(x + tick * 2 + 2, (yA + yB) / 2, 0);
    group.add(label);
}

function meshPrimitive(radiusTop, radiusBottom, h, color, sides = 32) {
    const geo = new THREE.CylinderGeometry(radiusTop, radiusBottom, h, sides, 1);
    const mat = new THREE.MeshStandardMaterial({
        color, metalness: 0.35, roughness: 0.45, emissive: 0x000000,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = true;
    return mesh;
}

function geometryForPart(part) {
    const role = part.role;
    let sides = 32;
    let radius = (part.width || part.diameter * 2.2) / 2;
    if (role === 'nut' || (role === 'part' && (part.corners || 0) >= 3)) {
        sides = (part.corners || 6);
        if (sides < 3) sides = 6;
        if (sides > 12) sides = 12;
        radius = hexRadius(part.width || part.diameter * 2.2, sides);
    }
    return { radius, sides };
}

/* ------------------------------------------------------------------ scene setup */

function initScene() {
    const container = els.canvasHost;
    if (!container) return;
    try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch (e) {
        renderer = null;
    }
    if (!renderer) {
        els.fallback.classList.remove('d-none');
        return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(40, container.clientWidth / container.clientHeight, 1, 20000);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa7b4, 1.15));
    const dir = new THREE.DirectionalLight(0xffffff, 1.1);
    dir.position.set(60, 120, 90);
    scene.add(dir);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.target.set(0, 50, 0);

    assemblyGroup = new THREE.Group();
    scene.add(assemblyGroup);

    renderer.domElement.addEventListener('pointermove', onPointerMove);
    renderer.domElement.addEventListener('pointerleave', () => { pointer.set(1e4, 1e4); });
    renderer.domElement.addEventListener('click', onPointerClick);
    window.addEventListener('resize', onResize);
    renderer.setAnimationLoop(animate);
}

function onResize() {
    if (!renderer || !camera) return;
    const w = els.canvasHost.clientWidth, h = els.canvasHost.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
}

/* ------------------------------------------------------------------ model building */

function disposeObject(obj) {
    obj.traverse((node) => {
        if (node.geometry) node.geometry.dispose();
        if (node.material) {
            const mats = Array.isArray(node.material) ? node.material : [node.material];
            for (const m of mats) {
                if (m.map) m.map.dispose();
                m.dispose();
            }
        }
    });
}

function clearModel() {
    if (!assemblyGroup) return;
    if (hovered) {
        hovered.material.emissive.setHex(0x000000);
        hovered.material.emissiveIntensity = 0;
        els.canvasHost.style.cursor = 'grab';
    }
    hovered = null;
    while (assemblyGroup.children.length) {
        disposeObject(assemblyGroup.children[0]);
        assemblyGroup.remove(assemblyGroup.children[0]);
    }
    partMeshes = [];
    gripMesh = null;
}

function buildModel(view) {
    clearModel();
    if (!view || !view.ok) return;

    const bolt = view.bolt || {};
    const L = Number(bolt.length) || 0;
    const headH = Number(bolt.head_height) || 0;
    const dia = Number(bolt.diameter) || 0;
    const headBottom = -headH;
    const caption = `${view.selection.standard} / ${view.selection.set} / \u2300${fin(view.selection.diameter)} \u00d7 ${fin(view.selection.length)} in`;

    if (!assemblyGroup) {
        els.caption.textContent = caption;
        return;
    }

    // --- bolt head + shank ------------------------------------------------
    const headSides = (bolt.head_corners || 6) >= 3 ? (bolt.head_corners || 6) : 6;
    const headR = hexRadius(Number(bolt.head_width) || dia * 2.2, headSides);
    const head = meshPrimitive(headR, headR, headH, COLORS.head, headSides);
    head.position.y = headBottom + headH / 2;
    head.userData = { kind: 'bolt', label: 'Bolt head' };
    assemblyGroup.add(head);

    const shankR = Math.max(dia / 2, 0.01);
    const shank = meshPrimitive(shankR, shankR, Math.max(L, 0.01), COLORS.shank, 32);
    shank.position.y = L / 2;
    shank.userData = { kind: 'bolt', label: 'Bolt shank' };
    assemblyGroup.add(shank);

    // --- schematic grip (clamped material) --------------------------------
    const grip = view.grip || {};
    const gripH = Math.max(Number(grip.thickness) || 0, 0.01);
    const gripR = shankR * 1.9;
    const gripBottom = Number(grip.bottom) || 0;
    if (gripH > 0.01) {
        const gmat = new THREE.MeshStandardMaterial({
            color: COLORS.grip, transparent: true, opacity: 0.16,
            metalness: 0.0, roughness: 0.9, depthWrite: false, side: THREE.DoubleSide,
        });
        gripMesh = new THREE.Mesh(new THREE.CylinderGeometry(gripR, gripR, gripH, 48, 1), gmat);
        gripMesh.position.y = gripBottom + gripH / 2;
        gripMesh.userData = { kind: 'grip', label: 'Clamped material (schematic grip)' };
        gripMesh.renderOrder = 2;
        assemblyGroup.add(gripMesh);
        const ringMat = new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.9 });
        for (const y of [gripBottom, gripBottom + gripH]) {
            const pts = [];
            for (let i = 0; i <= 48; i++) {
                const a = (i / 48) * Math.PI * 2;
                pts.push(new THREE.Vector3(Math.cos(a) * gripR, y, Math.sin(a) * gripR));
            }
            assemblyGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), ringMat));
        }
    } else {
        gripMesh = null;
    }

    // --- centreline + dimension lines --------------------------------------
    const maxR = Math.max(headR, shankR, gripR, ...(view.components || []).map((p) => geometryForPart(p).radius));
    const dimX = maxR + 14;
    const dims = new THREE.Group();
    const axisTop = L + 6;
    const axisBottom = headBottom - 6;
    const dashMat = new THREE.LineDashedMaterial({ color: COLORS.centerline, dashSize: 3, gapSize: 2 });
    const axis = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, axisBottom, 0), new THREE.Vector3(0, axisTop, 0)]),
        dashMat,
    );
    axis.computeLineDistances();
    dims.add(axis);

    dimensionLine(axisBottom, axisTop, dimX, `total ${fin(L + headH)} in`, dims);
    if (gripH > 0.01) {
        dimensionLine(gripBottom, gripBottom + gripH, dimX + 24, `grip ${fin(gripH)} in`, dims);
    }
    const diaLine = new THREE.LineBasicMaterial({ color: COLORS.dimline });
    const dx = shankR;
    const dY = axisBottom - 10;
    dims.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(
        [new THREE.Vector3(-dx, dY, 0), new THREE.Vector3(dx, dY, 0)]), diaLine));
    const diaLabel = makeLabel(`\u2300 ${fin(dia)} in`);
    diaLabel.position.set(0, dY - 4.5, 0);
    dims.add(diaLabel);
    assemblyGroup.add(dims);

    // --- component parts ----------------------------------------------------
    const colorFor = (p) => (p.matched ? COLORS[p.role] || COLORS.part : COLORS.unmatched);
    for (const part of view.components || []) {
        const h = Math.max(Number(part.stack_top) - Number(part.stack_bottom), 0.05);
        const { radius, sides } = geometryForPart(part);
        const mesh = meshPrimitive(radius, radius, h, colorFor(part), sides);
        mesh.userData = { kind: 'component', part };
        const bottom = Number(part.stack_bottom);
        mesh.position.y = bottom + h / 2;
        mesh.renderOrder = 3;
        assemblyGroup.add(mesh);
        partMeshes.push({ mesh, bottom, h, top: bottom + h, part });
    }
    els.caption.textContent = caption;
    fitNeeded = true;
}

/* ------------------------------------------------------------------ exploded / assembled */

function explodeGap() {
    const L = serverView && serverView.bolt ? Number(serverView.bolt.length) : 100;
    return Math.max(6, Math.min(28, L * 0.09));
}

function partTargets(exploded) {
    if (!display || !display.ok) return;
    const grip = display.grip || {};
    const gripBottom = Number(grip.bottom) || 0;
    const gripTop = Number(grip.top) || 1e9;
    const gripH = Math.max(Number(grip.thickness) || 0, 0);

    if (!exploded) {
        for (const pm of partMeshes) pm.mesh.userData.targetBottom = pm.bottom;
        if (gripMesh) gripMesh.userData.targetBottom = gripBottom;
        return;
    }
    const gap = explodeGap();
    const bySide = { head: [], nut: [] };
    for (const pm of partMeshes) {
        const side = pm.part.side || (pm.top <= gripBottom + 0.001 ? 'head' : 'nut');
        bySide[side].push(pm);
    }
    bySide.head.sort((a, b) => a.bottom - b.bottom);
    bySide.nut.sort((a, b) => a.bottom - b.bottom);

    let cur = 0; // head stack starts directly on the head (y = 0)
    for (const pm of bySide.head) {
        cur += gap;
        pm.mesh.userData.targetBottom = cur;
        cur += pm.h;
    }
    const materialBottom = cur + (bySide.head.length ? gap : 0);
    if (gripMesh) gripMesh.userData.targetBottom = materialBottom;
    cur = materialBottom + gripH;
    for (const pm of bySide.nut) {
        cur += gap;
        pm.mesh.userData.targetBottom = cur;
        cur += pm.h;
    }
    fitNeeded = true;
}

/* ------------------------------------------------------------------ draft state */

function optionKey(p) {
    return `${p.standard}\u0001${p.material}\u0001${p.diameter}`;
}

function candidateParts(diameter) {
    const parts = (serverView && serverView.catalog_parts) || [];
    if (diameter == null) return parts;
    return parts.filter((p) => Math.abs(Number(p.diameter) - Number(diameter)) < DIA_TOLERANCE);
}

function partFromComponent(p) {
    return {
        standard: p.din, material: p.material, diameter: p.diameter, role: p.role,
        name: p.name, height: p.height, width: p.width, corners: p.corners,
        weight: p.weight, item_number: p.item_number, matched: p.matched,
    };
}

function makeDraftFromServer(view) {
    const slots = (view.components || []).map((p) => {
        const part = partFromComponent(p);
        return {
            id: `slot-${p.slot}`,
            slotNo: p.slot,
            position: p.position,
            side: p.side,
            order: p.layer,
            part,
            orig: { side: p.side, order: p.layer, part: { ...part } },
        };
    });
    return { slots, gripMode: 'auto', gripValue: 0 };
}

function normalizeOrders(d) {
    for (const side of ['head', 'nut']) {
        const members = d.slots.filter((s) => s.side === side).sort((a, b) => a.order - b.order);
        members.forEach((s, i) => { s.order = i; });
    }
}

function slotChanged(s) {
    return s.side !== s.orig.side || s.order !== s.orig.order || optionKey(s.part) !== optionKey(s.orig.part);
}

function draftDirty(d) {
    return d.slots.some(slotChanged);
}

function buildDisplay(d) {
    const bolt = serverView.bolt;
    const bySide = { head: [], nut: [] };
    for (const s of d.slots) {
        bySide[s.side].push({
            ...s.part,
            id: s.id,
            slot: s.slotNo,
            position: s.position,
            changed: slotChanged(s),
            orig_din: s.orig.part.standard,
        });
    }
    for (const side of ['head', 'nut']) bySide[side].sort((a, b) => a.order - b.order);

    const layout = layoutAssembly({
        length: Number(bolt.length) || 0,
        headHeight: Number(bolt.head_height) || 0,
        headSide: bySide.head,
        nutSide: bySide.nut,
        gripMode: d.gripMode,
        gripValue: Number(d.gripValue) || 0,
    });

    // Slot-level warnings (order: by slot number, matching the table).
    const warnings = [];
    for (const p of [...layout.parts].sort((a, b) => a.slot - b.slot)) {
        if (p.schematic_height) {
            warnings.push({
                severity: 'warning', code: 'schematic_height',
                message: `Slot ${p.slot} (${p.standard}) has no height in SetNutsBolts; a schematic thickness is used for display.`,
            });
        }
        if (!p.matched) {
            warnings.push({
                severity: p.role !== 'part' ? 'danger' : 'warning', code: 'unmatched_component',
                message: `Slot ${p.slot}: no unique SetNutsBolts record for Standard '${p.standard}', diameter ${fin(p.diameter)} in. Shown without catalog dimensions.`,
            });
        }
    }
    warnings.push(...layout.warnings);

    return {
        ok: true,
        selection: serverView.selection,
        bolt,
        components: layout.parts,
        grip: layout.grip,
        warnings,
        dirty: draftDirty(d),
    };
}

/* ------------------------------------------------------------------ info panels */

function infoRows(container, rows) {
    container.innerHTML = '';
    for (const [k, v] of rows) {
        const div = document.createElement('div');
        div.className = 'row-item d-flex justify-content-between border-bottom py-1';
        div.innerHTML = `<span class="k">${k}</span><span class="fw-semibold text-end">${v}</span>`;
        container.appendChild(div);
    }
}

function renderBoltPanel() {
    const b = serverView.bolt;
    if (!b) {
        els.boltInfo.innerHTML = '<div class="text-muted small">No matching SetBolts record.</div>';
        return;
    }
    infoRows(els.boltInfo, [
        ['Standard', b.standard || '\u2013'],
        ['Material', b.material || '\u2013'],
        ['Diameter', `${fin(b.diameter)} in`],
        ['Length (under head)', `${fin(b.length)} in`],
        ['Head', `${fin(b.head_width)} w \u00d7 ${fin(b.head_height)} h, ${b.head_corners || 6}-sided${b.head_corners_assumed ? ' *' : ''}`],
        ['Name', b.name || '\u2013'],
        ['Weight', b.weight != null ? `${fmt(b.weight)} kg` : '\u2013'],
        ['Source', 'SetBolts'],
    ]);
}

function describePart(p) {
    const rows = [
        ['Role', p.role],
        ['Slot', `DIN${p.slot}`],
        ['Standard', p.standard],
        ['Material', p.material || '\u2013'],
        ['Diameter', p.diameter != null ? `${fin(p.diameter)} in` : '\u2013'],
        ['Height', p.height != null ? `${fin(p.height)} in` : 'no record'],
        ['Width', p.width != null ? `${fin(p.width)} in` : 'no record'],
        ['Corners', p.corners != null ? String(p.corners) : 'no record'],
        ['Position field', p.position != null ? String(p.position) : '\u2013'],
    ];
    if (p.changed) {
        rows.push(['Preview', `replaced / moved in editor (original DIN${p.slot} = ${p.orig_din || p.standard})`]);
    } else {
        rows.push(['Record', p.matched ? `${p.name || p.standard} (SetNutsBolts)` : 'NO MATCH in SetNutsBolts']);
    }
    return rows;
}

function showDetail(rows) {
    if (rows) infoRows(els.detail, rows);
}

function renderWarnings(view) {
    const warnings = [...(view.warnings || [])];
    if (!view.ok) warnings.length = 0;
    els.warnings.innerHTML = '';
    if (!warnings.length) {
        els.warnings.innerHTML = '<div class="text-muted small">No warnings.</div>';
        return;
    }
    for (const w of warnings) {
        const div = document.createElement('div');
        div.className = `alert alert-${w.severity || 'info'} py-1 px-2 small`;
        div.textContent = w.message;
        els.warnings.appendChild(div);
    }
}

function renderNotes(view) {
    // Interpretation notes + bolt-rendering assumptions come from the payload.
    const notes = [...(view.assembly_notes || [])];
    if (view.bolt && view.bolt.head_corners_assumed) {
        notes.push('Bolt head corner count not recorded in SetBolts; rendered as hexagonal (6 sides) for the schematic.');
    }
    const host = $('notesPanel');
    if (!host) return;
    host.innerHTML = '';
    if (!notes.length) {
        host.innerHTML = '<div class="text-muted small">No interpretation notes.</div>';
        return;
    }
    for (const n of notes) {
        const div = document.createElement('div');
        div.className = 'alert alert-info py-1 px-2 small';
        div.textContent = n;
        host.appendChild(div);
    }
}

function renderRules(view) {
    const bands = view.screw_rules || [];
    els.rules.innerHTML = '';
    if (!bands.length) {
        els.rules.innerHTML = '<div class="text-muted small">No ScrewNew length rules for this diameter.</div>';
        return;
    }
    const active = view.active_screw_band;
    const tbl = document.createElement('table');
    tbl.className = 'table table-sm table-striped mb-0 small';
    tbl.innerHTML = '<thead><tr><th>Grip range (in)</th><th>Base length (in)</th><th>Delta (in)</th><th>Set</th></tr></thead>';
    const body = document.createElement('tbody');
    for (const band of bands) {
        const tr = document.createElement('tr');
        const isActive = active && active.grip_min === band.grip_min && active.grip_max === band.grip_max && active.base_length === band.base_length;
        if (isActive) tr.className = 'table-info';
        tr.innerHTML = [
            `<td>${fin(band.grip_min)}\u2013${fin(band.grip_max)}${isActive ? ' \u2190 grip' : ''}</td>`,
            `<td>${fin(band.base_length)}</td>`,
            `<td>${fin(band.length_delta)}</td>`,
            `<td>${band.set || '\u2013'}</td>`,
        ].join('');
        body.appendChild(tr);
    }
    tbl.appendChild(body);
    els.rules.appendChild(tbl);
    const tip = document.createElement('div');
    tip.className = 'text-muted small mt-2';
    tip.textContent = 'Grip band containing the schematic grip is highlighted. Rules drive automatic bolt-length selection in Advance Steel.';
    els.rules.appendChild(tip);
}

function renderTable(view) {
    const rows = view.components || [];
    els.tableBody.innerHTML = '';
    if (!rows.length) {
        els.tableBody.innerHTML = '<tr><td colspan="10" class="text-muted">No components defined in SetOfBolts for this set.</td></tr>';
        return;
    }
    for (const p of rows) {
        const tr = document.createElement('tr');
        const badge = !p.matched
            ? '<span class="badge bg-danger">unmatched</span>'
            : (p.changed ? '<span class="badge bg-info text-dark">preview</span>' : '<span class="badge bg-success">ok</span>');
        tr.innerHTML = [
            `<td><code>DIN${p.slot}</code></td>`,
            `<td>${p.role}</td>`,
            `<td>${p.standard}${p.changed && p.standard !== p.orig_din ? ` <span class="text-muted small" title="original: ${p.orig_din}">(orig ${p.orig_din})</span>` : ''}</td>`,
            `<td>${p.material || '\u2013'}</td>`,
            `<td class="text-end">${fin(p.diameter)}</td>`,
            `<td class="text-end">${fin(p.height)}</td>`,
            `<td class="text-end">${fin(p.width)}</td>`,
            `<td class="text-end">${p.position != null ? p.position : '\u2013'}</td>`,
            `<td>${p.name || p.standard}</td>`,
            `<td>${badge}</td>`,
        ].join('');
        els.tableBody.appendChild(tr);
    }
}

/* ------------------------------------------------------------------ picking */

function raycastMeshes() {
    raycaster.setFromCamera(pointer, camera);
    return raycaster.intersectObjects(partMeshes.map((pm) => pm.mesh), false);
}

function setHovered(mesh) {
    if (hovered === mesh) return;
    if (hovered) {
        hovered.material.emissive.setHex(0x000000);
        hovered.material.emissiveIntensity = 0;
    }
    hovered = mesh;
    if (mesh) {
        mesh.material.emissive.setHex(COLORS.highlight);
        mesh.material.emissiveIntensity = 0.4;
        showDetail(describePart(mesh.userData.part));
        els.canvasHost.style.cursor = 'pointer';
    } else {
        els.canvasHost.style.cursor = 'grab';
        showDetail(null);
        els.detail.innerHTML = '<div class="text-muted small">Hover a rendered component to identify its source record.</div>';
    }
}

function onPointerMove(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    const hits = raycastMeshes();
    setHovered(hits.length ? hits[0].object : null);
}

function onPointerClick() {
    const hits = raycastMeshes();
    if (hits.length) {
        const p = hits[0].object.userData.part;
        if (p) showDetail(describePart(p));
    }
}

/* ------------------------------------------------------------------ framing / animation */

function currentBounds() {
    let minY = 1e9, maxY = -1e9;
    if (display && display.ok && display.bolt) {
        minY = -Number(display.bolt.head_height || 0);
        maxY = Number(display.bolt.length || 0);
    }
    for (const pm of partMeshes) {
        const b = pm.mesh.userData.targetBottom != null ? pm.mesh.userData.targetBottom : pm.bottom;
        minY = Math.min(minY, b);
        maxY = Math.max(maxY, b + pm.h);
    }
    return { minY: minY - 18, maxY: maxY + 12 };
}

function frameScene() {
    if (!display || !display.ok || !renderer) return;
    const { minY, maxY } = currentBounds();
    const dia = Number(display.bolt.diameter) || 10;
    const width = Math.max(dia * 4, 90) + DIM_RIGHT_MARGIN;
    const centerY = (minY + maxY) / 2;
    const halfH = (maxY - minY) / 2;
    const halfW = width / 2;
    controls.target.set(0, centerY, 0);
    const aspect = camera.aspect || 1;
    const tan = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const dist = Math.max(halfH / tan, halfW / (aspect * tan)) * 1.18;
    camera.position.set(dist * 0.42, centerY + dist * 0.12, dist);
    controls.update();
}

function animate() {
    const dt = Math.min(clock.getDelta(), 0.05);
    if (renderer) {
        for (const pm of partMeshes) {
            const t = pm.mesh.userData.targetBottom;
            if (t != null) {
                const y = THREE.MathUtils.lerp(pm.mesh.position.y, t + pm.h / 2, 1 - Math.exp(-8 * dt));
                pm.mesh.position.y = y;
            }
        }
        if (gripMesh && gripMesh.userData.targetBottom != null) {
            const h = (gripMesh.geometry && gripMesh.geometry.parameters && gripMesh.geometry.parameters.height) || 0;
            gripMesh.position.y = THREE.MathUtils.lerp(gripMesh.position.y, gripMesh.userData.targetBottom + h / 2, 1 - Math.exp(-8 * dt));
        }
        controls.update();
        if (fitNeeded) {
            fitNeeded = false;
            frameScene();
        }
        renderer.render(scene, camera);
    }
}

/* ------------------------------------------------------------------ editor */

function renderEditor() {
    const host = els.editorRows;
    host.innerHTML = '';
    if (!draft || !draft.slots.length) {
        host.innerHTML = '<div class="text-muted small">No components to edit.</div>';
        return;
    }
    const partsByDiaCache = new Map();
    const optionsFor = (dia) => {
        if (!partsByDiaCache.has(dia)) partsByDiaCache.set(dia, candidateParts(dia));
        return partsByDiaCache.get(dia);
    };

    for (const s of draft.slots) {
        const row = document.createElement('div');
        row.className = 'editor-row';
        const changed = slotChanged(s);
        const dia = s.part.diameter != null ? s.part.diameter : (serverView.bolt.diameter);
        const opts = optionsFor(dia);
        const currentKey = s.part.matched ? optionKey(s.part) : '';

        const slotEl = document.createElement('span');
        slotEl.className = 'editor-slot';
        slotEl.innerHTML = `DIN${s.slotNo}${changed ? ' <span style="color:#d97706">&#9998;</span>' : ''}<small>${s.part.role}</small>`;

        const partSel = document.createElement('select');
        partSel.className = 'form-select form-select-sm partSelect';
        partSel.title = 'Component installed in this position (catalog SetNutsBolts records of matching size)';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = currentKey
            ? `${s.part.standard} \u00b7 ${s.part.name || ''} \u00b7 ${s.part.material} \u00b7 h ${fin(s.part.height)} \u00b7 \u2300${fin(s.part.width || s.part.diameter)} in`
            : `(no SetNutsBolts record for ${s.orig.part.standard})`;
        partSel.appendChild(placeholder);
        for (const p of opts) {
            const o = document.createElement('option');
            o.value = optionKey(p);
            o.textContent = `${p.standard} \u00b7 ${p.name || ''} \u00b7 ${p.material} \u00b7 h ${fin(p.height)} \u00b7 \u2300${fin(p.width || p.diameter)} in`;
            if (currentKey && o.value === currentKey) {
                placeholder.disabled = true;
                o.selected = true;
            }
            partSel.appendChild(o);
        }
        partSel.addEventListener('change', () => {
            if (!partSel.value) return;
            const chosen = opts.find((p) => optionKey(p) === partSel.value);
            if (chosen) {
                s.part = { ...chosen };
                commit();
            }
        });

        const sideSel = document.createElement('select');
        sideSel.className = 'form-select form-select-sm sideSelect';
        for (const [val, label] of [['nut', 'Nut end'], ['head', 'Head side']]) {
            const o = document.createElement('option');
            o.value = val;
            o.textContent = label;
            if (s.side === val) o.selected = true;
            sideSel.appendChild(o);
        }
        sideSel.title = 'Which side of the clamped material this component sits on';
        sideSel.addEventListener('change', () => {
            if (sideSel.value !== s.side) {
                s.side = sideSel.value;
                s.order = 0; // adjacent to the material on its new side
                normalizeOrders(draft);
                commit();
            }
        });

        // order within its side (bottom = adjacent to material)
        const sideList = draft.slots.filter((x) => x.side === s.side).sort((a, b) => a.order - b.order);
        const idx = sideList.indexOf(s);
        const moveBtn = (label, delta, disabled) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'btn btn-sm btn-outline-secondary';
            b.textContent = label;
            b.disabled = disabled;
            b.title = disabled ? '' : (delta < 0 ? 'Move toward the material' : 'Move outward');
            b.addEventListener('click', () => {
                const list = draft.slots.filter((x) => x.side === s.side).sort((a, b) => a.order - b.order);
                const i = list.indexOf(s);
                const other = list[i + delta];
                if (other) {
                    const tmp = s.order; s.order = other.order; other.order = tmp;
                    normalizeOrders(draft);
                    commit();
                }
            });
            return b;
        };
        const btnWrap = document.createElement('div');
        btnWrap.className = 'btn-group btn-group-sm';
        btnWrap.appendChild(moveBtn('\u2191', -1, idx <= 0));
        btnWrap.appendChild(moveBtn('\u2193', +1, idx >= sideList.length - 1));

        const meta = document.createElement('span');
        meta.className = 'editor-meta';
        meta.innerHTML = changed
            ? `&#9998; stack index ${s.order} ${s.side === 'nut' ? '(from material up)' : '(from head up)'}; original DIN${s.slotNo} = ${s.orig.part.standard} ${s.orig.part.name || ''}`
            : `stack index ${s.order} ${s.side === 'nut' ? '(from material up)' : '(from head up)'} \u00b7 catalog Position field: ${s.position != null ? s.position : '\u2013'}`;

        row.append(slotEl, partSel, sideSel, btnWrap, meta);
        host.appendChild(row);
    }
}

function commit() {
    if (!serverView) return;
    normalizeOrders(draft);
    display = buildDisplay(draft);
    display.ok = true;
    const mode = els.mode.value;
    buildModel(display);
    renderWarnings(display);
    renderTable(display);
    renderEditor();
    updateDirtyUI();
    partTargets(mode === 'exploded');
    els.detail.innerHTML = '<div class="text-muted small">Hover a rendered component to identify its source record.</div>';
}

function updateDirtyUI() {
    const dirty = display && display.dirty;
    els.editorBadge.textContent = dirty ? 'unsaved preview changes' : 'no changes';
    els.editorBadge.className = `badge ${dirty ? 'bg-warning text-dark' : 'bg-secondary'}`;
    els.resetDraft.disabled = !dirty;
    els.draftNotice.classList.toggle('d-none', !dirty);
    const grip = display ? display.grip : null;
    const modeTxt = draft.gripMode === 'fixed' ? 'fixed' : 'auto';
    els.gripResult.textContent = grip
        ? `effective grip: ${fin(grip.thickness)} in (${modeTxt})`
        : '';
}

function resetDraft() {
    if (!serverView) return;
    draft = makeDraftFromServer(serverView);
    els.gripAuto.checked = true;
    els.gripValue.disabled = true;
    els.gripValue.value = '';
    commit();
}

/* ------------------------------------------------------------------ data loading */

async function fetchPayload(params) {
    const qs = new URLSearchParams(params).toString();
    const resp = await fetch(`/db/${encodeURIComponent(DATABASE)}/bolt-set-viewer/payload?${qs}`, {
        headers: { Accept: 'application/json' },
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    if (!data.ok) throw new Error(data.error || 'view model failed');
    return data;
}

let loadSeq = 0;
async function loadSelection(preserveLength = true) {
    const comboVal = els.combo.value;
    if (!comboVal) return;
    const [standard, set, material, diameter] = comboVal.split('|');
    const seq = ++loadSeq;
    els.loading.classList.remove('d-none');
    try {
        const params = { standard, set, material, diameter };
        const wanted = preserveLength && els.length.value ? els.length.value : '';
        if (wanted) params.length = wanted;
        const view = await fetchPayload(params);
        if (seq !== loadSeq) return;

        const current = Number(view.selection.length);
        els.length.innerHTML = '';
        for (const len of view.available_lengths || []) {
            const opt = document.createElement('option');
            opt.value = len;
            opt.textContent = `${fin(len)} in`;
            if (len === current) opt.selected = true;
            els.length.appendChild(opt);
        }

        serverView = view;
        renderBoltPanel();
        renderRules(view);
        renderNotes(view);
        resetDraft();
    } catch (err) {
        if (seq !== loadSeq) return;
        els.warnings.innerHTML = `<div class="alert alert-danger py-1 px-2 small">${err.message}</div>`;
        els.caption.textContent = 'load failed';
    } finally {
        if (seq === loadSeq) els.loading.classList.add('d-none');
    }
}

/* ------------------------------------------------------------------ wiring */

function wire() {
    els.combo.addEventListener('change', () => {
        els.length.innerHTML = '';
        loadSelection(false);
    });
    els.length.addEventListener('change', () => loadSelection(true));
    els.mode.addEventListener('change', () => {
        partTargets(els.mode.value === 'exploded');
        fitNeeded = true;
    });
    els.resetView.addEventListener('click', () => frameScene());
    els.fitView.addEventListener('click', () => frameScene());
    els.resetDraft.addEventListener('click', resetDraft);

    els.gripAuto.addEventListener('change', () => {
        draft.gripMode = els.gripAuto.checked ? 'auto' : 'fixed';
        els.gripValue.disabled = els.gripAuto.checked;
        if (!els.gripAuto.checked && !els.gripValue.value) {
            const d = display ? display.grip.thickness : (serverView.grip ? serverView.grip.thickness : 0);
            els.gripValue.value = fmt(Math.max(Number(d) || 0, 0) / MM_PER_IN);
        }
        commit();
    });
    els.gripValue.addEventListener('input', () => {
        draft.gripValue = els.gripValue.value === '' ? 0 : (Number(els.gripValue.value) * MM_PER_IN);
        commit();
    });
}

initScene();

if (els.combo) {
    if (!els.combo.options.length) {
        els.caption.textContent = 'no bolt sets in this database';
        els.editorRows.innerHTML = '<div class="text-muted small">No bolt sets to edit.</div>';
    } else {
        wire();
        loadSelection(false).catch(() => {});
    }
}
