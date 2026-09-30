# Learning Panel (YouTube Summarize): project brief

Local web app: paste a YouTube link, get a structured summary (TL;DR, sections with timestamp links, takeaways). Goal: fast learning while **saving credit**: free local Ollama by default, optional paid cloud Claude via the user's own OpenRouter or Anthropic key. Never use Apify or other paid services.

## Where things are
- `README.md`: minimal user guide (3-line run script, port, which cloud key is accepted, limits, troubleshooting, dev, tech-stack table last). Keep it minimal.
- `docs/architecture.md`: stack and versions, components, how a summary is made, model routing, API table, storage, security, known limits. **Update it (and the README) when stack, endpoints or storage change.**
- `docs/superpowers/specs|plans/`: design specs and plans (process record; no git, so do not delete).
- `panel/` code, `tests/` (`.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests -q`, 191 pass), `.claude/skills/yt-summary/` (older Claude-run `/yt-summary` route that uses Claude credit; the panel shares its venv, `fetch_transcript.py`, `build_page.py`; do not delete).

## Run
`panel/setup.sh` checks Python 3.9+, the venv library, Ollama installed and running, and a qwen3.5 model, installing what is missing (Homebrew, pip, `ollama pull qwen3.5:9b`; never installs Homebrew itself; `--check` installs nothing). `panel/run.sh [localhost:number]` runs the quiet setup then starts the server (default port 8000; `PANEL_SKIP_SETUP=1` skips). Claude's preview launcher cannot start it (macOS blocks ~/Documents): start from a shell.

## Rules and decisions from the user (keep)
- **Models are fixed:** local Easy/Medium/Hard = qwen3.5:2b/9b/27b (low/medium/high load); cloud Easy/Medium/Hard = Haiku 4.5 / Sonnet 5.5 / Opus 5.5 (OpenRouter ids `anthropic/claude-haiku-4.5`, `-sonnet-5.5`, `-opus-5.5`). Do not add models without being asked.
- **One API key at a time**, entered by the user in the panel's Home key card (never ask for it in chat). Accepts `sk-or-` (OpenRouter) and `sk-ant-` (Anthropic); plain OpenAI keys are refused with an explanation. Stored in the macOS Keychain via `security -i` (never in argv); the page only gets `{saved, last4, provider}`; saved state shows a fixed star mask and an **Update** button (no Remove button); a rejected new key leaves the old one.
- **Abort is local-only.** Cloud requests cannot be cancelled once sent (may still bill): cloud jobs have `can_abort: false`, the button is hidden, the abort route returns 409.
- **Tags:** left rail and Home cards show only `Local` and `API`. The tool title shows a green Free pill for local selections; cloud selections drop it and put `$` on the Summarizer tag ("via OpenRouter" when that key is used). Cost line: local `free · local · <Effort> · <model> · <s>s`; cloud `≈ $x · <model> [via OpenRouter] · N in / M out tokens · <s>s` (estimate from OpenRouter's public price list).
- **YouTube page layout:** one bordered input card (title, link, effort dropdown, Summarize/Abort, hint, tags, progress, status); the summary is a separate area below a divider labelled "Summary".
- **History:** small text, a single trash-icon delete button, and a feature icon per item. An item is highlighted exactly while its summary shows in the middle (`present()`/`clearShown()`/`markSelected()`); nothing is highlighted on Home; the last shown summary is remembered in localStorage and reopened after a reload (a running job wins).
- **Icon theme (project only, not global):** every icon is outline, 24x24, 2px round stroke, `currentColor`, no fills or hard-coded colors, all defined in `panel/static/icons.js` (`ICON_SHAPES`, `iconSvg`); no inline `<svg>` elsewhere; brand tint via a CSS token (`--brand-youtube`). `tests/panel/test_icon_theme.py` enforces it.
- Render all model/transcript/title text with `textContent`; the server listens on 127.0.0.1 only.
- Status markers (✅ ❗️ ‼️ ⚠️ ❔) come from the user's personal `~/.claude/CLAUDE.md`.

## Working style that worked
Brainstorm, short design for approval, spec and plan for new subsystems, execute natively with tests first, then one fresh review for security-relevant work. Bounded changes get a short in-chat design and a wait for a clear yes. When a layout or ordering instruction can be read two ways, confirm or cover both (two misreadings happened).

## Verified
Live: local runs on 2b/9b, 28-minute video (9b, about 74 s), Abort (model unloads), reload/reattach, real key rejection by OpenRouter and Anthropic (fake keys), OpenAI key refusal, and **the user's own real cloud run** (OpenRouter, Haiku 4.5, 32 s, 10,931 in / 2,190 out tokens, about $0.022). Setup script: tested only with stand-in commands plus a real run where everything was already installed.

## Not done / deferred
Not verified: a real fresh-Mac install through `setup.sh`; a 4-hour video; the front end has no automated tests (checked in the browser). Minor issues: no timeout on the caption download; slow-model timeout shows the "start Ollama" message; odd OS usernames can stop startup; jobs and their clients stay in memory until restart; odd cloud reply shapes give generic error text; key state is not refreshed if changed outside the panel; a negative Content-Length can pin a thread. The OpenRouter/setup/port increments had no separate fresh-context review.
