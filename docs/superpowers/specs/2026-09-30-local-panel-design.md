# Local Panel App — Design

Date: 2026-09-30
Builds on: `2026-09-30-yt-summary-design.md` (the `/yt-summary` skill stays unchanged).

## Goal
A local, application-style page: one screen with a button per feature, a tool view in the middle, and a history sidebar on the right. First feature: YouTube Summarize (paste URL, get the structured summary). Zero credit spent: everything runs on the user's machine.

## Decisions (from the user)
- No Apify, no Claude/API in the loop; use local components wherever possible.
- Runs as a local app in this folder (`panel/`), opened at `http://localhost:8000`. Not a published artifact (artifacts cannot reach local Ollama or run Python).
- Summarizer: local Ollama, default model `qwen3.5:9b`; the model list comes from what Ollama has installed (`qwen3.5:2b`, `9b`, `27b` present).
- The YouTube input page shows information-only tags naming the third parties used, styled as small colored pills with an icon (see reference image): 
  - "YouTube captions · youtube-transcript-api" — tag **Local**
  - "Summarizer · Ollama <model>" — tag **Local**
  - "Video title · YouTube oEmbed" — tag **Network** (the only outside call)
- Each result shows a cost line at the top: `cost: free · local · <model> · <seconds>s`.
- App summaries are saved only in the app's own history file (not in Claude).

## Architecture
Python standard-library HTTP server (`http.server`, no new dependencies) bound to `127.0.0.1` only, serving a static front end and a small JSON API. Reuses `.claude/skills/yt-summary/fetch_transcript.py` (captions, video id, title) and `build_page.validate_summary` (summary validation) by import.

```
panel/
  server.py        # routes, job runner, static files
  summarizer.py    # Ollama client, chunking, merge, timestamp check
  history.py       # JSON-file store: add/list/get/delete
  tools.py         # server-side tool registry (id, name, tags)
  static/
    index.html  app.js  style.css   # shell + YouTube tool
  data/history.json                  # created on first save
  run.sh                             # starts the server
tests/panel/...
```

## API
- `GET /` and `/static/*` — front end.
- `GET /api/tools` — `[{id, name, tags:[{label, kind:"local"|"network", detail}]}]`.
- `GET /api/models` — installed Ollama models (from `http://localhost:11434/api/tags`); error object if Ollama is down.
- `POST /api/youtube/summarize` `{url, model}` — starts a background job, returns `{job_id}`.
- `GET /api/jobs/<id>` — `{status: "fetching"|"summarizing"|"done"|"error", progress: "part 2 of 4", result?, error?}`.
- `GET /api/history` — newest first `[{id, title, video_id, created, model, seconds}]`; `GET /api/history/<id>` — full record; `DELETE /api/history/<id>`.

## Pipeline
1. Fetch captions with `fetch_transcript` (title via oEmbed, falls back to video id).
2. Split the timestamped transcript into chunks of about 12,000 characters. One chunk: ask Ollama (`/api/chat`, `think: false`, JSON-schema `format`) for the summary JSON directly. Several chunks: ask for notes per chunk, then a final merge call that returns the summary JSON.
3. Schema = current summary shape (`tldr`, `sections[]` with `title`, `bullets[]`, `start` int seconds, `takeaways[]`). Section `start` values are snapped to the nearest real transcript timestamp; out-of-range values are clamped.
4. Validate with `validate_summary`; on a bad result retry once, then fail with a clear message.
5. Save the record (`id`, `video_id`, `title`, `summary`, `model`, `seconds`, `created`) to `panel/data/history.json` and return it.

## UI
- Left rail: one button per tool from `/api/tools` (only YouTube Summarize now). A tool is a small JS object `{id, render(container)}` in a list, so adding a tool later means adding one entry plus one server registry entry.
- Middle: URL input, model dropdown, Summarize button, tags row, progress line, then the result (TL;DR, collapsible sections, timestamp links opening `youtu.be/<id>?t=N` in a new tab, Copy as Markdown, cost line).
- Right sidebar: history list; click reopens the saved result; delete button per item.
- All model/transcript-derived text is rendered with `textContent` (no HTML injection). Responsive, light/dark via `prefers-color-scheme`.

## Error handling (plain-language messages)
- Ollama not running → "Start Ollama (`ollama serve`) and try again."
- Model missing → name it and show `ollama pull <model>`.
- No captions / blocked network / invalid link → messages from `fetch_transcript`.
- Bad model JSON → one retry, then "The model returned an unusable summary; try a larger model."
- Job unknown/expired → clear message. Server restart drops in-flight jobs (history is kept).

## Testing
- Unit: history store (add/list/get/delete, corrupt file recovery), chunking, timestamp snapping/clamping, summary retry logic with a fake Ollama client, API routes with a fake summarizer, tool registry.
- Live: one run against real `qwen3.5:9b` on a short captioned video; browser check of the page (layout, sidebar, dark mode, copy button).

## Out of scope
More tools now, logins/sharing, downloading models, changing the `/yt-summary` skill.

## Run
`panel/run.sh` (creates/uses the existing venv, starts the server). README gets a "Local panel" section: requirements (Python 3.9+, Ollama running with a model pulled) and the start command.
