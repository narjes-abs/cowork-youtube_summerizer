"""The icon theme: every icon follows the style of the tag icons (outline, 24 grid, 2px round stroke, currentColor)."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "panel" / "static"
ICONS = (STATIC / "icons.js").read_text(encoding="utf-8") if (STATIC / "icons.js").exists() else ""


def test_all_icons_live_in_icons_js_only():
    for name in ("app.js", "index.html"):
        assert "<svg" not in (STATIC / name).read_text(encoding="utf-8"), f"{name} has an inline <svg>; add it to icons.js"


def test_the_theme_attributes_are_defined_once_for_every_icon():
    for attr in ('viewBox="0 0 24 24"', 'fill="none"', 'stroke="currentColor"', 'stroke-width="2"',
                 'stroke-linecap="round"', 'stroke-linejoin="round"', 'aria-hidden="true"'):
        assert ICONS.count(attr) == 1, f"{attr} must appear exactly once (in the shared wrapper)"


def test_individual_icons_carry_no_colors_or_stroke_overrides():
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", ICONS), "hard-coded colors are not allowed in icons"
    assert ICONS.count("fill=") == 1 and ICONS.count("stroke=") == 1
    assert "stroke-width" not in ICONS.replace('stroke-width="2"', "")


def test_the_expected_icons_exist():
    for name in ("local", "network", "trash", "youtube"):
        assert re.search(rf"\b{name}:", ICONS), f"icon '{name}' missing"


def test_index_loads_icons_before_the_app():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index("icons.js") < html.index("app.js")
