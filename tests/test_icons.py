"""The chrome's inline SVG icons and the offline asset policy."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "catalog_studio" / "templates"
STATIC = ROOT / "catalog_studio" / "static"

ICON_CALL = re.compile(r"icon\('([a-z0-9_-]+)'")
# The emoji blocks: these need a colour emoji font, which a minimal Linux box
# and a headless browser do not have (they render as a tofu box). Monochrome
# symbols such as U+2713 / U+26A0 come from the text font and are fine.
COLOUR_EMOJI = re.compile("[\U0001F000-\U0001FAFF]")


def test_icons_render_as_inline_svg():
    from utils import icons

    markup = str(icons.icon("health"))
    assert markup.startswith("<svg")
    assert 'aria-hidden="true"' in markup
    assert 'stroke="currentColor"' in markup
    assert 'width="16"' in markup


def test_icon_size_and_class_are_applied():
    from utils import icons

    markup = str(icons.icon("bolt", size=18, cls="me-1"))
    assert 'width="18"' in markup and 'height="18"' in markup
    assert 'class="cs-icon me-1"' in markup


def test_unknown_icon_fails_loudly():
    from utils import icons

    with pytest.raises(KeyError):
        icons.icon("no-such-icon")


def test_every_icon_used_in_a_template_exists():
    from utils import icons

    used = set()
    for path in TEMPLATES.glob("*.html"):
        used.update(ICON_CALL.findall(path.read_text()))
    assert used, "no icon() calls found in the templates"
    missing = sorted(used - set(icons.names()))
    assert not missing, f"templates call unknown icons: {missing}"


def test_templates_carry_no_colour_emoji():
    """A colour emoji degrades to a tofu box when the host has no emoji font."""
    offenders = []
    for path in TEMPLATES.glob("*.html"):
        for match in COLOUR_EMOJI.finditer(path.read_text()):
            offenders.append(f"{path.name}: {match.group()!r}")
    assert not offenders, offenders


def test_base_template_loads_vendored_assets_only():
    """The tool must work offline: no CDN bootstrap, favicon and mark shipped."""
    body = (TEMPLATES / "base.html").read_text()
    assert "vendor/bootstrap/bootstrap.min.css" in body
    assert "vendor/bootstrap/bootstrap.bundle.min.js" in body
    assert "img/favicon.svg" in body
    assert "img/mark.svg" in body
    assert "cdn.jsdelivr.net" not in body
    assert (STATIC / "vendor" / "bootstrap" / "bootstrap.min.css").is_file()
    assert (STATIC / "vendor" / "bootstrap" / "bootstrap.bundle.min.js").is_file()
    assert (STATIC / "img" / "favicon.svg").is_file()
    assert (STATIC / "img" / "mark.svg").is_file()


def test_icon_global_is_registered_on_the_app():
    from app import app

    assert app.jinja_env.globals["icon"] is not None
    body = app.test_client().get("/db/SomeDb/find-replace").get_data(as_text=True)
    assert "css/theme.css" in body
