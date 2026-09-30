import json
from pathlib import Path

import pytest

import build_page as bp

GOOD = {
    "tldr": "One line.",
    "sections": [{"title": "Intro", "bullets": ["a", "b"], "start": 0}],
    "takeaways": ["t1"],
}
TEMPLATE_PATH = Path(bp.__file__).with_name("template.html")


def test_template_has_placeholder_exactly_once():
    assert TEMPLATE_PATH.read_text(encoding="utf-8").count(bp.PLACEHOLDER) == 1


def test_build_page_injects_valid_json():
    html = bp.build_page("x = " + bp.PLACEHOLDER + ";", GOOD, "dQw4w9WgXcQ", "My Video")
    payload = json.loads(html[len("x = "):-1])
    assert payload["tldr"] == "One line."
    assert payload["video_id"] == "dQw4w9WgXcQ"
    assert payload["title"] == "My Video"


def test_build_page_escapes_script_and_comment_breakouts():
    evil = {**GOOD, "tldr": '</script><script>alert(1)</script><!-- "q"  '}
    html = bp.build_page("<script>x = " + bp.PLACEHOLDER + ";</script>", evil, "dQw4w9WgXcQ", 'T"</script>')
    assert html.count("</script>") == 1  # only the template's own closing tag
    assert "<!--" not in html
    assert " " not in html


@pytest.mark.parametrize("mutate,msg", [
    (lambda s: s.update(tldr=""), "tldr"),
    (lambda s: s.update(sections=[]), "sections"),
    (lambda s: s["sections"][0].update(start=-5), "start"),
    (lambda s: s["sections"][0].update(start="12"), "start"),
    (lambda s: s["sections"][0].update(bullets=[]), "bullets"),
    (lambda s: s["sections"][0].update(title=""), "title"),
    (lambda s: s.update(takeaways="nope"), "takeaways"),
])
def test_validate_summary_rejects_bad_input(mutate, msg):
    bad = json.loads(json.dumps(GOOD))
    mutate(bad)
    with pytest.raises(ValueError, match=msg):
        bp.validate_summary(bad)


def test_validate_summary_accepts_good():
    bp.validate_summary(GOOD)


def test_main_reads_title_and_id_from_meta_file(tmp_path, capsys):
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps(GOOD))
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"video_id": "dQw4w9WgXcQ", "title": 'How I made $100k "fast" `x`'}))
    out = tmp_path / "out.html"
    assert bp.main([str(summary), str(meta), str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert '$100k \\"fast\\" `x`' in html
    assert "dQw4w9WgXcQ" in html


def test_main_non_object_summary_prints_json_error(tmp_path, capsys):
    summary = tmp_path / "summary.json"
    summary.write_text("[1, 2]")
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"video_id": "dQw4w9WgXcQ", "title": "t"}))
    assert bp.main([str(summary), str(meta), str(tmp_path / "o.html")]) == 1
    assert "error" in json.loads(capsys.readouterr().out)


def test_cost_is_optional_but_must_be_a_nonempty_string_when_given():
    bp.validate_summary({**GOOD, "cost": "≈ 40k tokens · 1% of 5-hour limit"})
    for bad in ("", "   ", 5, ["x"]):
        with pytest.raises(ValueError, match="cost"):
            bp.validate_summary({**GOOD, "cost": bad})


def test_template_renders_cost_line():
    assert "d.cost" in TEMPLATE_PATH.read_text(encoding="utf-8")
