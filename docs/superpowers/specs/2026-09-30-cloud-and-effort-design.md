# Cloud summarizer, effort levels, Home page — Design

Date: 2026-09-30
Builds on: `2026-09-30-local-panel-design.md` (panel, jobs, progress, abort, Free pill all exist).

## Goal
Let the user choose, per summary, between free local models and paid cloud (Claude) models, each in three effort levels (Easy / Medium / Hard), with the cost and machine-load implications visible. Store the user's Anthropic API key locally and safely.

## Decisions (from the user, all approved)
- Cloud access uses the **Anthropic API with the user's own API key** (option B). No Apify, no Claude Code CLI.
- The key is entered on the panel's first page and kept locally with restricted access: **macOS Keychain**.
- Local models stay; each gets an effort label that shows the pressure on the Mac. Cloud models are added.
- Tag rules follow the selected option: a fully free option shows the green **Free** pill; a cloud option drops the Free pill and puts a **$** next to the name of the tag that costs.

## Home page (panel opens here)
- Rail: **Home** first, then tools. Home shows one button/card per tool (each with its Free and/or $ marks) and an **Anthropic API key** card.
- Key card (updated by the user after approval): password-type input and **Test & save**. Once saved, the field shows only a fixed star mask (nothing real to copy) and the button says **Update**; to change the key the user clears the field, pastes the new key and presses Update. There is no Remove button (the DELETE endpoint remains; the item can also be removed in Keychain Access). A rejected new key leaves the old key saved. The key is validated with a free Anthropic call (`GET /v1/models`) before it is stored; a rejected key is not stored.
- Choosing a cloud option with no saved key shows "Add your API key on Home".

## Effort dropdown (YouTube tool, next to the URL; replaces the model dropdown)
| Group | Easy | Medium (default) | Hard |
|---|---|---|---|
| On this Mac (free) | qwen3.5:2b · low load | qwen3.5:9b · medium load | qwen3.5:27b · high load |
| Cloud ($) | claude-haiku-4-5-20251001 · Haiku 4.5 | claude-sonnet-5-5 · Sonnet 5.5 | claude-opus-5-5 · Opus 5.5 |
- Default selection: Medium, on this Mac. Cloud rows show "no load on your Mac". Cloud rows are disabled until a key is saved; local rows are disabled with "not installed" when Ollama lacks the model.
- Request: `POST /api/youtube/summarize {url, option}` where `option` is an id such as `local-medium` or `cloud-easy`. Unknown option → 400. (Legacy `model` field still accepted for local models.)
- Hint line: "Easy = fastest and cheapest · Hard = best quality, slowest, most load or cost".

## Tags and pills (follow the selected option)
- Tags: `YouTube captions · youtube-transcript-api` (Network), `Video title · YouTube oEmbed` (Network), and Summarizer: `Ollama <model>` (Local) or `Claude <model> $` (Network, paid).
- Tool pill: green **Free** when every tag of the selected option is unpaid; no Free pill otherwise. On Home and the rail a tool that offers both modes shows **Free** and **$**.
- Registry: tags carry `paid: true` for cloud; `tools.is_free(option)` decides the pill.

## Key storage (`keystore.py`)
- macOS Keychain through the `security` command: service `LearningPanel Anthropic API key`, account = current user. Functions: `get_key()`, `set_key(key)`, `delete_key()`, `status()` → `{saved, last4}`.
- The key is never written to the project folder, history, logs, job records or API responses, and error text is scrubbed of it. The browser gets only `{saved, last4}`.
- Endpoints: `GET /api/settings/key` → status; `POST /api/settings/key {key}` → validates format (`sk-ant-` prefix) and with Anthropic, then stores; `DELETE /api/settings/key`. Same Host and `X-Panel` protections as the rest of the API.
- Known limit (documented for the user): Keychain protects the key at rest; software running as the user could still request it. Recommend a dedicated key with a monthly spend limit.

## Cloud client (`AnthropicClient` in `summarizer.py`)
- Anthropic Messages API over HTTPS (`api.anthropic.com`, `x-api-key`, `anthropic-version: 2023-06-01`), standard-library `http.client`; base URL injectable for tests.
- Same interface as the Ollama client: `chat(model, messages, schema=None, token=None)`. System messages go in the `system` field; when a schema is given, JSON is obtained through a forced tool call whose `input_schema` is the summary schema.
- Reuses `CancelToken`: Abort closes the HTTPS socket. Tracks `input_tokens` / `output_tokens` across a job's calls.
- Errors in plain language: no key, key rejected (401), rate limited / overloaded (429/529: "try again shortly"), out of credit, network down. Key value never appears in messages.
- `unload` is a no-op for cloud (nothing to free).

## Jobs, results, history
- The job picks the client from the option; local behaviour is unchanged. Progress stages and Abort are shared.
- A history record stores `option`, `model`, `provider` ("local" | "cloud"), and for cloud `tokens_in` / `tokens_out`.
- Cost line: local `cost: free · local · Medium · qwen3.5:9b · 74s`; cloud `cost: $ · Sonnet 5.5 · 12,340 in / 1,020 out tokens · 9s` (tokens, not dollars, because current prices are not known to the app). Old records without these fields still render.
- Privacy: cloud runs send the transcript to Anthropic (stated next to the Network tag and in the README).

## Errors (plain language)
Cloud selected with no key → prompt to add it. Key rejected → "Anthropic rejected this key." Keychain unavailable → "Could not read the Keychain." Everything else as in the panel spec.

## Testing
- Unit: keystore against a fake `security` runner (never touches the real Keychain); option table and pill/tag rules; option→client/model mapping and 400s; cloud client against a fake local Anthropic server (request shape, tool-forced JSON, token counts, 401/429/529, abort under a hanging server, key scrubbed from errors); key endpoints (validation, no key in any response); history fields and old-record rendering.
- Browser: Home, key card states, dropdown groups/disabled rows, tag `$` and Free pill switching, abort still works.
- Live: local Easy run still works. The real cloud run needs the user's key: the user enters it in the panel themselves (never in chat) and runs one summary; documented in the README.

## Out of scope
Dollar-cost estimates, streaming progress, other providers, using the Claude Code CLI, multiple keys, editing prices.
