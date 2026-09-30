"""Validate a summary JSON and inject it into template.html."""
import argparse
import json
import sys
from pathlib import Path

PLACEHOLDER = "/*__SUMMARY_JSON__*/ null"


def validate_summary(summary: dict) -> None:
    if not isinstance(summary, dict):
        raise ValueError("summary must be a JSON object")
    if not isinstance(summary.get("tldr"), str) or not summary["tldr"].strip():
        raise ValueError("summary.tldr must be a non-empty string")
    sections = summary.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("summary.sections must be a non-empty list")
    for i, sec in enumerate(sections):
        where = f"sections[{i}]"
        if not isinstance(sec, dict):
            raise ValueError(f"{where} must be an object")
        if not isinstance(sec.get("title"), str) or not sec["title"].strip():
            raise ValueError(f"{where}.title must be a non-empty string")
        bullets = sec.get("bullets")
        if not isinstance(bullets, list) or not bullets or not all(isinstance(b, str) for b in bullets):
            raise ValueError(f"{where}.bullets must be a non-empty list of strings")
        start = sec.get("start")
        if isinstance(start, bool) or not isinstance(start, int) or start < 0:
            raise ValueError(f"{where}.start must be an integer number of seconds >= 0")
    if "cost" in summary and (not isinstance(summary["cost"], str) or not summary["cost"].strip()):
        raise ValueError("summary.cost, if given, must be a non-empty string")
    takeaways = summary.get("takeaways")
    if not isinstance(takeaways, list) or not all(isinstance(t, str) for t in takeaways):
        raise ValueError("summary.takeaways must be a list of strings")


def build_page(template: str, summary: dict, video_id: str, title: str) -> str:
    validate_summary(summary)
    payload = json.dumps({**summary, "video_id": video_id, "title": title}, ensure_ascii=False)
    payload = (
        payload.replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )
    if PLACEHOLDER not in template:
        raise ValueError("template is missing the summary placeholder")
    return template.replace(PLACEHOLDER, payload)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary_json")
    parser.add_argument("meta_json", help="fetch_transcript.py's JSON output (video_id, title)")
    parser.add_argument("out_html")
    args = parser.parse_args(argv)
    try:
        summary = json.loads(Path(args.summary_json).read_text(encoding="utf-8"))
        meta = json.loads(Path(args.meta_json).read_text(encoding="utf-8"))
        template = Path(__file__).with_name("template.html").read_text(encoding="utf-8")
        html = build_page(template, summary, meta["video_id"], meta["title"])
    except (ValueError, OSError, KeyError) as exc:  # JSONDecodeError is a ValueError
        print(json.dumps({"error": str(exc)}))
        return 1
    Path(args.out_html).write_text(html, encoding="utf-8")
    print(json.dumps({"out": args.out_html}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
