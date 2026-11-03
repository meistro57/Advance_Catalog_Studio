"""Inline SVG icons for the app chrome.

The tool ships no icon font and no emoji dependency: a colour emoji glyph only
renders when the host has an emoji font installed, and on a minimal Linux box or
a headless browser it degrades to a tofu box. Every icon here is a 24x24
stroke path that inherits `currentColor`, so it stays crisp, themeable and
offline.

Templates call `icon("bolt")`; `app.py` registers this module's `icon` as a
Jinja global. Pure and unit-tested (see tests/test_icons.py).
"""

from markupsafe import Markup

# 24x24 viewBox, stroke-only paths. Keys are the semantic names used in the
# templates; keep them stable, the tests walk the templates for unknown names.
ICONS = {
    # Hex nut: the bolt / fastener catalogs.
    "bolt": (
        '<path d="M12 3.25 19.75 7.5v9L12 20.75 4.25 16.5v-9z"/>'
        '<circle cx="12" cy="12" r="3.1"/>'
    ),
    # Add / clone diameter.
    "add": '<circle cx="12" cy="12" r="8.75"/><path d="M12 8v8M8 12h8"/>',
    # Drawing style: a ruler.
    "drawing": (
        '<rect x="2.25" y="8" width="19.5" height="8" rx="1.5"/>'
        '<path d="M6.5 8v3.5M10.25 8v5M14 8v3.5M17.75 8v5"/>'
    ),
    # Health report: a pulse trace.
    "health": '<path d="M2.5 12h4l2.5-6.5 4 13 2.5-6.5h6"/>',
    # Hint / help callout.
    "hint": (
        '<path d="M9.25 18h5.5M10.25 21h3.5"/>'
        '<path d="M12 2.75a6.25 6.25 0 0 0-3.6 11.35c.55.4.85 1 .85 1.7V17h5.5v-1.2'
        'c0-.7.3-1.3.85-1.7A6.25 6.25 0 0 0 12 2.75z"/>'
    ),
    # Preview / show.
    "preview": (
        '<path d="M2.25 12S6 5.5 12 5.5 21.75 12 21.75 12 18 18.5 12 18.5 2.25 12 2.25 12z"/>'
        '<circle cx="12" cy="12" r="2.9"/>'
    ),
    # Print / save as PDF.
    "print": (
        '<path d="M7.25 9V3.75h9.5V9"/>'
        '<rect x="3.75" y="9" width="16.5" height="7.25" rx="1.5"/>'
        '<path d="M7.25 13.5h9.5v6.75H7.25z"/>'
    ),
    # Library / delivered Advance Steel database.
    "library": (
        '<path d="M4 5.75A2.75 2.75 0 0 1 6.75 3H20v15H6.75A2.75 2.75 0 0 0 4 20.75z"/>'
        '<path d="M4 20.75A2.75 2.75 0 0 1 6.75 18H20v3H6.75"/>'
    ),
    # A record / file.
    "file": (
        '<path d="M14 2.75H7a2 2 0 0 0-2 2v14.5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7.75z"/>'
        '<path d="M14 2.75v5h5"/>'
    ),
    # Save changes.
    "save": (
        '<path d="M4.75 2.75h11l3.5 3.5v15H4.75z"/>'
        '<path d="M8.25 2.75v6h7v-6"/>'
        '<rect x="8.25" y="13" width="7.5" height="6.25"/>'
    ),
    # A labelled field.
    "tag": (
        '<path d="M20.5 13.2 13.2 20.5a1.9 1.9 0 0 1-2.7 0L3 13V3h10l7.5 7.5a1.9 1.9 0 0 1 0 2.7z"/>'
        '<circle cx="7.4" cy="7.4" r="1.2"/>'
    ),
    # Download / export.
    "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 20h16"/>',
    # Clear into the trash.
    "trash": (
        '<path d="M4 6.75h16"/>'
        '<path d="M9.5 4h5"/>'
        '<path d="M6.5 6.75 7.6 20.5h8.8l1.1-13.75"/>'
        '<path d="M10.5 10.5v6M13.5 10.5v6"/>'
    ),
    # Duplicate a row.
    "duplicate": (
        '<rect x="8.25" y="2.75" width="12" height="12" rx="2"/>'
        '<path d="M16 20.75H6a2 2 0 0 1-2-2V6.5"/>'
    ),
    # Warning.
    "warn": '<path d="M12 3.5 22 20.25H2z"/><path d="M12 9.5v4.5"/><circle cx="12" cy="17" r=".9"/>',
}


def icon(name, size=16, cls=""):
    """Return an inline SVG for `name`.

    Raises KeyError for an unknown name so a typo fails loudly in the test
    suite instead of rendering an empty box to the user.
    """
    if name not in ICONS:
        raise KeyError(f"unknown icon: {name}")
    classes = "cs-icon"
    if cls:
        classes = f"{classes} {cls}"
    return Markup(
        f'<svg class="{classes}" width="{int(size)}" height="{int(size)}" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round" focusable="false" '
        f'aria-hidden="true">{ICONS[name]}</svg>'
    )


def names():
    """Every icon name the module knows (used by the tests)."""
    return tuple(sorted(ICONS))
