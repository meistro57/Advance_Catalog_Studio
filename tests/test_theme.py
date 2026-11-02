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
