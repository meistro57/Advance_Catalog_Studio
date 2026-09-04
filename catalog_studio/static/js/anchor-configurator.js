/* static/js/anchor-configurator.js
 * Graphical anchor viewer for Advance Steel anchor catalogs. Loads a view
 * model from the Flask payload endpoint and renders the anchor as an
 * engineering schematic: rod, thread zone, concrete/surface plane, top and
 * embedded-end hardware (from AnchorsName -> SetNutsBolts), and the bottom
 * termination (plain / head / hook) from AnchorsDefinition.
 *
 * Interpretation notes and all y positions come from the server
 * (utils/anchor_sets.py); this module turns that dimension contract into
 * primitives. Visible dimensions are inches; the engine stays in millimetres.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';

const COLORS = {
    rod: 0x7c8ea3,
    thread: 0xc7d2de,
    concrete: 0xa3b18a,
    nut: 0x5b6ee1,
    washer: 0xe8a13c,
    part: 0xb48be0,
    unmatched: 0xe05d5d,
    centerline: 0x94a3b8,
    dimline: 0x64748b,
    highlight: 0xffe08a,
};

const DATABASE = window.ANCHOR_DATABASE;
const LABEL_WORLD_H = 6;
const DIM_RIGHT_MARGIN = 52;
const MM_PER_IN = 25.4;

const $ = (id) => document.getElementById(id);
const els = {
    anchor: $('anchorSelect'),
    length: $('lengthSelect'),
    mode: $('modeSelect'),
    resetView: $('resetViewBtn'),
    sheetLink: $('sheetLink'),
    caption: $('sceneCaption'),
    canvasHost: $('viewer3d'),
    fallback: $('webglFallback'),
    loading: $('loadingOverlay'),
    anchorInfo: $('anchorInfoPanel'),
    geometry: $('geometryPanel'),
    detail: $('detailPanel'),
    notes: $('notesPanel'),
    warnings: $('warningsPanel'),
    tableBody: document.querySelector('#componentTable tbody'),
};

let view = null;
let scene, camera, renderer, controls;
let assemblyGroup;
let partMeshes = [];
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

function fin(mm) {
    if (mm === null || mm === undefined || Number.isNaN(Number(mm))) return '\u2013';
    return fmt(Number(mm) / MM_PER_IN);
}

function makeLabel(text) {
    const cw = 512, ch = 128;
    const canvas = document.createElement('canvas');
    canvas.width = cw; canvas.height = ch;
    const ctx = canvas.getContext('2d');
    ctx.font = '700 64px system-ui, sans-serif';
    const tw = ctx.measureText(text).width;
    ctx.fillStyle = 'rgba(255,255,255,0.92)';
    ctx.fillRect(0, 0, cw, ch);
    ctx.fillStyle = '#1e293b';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, (cw - tw) / 2, ch / 2 + 4);
    const tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearFilter;
    tex.colorSpace = THREE.SRGBColorSpace;
    const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(LABEL_WORLD_H * (cw / ch), LABEL_WORLD_H, 1);
    sprite.renderOrder = 10;
    return sprite;
}

function dimensionLine(yA, yB, x, text, group) {
    const mat = new THREE.LineBasicMaterial({ color: COLORS.dimline });
    const span = Math.abs(yB - yA);
    const tick = Math.max(2, Math.min(6, span * 0.04));
    const pts = [new THREE.Vector3(x, yA, 0), new THREE.Vector3(x, yB, 0)];
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat);
    const mkTick = (y) => new THREE.Line(new THREE.BufferGeometry().setFromPoints(
        [new THREE.Vector3(x - tick, y, 0), new THREE.Vector3(x + tick, y, 0)]), mat);
    group.add(line, mkTick(yA), mkTick(yB));
    const label = makeLabel(text);
    label.position.set(x + tick * 2 + 2, (yA + yB) / 2, 0);
    group.add(label);
}

function cylinder(h, r, color, sides = 32, opacity = 1) {
    const mat = new THREE.MeshStandardMaterial({
        color, metalness: 0.35, roughness: 0.5,
        transparent: opacity < 1, opacity,
        emissive: 0x000000,
    });
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(r, r, Math.max(h, 0.01), sides, 1), mat);
    mesh.castShadow = true;
    return mesh;
}

function hexRadius(acrossFlats, sides = 6) {
    return acrossFlats / 2 / Math.cos(Math.PI / sides);
}

/* ------------------------------------------------------------------ scene */

function initScene() {
    try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch (e) {
        renderer = null;
    }
    if (!renderer) {
        els.fallback.classList.remove('d-none');
        return;
    }
    const host = els.canvasHost;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(host.clientWidth, host.clientHeight);
    host.appendChild(renderer.domElement);

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(40, host.clientWidth / host.clientHeight, 1, 20000);
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

function disposeObject(obj) {
    obj.traverse((node) => {
        if (node.geometry) node.geometry.dispose();
        if (node.material) {
            const mats = Array.isArray(node.material) ? node.material : [node.material];
            for (const m of mats) { if (m.map) m.map.dispose(); m.dispose(); }
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
}

/* ------------------------------------------------------------------ model */

function partGeometry(part) {
    let sides = 32;
    let radius = (part.width || part.diameter * 2.2) / 2;
    if (part.role === 'nut' || (part.role === 'part' && (part.corners || 0) >= 3)) {
        sides = Math.min(Math.max(part.corners || 6, 3), 12);
        radius = hexRadius(part.width || part.diameter * 2.2, sides);
    }
    return { radius, sides };
}

function threadRings(yFrom, yTo, r, group) {
    const mat = new THREE.LineBasicMaterial({ color: COLORS.thread });
    const step = Math.max(1.5, r * 0.9);
    let count = 0;
    for (let y = yFrom; y <= yTo && count < 90; y += step, count++) {
        const pts = [];
        for (let i = 0; i <= 24; i++) {
            const a = (i / 24) * Math.PI * 2;
            pts.push(new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r));
        }
        group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat));
    }
}

function buildHook(radius, tubeR, group) {
    // Schematic J: 180 deg bend below the rod end plus a short upward stub.
    const R = Math.max(radius, tubeR * 2);
    const pts = [];
    for (let i = 0; i <= 24; i++) {
        const a = (i / 24) * Math.PI;
        pts.push(new THREE.Vector3(R - R * Math.cos(a), -R * Math.sin(a), 0));
    }
    const stubLen = Math.min(R * 0.8, tubeR * 8);
    pts.push(new THREE.Vector3(2 * R, 0, 0), new THREE.Vector3(2 * R, stubLen, 0));
    const curve = new THREE.CatmullRomCurve3(pts);
    const geo = new THREE.TubeGeometry(curve, 64, tubeR, 12, false);
    const mat = new THREE.MeshStandardMaterial({
        color: COLORS.rod, metalness: 0.5, roughness: 0.4,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData = { kind: 'termination', label: 'Hook bend (schematic)' };
    group.add(mesh);
    return mesh;
}

function buildModel(v) {
    clearModel();
    if (!v || !v.ok) return;

    const L = Number(v.geometry.length_mm) || 0;
    const dia = Number(v.anchor.diameter) || 0;
    const rodR = Math.max(dia / 2, 0.01);
    const term = v.geometry.termination || { kind: 'plain' };
    const headH = term.kind === 'head' ? (Number(term.height) || 0) : 0;
    const caption = `${v.selection.part_name || ''} \u00b7 \u2300${fin(dia)} \u00d7 ${fin(L)} in`;

    // rod body (from top of the bottom termination to the rod tip)
    const rodBottom = headH;
    const rod = cylinder(L - rodBottom, rodR, COLORS.rod);
    rod.position.y = rodBottom + (L - rodBottom) / 2;
    rod.userData = { kind: 'rod', label: 'Anchor rod' };
    assemblyGroup.add(rod);

    // thread zone (top portion of the rod)
    const tTop = Number(v.thread.top);
    const tBottom = Math.max(Number(v.thread.bottom), rodBottom);
    if (tTop - tBottom > 0.5) {
        const th = cylinder(tTop - tBottom, rodR * 1.04, COLORS.thread, 24, 0.55);
        th.position.y = tBottom + (tTop - tBottom) / 2;
        th.userData = { kind: 'thread', label: 'Thread zone' };
        assemblyGroup.add(th);
        threadRings(tBottom, tTop, rodR * 1.12, assemblyGroup);
    }

    // concrete / surface plane
    const concY = v.concrete_y;
    if (concY !== null && concY > rodBottom && concY < L) {
        const plateW = Math.max(rodR * 9, dia * 4.5);
        const plate = new THREE.Mesh(
            new THREE.BoxGeometry(plateW, 1.2, plateW),
            new THREE.MeshStandardMaterial({
                color: COLORS.concrete, transparent: true, opacity: 0.35,
                roughness: 0.9, metalness: 0, side: THREE.DoubleSide, depthWrite: false,
            }),
        );
        plate.position.y = concY;
        plate.userData = { kind: 'concrete', label: 'Concrete / top surface' };
        assemblyGroup.add(plate);
        const edge = new THREE.LineBasicMaterial({ color: COLORS.concrete });
        const rPts = [];
        for (let i = 0; i <= 48; i++) {
            const a = (i / 48) * Math.PI * 2;
            rPts.push(new THREE.Vector3(Math.cos(a) * plateW / 2, concY, Math.sin(a) * plateW / 2));
        }
        assemblyGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(rPts), edge));
    }

    // bottom termination
    let lowestY = 0;
    if (term.kind === 'head') {
        const sides = Math.min(Math.max(term.corners || 6, 3), 12);
        const R = hexRadius(term.width || dia * 2.2, sides);
        const head = cylinder(headH, R, COLORS.rod, sides);
        head.position.y = headH / 2;
        head.userData = { kind: 'termination', label: 'Head (AnchorsDefinition)' };
        assemblyGroup.add(head);
        lowestY = 0;
    } else if (term.kind === 'hook') {
        const hookR = Number(term.hook_radius) || dia * 2;
        buildHook(hookR, rodR, assemblyGroup);
        lowestY = -hookR * 1.4;
    }

    // hardware components (top + embedded end)
    const colorFor = (p) => (p.matched ? COLORS[p.role] || COLORS.part : COLORS.unmatched);
    for (const part of v.components || []) {
        const h = Math.max(Number(part.stack_top) - Number(part.stack_bottom), 0.05);
        const { radius, sides } = partGeometry(part);
        const mesh = cylinder(h, radius, colorFor(part), sides);
        const bottom = Number(part.stack_bottom);
        mesh.position.y = bottom + h / 2;
        mesh.userData = { kind: 'component', part };
        mesh.renderOrder = 3;
        assemblyGroup.add(mesh);
        partMeshes.push({ mesh, bottom, h, side: part.side, part });
    }

    // centreline + dimension lines
    const maxR = Math.max(rodR * 1.12, ...(v.components || []).map((p) => partGeometry(p).radius));
    const dimX = maxR + 16;
    const dims = new THREE.Group();
    const axisTop = L + 6;
    const axisBottom = lowestY - 6;
    const dashMat = new THREE.LineDashedMaterial({ color: COLORS.centerline, dashSize: 3, gapSize: 2 });
    const axis = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, axisBottom, 0), new THREE.Vector3(0, axisTop, 0)]),
        dashMat,
    );
    axis.computeLineDistances();
    dims.add(axis);

    dimensionLine(axisBottom, axisTop, dimX, `total ${fin(L)} in`, dims);
    let extraDim = 0;
    if (tTop - tBottom > 0.5) {
        dimensionLine(tBottom, tTop, dimX + 26, `thread ${fin(tTop - tBottom)} in`, dims);
        extraDim += 26;
    }
    if (concY !== null && concY > rodBottom && concY < L) {
        dimensionLine(concY, L, dimX + extraDim + 26, `top ${fin(L - concY)} in`, dims);
    }
    // diameter callout near the bottom of the rod
    const dY = axisBottom - 8;
    const diaLine = new THREE.LineBasicMaterial({ color: COLORS.dimline });
    dims.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(
        [new THREE.Vector3(-rodR, dY, 0), new THREE.Vector3(rodR, dY, 0)]), diaLine));
    const diaLabel = makeLabel(`\u2300 ${fin(dia)} in`);
    diaLabel.position.set(0, dY - 4.5, 0);
    dims.add(diaLabel);
    assemblyGroup.add(dims);

    els.caption.textContent = caption;
    fitNeeded = true;
}

/* ------------------------------------------------------------------ exploded */

function partTargets(exploded) {
    if (!partMeshes.length) return;
    for (const pm of partMeshes) pm.mesh.userData.targetBottom = pm.bottom;
    if (!exploded) return;
    const gap = Math.max(6, Math.min(20, (view.geometry.length_mm || 100) * 0.06));
    const top = partMeshes.filter((p) => p.side === 'top').sort((a, b) => a.bottom - b.bottom);
    const bottom = partMeshes.filter((p) => p.side === 'bottom').sort((a, b) => a.bottom - b.bottom);
    top.forEach((pm, i) => { pm.mesh.userData.targetBottom = pm.bottom + (i + 1) * gap; });
    bottom.forEach((pm, i) => { pm.mesh.userData.targetBottom = pm.bottom - (i + 1) * gap; });
    fitNeeded = true;
}

/* ------------------------------------------------------------------ panels */

function infoRows(container, rows) {
    container.innerHTML = '';
    for (const [k, v] of rows) {
        const div = document.createElement('div');
        div.className = 'row-item d-flex justify-content-between border-bottom py-1';
        div.innerHTML = `<span class="k">${k}</span><span class="fw-semibold text-end">${v}</span>`;
        container.appendChild(div);
    }
}

function termText(term) {
    if (term.kind === 'head') {
        const sides = Math.min(Math.max(term.corners || 6, 3), 12);
        return `Head ${fin(term.width)} w \u00d7 ${fin(term.height)} h, ${sides}-sided`;
    }
    if (term.kind === 'hook') return `Hook bend, radius ${fin(term.hook_radius)} in (schematic)`;
    return 'Plain (rod) end';
}

function renderAnchorPanel(v) {
    infoRows(els.anchorInfo, [
        ['Standard', v.anchor.standard || '\u2013'],
        ['Set (SetName)', v.anchor.set_name || '\u2013'],
        ['Material', v.anchor.material || '\u2013'],
        ['Diameter', `${fin(v.anchor.diameter)} in`],
        ['Part name', v.selection.part_name || '\u2013'],
        ['NumItems', v.anchor.num_items != null ? String(v.anchor.num_items) : '\u2013'],
        ['Explodable', v.anchor.explodable ? 'yes' : 'no'],
        ['ClassID', v.anchor.class_id != null ? String(v.anchor.class_id) : '\u2013'],
        ['Weight', v.anchor.weight != null ? `${fmt(v.anchor.weight)} kg` : '\u2013'],
        ['Source', 'AnchorsName + AnchorsDefinition'],
    ]);
}

function renderGeometryPanel(v) {
    const g = v.geometry;
    const rows = [
        ['Overall length', `${fin(g.length_mm)} in`],
        ['Thread length', g.thread_length_mm != null && g.thread_length_mm > 0 ? `${fin(g.thread_length_mm)} in` : '\u2013'],
        ['Top distance', g.top_distance_mm != null && g.top_distance_mm > 0 ? `${fin(g.top_distance_mm)} in` : '\u2013'],
        ['Bottom termination', termText(g.termination)],
    ];
    for (const d of g.distances) {
        rows.push([d.label, `${fin(d.value_mm)} in`]);
    }
    infoRows(els.geometry, rows);
}

function describePart(p) {
    return [
        ['Role', p.role],
        ['Slot', `DIN${p.slot}`],
        ['End', p.side === 'top' ? 'top (surface end)' : 'embedded end'],
        ['Standard', p.din],
        ['Material', p.material || '\u2013'],
        ['Diameter', p.diameter != null ? `${fin(p.diameter)} in` : '\u2013'],
        ['Height', p.height != null ? `${fin(p.height)} in` : 'no record'],
        ['Width', p.width != null ? `${fin(p.width)} in` : 'no record'],
        ['Corners', p.corners != null ? String(p.corners) : 'no record'],
        ['Position field', p.position != null ? String(p.position) : '\u2013'],
        ['Record', p.matched ? `${p.name || p.din} (SetNutsBolts)` : 'NO MATCH in SetNutsBolts'],
    ];
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
        infoRows(els.detail, describePart(mesh.userData.part));
        els.canvasHost.style.cursor = 'pointer';
    } else {
        els.canvasHost.style.cursor = 'grab';
        els.detail.innerHTML = '<div class="text-muted small">Hover a rendered component to identify its source record.</div>';
    }
}

function onPointerMove(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(partMeshes.map((p) => p.mesh), false);
    setHovered(hits.length ? hits[0].object : null);
}

function onPointerClick() {
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(partMeshes.map((p) => p.mesh), false);
    if (hits.length && hits[0].object.userData.part) {
        infoRows(els.detail, describePart(hits[0].object.userData.part));
    }
}

function formatWarning(w) {
    switch (w.code) {
    case 'unmatched_component':
        return `Slot ${w.values.slot}: no unique SetNutsBolts record for Standard '${w.values.standard}', diameter ${fin(w.values.diameter_mm)} in.`;
    case 'schematic_height':
        return 'Some components have no height in SetNutsBolts; schematic thicknesses are used for display.';
    case 'stack_below_concrete':
        return `Top hardware stack reaches ${fin(w.values.stack_mm)} in below the concrete plane; check the TopDistance / Length interpretation.`;
    case 'thread_exceeds_length':
        return `Recorded thread length ${fin(w.values.thread_mm)} in exceeds the overall rod length ${fin(w.values.length_mm)} in; thread zone clamped to the rod.`;
    default:
        return w.message || w.code;
    }
}

function renderNotes(v) {
    els.notes.innerHTML = '';
    const notes = v.notes || [];
    if (!notes.length) {
        els.notes.innerHTML = '<div class="text-muted small">No notes.</div>';
        return;
    }
    for (const n of notes) {
        const div = document.createElement('div');
        div.className = 'alert alert-info py-1 px-2 small';
        div.textContent = n;
        els.notes.appendChild(div);
    }
}

function renderWarnings(v) {
    els.warnings.innerHTML = '';
    const warnings = v.warnings || [];
    if (!warnings.length) {
        els.warnings.innerHTML = '<div class="text-muted small">No warnings.</div>';
        return;
    }
    for (const w of warnings) {
        const div = document.createElement('div');
        div.className = `alert alert-${w.severity || 'info'} py-1 px-2 small`;
        div.textContent = formatWarning(w);
        els.warnings.appendChild(div);
    }
}

function renderTable(v) {
    const rows = v.components || [];
    els.tableBody.innerHTML = '';
    if (!rows.length) {
        els.tableBody.innerHTML = '<tr><td colspan="11" class="text-muted">No hardware components defined in AnchorsName for this anchor.</td></tr>';
        return;
    }
    for (const p of rows) {
        const tr = document.createElement('tr');
        const badge = p.matched
            ? '<span class="badge bg-success">ok</span>'
            : '<span class="badge bg-danger">unmatched</span>';
        tr.innerHTML = [
            `<td><code>DIN${p.slot}</code></td>`,
            `<td>${p.side === 'top' ? 'top' : 'embedded'}</td>`,
            `<td>${p.role}</td>`,
            `<td>${p.din}</td>`,
            `<td>${p.material || '\u2013'}</td>`,
            `<td class="text-end">${fin(p.diameter)}</td>`,
            `<td class="text-end">${fin(p.height)}</td>`,
            `<td class="text-end">${fin(p.width)}</td>`,
            `<td class="text-end">${p.position != null ? p.position : '\u2013'}</td>`,
            `<td>${p.name || p.din}</td>`,
            `<td>${badge}</td>`,
        ].join('');
        els.tableBody.appendChild(tr);
    }
}

/* ------------------------------------------------------------------ framing */

function currentBounds() {
    let minY = 1e9, maxY = -1e9;
    if (view && view.ok) {
        minY = -8;
        maxY = Number(view.geometry.length_mm) + 6;
    }
    for (const pm of partMeshes) {
        const b = pm.mesh.userData.targetBottom != null ? pm.mesh.userData.targetBottom : pm.bottom;
        minY = Math.min(minY, b - 4);
        maxY = Math.max(maxY, b + pm.h + 4);
    }
    return { minY, maxY };
}

function frameScene() {
    if (!view || !view.ok || !renderer) return;
    const { minY, maxY } = currentBounds();
    const dia = Number(view.anchor.diameter) || 10;
    const width = Math.max(dia * 5, 110) + DIM_RIGHT_MARGIN;
    const centerY = (minY + maxY) / 2;
    controls.target.set(0, centerY, 0);
    const aspect = camera.aspect || 1;
    const tan = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const dist = Math.max((maxY - minY) / 2 / tan, width / (aspect * tan)) * 1.18;
    camera.position.set(dist * 0.42, centerY + dist * 0.1, dist);
    controls.update();
}

function animate() {
    const dt = Math.min(clock.getDelta(), 0.05);
    if (renderer) {
        for (const pm of partMeshes) {
            const t = pm.mesh.userData.targetBottom;
            if (t != null) {
                pm.mesh.position.y = THREE.MathUtils.lerp(pm.mesh.position.y, t + pm.h / 2, 1 - Math.exp(-8 * dt));
            }
        }
        controls.update();
        if (fitNeeded) { fitNeeded = false; frameScene(); }
        renderer.render(scene, camera);
    }
}

/* ------------------------------------------------------------------ data */

async function fetchPayload(anchorId, defId) {
    const qs = new URLSearchParams({ anchor_id: anchorId, def_id: defId }).toString();
    const resp = await fetch(`/db/${encodeURIComponent(DATABASE)}/anchor-configurator/payload?${qs}`, {
        headers: { Accept: 'application/json' },
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    return data;
}

let loadSeq = 0;
async function loadSelection(keepDef = false) {
    const anchorId = els.anchor.value;
    if (!anchorId) return;
    const seq = ++loadSeq;
    const defId = keepDef && els.length.value ? els.length.value : 0;
    els.loading.classList.remove('d-none');
    try {
        const data = await fetchPayload(anchorId, defId);
        if (seq !== loadSeq) return;

        const currentDef = Number(data.selection.def_id);
        els.length.innerHTML = '';
        for (const l of data.available_lengths || []) {
            const opt = document.createElement('option');
            opt.value = l.def_id;
            opt.textContent = `${l.part_name || ''} \u00b7 ${fin(l.length_mm)} in`;
            if (l.def_id === currentDef) opt.selected = true;
            els.length.appendChild(opt);
        }
        view = data;
        buildModel(data);
        renderAnchorPanel(data);
        renderGeometryPanel(data);
        renderNotes(data);
        renderWarnings(data);
        renderTable(data);
        updateSheetLink(data);
        els.detail.innerHTML = '<div class="text-muted small">Hover a rendered component to identify its source record.</div>';
        partTargets(els.mode.value === 'exploded');
    } catch (err) {
        if (seq !== loadSeq) return;
        els.warnings.innerHTML = `<div class="alert alert-danger py-1 px-2 small">${err.message}</div>`;
        els.caption.textContent = 'load failed';
    } finally {
        if (seq === loadSeq) els.loading.classList.add('d-none');
    }
}

function updateSheetLink(v) {
    if (!els.sheetLink || !v || !v.ok) return;
    const qs = new URLSearchParams({
        anchor_id: v.selection.anchor_id,
        def_id: v.selection.def_id,
    }).toString();
    els.sheetLink.href = `/db/${encodeURIComponent(DATABASE)}/fabrication-sheet?${qs}`;
    els.sheetLink.classList.remove('d-none');
}

function wire() {
    els.anchor.addEventListener('change', () => {
        els.length.innerHTML = '';
        loadSelection(false);
    });
    els.length.addEventListener('change', () => loadSelection(true));
    els.mode.addEventListener('change', () => {
        partTargets(els.mode.value === 'exploded');
        fitNeeded = true;
    });
    els.resetView.addEventListener('click', () => frameScene());
}

initScene();

if (els.anchor) {
    // skip options that have no length variants when choosing the default
    const usable = Array.from(els.anchor.options).findIndex((o) => !o.textContent.includes('(no lengths)'));
    if (usable > 0) els.anchor.selectedIndex = usable;
    if (els.anchor.options.length) {
        wire();
        loadSelection(false).catch(() => {});
    } else {
        els.caption.textContent = 'no anchors in this database';
    }
}
