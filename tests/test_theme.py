"""The light/dark switch: markup hooks, assets, and theme tokens."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "catalog_studio" / "templates"
STATIC = ROOT / "catalog_studio" / "static"


def test_base_template_ships_the_theme_toggle():
    from app import app
    resp = app.test_client().get("/db/SomeDb/find-replace")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="themeToggle"' in body
    assert "css/theme.css" in body
    assert "js/theme.js" in body
    # Applied before first paint, so a stored choice does not flash light.
    assert body.index("catalogStudioTheme") < body.index("bootstrap.min.css")


def test_theme_stylesheet_defines_both_themes():
    css = (STATIC / "css" / "theme.css").read_text()
    assert "--cs-page-bg" in css
    assert '[data-bs-theme="dark"]' in css
    # Light-only utilities the templates use must follow the theme.
    assert ".bg-white" in css and ".bg-light" in css
    # Drawings stay on light paper in both themes.
    assert ".bp-host" in css and "--cs-paper" in css


def test_theme_stylesheet_ships_the_design_layer():
    """The chrome's shared primitives live in theme.css, not per-page CSS."""
    css = (STATIC / "css" / "theme.css").read_text()
    for selector in (".cs-icon", ".cs-chip", ".cs-toolbar", ".cs-stat", ".cs-skip-link"):
        assert selector in css, f"{selector} missing from theme.css"
    # Both themes must drive the same token set.
    assert css.count("--cs-surface:") == 2


def test_viewer_canvas_height_is_declared_once():
    """The canvas height was declared twice (540px, then 460px); keep one rule."""
    css = (STATIC / "css" / "bolt-set-viewer.css").read_text()
    assert css.count("#viewer3d {") == 1
    assert "clamp(" in css


def test_theme_script_handles_the_switch_and_storage():
    js = (STATIC / "js" / "theme.js").read_text()
    assert "catalogStudioTheme" in js
    assert "themeToggle" in js
    assert "prefers-color-scheme" in js
    assert "localStorage" in js


def test_only_base_template_applies_the_theme_attribute():
    for path in TEMPLATES.glob("*.html"):
        text = path.read_text()
        if path.name == "base.html":
            assert "data-bs-theme" in text
        else:
            assert "data-bs-theme" not in text, f"{path.name} sets the theme itself"


def test_navigation_links_to_the_issue_tracker():
    from app import app
    from config import ISSUES_URL
    resp = app.test_client().get("/db/SomeDb/find-replace")
    body = resp.get_data(as_text=True)
    assert ISSUES_URL.startswith("https://github.com/")
    assert ISSUES_URL.endswith("/issues")
    assert f'href="{ISSUES_URL}"' in body
    assert 'rel="noopener"' in body
    assert ">Issues<" in body


def test_home_splits_fastener_and_drawing_style_management(monkeypatch):
    """Issue #20: home page splits attached DBs and tools into Fastener vs Drawing Style realms."""
    from app import app

    monkeypatch.setattr("utils.docker_ops.container_is_running", lambda: True)
    monkeypatch.setattr("utils.db.list_databases", lambda: ["A325Bolts", "MarksRailing", "HiltiAnchors"])
    monkeypatch.setattr("utils.db.server_file_version", lambda: 904)
    monkeypatch.setattr("utils.db.compatibility_problem", lambda v: None)
    monkeypatch.setattr("utils.metadata.all_meta", lambda: {
        "A325Bolts": {"catalog_type": "bolt", "as_version": 2026},
        "MarksRailing": {"catalog_type": "drawing style", "as_version": 2026},
        "HiltiAnchors": {"catalog_type": "anchor", "as_version": 2026},
    })

    resp = app.test_client().get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert 'id="fastenerManagementZone"' in body
    assert 'id="drawingStyleManagementZone"' in body
    fastener_start = body.index('id="fastenerManagementZone"')
    style_start = body.index('id="drawingStyleManagementZone"')
    fastener_zone = body[fastener_start:style_start]
    style_zone = body[style_start:]

    # Fastener databases and actions live in the Fastener Management zone
    assert "/db/A325Bolts" in fastener_zone
    assert "/db/HiltiAnchors" in fastener_zone
    assert "/db/MarksRailing" not in fastener_zone
    assert "Bolt-Set Viewer" in fastener_zone
    assert "Anchor Configurator" in fastener_zone

    # Drawing Style database and DSM tools live in the Drawing Style Management zone
    assert "/db/MarksRailing" in style_zone
    assert "/db/A325Bolts" not in style_zone
    assert "Style Editor" in style_zone
    assert "Rename Deep Copies" in style_zone
    assert "Open Detail Diff" in style_zone


def test_drawing_style_workspace_has_distinct_theme_classes_and_tokens(monkeypatch):
    """Issue #20: drawing-style pages apply body.cs-style-workspace and distinct CSS tokens."""
    from app import app

    css = (STATIC / "css" / "theme.css").read_text()
    for token in (
        "--cs-fastener-bg",
        "--cs-style-bg",
        ".cs-zone-fasteners",
        ".cs-zone-styles",
        "body.cs-style-workspace",
    ):
        assert token in css, f"{token} missing from theme.css"

    client = app.test_client()
    diff_body = client.get("/detail-diff").get_data(as_text=True)
    assert 'class="cs-style-workspace"' in diff_body

    monkeypatch.setattr("utils.db.list_tables", lambda db_name: ["DetailStyle"])
    monkeypatch.setattr("utils.db.get_row_count", lambda db_name, t: 1)
    monkeypatch.setattr("utils.db.get_catalog_diameters", lambda db_name: [])
    monkeypatch.setattr("utils.metadata.get", lambda db_name: {})

    monkeypatch.setattr("utils.db.guess_catalog_type", lambda db_name: "drawing style")
    style_db_html = client.get("/db/MarksRailing").get_data(as_text=True)
    assert 'class="cs-style-workspace"' in style_db_html

    monkeypatch.setattr("utils.db.guess_catalog_type", lambda db_name: "bolt")
    bolt_db_html = client.get("/db/A325Bolts").get_data(as_text=True)
    assert 'class="cs-style-workspace"' not in bolt_db_html


def test_app_version_and_changelog_are_aligned():
    """VERSION file, config.APP_VERSION, CHANGELOG.md, and navbar badge stay in sync."""
    import re
    import config
    from app import app

    ver_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.match(r"^\d+\.\d+\.\d+$", ver_file)
    assert config.APP_VERSION == ver_file

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"[{ver_file}]" in changelog

    resp = app.test_client().get("/db/SomeDb/find-replace")
    body = resp.get_data(as_text=True)
    assert f"v{ver_file}" in body
    assert 'id="appVersionBadge"' in body
