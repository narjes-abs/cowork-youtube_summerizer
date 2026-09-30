# YouTube Summary Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/yt-summary <youtube-link>` fetches a video's transcript, has Claude summarize it into structured JSON, and publishes an interactive artifact page (collapsible sections, clickable timestamps that seek an embedded player, Markdown copy/download).

**Architecture:** A project skill with two small Python scripts (fetch transcript; inject summary JSON into an HTML template) plus a static `template.html`. Claude itself does the summarizing (no API key). The page is one self-contained HTML file per video, published with the Artifact tool. No database.

**Tech Stack:** Python 3.9+, `youtube-transcript-api` (>=1.0), pytest, vanilla HTML/CSS/JS (YouTube iframe embed + postMessage for seeking).

**Spec:** `docs/superpowers/specs/2026-09-30-yt-summary-design.md`

> Note: this folder is not a git repo (user's choice), so there are no commit steps. Each task ends with a verification step instead.

## Global Constraints

- Skill lives at `.claude/skills/yt-summary/` (project skill), invoked as `/yt-summary <link>`.
- Transcripts are fetched locally by the skill; the artifact page never fetches from YouTube (blocked in browsers). Only the video embed loads from YouTube.
- No separate API key: Claude does the summarizing.
- Summary JSON: `tldr` (one line), `sections[]` (3–7; each `title`, `bullets[]`, `start` seconds), `takeaways[]`.
- UI: TL;DR on top, collapsible sections, embedded player with timestamp seek, "Copy as Markdown" and "Download .md" buttons, responsive on phone, light/dark mode.
- Errors: no captions → clear message and stop (no Whisper); videos over ~2 hours → transcript summarized in chunks; invalid URL → plain error message.
- Out of scope for v1: history, quiz mode, Q&A follow-ups, Whisper. (History is a documented phase 2, not in this plan.)

## Review Focus

- URL variants: `youtu.be/ID?si=...`, `watch?v=ID&t=90s`, `/shorts/ID`, `m.youtube.com`, a bare 11-char ID → all resolve to the same ID (Task 1 tests).
- Non-YouTube or garbage input (`https://example.com`, empty string) → clear "Not a valid YouTube link" error, not a traceback (Task 1 tests).
- Summary text containing `</script>`, `<!--`, quotes, or unicode line separators must not break or inject into the page (Task 2 tests).
- Malformed summary JSON (empty tldr, zero sections, non-integer or negative `start`) is rejected with a specific message before publishing (Task 2 tests).
- Videos of an hour or more: timestamps render as `h:mm:ss`, and very long transcripts go to a file rather than being printed whole (Task 1 tests + SKILL chunking rule in Task 3).

---

## File Structure

```
.claude/skills/yt-summary/
  SKILL.md               # instructions Claude follows for /yt-summary
  fetch_transcript.py    # URL -> video id, title, timestamped transcript file
  build_page.py          # validate summary JSON + inject into template -> html
  template.html          # interactive UI (data placeholder)
  requirements.txt
tests/
  conftest.py            # puts the skill dir on sys.path
  test_fetch_transcript.py
  test_build_page.py
```

---

### Task 1: Transcript fetcher

**Files:**
- Create: `.claude/skills/yt-summary/requirements.txt`
- Create: `.claude/skills/yt-summary/fetch_transcript.py`
- Create: `tests/conftest.py`
- Test: `tests/test_fetch_transcript.py`

**Interfaces:**
- Produces (used by Task 3 SKILL.md):
  - `extract_video_id(url: str) -> str` (raises `ValueError("Not a valid YouTube link: ...")`)
  - `format_timestamp(seconds: float) -> str` (`m:ss` under 1h, else `h:mm:ss`)
  - `format_transcript(segments: list[dict]) -> str` (segments are `{"start": float, "text": str}`; one line each: `[m:ss] text`)
  - `fetch_video(video_id: str) -> dict` returning `{"video_id", "title", "duration_seconds", "segments"}`; raises `NoCaptions(Exception)` when unavailable
  - CLI: `python fetch_transcript.py <url> --out <path>` prints one JSON line to stdout: success `{"video_id","title","duration_seconds","chars","transcript_path"}` or failure `{"error": "..."}` with exit code 1.

- [ ] **Step 1: Set up the environment**

Run:
```bash
cd cowork_youtube_summerizer
mkdir -p .claude/skills/yt-summary tests
printf 'youtube-transcript-api>=1.0\npytest\n' > .claude/skills/yt-summary/requirements.txt
python3 -m venv .claude/skills/yt-summary/.venv
.claude/skills/yt-summary/.venv/bin/python -m pip install -q -r .claude/skills/yt-summary/requirements.txt
```
Expected: installs without error.

- [ ] **Step 2: Write conftest and the failing tests**

`tests/conftest.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "skills" / "yt-summary"))
```

`tests/test_fetch_transcript.py`:
```python
import json

import pytest

import fetch_transcript as ft

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&t=90s",
    f"https://youtu.be/{VID}?si=abc123",
    f"https://m.youtube.com/watch?v={VID}",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"  {VID}  ",
])
def test_extract_video_id_variants(url):
    assert ft.extract_video_id(url) == VID


@pytest.mark.parametrize("bad", ["", "https://example.com/watch?v=" + VID, "hello", "https://www.youtube.com/watch"])
def test_extract_video_id_rejects_garbage(bad):
    with pytest.raises(ValueError, match="Not a valid YouTube link"):
        ft.extract_video_id(bad)


def test_format_timestamp():
    assert ft.format_timestamp(0) == "0:00"
    assert ft.format_timestamp(65.9) == "1:05"
    assert ft.format_timestamp(3600) == "1:00:00"
    assert ft.format_timestamp(3725) == "1:02:05"


def test_format_transcript_lines():
    segs = [{"start": 0.0, "text": "hi"}, {"start": 3700.0, "text": "late"}]
    assert ft.format_transcript(segs) == "[0:00] hi\n[1:01:40] late"


def test_main_invalid_url_prints_json_error(capsys, tmp_path):
    code = ft.main(["nonsense", "--out", str(tmp_path / "t.txt")])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert "Not a valid YouTube link" in out["error"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.claude/skills/yt-summary/.venv/bin/python -m pytest tests/test_fetch_transcript.py -v`
Expected: FAIL / collection error (`No module named 'fetch_transcript'`).

- [ ] **Step 4: Write the implementation**

`.claude/skills/yt-summary/fetch_transcript.py`:
```python
"""Fetch a YouTube video's captions and write a timestamped transcript file."""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class NoCaptions(Exception):
    """Raised when a video has no retrievable captions."""


def extract_video_id(url: str) -> str:
    url = url.strip()
    if ID_RE.match(url):
        return url
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    vid = None
    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            vid = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
        else:
            m = re.match(r"^/(shorts|embed|live|v)/([^/?]+)", parsed.path)
            if m:
                vid = m.group(2)
    if vid and ID_RE.match(vid):
        return vid
    raise ValueError(f"Not a valid YouTube link: {url!r}")


def format_timestamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def format_transcript(segments: list) -> str:
    return "\n".join(f"[{format_timestamp(s['start'])}] {s['text']}" for s in segments)


def _fetch_title(video_id: str) -> str:
    url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(
        f"https://www.youtube.com/watch?v={video_id}", safe=""
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.load(resp)["title"]
    except Exception:
        return video_id


def fetch_video(video_id: str) -> dict:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import CouldNotRetrieveTranscript, NoTranscriptFound

    try:
        transcripts = YouTubeTranscriptApi().list(video_id)
        try:
            transcript = transcripts.find_transcript(["en"])
        except NoTranscriptFound:
            transcript = next(iter(transcripts))
        fetched = transcript.fetch()
    except (CouldNotRetrieveTranscript, StopIteration) as exc:
        raise NoCaptions(
            "This video has no retrievable captions (disabled, private, or unavailable)."
        ) from exc
    segments = [
        {"start": float(sn.start), "text": " ".join(sn.text.split())} for sn in fetched
    ]
    if not segments:
        raise NoCaptions("The caption track for this video is empty.")
    last = fetched[-1]
    return {
        "video_id": video_id,
        "title": _fetch_title(video_id),
        "duration_seconds": int(last.start + last.duration),
        "segments": segments,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--out", required=True, help="where to write the transcript text")
    args = parser.parse_args(argv)
    try:
        video = fetch_video(extract_video_id(args.url))
    except (ValueError, NoCaptions) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    text = format_transcript(video["segments"])
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(json.dumps({
        "video_id": video["video_id"],
        "title": video["title"],
        "duration_seconds": video["duration_seconds"],
        "chars": len(text),
        "transcript_path": args.out,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.claude/skills/yt-summary/.venv/bin/python -m pytest tests/test_fetch_transcript.py -v`
Expected: all PASS.

- [ ] **Step 6: Live check against real videos (network)**

Run with any short captioned video, e.g. the ID `jNQXAC9IVRw` ("Me at the zoo"):
```bash
.claude/skills/yt-summary/.venv/bin/python .claude/skills/yt-summary/fetch_transcript.py "https://youtu.be/jNQXAC9IVRw" --out /tmp/t.txt && head -3 /tmp/t.txt
```
Expected: JSON with `title`, `chars` > 0; `head` shows `[0:00] ...` lines. If the library raises an attribute error (API differences between versions), adjust `fetch_video` to the installed version's `list()` / `.fetch()` / snippet attributes (`text`, `start`, `duration`) and re-run the unit tests.

Then a no-captions/unavailable case (use a bogus but well-formed ID such as `AAAAAAAAAAA`):
```bash
.claude/skills/yt-summary/.venv/bin/python .claude/skills/yt-summary/fetch_transcript.py AAAAAAAAAAA --out /tmp/t2.txt; echo "exit=$?"
```
Expected: `{"error": "This video has no retrievable captions ..."}` and `exit=1`, no traceback.

---

### Task 2: Page builder and interactive template

**Files:**
- Create: `.claude/skills/yt-summary/build_page.py`
- Create: `.claude/skills/yt-summary/template.html`
- Test: `tests/test_build_page.py`

**Interfaces:**
- Consumes: nothing from Task 1 at runtime (video id and title are passed in).
- Produces (used by Task 3):
  - `validate_summary(summary: dict) -> None` (raises `ValueError` with a specific message)
  - `build_page(template: str, summary: dict, video_id: str, title: str) -> str`
  - `PLACEHOLDER = "/*__SUMMARY_JSON__*/ null"` — appears exactly once in `template.html`
  - CLI: `python build_page.py <summary.json> <video_id> <title> <out.html>`; prints `{"out": path}` on success or `{"error": "..."}` with exit 1.
  - Page data contract: the injected object is `{tldr, sections:[{title, bullets, start}], takeaways, video_id, title}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_build_page.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.claude/skills/yt-summary/.venv/bin/python -m pytest tests/test_build_page.py -v`
Expected: FAIL (`No module named 'build_page'`).

- [ ] **Step 3: Write `build_page.py`**

`.claude/skills/yt-summary/build_page.py`:
```python
"""Validate a summary JSON and inject it into template.html."""
import argparse
import json
import sys
from pathlib import Path

PLACEHOLDER = "/*__SUMMARY_JSON__*/ null"


def validate_summary(summary: dict) -> None:
    if not isinstance(summary.get("tldr"), str) or not summary["tldr"].strip():
        raise ValueError("summary.tldr must be a non-empty string")
    sections = summary.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("summary.sections must be a non-empty list")
    for i, sec in enumerate(sections):
        where = f"sections[{i}]"
        if not isinstance(sec.get("title"), str) or not sec["title"].strip():
            raise ValueError(f"{where}.title must be a non-empty string")
        bullets = sec.get("bullets")
        if not isinstance(bullets, list) or not bullets or not all(isinstance(b, str) for b in bullets):
            raise ValueError(f"{where}.bullets must be a non-empty list of strings")
        start = sec.get("start")
        if isinstance(start, bool) or not isinstance(start, int) or start < 0:
            raise ValueError(f"{where}.start must be an integer number of seconds >= 0")
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
    parser.add_argument("video_id")
    parser.add_argument("title")
    parser.add_argument("out_html")
    args = parser.parse_args(argv)
    try:
        summary = json.loads(Path(args.summary_json).read_text(encoding="utf-8"))
        template = Path(__file__).with_name("template.html").read_text(encoding="utf-8")
        html = build_page(template, summary, args.video_id, args.title)
    except (ValueError, OSError) as exc:  # JSONDecodeError is a ValueError
        print(json.dumps({"error": str(exc)}))
        return 1
    Path(args.out_html).write_text(html, encoding="utf-8")
    print(json.dumps({"out": args.out_html}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write `template.html`**

Before writing it, load the `artifact-design` skill (required for any artifact page) and follow its contract: `<title>` of 2–4 words, color tokens on `:root` with dark-mode overrides under `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])` and again under `:root[data-theme="dark"]`, explicit `body` background, 16px side gutters, no horizontal scroll at phone width. Adjust the styling below to match that guidance; the structure, ids, and JS must stay as written.

`.claude/skills/yt-summary/template.html`:
```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video Summary</title>
<style>
  :root {
    --bg: #fafaf9; --surface: #ffffff; --text: #1c1917; --muted: #57534e;
    --border: #e7e5e4; --accent: #b45309; --accent-bg: #fef3c7;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #1c1917; --surface: #292524; --text: #fafaf9; --muted: #a8a29e;
      --border: #44403c; --accent: #fbbf24; --accent-bg: #422006;
    }
  }
  :root[data-theme="dark"] {
    --bg: #1c1917; --surface: #292524; --text: #fafaf9; --muted: #a8a29e;
    --border: #44403c; --accent: #fbbf24; --accent-bg: #422006;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
    font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 860px; margin: 0 auto; padding: 24px 16px 64px; }
  h1 { font-size: 1.35rem; margin: 0 0 4px; line-height: 1.3; }
  .tldr { background: var(--accent-bg); border-left: 4px solid var(--accent);
    padding: 12px 16px; border-radius: 6px; margin: 16px 0; font-size: 1.05rem; }
  .player { position: relative; aspect-ratio: 16 / 9; width: 100%; background: #000;
    border-radius: 8px; overflow: hidden; margin: 16px 0 8px; }
  .player iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
  .toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 20px; }
  button, .btn { font: inherit; cursor: pointer; padding: 8px 14px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--surface); color: var(--text);
    text-decoration: none; display: inline-block; }
  button:hover, .btn:hover { border-color: var(--accent); }
  details { background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; margin: 10px 0; }
  summary { cursor: pointer; padding: 12px 16px; font-weight: 600; display: flex;
    gap: 10px; align-items: baseline; }
  .ts { font-variant-numeric: tabular-nums; color: var(--accent); font-weight: 600;
    background: none; border: 0; padding: 0; text-decoration: underline; }
  .body { padding: 0 16px 12px 16px; }
  ul { margin: 6px 0; padding-left: 20px; }
  li { margin: 4px 0; }
  h2 { font-size: 1.05rem; margin: 28px 0 8px; }
  .muted { color: var(--muted); font-size: 0.9rem; }
  .error { padding: 24px 16px; }
</style>
</head>
<body>
<main id="app"></main>
<script>
const DATA = /*__SUMMARY_JSON__*/ null;

function fmt(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  Object.assign(node, props || {});
  for (const k of kids) node.append(k);
  return node;
}

function toMarkdown(d) {
  const url = (t) => `https://youtu.be/${d.video_id}?t=${t}`;
  let md = `# ${d.title}\n\n> ${d.tldr}\n\n`;
  for (const s of d.sections) {
    md += `## ${s.title} ([${fmt(s.start)}](${url(s.start)}))\n`;
    md += s.bullets.map((b) => `- ${b}`).join("\n") + "\n\n";
  }
  if (d.takeaways.length) {
    md += `## Key takeaways\n` + d.takeaways.map((t) => `- ${t}`).join("\n") + "\n";
  }
  md += `\nSource: https://youtu.be/${d.video_id}\n`;
  return md;
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = el("textarea", { value: text });
    document.body.append(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e2) {}
    ta.remove();
  }
  const old = btn.textContent;
  btn.textContent = "Copied";
  setTimeout(() => (btn.textContent = old), 1500);
}

function download(text, name) {
  const a = el("a", { href: URL.createObjectURL(new Blob([text], { type: "text/markdown" })), download: name });
  document.body.append(a);
  a.click();
  a.remove();
}

function render(d) {
  const app = document.getElementById("app");
  const iframe = el("iframe", {
    src: `https://www.youtube.com/embed/${encodeURIComponent(d.video_id)}?enablejsapi=1&rel=0`,
    allow: "accelerometer; encrypted-media; picture-in-picture; fullscreen",
    allowFullscreen: true,
    title: d.title,
  });
  function seek(t) {
    const send = (func, args) =>
      iframe.contentWindow.postMessage(JSON.stringify({ event: "command", func, args }), "*");
    send("seekTo", [t, true]);
    send("playVideo", []);
    document.querySelector(".player").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  const md = toMarkdown(d);
  const copyBtn = el("button", { textContent: "Copy as Markdown" });
  copyBtn.onclick = () => copyText(md, copyBtn);
  const dlBtn = el("button", { textContent: "Download .md" });
  dlBtn.onclick = () => download(md, `${d.video_id}-summary.md`);
  const ytLink = el("a", { className: "btn", href: `https://youtu.be/${d.video_id}`, target: "_blank", rel: "noopener", textContent: "Open on YouTube" });

  app.append(
    el("h1", { textContent: d.title }),
    el("div", { className: "tldr", textContent: d.tldr }),
    el("div", { className: "player" }, iframe),
    el("div", { className: "toolbar" }, copyBtn, dlBtn, ytLink),
  );

  d.sections.forEach((s, i) => {
    const tsBtn = el("button", { className: "ts", textContent: fmt(s.start), title: "Jump to this moment" });
    tsBtn.onclick = (e) => { e.preventDefault(); e.stopPropagation(); seek(s.start); };
    const sum = el("summary", null, tsBtn, el("span", { textContent: s.title }));
    const ul = el("ul");
    s.bullets.forEach((b) => ul.append(el("li", { textContent: b })));
    const det = el("details", { open: i === 0 }, sum, el("div", { className: "body" }, ul));
    app.append(det);
  });

  if (d.takeaways.length) {
    const ul = el("ul");
    d.takeaways.forEach((t) => ul.append(el("li", { textContent: t })));
    app.append(el("h2", { textContent: "Key takeaways" }), ul);
  }
}

if (DATA) {
  render(DATA);
} else {
  document.getElementById("app").append(
    el("p", { className: "error", textContent: "No summary data was embedded in this page." })
  );
}
</script>
</body>
</html>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.claude/skills/yt-summary/.venv/bin/python -m pytest tests/ -v`
Expected: all tests in both test files PASS.

- [ ] **Step 6: Render the page in the browser and check the UI**

Create a sample summary and build a page:
```bash
cat > /tmp/sample_summary.json <<'EOF'
{"tldr":"A 19-second clip about elephants at the zoo.",
 "sections":[
  {"title":"Intro","bullets":["Speaker is at the zoo","Points at elephants"],"start":0},
  {"title":"Later part","bullets":["Comments on trunks </script> & \"quotes\""],"start":10}],
 "takeaways":["Elephants have really long trunks"]}
EOF
.claude/skills/yt-summary/.venv/bin/python .claude/skills/yt-summary/build_page.py /tmp/sample_summary.json jNQXAC9IVRw "Me at the zoo" /tmp/sample_page.html
```
Open `file:///tmp/sample_page.html` in the browser pane (`mcp__Claude_Browser__navigate`) and verify:
- Title, TL;DR, and the player render; the `</script>` text appears literally in the second section and the page is not broken.
- First section is open, second collapsed; clicking a summary toggles it; clicking a timestamp does NOT toggle the section, and seeks the player (start time 10s plays).
- "Copy as Markdown" flips to "Copied"; "Download .md" triggers a download (if blocked by the artifact sandbox later, note it and keep Copy only).
- Resize to mobile width (375px): no horizontal scroll. Check `colorScheme: "dark"` also looks right.

Expected: all pass. Fix the template if any check fails, then re-run Step 5.

---

### Task 3: SKILL.md and end-to-end run

**Files:**
- Create: `.claude/skills/yt-summary/SKILL.md`

**Interfaces:**
- Consumes: `fetch_transcript.py` CLI (Task 1), `build_page.py` CLI (Task 2), the summary JSON contract from Global Constraints.

- [ ] **Step 1: Write the skill**

`.claude/skills/yt-summary/SKILL.md`:
````markdown
---
name: yt-summary
description: Summarize a YouTube video into a structured, interactive artifact page (TL;DR, collapsible sections, clickable timestamps, Markdown export). Use when the user runs /yt-summary <link> or asks to summarize a YouTube video for fast learning.
---

# YouTube Summary

Turn a YouTube link into an interactive summary page. Skill dir: `.claude/skills/yt-summary/` (call it `$SKILL`).

## Steps

1. **Get the link** from the arguments. If none was given, ask for it.

2. **Set up once.** If `$SKILL/.venv` does not exist:
   ```bash
   python3 -m venv $SKILL/.venv && $SKILL/.venv/bin/python -m pip install -q -r $SKILL/requirements.txt
   ```

3. **Fetch the transcript** into the scratchpad directory:
   ```bash
   $SKILL/.venv/bin/python $SKILL/fetch_transcript.py "<link>" --out <scratchpad>/transcript.txt
   ```
   The command prints one JSON line. If it contains `"error"`, tell the user that message plainly and STOP (no fallback; do not invent a summary).

4. **Read the transcript** (`transcript_path`). Lines look like `[12:03] text`.
   - If `chars` <= 150000: read it whole.
   - If larger (roughly videos over 2 hours): read it in parts of about 100000 characters (Read with offset/limit), note the key points and their timestamps for each part, then merge into one summary.

5. **Write the summary JSON** to `<scratchpad>/summary.json`, exactly this shape:
   ```json
   {
     "tldr": "One sentence: what the video is and its main point.",
     "sections": [
       {"title": "Short section title", "bullets": ["concrete point", "concrete point"], "start": 0}
     ],
     "takeaways": ["The 3-6 things worth remembering"]
   }
   ```
   Rules: 3-7 sections in chronological order; `start` is an integer number of seconds taken from the transcript timestamps at the moment that section begins (convert `[1:02:05]` to 3725); bullets are concrete facts and claims, not vague descriptions; write in the transcript's language; base everything on the transcript only.

6. **Build the page:**
   ```bash
   $SKILL/.venv/bin/python $SKILL/build_page.py <scratchpad>/summary.json <video_id> "<title>" <scratchpad>/summary.html
   ```
   If it prints an `"error"`, fix `summary.json` accordingly and re-run.

7. **Publish** `<scratchpad>/summary.html` with the Artifact tool (action publish, `icon: "video"`, a one-sentence `description`). Load the `artifact-design` skill first if it has not been loaded this session.

8. **Reply** with the artifact link and a 2-line gist (the tldr plus the single most important takeaway). Do not paste the whole summary.
````

- [ ] **Step 2: End-to-end run**

In a fresh message, run `/yt-summary https://youtu.be/jNQXAC9IVRw` (or any short captioned video the user picks) and confirm:
- The skill is discovered and listed as `yt-summary`.
- Transcript fetched, `summary.json` written in the specified shape, `build_page.py` succeeds, artifact published.
- Opening the artifact link shows the same UI verified in Task 2 with real content; timestamp click seeks the embedded video. If the YouTube embed is blocked inside the artifact sandbox, note it and keep "Open on YouTube" plus timestamped `youtu.be/...?t=` links in the Markdown export as the fallback (report this to the user rather than silently changing scope).

- [ ] **Step 3: Failure-path run**

Run `/yt-summary https://example.com` and `/yt-summary AAAAAAAAAAA`.
Expected: each ends with a one-line plain-language error and no artifact published.

- [ ] **Step 4: Final verification**

Run: `.claude/skills/yt-summary/.venv/bin/python -m pytest tests/ -v`
Expected: all PASS. Report the artifact link and any noted limitation (embed or download blocked) to the user.
