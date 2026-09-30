# YouTube Summary Skill — Design

Date: 2026-09-30

## Goal
Run `/yt-summary <youtube-link>` in Claude and get a structured, skimmable summary of the video as an interactive artifact page, for fast learning.

## Constraints
- Personal use, keep it simple.
- Browser pages cannot fetch YouTube transcripts (blocked), so fetching happens in the skill on the local machine; the artifact only displays the result.
- Claude does the summarizing itself: no separate API key.

## Approach
One self-contained artifact page per video (transcript fetched locally, summary JSON embedded in an HTML template, published as an artifact). No database.

## Components (project skill at `.claude/skills/yt-summary/`)
- `SKILL.md` — instructions Claude follows for `/yt-summary <link>`.
- `fetch_transcript.py` — takes a URL, extracts the video ID, returns title + transcript segments with timestamps (via `youtube-transcript-api`).
- `template.html` — interactive UI with a placeholder for the summary JSON.

## Flow
1. User runs `/yt-summary <link>`.
2. Script fetches transcript + timestamps.
3. Claude writes JSON: `tldr` (one line), `sections[]` (3–7; each with `title`, `bullets[]`, `start` seconds), `takeaways[]`.
4. JSON is embedded into `template.html` and published as an artifact.
5. Claude replies with the link and a 2-line gist.

## UI
- TL;DR at top; collapsible/expandable sections below.
- Embedded YouTube player; clicking a section timestamp seeks the player.
- "Copy as Markdown" and "Download .md" buttons.
- Responsive for phone; supports light/dark mode.

## Error handling
- No captions: clear message, stop (Whisper fallback is out of scope for v1).
- Videos over ~2 hours: transcript chunked before summarizing.
- Invalid URL: plain error message.

## Testing
- Script on one short captioned video and one without captions.
- Render page in browser: timestamp seek, collapse/expand, copy button.

## Phase 2 (nice-to-have, after v1 works)
History of summarized videos: the skill appends `{title, url, artifact link, date}` to a local `history.json` and can publish/refresh an index page listing past summaries. Designed as an add-on; v1 does not depend on it.

## Out of scope
Quiz mode, Q&A follow-ups, Whisper audio transcription.
