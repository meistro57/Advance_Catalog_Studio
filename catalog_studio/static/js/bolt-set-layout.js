/* static/js/bolt-set-layout.js
 * Client-side mirror of the assembly layout in
 * catalog_studio/utils/bolt_sets.py (build_layout). Phase 2 draft previews
 * update immediately when the user edits the assembly, so the same math must
 * run in the browser without a server round trip.
 *
 * KEEP IN SYNC WITH build_layout() IN bolt_sets.py.
 *
 * All MATH stays in millimetres (the catalog's internal unit). User-facing
 * warning text reports inches, mirroring the viewer's display convention.
 *
 * Conventions (shared with the Python side):
 * - Bolt shank spans y in [0, length]; head occupies [-head_height, 0].
 * - headSide / nutSide arrays are ordered bottom-to-top on their side
 *   (index 0 is adjacent to the clamped material).
 * - grip mode "auto": nut stack is anchored with its top at the shank end and
 *   the grip is whatever shank length remains.
 * - grip mode "fixed": the requested clamped-material thickness is honoured
 *   but reduced (with a warning) if the hardware stacks + request exceed the
 *   shank length.
 */

export function partHeight(p) {
    if (p.height != null && Number(p.height) > 0) return Number(p.height);
    const dia = Number(p.diameter) || 0;
    if (p.role === 'nut') return Math.max(dia * 0.8, 1.0);
    return Math.max(dia * 0.25, 0.5);
}

export function layoutAssembly({ length, headHeight, headSide = [], nutSide = [],
                                 gripMode = 'auto', gripValue = 0 }) {
    length = Number(length) || 0;
    const parts = [];
    const warnings = [];
    let headUsed = 0;

    headSide.forEach((c, layer) => {
        const h = partHeight(c);
        const bottom = headUsed;
        parts.push({ ...c, side: 'head', layer,
                     stack_bottom: round4(bottom), stack_top: round4(bottom + h),
                     schematic_height: c.height == null || Number(c.height) <= 0 });
        headUsed = bottom + h;
    });

    const nutTotal = nutSide.reduce((s, c) => s + partHeight(c), 0);

    let nutBottom;
    if (gripMode === 'fixed' && gripValue >= 0) {
        const requested = Number(gripValue) || 0;
        const available = length - headUsed - nutTotal;
        if (requested > available + 1e-9) {
            warnings.push({
                severity: 'warning', code: 'grip_limited',
                message: `Requested clamped-material thickness ${in2(requested)} in does not fit ` +
                         `on the ${in2(length)} in bolt (hardware stacks take ${in2(headUsed + nutTotal)} in); ` +
                         `reduced to ${in2(Math.max(available, 0))} in.`,
            });
        }
        nutBottom = headUsed + Math.min(requested, Math.max(available, 0));
    } else {
        nutBottom = length - nutTotal;
    }

    let cursor = nutBottom;
    nutSide.forEach((c, layer) => {
        const h = partHeight(c);
        const bottom = cursor;
        parts.push({ ...c, side: 'nut', layer,
                     stack_bottom: round4(bottom), stack_top: round4(bottom + h),
                     schematic_height: c.height == null || Number(c.height) <= 0 });
        cursor = bottom + h;
    });

    const gripBottom = headUsed;
    const gripThickness = nutBottom - gripBottom;
    if (gripThickness <= 0) {
        warnings.push({
            severity: 'danger', code: 'impossible_stack',
            message: `Hardware stack (head-side ${in2(headUsed)} in + nut-side ${in2(nutTotal)} in) ` +
                     `exceeds the ${in2(length)} in bolt length; this set cannot assemble on this length.`,
        });
    }
    const gripH = Math.max(gripThickness, 0);

    return {
        parts,
        head_used: round4(headUsed),
        nut_used: round4(nutTotal),
        grip: { bottom: round4(gripBottom), top: round4(nutBottom), thickness: round4(gripH) },
        warnings,
    };
}

export function round4(n) {
    return Math.round(n * 10000) / 10000;
}

function r2(n) {
    return String(Math.round(n * 100) / 100);
}

const MM_PER_IN = 25.4;

function in2(mm) {
    return String(Math.round((mm / MM_PER_IN) * 1000) / 1000);
}
