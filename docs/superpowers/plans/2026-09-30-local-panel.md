# Local Panel App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, application-style page (`http://localhost:8000`) with a button per feature, a YouTube Summarize tool (URL input, Local/Network info tags, summary result) and a right-hand history sidebar, summarizing with local Ollama at zero credit.

**Architecture:** Python standard-library HTTP server bound to 127.0.0.1 with a small JSON API and static front end. Captions come from the existing `fetch_transcript.py`; summaries come from Ollama (`/api/chat`, JSON-schema output, chunk-and-merge for long videos) and are validated with the existing `build_page.validate_summary`. History is a JSON file.

**Tech Stack:** Python 3.9+ standard library, existing venv (`youtube-transcript-api`, pytest), Ollama HTTP API, vanilla HTML/CSS/JS.

**Spec:** `docs/superpowers/specs/2026-09-30-local-panel-design.md`

## Global Constraints

- All code in `panel/` inside `cowork_youtube_summerizer`; tests in `tests/panel/`.
- Python 3.9 compatible (no `X | Y` type unions, no `match`); standard library only for `panel/` (no new dependencies).
- Server binds `127.0.0.1` only, default port 8000 (override with `PORT` env or first CLI arg).
- Zero credit: no Apify, no Claude/Anthropic API calls. Default model `qwen3.5:9b`; model list comes from Ollama `/api/tags`. Ollama calls use `"think": false`.
- Tags on the YouTube page (information only): `YouTube captions · youtube-transcript-api` (Local), `Summarizer · Ollama <model>` (Local), `Video title · YouTube oEmbed` (Network).
- Cost line format: `cost: free · local · <model> · <seconds>s`.
- All model/transcript-derived text is rendered with `textContent` (never `innerHTML`).
- Summary JSON shape is unchanged: `tldr`, `sections[]` (`title`, `bullets[]`, integer `start`), `takeaways[]`.
- Reuses `.claude/skills/yt-summary/fetch_transcript.py` and `build_page.py` (import, don't copy). The `/yt-summary` skill is not modified.
- Not a git repo: no commit steps; each task ends with a verification step.

## Review Focus

- Ollama not running, or the chosen model not installed: the job ends with a plain "how to fix" message, never a traceback or a hang (Task 2 and 3 tests).
- The model returns non-JSON, floats or negative numbers for `start`, or timestamps not in the video: one retry, then normalize/snap; a persistent failure gives a clear message (Task 2 tests).
- A long transcript (many chunks): chunks never split a transcript line, notes are merged, progress is reported (Task 2 tests).
- A web page in another browser tab trying to call the local API (wrong `Host`, or a POST/DELETE without the `X-Panel` header) and path traversal on the static route are rejected (Task 3 tests).
- A missing or corrupt `history.json` starts empty instead of crashing, and a video title or summary containing HTML (`<img onerror>`) is displayed as text (Task 1 tests + Task 4 browser check).

---

## File Structure

```
panel/
  history.py       # HistoryStore: add/list/get/delete on a JSON file
  tools.py         # server-side tool registry with info tags
  summarizer.py    # OllamaClient, chunking, notes/merge, normalize, snap, retry
  server.py        # App (routing + jobs), static serving, main()
  run.sh           # start script
  static/index.html  style.css  app.js
  data/            # history.json created at runtime
tests/panel/
  conftest.py  test_history.py  test_tools.py  test_summarizer.py  test_server.py
.claude/launch.json   # preview config for the browser check
```

---

### Task 1: History store and tool registry

**Files:**
- Create: `panel/history.py`, `panel/tools.py`
- Create: `tests/panel/conftest.py`
- Test: `tests/panel/test_history.py`, `tests/panel/test_tools.py`

**Interfaces:**
- Produces:
  - `HistoryStore(path)` with `add(record: dict) -> dict` (adds `id` = 12 hex chars and `created` = UTC ISO string, returns the stored record), `list() -> list[dict]` (newest first; keys `id,title,video_id,created,model,seconds`), `get(id) -> dict|None`, `delete(id) -> bool`.
  - `tools.list_tools() -> list[dict]`: `[{"id","name","tags":[{"label","detail","kind"}]}]`, `kind` is `"local"` or `"network"`.

- [ ] **Step 1: Write conftest and failing tests**

`tests/panel/conftest.py`:
```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "panel", ROOT / ".claude" / "skills" / "yt-summary"):
    sys.path.insert(0, str(p))
```

`tests/panel/test_history.py`:
```python
import json

from history import HistoryStore


def rec(title="T", vid="dQw4w9WgXcQ"):
    return {"video_id": vid, "title": title, "summary": {"tldr": "x"}, "model": "m", "seconds": 3}


def test_add_list_get_delete(tmp_path):
    h = HistoryStore(tmp_path / "h.json")
    a = h.add(rec("first"))
    b = h.add(rec("second"))
    assert len(a["id"]) == 12 and a["created"]
    listed = h.list()
    assert [r["title"] for r in listed] == ["second", "first"]  # newest first
    assert set(listed[0]) == {"id", "title", "video_id", "created", "model", "seconds"}
    assert h.get(a["id"])["summary"] == {"tldr": "x"}
    assert h.get("nope") is None
    assert h.delete(a["id"]) is True
    assert h.delete(a["id"]) is False
    assert [r["id"] for r in h.list()] == [b["id"]]


def test_missing_file_is_empty(tmp_path):
    assert HistoryStore(tmp_path / "nope" / "h.json").list() == []


def test_corrupt_file_recovers(tmp_path):
    p = tmp_path / "h.json"
    p.write_text("{not json")
    h = HistoryStore(p)
    assert h.list() == []
    h.add(rec())
    assert len(json.loads(p.read_text())) == 1
    assert (tmp_path / "h.json.bak").exists()


def test_persists_across_instances(tmp_path):
    p = tmp_path / "h.json"
    HistoryStore(p).add(rec("kept"))
    assert HistoryStore(p).list()[0]["title"] == "kept"
```

`tests/panel/test_tools.py`:
```python
import tools


def test_youtube_tool_and_tags():
    listed = tools.list_tools()
    yt = next(t for t in listed if t["id"] == "youtube")
    assert yt["name"] == "YouTube Summarize"
    tags = {t["label"]: t for t in yt["tags"]}
    assert tags["YouTube captions"]["kind"] == "local"
    assert tags["Summarizer"]["kind"] == "local"
    assert tags["Video title"]["kind"] == "network"
    assert tags["Video title"]["detail"] == "YouTube oEmbed"
    assert tags["YouTube captions"]["detail"] == "youtube-transcript-api"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests/panel -q`
Expected: FAIL / collection errors (`No module named 'history'`, `'tools'`).

- [ ] **Step 3: Write the implementation**

`panel/history.py`:
```python
"""JSON-file history of saved summaries."""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

LIST_KEYS = ("id", "title", "video_id", "created", "model", "seconds")


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            raise ValueError("history file is not a list")
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            try:
                os.replace(self.path, self.path.with_name(self.path.name + ".bak"))
            except OSError:
                pass
            return []

    def _save(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, record):
        with self._lock:
            items = self._load()
            stored = {
                **record,
                "id": uuid.uuid4().hex[:12],
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            items.append(stored)
            self._save(items)
            return stored

    def list(self):
        with self._lock:
            items = self._load()
        return [{k: r.get(k) for k in LIST_KEYS} for r in reversed(items)]

    def get(self, record_id):
        with self._lock:
            return next((r for r in self._load() if r.get("id") == record_id), None)

    def delete(self, record_id):
        with self._lock:
            items = self._load()
            kept = [r for r in items if r.get("id") != record_id]
            if len(kept) == len(items):
                return False
            self._save(kept)
            return True
```

`panel/tools.py`:
```python
"""Server-side registry of the panel's tools and their information tags."""

TOOLS = [
    {
        "id": "youtube",
        "name": "YouTube Summarize",
        "tags": [
            {"label": "YouTube captions", "detail": "youtube-transcript-api", "kind": "local"},
            {"label": "Summarizer", "detail": "Ollama", "kind": "local"},
            {"label": "Video title", "detail": "YouTube oEmbed", "kind": "network"},
        ],
    },
]


def list_tools():
    return TOOLS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests/panel -q`
Expected: all PASS.

---

### Task 2: Summarizer (Ollama client, chunking, retry)

**Files:**
- Create: `panel/summarizer.py`
- Test: `tests/panel/test_summarizer.py`

**Interfaces:**
- Consumes: `build_page.validate_summary(summary)` (raises `ValueError`).
- Produces:
  - Exceptions `OllamaDown`, `ModelMissing`, `SummaryFailed` (each with a plain-language message).
  - `OllamaClient(base="http://localhost:11434")` with `list_models() -> list[str]` and `chat(model, messages, schema=None) -> str`.
  - `transcript_times(text) -> list[int]`, `chunk_lines(text, max_chars=12000) -> list[str]`, `normalize(summary) -> dict`, `snap_starts(summary, times) -> dict`.
  - `summarize(client, model, title, transcript, progress=None) -> dict` (returns a validated summary; `progress(msg: str)` called with `"reading part i of n"` / `"writing summary"`).
  - Any object with `chat(model, messages, schema=None) -> str` works as a client (tests use a fake).

- [ ] **Step 1: Write the failing tests**

`tests/panel/test_summarizer.py`:
```python
import json

import pytest

import summarizer as sm

TRANSCRIPT = "\n".join(f"[{i // 60}:{i % 60:02d}] line {i}" for i in range(0, 600, 5))
GOOD = {
    "tldr": "A talk.",
    "sections": [
        {"title": "A", "bullets": ["a"], "start": 0},
        {"title": "B", "bullets": ["b"], "start": 303},
    ],
    "takeaways": ["t"],
}


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, model, messages, schema=None):
        self.calls.append({"model": model, "messages": messages, "schema": schema})
        return self.replies.pop(0)


def test_transcript_times_parses_minutes_and_hours():
    assert sm.transcript_times("[0:05] a\n[12:03] b\n[1:02:05] c\nno stamp") == [5, 723, 3725]


def test_chunk_lines_never_splits_a_line_and_covers_everything():
    chunks = sm.chunk_lines(TRANSCRIPT, max_chars=200)
    assert len(chunks) > 1
    assert "\n".join(chunks) == TRANSCRIPT
    assert all(len(c) <= 200 for c in chunks)


def test_chunk_lines_keeps_a_single_oversized_line():
    assert sm.chunk_lines("x" * 50, max_chars=10) == ["x" * 50]


def test_normalize_coerces_starts():
    s = {"tldr": "x", "sections": [
        {"title": "a", "bullets": ["b"], "start": 12.7},
        {"title": "c", "bullets": ["d"], "start": "45"},
        {"title": "e", "bullets": ["f"], "start": -3},
    ], "takeaways": []}
    assert [x["start"] for x in sm.normalize(s)["sections"]] == [12, 45, 0]


def test_snap_starts_uses_nearest_real_timestamp_and_clamps():
    s = json.loads(json.dumps(GOOD))
    s["sections"][1]["start"] = 99999
    out = sm.snap_starts(s, sm.transcript_times(TRANSCRIPT))
    assert out["sections"][0]["start"] == 0
    assert out["sections"][1]["start"] == 595  # last real timestamp


def test_summarize_single_chunk_uses_schema_and_snaps():
    client = FakeClient([json.dumps({**GOOD, "sections": [
        {"title": "A", "bullets": ["a"], "start": 2.0},
        {"title": "B", "bullets": ["b"], "start": 303}]})])
    msgs = []
    out = sm.summarize(client, "m", "Title", TRANSCRIPT, progress=msgs.append)
    assert len(client.calls) == 1
    assert client.calls[0]["schema"] == sm.SUMMARY_SCHEMA
    assert "Title" in client.calls[0]["messages"][-1]["content"]
    assert [s["start"] for s in out["sections"]] == [0, 305]  # snapped to real stamps
    assert msgs == ["writing summary"]


def test_summarize_many_chunks_takes_notes_then_merges(monkeypatch):
    monkeypatch.setattr(sm, "MAX_CHUNK_CHARS", 300)
    n = len(sm.chunk_lines(TRANSCRIPT, 300))
    assert n > 1
    client = FakeClient([f"notes {i}" for i in range(n)] + [json.dumps(GOOD)])
    msgs = []
    out = sm.summarize(client, "m", "T", TRANSCRIPT, progress=msgs.append)
    assert len(client.calls) == n + 1
    assert all(c["schema"] is None for c in client.calls[:n])
    assert client.calls[-1]["schema"] == sm.SUMMARY_SCHEMA
    assert "notes 0" in client.calls[-1]["messages"][-1]["content"]
    assert msgs[0] == f"reading part 1 of {n}" and msgs[-1] == "writing summary"
    assert out["tldr"] == "A talk."


def test_summarize_retries_once_on_bad_json():
    client = FakeClient(["not json at all", json.dumps(GOOD)])
    assert sm.summarize(client, "m", "T", TRANSCRIPT)["tldr"] == "A talk."
    assert len(client.calls) == 2


def test_summarize_retries_once_on_invalid_summary_then_fails():
    bad = json.dumps({"tldr": "", "sections": [], "takeaways": []})
    client = FakeClient([bad, bad])
    with pytest.raises(sm.SummaryFailed, match="larger model"):
        sm.summarize(client, "m", "T", TRANSCRIPT)
    assert len(client.calls) == 2


def test_ollama_down_message(monkeypatch):
    import urllib.error
    import urllib.request

    def boom(*a, **k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(sm.OllamaDown, match="ollama serve"):
        sm.OllamaClient().list_models()
    with pytest.raises(sm.OllamaDown, match="ollama serve"):
        sm.OllamaClient().chat("m", [{"role": "user", "content": "x"}])


def test_model_missing_message(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    def missing(*a, **k):
        raise urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(urllib.request, "urlopen", missing)
    with pytest.raises(sm.ModelMissing, match="ollama pull qwen9"):
        sm.OllamaClient().chat("qwen9", [{"role": "user", "content": "x"}])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests/panel/test_summarizer.py -q`
Expected: FAIL (`No module named 'summarizer'`).

- [ ] **Step 3: Write the implementation**

`panel/summarizer.py`:
```python
"""Summarize a timestamped transcript with a local Ollama model."""
import json
import re
import urllib.error
import urllib.request

from build_page import validate_summary

OLLAMA_URL = "http://localhost:11434"
MAX_CHUNK_CHARS = 12000

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "tldr": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "start": {"type": "integer"},
                },
                "required": ["title", "bullets", "start"],
            },
        },
        "takeaways": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tldr", "sections", "takeaways"],
}

SYSTEM = (
    "You summarize YouTube video transcripts for fast learning. "
    "Use only the transcript. Be concrete, not vague."
)
SUMMARY_TASK = (
    "Write the summary as JSON: tldr (one sentence: what the video is and its main point); "
    "3-7 sections in chronological order, each with a title, 2-5 concrete bullets, and start = "
    "the timestamp in whole seconds where the section begins (convert [1:02:05] to 3725); "
    "and 3-6 takeaways worth remembering."
)
TIME_RE = re.compile(r"^\[(?:(\d+):)?(\d+):(\d{2})\]", re.M)


class OllamaDown(Exception):
    pass


class ModelMissing(Exception):
    pass


class SummaryFailed(Exception):
    pass


DOWN_MSG = "Ollama is not reachable. Start it (`ollama serve`) and try again."


class OllamaClient:
    def __init__(self, base=OLLAMA_URL):
        self.base = base

    def _request(self, path, payload=None, timeout=900, model=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and model:
                raise ModelMissing(
                    f"Model {model} is not installed. Run: ollama pull {model}"
                ) from exc
            raise OllamaDown(f"Ollama returned an error ({exc.code}).") from exc
        except OSError as exc:  # URLError, refused, timeout
            raise OllamaDown(DOWN_MSG) from exc

    def list_models(self):
        data = self._request("/api/tags", timeout=5)
        return [m["name"] for m in data.get("models", [])]

    def chat(self, model, messages, schema=None):
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2, "num_ctx": 16384},
        }
        if schema:
            payload["format"] = schema
        data = self._request("/api/chat", payload, model=model)
        return data.get("message", {}).get("content", "")


def transcript_times(text):
    return [
        int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        for m in TIME_RE.finditer(text)
    ]


def chunk_lines(text, max_chars=MAX_CHUNK_CHARS):
    chunks, cur, size = [], [], 0
    for line in text.split("\n"):
        extra = len(line) + (1 if cur else 0)
        if cur and size + extra > max_chars:
            chunks.append("\n".join(cur))
            cur, size = [], 0
            extra = len(line)
        cur.append(line)
        size += extra
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def normalize(summary):
    if isinstance(summary, dict):
        for sec in summary.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            start = sec.get("start")
            try:
                if not isinstance(start, bool):
                    sec["start"] = max(0, int(float(start)))
            except (TypeError, ValueError):
                pass
    return summary


def snap_starts(summary, times):
    if times:
        for sec in summary["sections"]:
            sec["start"] = min(times, key=lambda t: abs(t - sec["start"]))
    return summary


def _user(title, label, body):
    return {
        "role": "user",
        "content": f"Video title: {title}\n\n{label}:\n{body}\n\n{SUMMARY_TASK}",
    }


def summarize(client, model, title, transcript, progress=None):
    progress = progress or (lambda msg: None)
    chunks = chunk_lines(transcript, MAX_CHUNK_CHARS)
    if len(chunks) == 1:
        message = _user(title, "Transcript (lines start with [m:ss] timestamps)", chunks[0])
    else:
        notes = []
        for i, chunk in enumerate(chunks, 1):
            progress(f"reading part {i} of {len(chunks)}")
            notes.append(client.chat(model, [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": (
                    f"Video title: {title}\nThis is part {i} of {len(chunks)} of the transcript "
                    "(lines start with [m:ss] timestamps). List the key points as short bullet "
                    "lines, each starting with its [m:ss] timestamp.\n\n" + chunk)},
            ]))
        message = _user(title, "Notes from every part of the video, in order", "\n".join(notes))
    progress("writing summary")
    for _ in range(2):
        raw = client.chat(model, [{"role": "system", "content": SYSTEM}, message], schema=SUMMARY_SCHEMA)
        try:
            summary = normalize(json.loads(raw))
            validate_summary(summary)
        except ValueError:
            continue
        return snap_starts(summary, transcript_times(transcript))
    raise SummaryFailed("The model returned an unusable summary. Try a larger model.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests/panel -q`
Expected: all PASS. If a test fails because the code is wrong, fix the code; if a test's expectation is wrong versus the spec, fix the test and note why.

---

### Task 3: Server (API, jobs, static serving, run script)

**Files:**
- Create: `panel/server.py`, `panel/run.sh`
- Create: `panel/static/index.html` (placeholder page: `<!doctype html><title>Learning Panel</title><p>Loading…</p>`, replaced in Task 4)
- Test: `tests/panel/test_server.py`

**Interfaces:**
- Consumes: `HistoryStore` (Task 1), `tools.list_tools` (Task 1), `summarizer` (Task 2), `fetch_transcript.fetch_video/extract_video_id/format_transcript/NoCaptions`.
- Produces:
  - `App(history, client, fetch=None)` with `handle(method, path, body=None, headers=None) -> (status:int, obj:dict|list)` and `wait(job_id, timeout=10)` (joins the job thread; for tests).
  - `serve_static(path) -> (status:int, body:bytes, content_type:str)`.
  - Routes exactly as in the spec's API section. Job dict: `{"status","progress","result","error"}`. `GET /api/models` returns `{"models":[...], "default":"qwen3.5:9b"}` or `{"models":[], "default":..., "error": "<message>"}` with status 200.
  - Non-GET requests need header `X-Panel: 1`; `Host` must be `localhost` or `127.0.0.1` (port ignored), otherwise 403.
  - `main(argv=None)` starts `ThreadingHTTPServer(("127.0.0.1", port))`.

- [ ] **Step 1: Write the failing tests**

`tests/panel/test_server.py`:
```python
import json

import fetch_transcript as ft
import server
import summarizer as sm
from history import HistoryStore

H = {"Host": "localhost:8000", "X-Panel": "1"}
GOOD = {"tldr": "T", "sections": [{"title": "A", "bullets": ["a"], "start": 5}], "takeaways": ["t"]}
VIDEO = {"video_id": "dQw4w9WgXcQ", "title": "Video <b>Title</b>", "duration_seconds": 30,
         "segments": [{"start": 5.0, "text": "hello"}, {"start": 20.0, "text": "bye"}]}


class FakeClient:
    def __init__(self, models=("qwen3.5:9b",), reply=None, error=None):
        self.models, self.reply, self.error = list(models), reply or json.dumps(GOOD), error

    def list_models(self):
        if self.error:
            raise self.error
        return self.models

    def chat(self, model, messages, schema=None):
        if self.error:
            raise self.error
        return self.reply


def make_app(tmp_path, client=None, fetch=None):
    return server.App(HistoryStore(tmp_path / "h.json"), client or FakeClient(),
                      fetch or (lambda url: VIDEO))


def run_job(app, url="https://youtu.be/dQw4w9WgXcQ", model="qwen3.5:9b"):
    status, body = app.handle("POST", "/api/youtube/summarize", {"url": url, "model": model}, H)
    assert status == 200
    app.wait(body["job_id"])
    return app.handle("GET", f"/api/jobs/{body['job_id']}", None, H)[1]


def test_tools_and_models(tmp_path):
    app = make_app(tmp_path)
    assert app.handle("GET", "/api/tools", None, H)[1][0]["id"] == "youtube"
    status, body = app.handle("GET", "/api/models", None, H)
    assert status == 200 and body["models"] == ["qwen3.5:9b"] and body["default"] == "qwen3.5:9b"


def test_models_when_ollama_down(tmp_path):
    app = make_app(tmp_path, FakeClient(error=sm.OllamaDown(sm.DOWN_MSG)))
    status, body = app.handle("GET", "/api/models", None, H)
    assert status == 200 and body["models"] == [] and "ollama serve" in body["error"]


def test_successful_job_saves_history(tmp_path):
    app = make_app(tmp_path)
    job = run_job(app)
    assert job["status"] == "done"
    rec = job["result"]
    assert rec["title"] == "Video <b>Title</b>" and rec["model"] == "qwen3.5:9b"
    assert isinstance(rec["seconds"], int) and rec["summary"]["tldr"] == "T"
    hist = app.handle("GET", "/api/history", None, H)[1]
    assert [h["id"] for h in hist] == [rec["id"]]
    assert app.handle("GET", f"/api/history/{rec['id']}", None, H)[1]["summary"]["tldr"] == "T"
    assert app.handle("DELETE", f"/api/history/{rec['id']}", None, H)[0] == 200
    assert app.handle("GET", f"/api/history/{rec['id']}", None, H)[0] == 404
    assert app.handle("GET", "/api/history", None, H)[1] == []


def test_job_errors_are_plain_messages(tmp_path):
    cases = [
        (FakeClient(error=sm.OllamaDown(sm.DOWN_MSG)), None, "ollama serve"),
        (FakeClient(error=sm.ModelMissing("Model x is not installed. Run: ollama pull x")), None, "ollama pull"),
        (FakeClient(reply="garbage"), None, "larger model"),
        (None, lambda url: (_ for _ in ()).throw(ft.NoCaptions("no captions here")), "no captions here"),
        (None, lambda url: (_ for _ in ()).throw(ValueError("Not a valid YouTube link: 'x'")), "Not a valid YouTube link"),
        (None, lambda url: (_ for _ in ()).throw(RuntimeError("boom")), "Unexpected error"),
    ]
    for client, fetch, expected in cases:
        job = run_job(make_app(tmp_path, client, fetch))
        assert job["status"] == "error" and expected in job["error"], (expected, job)


def test_bad_requests(tmp_path):
    app = make_app(tmp_path)
    assert app.handle("POST", "/api/youtube/summarize", {"url": ""}, H)[0] == 400
    assert app.handle("POST", "/api/youtube/summarize", None, H)[0] == 400
    assert app.handle("GET", "/api/jobs/unknown", None, H)[0] == 404
    assert app.handle("GET", "/api/nope", None, H)[0] == 404


def test_rejects_foreign_host_and_missing_header(tmp_path):
    app = make_app(tmp_path)
    assert app.handle("GET", "/api/tools", None, {"Host": "evil.example"})[0] == 403
    assert app.handle("POST", "/api/youtube/summarize", {"url": "x"}, {"Host": "localhost:8000"})[0] == 403
    assert app.handle("DELETE", "/api/history/abc", None, {"Host": "127.0.0.1:8000"})[0] == 403
    assert app.handle("GET", "/api/tools", None, {"Host": "127.0.0.1:8000"})[0] == 200


def test_static_serving_and_traversal():
    status, body, ctype = server.serve_static("/")
    assert status == 200 and b"Learning Panel" in body and "text/html" in ctype
    assert server.serve_static("/static/index.html")[0] == 200
    for bad in ("/../server.py", "/static/../server.py", "/..%2fserver.py", "/nope.js"):
        assert server.serve_static(bad)[0] == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests/panel/test_server.py -q`
Expected: FAIL (`No module named 'server'`).

- [ ] **Step 3: Write the implementation**

`panel/static/index.html` (placeholder):
```html
<!doctype html><meta charset="utf-8"><title>Learning Panel</title><p>Loading…</p>
```

`panel/server.py`:
```python
"""Local panel server: JSON API + static files, bound to 127.0.0.1."""
import json
import mimetypes
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
SKILL_DIR = ROOT.parent / ".claude" / "skills" / "yt-summary"
for _p in (str(SKILL_DIR), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fetch_transcript as ft  # noqa: E402
import summarizer as sm  # noqa: E402
import tools  # noqa: E402
from history import HistoryStore  # noqa: E402

STATIC = ROOT / "static"
DEFAULT_MODEL = "qwen3.5:9b"
ALLOWED_HOSTS = ("localhost", "127.0.0.1")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class App:
    def __init__(self, history, client, fetch=None):
        self.history = history
        self.client = client
        self.fetch = fetch or (lambda url: ft.fetch_video(ft.extract_video_id(url)))
        self.jobs = {}
        self.threads = {}

    def handle(self, method, path, body=None, headers=None):
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        host = headers.get("host", "").split(":")[0]
        if host not in ALLOWED_HOSTS:
            return 403, {"error": "Forbidden host"}
        if method != "GET" and headers.get("x-panel") != "1":
            return 403, {"error": "Missing X-Panel header"}
        try:
            return self._route(method, urlparse(path).path, body)
        except ApiError as exc:
            return exc.status, {"error": exc.message}

    def _route(self, method, path, body):
        parts = [p for p in path.split("/") if p]
        if parts[:1] != ["api"]:
            raise ApiError(404, "Not found")
        parts = parts[1:]
        if method == "GET" and parts == ["tools"]:
            return 200, tools.list_tools()
        if method == "GET" and parts == ["models"]:
            try:
                return 200, {"models": self.client.list_models(), "default": DEFAULT_MODEL}
            except sm.OllamaDown as exc:
                return 200, {"models": [], "default": DEFAULT_MODEL, "error": str(exc)}
        if method == "POST" and parts == ["youtube", "summarize"]:
            return 200, {"job_id": self._start_job(body)}
        if method == "GET" and len(parts) == 2 and parts[0] == "jobs":
            job = self.jobs.get(parts[1])
            if not job:
                raise ApiError(404, "Unknown job (the server may have restarted).")
            return 200, dict(job)
        if parts[:1] == ["history"]:
            if method == "GET" and len(parts) == 1:
                return 200, self.history.list()
            if len(parts) == 2:
                if method == "GET":
                    rec = self.history.get(parts[1])
                    if not rec:
                        raise ApiError(404, "No such history item.")
                    return 200, rec
                if method == "DELETE":
                    if not self.history.delete(parts[1]):
                        raise ApiError(404, "No such history item.")
                    return 200, {"deleted": parts[1]}
        raise ApiError(404, "Not found")

    def _start_job(self, body):
        if not isinstance(body, dict) or not isinstance(body.get("url"), str) or not body["url"].strip():
            raise ApiError(400, "Paste a YouTube link first.")
        model = body.get("model") or DEFAULT_MODEL
        if not isinstance(model, str):
            raise ApiError(400, "Invalid model.")
        job_id = uuid.uuid4().hex[:12]
        self.jobs[job_id] = {"status": "fetching", "progress": "fetching captions", "result": None, "error": None}
        thread = threading.Thread(target=self._run, args=(job_id, body["url"].strip(), model), daemon=True)
        self.threads[job_id] = thread
        thread.start()
        return job_id

    def _run(self, job_id, url, model):
        job = self.jobs[job_id]
        started = time.time()
        try:
            video = self.fetch(url)
            transcript = ft.format_transcript(video["segments"])
            job.update(status="summarizing", progress="starting")
            summary = sm.summarize(self.client, model, video["title"], transcript,
                                   progress=lambda msg: job.update(progress=msg))
            record = self.history.add({
                "video_id": video["video_id"], "title": video["title"], "summary": summary,
                "model": model, "seconds": round(time.time() - started),
            })
            job.update(status="done", progress="done", result=record)
        except (ValueError, ft.NoCaptions, sm.OllamaDown, sm.ModelMissing, sm.SummaryFailed) as exc:
            job.update(status="error", error=str(exc))
        except Exception as exc:  # never leave a job hanging
            job.update(status="error", error=f"Unexpected error: {exc}")

    def wait(self, job_id, timeout=10):
        self.threads[job_id].join(timeout)


def serve_static(path):
    rel = unquote(urlparse(path).path)
    rel = "index.html" if rel in ("", "/") else rel.lstrip("/")
    if rel.startswith("static/"):
        rel = rel[len("static/"):]
    target = (STATIC / rel).resolve()
    if STATIC.resolve() not in target.parents or not target.is_file():
        return 404, b"Not found", "text/plain"
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
        ctype += "; charset=utf-8"
    return 200, target.read_bytes(), ctype


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, ctype="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method):
            if method == "GET" and not self.path.startswith("/api/"):
                return self._send(*serve_static(self.path))
            body = None
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    body = json.loads(self.rfile.read(length))
                except ValueError:
                    return self._send(400, json.dumps({"error": "Invalid JSON"}).encode())
            status, obj = app.handle(method, self.path, body, dict(self.headers))
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def log_message(self, fmt, *args):
            pass

    return Handler


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port = int(argv[0]) if argv else int(os.environ.get("PORT", "8000"))
    app = App(HistoryStore(ROOT / "data" / "history.json"), sm.OllamaClient())
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"Learning Panel running at http://localhost:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

`panel/run.sh`:
```bash
#!/usr/bin/env bash
# Start the Learning Panel. Needs Ollama running (ollama serve) with a model pulled.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/../.claude/skills/yt-summary/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q -r "$HERE/../.claude/skills/yt-summary/requirements.txt"
fi
exec "$VENV/bin/python" -W ignore "$HERE/server.py" "$@"
```
Then run `chmod +x panel/run.sh`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests -q`
Expected: all tests (skill tests and panel tests) PASS.

- [ ] **Step 5: Smoke-test the real server**

Run: `PORT=8123 panel/run.sh &` then `curl -s -H 'X-Panel: 1' localhost:8123/api/tools` and `curl -s localhost:8123/api/models`, then stop the server.
Expected: tools JSON with the three tags; models lists the installed `qwen3.5:*` models with `default`.

---

### Task 4: Front end (app shell, YouTube tool, history sidebar)

**Files:**
- Modify (replace): `panel/static/index.html`
- Create: `panel/static/style.css`, `panel/static/app.js`
- Create: `.claude/launch.json`

**Interfaces:**
- Consumes: API from Task 3 exactly as specified (`/api/tools`, `/api/models`, `/api/youtube/summarize`, `/api/jobs/<id>`, `/api/history`, `/api/history/<id>`), sending `X-Panel: 1` and `Content-Type: application/json` on every request.
- Produces: element ids used in checks: `#rail`, `#stage`, `#history-list`, `#yt-url`, `#yt-model`, `#yt-go`, `#yt-result`, `#copy-md`.

There are no automated JS tests in this project; verification is a syntax check plus a browser check (Steps 4-5).

- [ ] **Step 1: Write `panel/static/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Learning Panel</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="app">
  <nav class="rail" id="rail" aria-label="Tools"></nav>
  <main class="stage" id="stage"></main>
  <aside class="history" aria-label="History">
    <h2>History</h2>
    <ul id="history-list"></ul>
  </aside>
</div>
<script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `panel/static/style.css`**

```css
:root {
  --bg: #f5f6f8; --surface: #ffffff; --fg: #16181d; --muted: #565c68; --line: #dde0e6;
  --accent: #0b6e8a; --accent-bg: #e3f1f5; --on-accent: #ffffff;
  --ok: #1a7f37; --ok-bg: #e3f6e8; --warn: #9a5b00; --warn-bg: #fdf0d8; --bad: #b42318;
  --font: system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #101317; --surface: #171b21; --fg: #eceef2; --muted: #9aa1ad; --line: #2a3038;
    --accent: #62c3df; --accent-bg: #12303a; --on-accent: #06222b;
    --ok: #6fd28a; --ok-bg: #12301b; --warn: #f0b95a; --warn-bg: #33270d; --bad: #ff8a80;
    color-scheme: dark;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.55 var(--font); }
.app { display: grid; grid-template-columns: 200px minmax(0, 1fr) 280px; min-height: 100vh; }
.rail, .history { background: var(--surface); padding: 16px; }
.rail { border-right: 1px solid var(--line); display: flex; flex-direction: column; gap: 6px; align-content: start; }
.history { border-left: 1px solid var(--line); }
.stage { padding: 24px 24px 64px; min-width: 0; }
h1 { font-size: 1.35rem; line-height: 1.3; margin: 0 0 4px; text-wrap: balance; }
h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); margin: 0 0 10px; }
button, input, select { font: inherit; color: var(--fg); }
button { cursor: pointer; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.tool-btn { text-align: left; padding: 10px 12px; border: 1px solid transparent; border-radius: 8px; background: none; }
.tool-btn:hover { background: var(--bg); }
.tool-btn.active { background: var(--accent-bg); color: var(--accent); font-weight: 600; }
.form { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.form input { flex: 1 1 280px; min-width: 0; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
.form select { padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
.primary { padding: 10px 18px; border: 0; border-radius: 8px; background: var(--accent); color: var(--on-accent); font-weight: 600; }
.primary:disabled { opacity: 0.55; cursor: progress; }
.tags { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 12px; }
.tag { display: inline-flex; align-items: center; gap: 7px; padding: 6px 11px; border-radius: 9px; font-size: 0.85rem; }
.tag b { font-weight: 600; }
.tag svg { flex: none; }
.tag.local { background: var(--ok-bg); color: var(--ok); }
.tag.network { background: var(--warn-bg); color: var(--warn); }
.status { color: var(--muted); margin: 8px 0; min-height: 1.5em; }
.status.error { color: var(--bad); }
.cost { font-family: var(--mono); font-size: 0.8rem; color: var(--muted); margin: 0 0 6px; overflow-wrap: anywhere; }
.source { margin: 0 0 10px; font-size: 0.9rem; }
.source a, .ts { color: var(--accent); }
.tldr { background: var(--accent-bg); border-radius: 8px; padding: 14px 16px; margin: 0 0 12px; font-size: 1.05rem; }
.toolbar { margin-bottom: 12px; }
.toolbar button { padding: 8px 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
details { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; margin: 8px 0; }
summary { cursor: pointer; padding: 12px 16px; font-weight: 600; display: flex; gap: 12px; align-items: baseline; }
summary span { min-width: 0; overflow-wrap: anywhere; }
.ts { font-family: var(--mono); font-weight: 500; font-size: 0.85rem; white-space: nowrap; }
.body { padding: 0 16px 12px; }
ul { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px; }
#history-list { list-style: none; padding: 0; gap: 4px; }
.hist-item { display: flex; align-items: stretch; gap: 4px; }
.hist-open { flex: 1; min-width: 0; text-align: left; padding: 8px 10px; border: 1px solid transparent; border-radius: 8px; background: none; }
.hist-open:hover { background: var(--bg); }
.hist-open span { display: block; overflow-wrap: anywhere; }
.hist-open small { color: var(--muted); }
.hist-del { border: 0; background: none; color: var(--muted); padding: 0 8px; border-radius: 8px; font-size: 1.1rem; }
.hist-del:hover { color: var(--bad); background: var(--bg); }
.empty { color: var(--muted); font-size: 0.9rem; }
@media (max-width: 900px) {
  .app { grid-template-columns: minmax(0, 1fr); }
  .rail { flex-direction: row; border-right: 0; border-bottom: 1px solid var(--line); overflow-x: auto; }
  .history { border-left: 0; border-top: 1px solid var(--line); }
  .stage { padding: 16px 16px 40px; }
}
```

- [ ] **Step 3: Write `panel/static/app.js`**

```js
"use strict";

const el = (tag, props, ...kids) => {
  const n = document.createElement(tag);
  Object.assign(n, props || {});
  for (const k of kids) n.append(k);
  return n;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fmt(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Panel": "1" } });
  let data = {};
  try { data = await res.json(); } catch (e) { /* non-JSON error body */ }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

/* ---------- info tags ---------- */
const ICON_LOCAL = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="M9 12l2 2 4-4"/></svg>';
const ICON_NET = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/></svg>';

function tagChip(tag, detail) {
  return el("span", { className: `tag ${tag.kind}` },
    el("span", { innerHTML: tag.kind === "local" ? ICON_LOCAL : ICON_NET }),
    el("b", { textContent: tag.kind === "local" ? "Local" : "Network" }),
    el("span", { textContent: `${tag.label} · ${detail || tag.detail}` }));
}

/* ---------- result view ---------- */
const ytLink = (rec, t) => `https://youtu.be/${encodeURIComponent(rec.video_id)}` + (t ? `?t=${t}` : "");
const costLine = (rec) => `cost: free · local · ${rec.model} · ${rec.seconds}s`;

function toMarkdown(rec) {
  const s = rec.summary;
  let md = `# ${rec.title}\n\n> ${s.tldr}\n\n`;
  for (const sec of s.sections) {
    md += `## ${sec.title} ([${fmt(sec.start)}](${ytLink(rec, sec.start)}))\n`;
    md += sec.bullets.map((b) => `- ${b}`).join("\n") + "\n\n";
  }
  if (s.takeaways.length) md += `## Key takeaways\n` + s.takeaways.map((t) => `- ${t}`).join("\n") + "\n";
  return md + `\nSource: ${ytLink(rec, 0)}\n`;
}

async function copyText(text, btn) {
  let ok = true;
  try { await navigator.clipboard.writeText(text); } catch (e) {
    const ta = el("textarea", { value: text });
    document.body.append(ta); ta.select();
    try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
    ta.remove();
  }
  const old = btn.textContent;
  btn.textContent = ok ? "Copied" : "Copy failed";
  setTimeout(() => (btn.textContent = old), 2000);
}

function renderResult(box, rec) {
  const s = rec.summary;
  const copy = el("button", { id: "copy-md", textContent: "Copy as Markdown" });
  copy.onclick = () => copyText(toMarkdown(rec), copy);
  const nodes = [
    el("p", { className: "cost", textContent: costLine(rec) }),
    el("h1", { textContent: rec.title }),
    el("p", { className: "source" }, el("a", { href: ytLink(rec, 0), target: "_blank", rel: "noopener", textContent: "Watch on YouTube" })),
    el("p", { className: "tldr", textContent: s.tldr }),
    el("div", { className: "toolbar" }, copy),
  ];
  s.sections.forEach((sec, i) => {
    const ts = el("a", { className: "ts", href: ytLink(rec, sec.start), target: "_blank", rel: "noopener", textContent: fmt(sec.start), title: "Open the video at this moment" });
    ts.onclick = (e) => e.stopPropagation();
    const ul = el("ul");
    sec.bullets.forEach((b) => ul.append(el("li", { textContent: b })));
    nodes.push(el("details", { open: i === 0 },
      el("summary", null, ts, el("span", { textContent: sec.title })),
      el("div", { className: "body" }, ul)));
  });
  if (s.takeaways.length) {
    const ul = el("ul");
    s.takeaways.forEach((t) => ul.append(el("li", { textContent: t })));
    nodes.push(el("h2", { textContent: "Key takeaways", style: "margin-top:16px" }), ul);
  }
  box.replaceChildren(...nodes);
}

/* ---------- YouTube tool ---------- */
function youtubeView(stage, meta, record) {
  const url = el("input", { id: "yt-url", type: "url", placeholder: "Paste a YouTube link", autocomplete: "off" });
  const model = el("select", { id: "yt-model", title: "Ollama model" });
  const go = el("button", { id: "yt-go", className: "primary", textContent: "Summarize" });
  const tagsBox = el("div", { className: "tags" });
  const status = el("p", { className: "status", role: "status" });
  const out = el("div", { id: "yt-result" });

  const drawTags = () => tagsBox.replaceChildren(...meta.tags.map((t) =>
    tagChip(t, t.label === "Summarizer" ? `Ollama ${model.value || ""}`.trim() : undefined)));
  model.onchange = drawTags;

  const setStatus = (text, isError) => { status.className = isError ? "status error" : "status"; status.textContent = text; };

  async function loadModels() {
    try {
      const data = await api("/api/models");
      model.replaceChildren(...data.models.map((m) => el("option", { value: m, textContent: m })));
      if (data.models.includes(data.default)) model.value = data.default;
      if (data.error) setStatus(data.error, true);
      if (!data.models.length && !data.error) setStatus("No Ollama models found. Run: ollama pull qwen3.5:9b", true);
    } catch (e) { setStatus(e.message, true); }
    drawTags();
  }

  async function run() {
    const link = url.value.trim();
    if (!link) return setStatus("Paste a YouTube link first.", true);
    if (!model.value) return setStatus("No model available. Start Ollama and pull a model.", true);
    go.disabled = true; out.replaceChildren(); setStatus("starting…");
    try {
      const { job_id } = await api("/api/youtube/summarize", { method: "POST", body: JSON.stringify({ url: link, model: model.value }) });
      for (;;) {
        await sleep(1000);
        const job = await api(`/api/jobs/${job_id}`);
        if (job.status === "error") throw new Error(job.error);
        if (job.status === "done") { renderResult(out, job.result); setStatus(""); refreshHistory(); break; }
        setStatus(job.progress || job.status);
      }
    } catch (e) { setStatus(e.message, true); } finally { go.disabled = false; }
  }
  go.onclick = run;
  url.onkeydown = (e) => { if (e.key === "Enter") run(); };

  stage.replaceChildren(
    el("h2", { textContent: meta.name }),
    el("div", { className: "form" }, url, model, go),
    tagsBox, status, out);
  drawTags();
  loadModels();
  if (record) renderResult(out, record);
}

/* ---------- shell: rail, history ---------- */
const VIEWS = { youtube: youtubeView };
const state = { tools: [] };

function openTool(id, record) {
  const meta = state.tools.find((t) => t.id === id);
  if (!meta || !VIEWS[id]) return;
  document.querySelectorAll(".tool-btn").forEach((b) => b.classList.toggle("active", b.dataset.id === id));
  VIEWS[id](document.getElementById("stage"), meta, record);
}

async function refreshHistory() {
  const list = document.getElementById("history-list");
  try {
    const items = await api("/api/history");
    if (!items.length) return list.replaceChildren(el("li", { className: "empty", textContent: "Summaries you make will appear here." }));
    list.replaceChildren(...items.map((it) => {
      const open = el("button", { className: "hist-open" },
        el("span", { textContent: it.title || it.video_id }),
        el("small", { textContent: `${new Date(it.created).toLocaleString()} · ${it.model}` }));
      open.onclick = async () => {
        try { openTool("youtube", await api(`/api/history/${it.id}`)); } catch (e) { list.prepend(el("li", { className: "empty", textContent: e.message })); }
      };
      const del = el("button", { className: "hist-del", textContent: "×", title: "Delete", ariaLabel: `Delete ${it.title}` });
      del.onclick = async () => { try { await api(`/api/history/${it.id}`, { method: "DELETE" }); } catch (e) { /* already gone */ } refreshHistory(); };
      return el("li", { className: "hist-item" }, open, del);
    }));
  } catch (e) { list.replaceChildren(el("li", { className: "empty", textContent: e.message })); }
}

async function init() {
  const rail = document.getElementById("rail");
  try { state.tools = await api("/api/tools"); } catch (e) {
    return document.getElementById("stage").replaceChildren(el("p", { className: "status error", textContent: e.message }));
  }
  rail.replaceChildren(...state.tools.map((t) => {
    const b = el("button", { className: "tool-btn", textContent: t.name });
    b.dataset.id = t.id;
    b.onclick = () => openTool(t.id);
    return b;
  }));
  openTool(state.tools[0].id);
  refreshHistory();
}
init();
```

`.claude/launch.json`:
```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "learning-panel",
      "runtimeExecutable": "panel/run.sh",
      "runtimeArgs": ["8123"],
      "port": 8123
    }
  ]
}
```

- [ ] **Step 4: Syntax check**

Run: `node --check panel/static/app.js && echo OK`
Expected: `OK`.

- [ ] **Step 5: Browser check**

Seed one hostile history record and start the app:
```bash
.claude/skills/yt-summary/.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "panel")
from history import HistoryStore
HistoryStore("panel/data/history.json").add({"video_id": "dQw4w9WgXcQ", "title": "<img src=x onerror=document.title='HACKED'> Test", "model": "qwen3.5:9b", "seconds": 5,
  "summary": {"tldr": "<b>bold?</b>", "sections": [{"title": "S <i>1</i>", "bullets": ["<script>window.__x=1</script>"], "start": 65}], "takeaways": ["t"]}})
EOF
```
Start with `preview_start` name `learning-panel`, then check in the browser at `http://localhost:8123`:
- Left rail shows "YouTube Summarize"; the middle shows URL box, model dropdown (`qwen3.5:9b` selected), Summarize button, and three tags (green Local x2, amber Network x1; the Summarizer tag names the chosen model; changing the dropdown updates it).
- The history sidebar lists the seeded item; clicking it shows the result with the cost line `cost: free · local · qwen3.5:9b · 5s`; the title, TL;DR and bullets appear as literal text (`document.title` must still be "Learning Panel", `window.__x` undefined).
- The timestamp link shows `1:05` and points to `youtu.be/dQw4w9WgXcQ?t=65`; clicking it does not toggle the section; Copy as Markdown flips to "Copied".
- Clicking × deletes the seeded item and the sidebar shows the empty message.
- Empty URL + Summarize shows "Paste a YouTube link first." Layout at 375px width has no horizontal scroll and stacks vertically; dark mode looks correct.
Expected: all true. Fix and re-check anything that isn't.

---

### Task 5: Live run, README, final verification

**Files:**
- Modify: `README.md` (add a "Local panel" section)

- [ ] **Step 1: Live end-to-end run with the real model**

With the server running (`PORT=8123 panel/run.sh`), start a job through the API with a short captioned video and the default model, then poll:
```bash
J=$(curl -s -X POST -H 'X-Panel: 1' -H 'Content-Type: application/json' -d '{"url":"https://youtu.be/jNQXAC9IVRw","model":"qwen3.5:9b"}' localhost:8123/api/youtube/summarize | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
for i in $(seq 1 60); do sleep 3; curl -s localhost:8123/api/jobs/$J -H 'Host: localhost'; echo; done | tail -3
```
Expected: final status `done` with a `result` whose summary has a TL;DR, at least 1 section whose `start` values are real transcript timestamps, and `seconds` recorded. If the job errors, read the message: fix real bugs (e.g. Ollama field names) and add a regression test; if the model output is merely weak, note it.

- [ ] **Step 2: Run the long video through the browser UI**

In the browser at `http://localhost:8123`, paste `https://www.youtube.com/watch?v=5KvY8CnBB3w` (28 minutes, four or more chunks), press Summarize, and watch the progress line change ("reading part 1 of N", …, "writing summary"). Expected: it finishes with a structured result, appears in the history sidebar, and reopens from there after a page reload. Record how long it took.

- [ ] **Step 3: Add the README section**

Append to `README.md`:
```markdown
## Local panel (free, runs on your machine)

An app-style page with a button per tool, a YouTube Summarize tool, and a history sidebar. It uses no credit: captions come from a local Python library and the summary comes from your local Ollama models.

**Needs:** Python 3.9+, [Ollama](https://ollama.com) running (`ollama serve`) with at least one model pulled, e.g. `ollama pull qwen3.5:9b`.

**Start:**

```bash
panel/run.sh
```

Then open http://localhost:8000. Paste a YouTube link, pick a model (9b is fast, 27b is better but slower), press Summarize. Results are saved to `panel/data/history.json` and shown in the right sidebar.

**Info tags** on the YouTube page show what is used: Local (captions library, Ollama) and Network (YouTube title lookup). Only that title lookup and the caption download go to the internet.

**Adding a tool later:** add an entry in `panel/tools.py`, and a view function plus an entry in `VIEWS` in `panel/static/app.js`.
```

- [ ] **Step 4: Final verification**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests -q` and delete any leftover test history records (`panel/data/history.json` should only contain summaries the user wants).
Expected: all tests PASS. Report to the user: how to start, what was verified live, model timing for the short and long video, and any limitations seen (e.g. quality of the 9b model).
