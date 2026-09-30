# Cloud Summarizer, Effort Levels, Home Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Home page with an Anthropic API key card (key kept in the macOS Keychain), and an Easy/Medium/Hard effort dropdown listing free local models and paid cloud (Claude) models, with Free/$ tags that follow the selected option.

**Architecture:** New `keystore.py` (Keychain via `security -i`, key never in argv), new `cloud.py` (Anthropic Messages API client with the same `chat()` interface as the Ollama client, tool-forced JSON, token counts, abort via the existing `CancelToken`), an option table in `tools.py`, server routes for the key and for `option`-based jobs, and a rewritten front-end shell (Home, key card, grouped dropdown).

**Tech Stack:** Python 3.9 standard library only, macOS `security` command, Anthropic Messages API over HTTPS, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-09-30-cloud-and-effort-design.md` (builds on `2026-09-30-local-panel-design.md`; all existing panel code and 79 tests are the starting point).

## Global Constraints

- Code in `panel/`, tests in `tests/panel/`; Python 3.9 compatible (no `X | Y` type unions, no `match`); standard library only.
- The API key value must never appear in: any API response (only `{saved, last4}`), history, job dicts, logs, error text, the project folder, or a command's argv (`security` gets it on stdin through `security -i`). Only format-valid keys (`^sk-ant-[A-Za-z0-9_-]{20,200}$`) reach any command or request.
- Tests never touch the real Keychain or the real Anthropic API (fake runner, fake local HTTP server). The real cloud run is done by the user with their own key entered in the panel.
- Cloud request host is `api.anthropic.com` over HTTPS, header `x-api-key`, `anthropic-version: 2023-06-01`.
- Option ids and models (exact): `local-easy` qwen3.5:2b (low load), `local-medium` qwen3.5:9b (medium load, default), `local-hard` qwen3.5:27b (high load); `cloud-easy` claude-haiku-4-5-20251001 "Haiku 4.5", `cloud-medium` claude-sonnet-5-5 "Sonnet 5.5", `cloud-hard` claude-opus-5-5 "Opus 5.5".
- Tag rules: local option → green Free pill, Summarizer tag `Ollama <model>` (local); cloud option → no Free pill, Summarizer tag `Claude <name>` with a `$` (network, `paid: true`). Captions and title tags stay Network, unpaid.
- Cost lines: local `cost: free · local · <Effort> · <model> · <s>s` (effort omitted for old records); cloud `cost: $ · <name> · <in> in / <out> out tokens · <s>s`. Tokens, not dollars.
- All text rendered with `textContent` (never `innerHTML`, except constant SVG icons).
- Not a git repo: no commit steps. Existing tests must keep passing except where a task explicitly updates one.
- Test command: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests -q`.

## Review Focus

- The key never leaks: not in any response, history record, job dict, error message, log line, or argv; a key containing quotes, spaces, newlines or shell metacharacters is rejected before any command runs (Tasks 1, 4 tests).
- Every cloud failure (401 rejected key, 429/529 overloaded, out of credit, no internet) ends the job with a plain message and never hangs (Tasks 3, 4 tests).
- Abort during a cloud request returns immediately, saves nothing, and does not break local abort (Task 3 test + Task 6 check).
- Choosing a cloud option with no saved key, removing the key while the page is open, or an unknown option id gives a clear message, not a crash (Task 4 tests + Task 5 browser check).
- Old history records (no effort/provider/tokens fields) still list, open, and show a sensible cost line (Tasks 2, 5).

---

## File Structure

```
panel/keystore.py      # Keystore: get/set/delete/status on the macOS Keychain
panel/cloud.py         # AnthropicClient, CloudError, check_key
panel/tools.py         # + options table, tags per option, has_free/has_paid   (modify)
panel/history.py       # + effort/provider/model_name list keys                (modify)
panel/server.py        # + key routes, option-based jobs, cloud client         (modify)
panel/static/app.js    # + Home, key card, grouped dropdown, dynamic tags/pill (modify)
panel/static/style.css # + cards, key card, dollar mark                        (modify)
tests/panel/conftest.py (+fake_anthropic fixture) test_keystore.py test_cloud.py test_options.py; extend test_server.py test_history.py test_tools.py
```

---

### Task 1: Keychain key store

**Files:**
- Create: `panel/keystore.py`
- Test: `tests/panel/test_keystore.py`

**Interfaces:**
- Produces:
  - `valid_key_format(key: str) -> bool`
  - `KeystoreError(Exception)` (plain messages, never contain the key)
  - `Keystore(run=None, account=None)`: `get_key() -> str|None`, `set_key(key) -> None` (raises `ValueError` for a bad-format key before running anything; `KeystoreError` on Keychain failure; verifies by reading back), `delete_key() -> None`, `status() -> {"saved": bool, "last4": str|None}`.
  - A `run(args: list, input: str|None) -> obj with returncode, stdout, stderr` callable is injectable (default runs `subprocess.run(..., capture_output=True, text=True, timeout=15)`).

- [ ] **Step 1: Write the failing tests**

`tests/panel/test_keystore.py`:
```python
import shlex
from types import SimpleNamespace

import pytest

import keystore as ks

KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"


class FakeSecurity:
    """In-memory stand-in for the `security` command."""

    def __init__(self, fail_write=False):
        self.items, self.calls, self.fail_write = {}, [], fail_write

    def __call__(self, args, input=None):
        self.calls.append((list(args), input))
        if args[:2] == ["security", "find-generic-password"]:
            k = self.items.get("key")
            return SimpleNamespace(returncode=0 if k else 44, stdout=(k + "\n") if k else "", stderr="")
        if args == ["security", "-i"]:
            words = shlex.split(input)
            assert words[0] == "add-generic-password"
            if self.fail_write:
                return SimpleNamespace(returncode=1, stdout="", stderr="denied")
            self.items["key"] = words[words.index("-w") + 1]
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:2] == ["security", "delete-generic-password"]:
            existed = self.items.pop("key", None)
            return SimpleNamespace(returncode=0 if existed else 44, stdout="", stderr="")
        raise AssertionError(args)


def test_round_trip_and_status():
    sec = FakeSecurity()
    store = ks.Keystore(run=sec, account="tester")
    assert store.get_key() is None and store.status() == {"saved": False, "last4": None}
    store.set_key(KEY)
    assert store.get_key() == KEY
    assert store.status() == {"saved": True, "last4": KEY[-4:]}
    store.delete_key()
    assert store.get_key() is None
    store.delete_key()  # deleting nothing is fine


def test_key_is_never_in_argv_only_on_stdin():
    sec = FakeSecurity()
    ks.Keystore(run=sec, account="tester").set_key(KEY)
    for args, stdin in sec.calls:
        assert KEY not in " ".join(args)
    assert any(stdin and KEY in stdin for _, stdin in sec.calls)


@pytest.mark.parametrize("bad", [
    "", "   ", "sk-ant-short", 'sk-ant-abcdefghijklmnopqrstuvwxyz" ; delete-generic-password -a x',
    "sk-ant-abcdefghijklmnopqrstuvwxyz\nadd-generic-password", "sk-ant-abcdefghij klmnopqrstuvwxyz",
    "sk-ant-abcdefghijklmnopqrstuvwxyz`id`", "sk-ant-abcdefghijklmnopqrstuvwxyz$(id)", "not-a-key" * 5,
])
def test_bad_keys_never_reach_the_security_command(bad):
    sec = FakeSecurity()
    with pytest.raises(ValueError):
        ks.Keystore(run=sec, account="tester").set_key(bad)
    assert sec.calls == []
    assert ks.valid_key_format(bad) is False


def test_keychain_failure_message_has_no_key():
    store = ks.Keystore(run=FakeSecurity(fail_write=True), account="tester")
    with pytest.raises(ks.KeystoreError) as exc:
        store.set_key(KEY)
    assert KEY not in str(exc.value) and "Keychain" in str(exc.value)


def test_write_that_silently_did_not_stick_is_an_error():
    class Liar(FakeSecurity):
        def __call__(self, args, input=None):
            if args == ["security", "-i"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return super().__call__(args, input)

    with pytest.raises(ks.KeystoreError):
        ks.Keystore(run=Liar(), account="tester").set_key(KEY)


def test_unusual_account_names_are_rejected():
    with pytest.raises(ks.KeystoreError):
        ks.Keystore(run=FakeSecurity(), account='mo"lly')

- [ ] **Step 2: Run tests to verify they fail**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests/panel/test_keystore.py -q`
Expected: FAIL (`No module named 'keystore'`).

- [ ] **Step 3: Write the implementation**

`panel/keystore.py`:
```python
"""Anthropic API key in the macOS Keychain, through the `security` command.

The key is only ever passed on stdin (`security -i`), never in the command line,
so it does not show up in the process list.
"""
import getpass
import re
import subprocess

SERVICE = "LearningPanel Anthropic API key"
KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_-]{20,200}$")
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
NOT_FOUND = 44


class KeystoreError(Exception):
    pass


def valid_key_format(key):
    return isinstance(key, str) and bool(KEY_RE.match(key))


def _run(args, input=None):
    return subprocess.run(args, input=input, capture_output=True, text=True, timeout=15)


class Keystore:
    def __init__(self, run=None, account=None):
        self._run = run or _run
        self.account = account or getpass.getuser()
        if not ACCOUNT_RE.match(self.account):
            raise KeystoreError("Could not use this account name with the Keychain.")

    def _call(self, args, input=None):
        try:
            return self._run(args, input=input)
        except (OSError, subprocess.SubprocessError) as exc:
            raise KeystoreError("Could not reach the Keychain.") from exc

    def get_key(self):
        proc = self._call(["security", "find-generic-password", "-a", self.account, "-s", SERVICE, "-w"])
        if proc.returncode == NOT_FOUND:
            return None
        if proc.returncode != 0:
            raise KeystoreError("Could not read the Keychain.")
        return proc.stdout.strip() or None

    def set_key(self, key):
        if not valid_key_format(key):
            raise ValueError("That does not look like an Anthropic API key (it starts with sk-ant-).")
        command = f'add-generic-password -a "{self.account}" -s "{SERVICE}" -w "{key}" -U\n'
        proc = self._call(["security", "-i"], input=command)
        if proc.returncode != 0 or self.get_key() != key:
            raise KeystoreError("Could not save the key to the Keychain.")

    def delete_key(self):
        proc = self._call(["security", "delete-generic-password", "-a", self.account, "-s", SERVICE])
        if proc.returncode not in (0, NOT_FOUND):
            raise KeystoreError("Could not remove the key from the Keychain.")

    def status(self):
        key = self.get_key()
        return {"saved": bool(key), "last4": key[-4:] if key else None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests/panel/test_keystore.py -q`
Expected: all PASS.

- [ ] **Step 5: One-time smoke test of the real `security -i` mechanism (dummy value, then cleaned up)**

The unit tests use a fake `security`, so prove the real command behaves the way the code assumes, using a throwaway service name and a dummy value (never a real key):
```bash
printf 'add-generic-password -a "plan-smoke" -s "LearningPanel-smoke-test" -w "dummy-value-123" -U\n' | security -i; echo "add rc=$?"
security find-generic-password -a plan-smoke -s LearningPanel-smoke-test -w; echo "find rc=$?"
security delete-generic-password -a plan-smoke -s LearningPanel-smoke-test >/dev/null; echo "delete rc=$?"
security find-generic-password -a plan-smoke -s LearningPanel-smoke-test -w >/dev/null 2>&1; echo "find-after-delete rc=$?"
```
Expected: add rc=0, find prints `dummy-value-123` with rc=0, delete rc=0, find-after-delete rc=44. If `security -i` reports success differently (e.g. exit 0 on failure), the read-back check in `set_key` already covers it; if rc for "not found" is not 44, change `NOT_FOUND` and re-run tests. Nothing real is stored by this step.

---

### Task 2: Option table, tags and pills

**Files:**
- Modify: `panel/tools.py`, `panel/history.py`
- Test: `tests/panel/test_options.py`; update `tests/panel/test_history.py`

**Interfaces:**
- Produces:
  - `tools.OPTIONS` (list of dicts): `{"id","provider":"local"|"cloud","effort":"Easy|Medium|Hard","model","name","load","tag"}`; `tag` is the Summarizer tag for that option. `tools.DEFAULT_OPTION = "local-medium"`; `tools.get_option(option_id) -> dict|None`.
  - `tools.list_tools()` youtube entry additionally has `options`, `default_option`, `has_free` (bool), `has_paid` (bool); existing `tags` (with the default option's Summarizer tag), `stages`, `bounds`, `free` are unchanged in meaning (`free` = default option is free).
  - `tools.option_is_free(tool, option) -> bool`: true when no tag of the tool (with the Summarizer tag replaced by the option's tag) has `paid: true`.
  - `history.LIST_KEYS` gains `"effort", "provider", "model_name"`.

- [ ] **Step 1: Write the failing tests**

`tests/panel/test_options.py`:
```python
import tools


def yt():
    return tools.get_tool("youtube")


def test_six_options_with_exact_models():
    got = {o["id"]: (o["provider"], o["effort"], o["model"], o["name"], o["load"]) for o in tools.OPTIONS}
    assert got == {
        "local-easy": ("local", "Easy", "qwen3.5:2b", "qwen3.5:2b", "low"),
        "local-medium": ("local", "Medium", "qwen3.5:9b", "qwen3.5:9b", "medium"),
        "local-hard": ("local", "Hard", "qwen3.5:27b", "qwen3.5:27b", "high"),
        "cloud-easy": ("cloud", "Easy", "claude-haiku-4-5-20251001", "Haiku 4.5", None),
        "cloud-medium": ("cloud", "Medium", "claude-sonnet-5-5", "Sonnet 5.5", None),
        "cloud-hard": ("cloud", "Hard", "claude-opus-5-5", "Opus 5.5", None),
    }
    assert tools.DEFAULT_OPTION == "local-medium"
    assert tools.get_option("nope") is None


def test_summarizer_tag_per_option():
    local = tools.get_option("local-hard")["tag"]
    assert local == {"label": "Summarizer", "detail": "Ollama qwen3.5:27b", "kind": "local"}
    cloud = tools.get_option("cloud-medium")["tag"]
    assert cloud == {"label": "Summarizer", "detail": "Claude Sonnet 5.5", "kind": "network", "paid": True}


def test_free_only_for_local_options():
    tool = yt()
    assert all(tools.option_is_free(tool, o) for o in tools.OPTIONS if o["provider"] == "local")
    assert not any(tools.option_is_free(tool, o) for o in tools.OPTIONS if o["provider"] == "cloud")


def test_tool_summary_flags():
    tool = yt()
    assert tool["has_free"] is True and tool["has_paid"] is True
    assert tool["default_option"] == "local-medium" and tool["free"] is True
    assert len(tool["options"]) == 6
    assert {t["label"] for t in tool["tags"]} == {"YouTube captions", "Summarizer", "Video title"}
```
Update `tests/panel/test_history.py::test_add_list_get_delete`: the expected key set becomes `{"id", "title", "video_id", "created", "model", "seconds", "effort", "provider", "model_name"}`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests/panel/test_options.py tests/panel/test_history.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `panel/history.py` change:
```python
LIST_KEYS = ("id", "title", "video_id", "created", "model", "seconds", "effort", "provider", "model_name")
```

In `panel/tools.py` replace the file with:
```python
"""Server-side registry of the panel's tools: info tags, progress stages, summarizer options."""

_LOCAL = [("Easy", "qwen3.5:2b", "low"), ("Medium", "qwen3.5:9b", "medium"), ("Hard", "qwen3.5:27b", "high")]
_CLOUD = [
    ("Easy", "claude-haiku-4-5-20251001", "Haiku 4.5"),
    ("Medium", "claude-sonnet-5-5", "Sonnet 5.5"),
    ("Hard", "claude-opus-5-5", "Opus 5.5"),
]

OPTIONS = [
    {"id": f"local-{effort.lower()}", "provider": "local", "effort": effort, "model": model, "name": model,
     "load": load, "tag": {"label": "Summarizer", "detail": f"Ollama {model}", "kind": "local"}}
    for effort, model, load in _LOCAL
] + [
    {"id": f"cloud-{effort.lower()}", "provider": "cloud", "effort": effort, "model": model, "name": name,
     "load": None, "tag": {"label": "Summarizer", "detail": f"Claude {name}", "kind": "network", "paid": True}}
    for effort, model, name in _CLOUD
]
DEFAULT_OPTION = "local-medium"

_BASE_TAGS = [
    {"label": "YouTube captions", "detail": "youtube-transcript-api", "kind": "network"},
    {"label": "Summarizer", "detail": "Ollama", "kind": "local"},
    {"label": "Video title", "detail": "YouTube oEmbed", "kind": "network"},
]

TOOLS = [
    {
        "id": "youtube",
        "name": "YouTube Summarize",
        "tags": _BASE_TAGS,
        # progress stages shown to the user, and the percent range each one covers
        "stages": ["Accessing YouTube", "Reading captions", "Summarizing", "Finishing"],
        "bounds": [[0, 8], [8, 15], [15, 92], [92, 100]],
        "options": OPTIONS,
        "default_option": DEFAULT_OPTION,
    },
]


def get_option(option_id):
    return next((o for o in OPTIONS if o["id"] == option_id), None)


def is_free(tool):
    """A tool (a dict with tags) is free when none of its tags is marked paid."""
    return not any(t.get("paid") for t in tool.get("tags", []))


def option_is_free(tool, option):
    tags = [option["tag"] if t["label"] == "Summarizer" else t for t in tool["tags"]]
    return is_free({"tags": tags})


def list_tools():
    out = []
    for t in TOOLS:
        item = {**t, "free": is_free(t)}
        if "options" in t:
            item["has_free"] = any(option_is_free(t, o) for o in t["options"])
            item["has_paid"] = any(not option_is_free(t, o) for o in t["options"])
        out.append(item)
    return out


def get_tool(tool_id):
    return next((t for t in list_tools() if t["id"] == tool_id), None)
```

- [ ] **Step 4: Run the full suite**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests -q`
Expected: all PASS (the earlier `test_tools.py` tests still hold: default tags contain the local Summarizer tag, `free` is True, stages and bounds unchanged).

---

### Task 3: Anthropic cloud client

**Files:**
- Create: `panel/cloud.py`
- Modify: `tests/panel/conftest.py` (add fixture)
- Test: `tests/panel/test_cloud.py`

**Interfaces:**
- Consumes: `summarizer.CancelToken`, `summarizer.Aborted`.
- Produces:
  - `CloudError(Exception)` with plain-language messages (never containing the key).
  - `AnthropicClient(key, host="api.anthropic.com", port=443, secure=True)` with `chat(model, messages, schema=None, token=None) -> str` (JSON string when `schema` is given, via a forced tool call), `unload(model)` (no-op), attributes `tokens_in`, `tokens_out`, `check() -> None` (raises `CloudError` if the key is rejected; used to validate a key with a free `GET /v1/models?limit=1`).
  - `cloud.check_key(key) -> None` = `AnthropicClient(key).check()`.

- [ ] **Step 1: Add the fake Anthropic server fixture**

Append to `tests/panel/conftest.py`:
```python
import http.server
import json
import threading

import pytest


class _AnthropicHandler(http.server.BaseHTTPRequestHandler):
    def _reply(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self):
        srv = self.server
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        srv.requests.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})
        mode = srv.mode
        if mode == "hang":
            srv.started.set()
            srv.release.wait(10)
            return
        if mode in ("401", "403", "404", "429", "529", "500"):
            msg = {"401": "invalid x-api-key", "403": "forbidden", "404": "model not found"}.get(mode, "problem")
            return self._reply(int(mode), {"type": "error", "error": {"type": "e", "message": msg + " " + srv.echo}})
        if mode == "credit":
            return self._reply(400, {"type": "error", "error": {"type": "invalid_request_error",
                                                                "message": "Your credit balance is too low to access the Anthropic API."}})
        if self.path.startswith("/v1/models"):
            return self._reply(200, {"data": [{"id": "claude-haiku-4-5-20251001"}]})
        usage = {"input_tokens": 1200, "output_tokens": 300}
        if body and body.get("tools"):
            return self._reply(200, {"content": [{"type": "tool_use", "name": "submit_summary", "input": srv.tool_input}], "usage": usage})
        return self._reply(200, {"content": [{"type": "text", "text": "some notes"}], "usage": usage})

    do_GET = do_POST = _handle

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_anthropic():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _AnthropicHandler)
    srv.mode, srv.requests, srv.echo = "ok", [], ""
    srv.tool_input = {"tldr": "T", "sections": [{"title": "A", "bullets": ["a"], "start_time": "0:05"}], "takeaways": ["t"]}
    srv.started, srv.release = threading.Event(), threading.Event()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.port = srv.server_address[1]
    yield srv
    srv.release.set()
    srv.shutdown()
    srv.server_close()
```

- [ ] **Step 2: Write the failing tests**

`tests/panel/test_cloud.py`:
```python
import json
import threading
import time

import pytest

import cloud
import summarizer as sm

KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
MSGS = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hello"}]


def client(srv, key=KEY):
    return cloud.AnthropicClient(key, host="127.0.0.1", port=srv.port, secure=False)


def test_text_call_shape_headers_and_tokens(fake_anthropic):
    c = client(fake_anthropic)
    assert c.chat("claude-haiku-4-5-20251001", MSGS) == "some notes"
    req = fake_anthropic.requests[0]
    assert req["path"] == "/v1/messages" and req["method"] == "POST"
    assert req["headers"]["x-api-key"] == KEY and req["headers"]["anthropic-version"] == "2023-06-01"
    body = req["body"]
    assert body["model"] == "claude-haiku-4-5-20251001" and body["system"] == "be brief"
    assert body["messages"] == [{"role": "user", "content": "hello"}] and body["max_tokens"] > 0
    assert "tools" not in body
    assert (c.tokens_in, c.tokens_out) == (1200, 300)


def test_schema_uses_a_forced_tool_call_and_returns_json(fake_anthropic):
    c = client(fake_anthropic)
    out = json.loads(c.chat("m", MSGS, schema=sm.SUMMARY_SCHEMA))
    assert out["tldr"] == "T"
    body = fake_anthropic.requests[0]["body"]
    assert body["tools"][0]["input_schema"] == sm.SUMMARY_SCHEMA
    assert body["tool_choice"] == {"type": "tool", "name": body["tools"][0]["name"]}
    c.chat("m", MSGS, schema=sm.SUMMARY_SCHEMA)
    assert (c.tokens_in, c.tokens_out) == (2400, 600)  # accumulates across calls


@pytest.mark.parametrize("mode,expected", [
    ("401", "rejected"), ("403", "not allowed"), ("404", "could not find"), ("429", "rate"),
    ("529", "overloaded"), ("500", "overloaded"), ("credit", "credit"),
])
def test_errors_are_plain_and_never_contain_the_key(fake_anthropic, mode, expected):
    fake_anthropic.mode, fake_anthropic.echo = mode, KEY  # even a server that echoes the key back
    with pytest.raises(cloud.CloudError) as exc:
        client(fake_anthropic).chat("m", MSGS)
    assert expected in str(exc.value).lower() and KEY not in str(exc.value)


def test_network_down_message():
    c = cloud.AnthropicClient(KEY, host="127.0.0.1", port=1, secure=False)
    with pytest.raises(cloud.CloudError, match="internet"):
        c.chat("m", MSGS)


def test_check_key_ok_and_rejected(fake_anthropic):
    client(fake_anthropic).check()
    assert fake_anthropic.requests[0]["path"].startswith("/v1/models")
    fake_anthropic.mode = "401"
    with pytest.raises(cloud.CloudError, match="rejected"):
        client(fake_anthropic).check()


def test_abort_interrupts_a_busy_request_immediately(fake_anthropic):
    fake_anthropic.mode = "hang"
    token, result = sm.CancelToken(), {}

    def call():
        try:
            client(fake_anthropic).chat("m", MSGS, token=token)
        except Exception as exc:
            result["exc"] = exc

    t = threading.Thread(target=call)
    t.start()
    assert fake_anthropic.started.wait(3)
    t0 = time.time()
    token.cancel()
    t.join(3)
    assert not t.is_alive() and time.time() - t0 < 2 and isinstance(result["exc"], sm.Aborted)


def test_unload_is_a_noop(fake_anthropic):
    client(fake_anthropic).unload("m")
    assert fake_anthropic.requests == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests/panel/test_cloud.py -q`
Expected: FAIL (`No module named 'cloud'`).

- [ ] **Step 4: Write the implementation**

`panel/cloud.py`:
```python
"""Anthropic Messages API client with the same chat() interface as the Ollama client."""
import http.client
import json

import summarizer as sm

API_HOST = "api.anthropic.com"
API_VERSION = "2023-06-01"


class CloudError(Exception):
    """Plain-language error. Never contains the API key."""


def _message_for(status, raw):
    text = raw.decode("utf-8", "replace").lower() if isinstance(raw, bytes) else str(raw).lower()
    if status == 401:
        return "Anthropic rejected this API key. Check it on the Home page."
    if status == 403:
        return "This API key is not allowed to use that model."
    if status == 404:
        return "Anthropic could not find that model for this key."
    if status == 429:
        return "Anthropic is rate limiting requests. Try again shortly."
    if status in (500, 502, 503, 529):
        return "Anthropic is overloaded right now. Try again shortly."
    if status == 400 and "credit" in text:
        return "Your Anthropic account is out of credit."
    return f"Anthropic returned an error ({status})."


class AnthropicClient:
    def __init__(self, key, host=API_HOST, port=443, secure=True):
        self.key, self.host, self.port, self.secure = key, host, port, secure
        self.tokens_in = self.tokens_out = 0

    def _request(self, method, path, payload=None, token=None, timeout=300):
        cls = http.client.HTTPSConnection if self.secure else http.client.HTTPConnection
        conn = cls(self.host, self.port, timeout=timeout)
        try:
            if token:
                token.check()
                token.bind(conn)
            headers = {"x-api-key": self.key, "anthropic-version": API_VERSION, "content-type": "application/json"}
            body = None if payload is None else json.dumps(payload).encode("utf-8")
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
        except (OSError, http.client.HTTPException) as exc:
            if token and token.cancelled:
                raise sm.Aborted("Aborted.") from exc
            raise CloudError("Could not reach Anthropic. Check your internet connection.") from exc
        finally:
            conn.close()
        if resp.status >= 400:
            raise CloudError(_message_for(resp.status, raw))
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise CloudError("Anthropic sent a reply that could not be read.") from exc

    def check(self):
        self._request("GET", "/v1/models?limit=1", timeout=15)

    def chat(self, model, messages, schema=None, token=None):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        payload = {
            "model": model,
            "max_tokens": 4096,
            "messages": [m for m in messages if m["role"] != "system"],
        }
        if system:
            payload["system"] = system
        if schema:
            payload["tools"] = [{"name": "submit_summary", "description": "Submit the finished summary.",
                                 "input_schema": schema}]
            payload["tool_choice"] = {"type": "tool", "name": "submit_summary"}
        data = self._request("POST", "/v1/messages", payload, token=token)
        usage = data.get("usage") or {}
        self.tokens_in += usage.get("input_tokens", 0)
        self.tokens_out += usage.get("output_tokens", 0)
        for block in data.get("content") or []:
            if schema and block.get("type") == "tool_use":
                return json.dumps(block.get("input", {}))
            if not schema and block.get("type") == "text":
                return block.get("text", "")
        raise CloudError("Anthropic returned an empty answer.")

    def unload(self, model):
        """Nothing to free for a cloud model."""


def check_key(key):
    AnthropicClient(key).check()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests -q`
Expected: all PASS.

---

### Task 4: Server — key endpoints, option-based jobs, cloud runs

**Files:**
- Modify: `panel/server.py`
- Test: extend `tests/panel/test_server.py`

**Interfaces:**
- Consumes: `keystore.Keystore`, `cloud.AnthropicClient`, `cloud.check_key`, `cloud.CloudError`, `tools.get_option/DEFAULT_OPTION/get_tool`.
- Produces:
  - `App(history, client, fetch=None, keystore=None, cloud_factory=None, key_check=None)`; defaults: `Keystore()`, `cloud.AnthropicClient`, `cloud.check_key`.
  - Routes: `GET /api/settings/key` → `{saved, last4}`; `POST /api/settings/key {key}` → status dict (400 for bad format or Anthropic-rejected key, 500 for Keychain trouble); `DELETE /api/settings/key` → `{saved: false, last4: null}`.
  - `POST /api/youtube/summarize {url, option?, model?}`: `option` id selects local/cloud; unknown → 400; cloud without saved key → 400 "Add your Anthropic API key on the Home page first."; without `option`, the legacy `model` field means a local run of that model.
  - Saved records include `option`, `provider`, `effort`, `model_name`, and for cloud `tokens_in`, `tokens_out`.
  - Any exception text in a job error is scrubbed of the key value (`[key]`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/panel/test_server.py`:
```python
# ---------- key endpoints and option-based jobs ----------
import cloud as cloud_mod

KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"


class FakeKeystore:
    def __init__(self, key=None, fail=None):
        self.key, self.fail = key, fail

    def get_key(self):
        return self.key

    def set_key(self, key):
        if self.fail:
            raise self.fail
        self.key = key

    def delete_key(self):
        self.key = None

    def status(self):
        return {"saved": bool(self.key), "last4": self.key[-4:] if self.key else None}


class FakeCloud(FakeClient):
    def __init__(self, key):
        super().__init__()
        self.key = key
        self.tokens_in, self.tokens_out = 1234, 567


def make_cloud_app(tmp_path, keystore=None, key_check=None, cloud_factory=None, **kw):
    return server.App(HistoryStore(tmp_path / "h.json"), kw.get("client") or FakeClient(), lambda url: VIDEO,
                      keystore=keystore or FakeKeystore(), cloud_factory=cloud_factory or FakeCloud,
                      key_check=key_check or (lambda key: None))


def test_key_status_save_and_remove(tmp_path):
    app = make_cloud_app(tmp_path)
    assert app.handle("GET", "/api/settings/key", None, H)[1] == {"saved": False, "last4": None}
    status, body = app.handle("POST", "/api/settings/key", {"key": KEY}, H)
    assert status == 200 and body == {"saved": True, "last4": KEY[-4:]}
    assert KEY not in json.dumps(app.handle("GET", "/api/settings/key", None, H)[1])
    assert app.handle("DELETE", "/api/settings/key", None, H)[1] == {"saved": False, "last4": None}


def test_save_key_rejects_bad_format_and_never_stores_it(tmp_path):
    ks = FakeKeystore()
    app = make_cloud_app(tmp_path, ks)
    for bad in ("", "nope", KEY + '" ; rm', None, 5):
        status, body = app.handle("POST", "/api/settings/key", {"key": bad}, H)
        assert status == 400 and "sk-ant-" in body["error"]
    assert ks.key is None


def test_save_key_rejected_by_anthropic_is_not_stored(tmp_path):
    def reject(key):
        raise cloud_mod.CloudError("Anthropic rejected this API key. Check it on the Home page.")

    ks = FakeKeystore()
    status, body = make_cloud_app(tmp_path, ks, key_check=reject).handle("POST", "/api/settings/key", {"key": KEY}, H)
    assert status == 400 and "rejected" in body["error"] and KEY not in json.dumps(body) and ks.key is None


def test_keychain_trouble_is_a_500_without_the_key(tmp_path):
    import keystore as ks_mod

    app = make_cloud_app(tmp_path, FakeKeystore(fail=ks_mod.KeystoreError("Could not save the key to the Keychain.")))
    status, body = app.handle("POST", "/api/settings/key", {"key": KEY}, H)
    assert status == 500 and "Keychain" in body["error"] and KEY not in json.dumps(body)


def test_key_routes_need_the_panel_header_and_local_host(tmp_path):
    app = make_cloud_app(tmp_path)
    assert app.handle("POST", "/api/settings/key", {"key": KEY}, {"Host": "localhost"})[0] == 403
    assert app.handle("DELETE", "/api/settings/key", None, {"Host": "localhost"})[0] == 403
    assert app.handle("GET", "/api/settings/key", None, {"Host": "evil.example"})[0] == 403


def run_option(app, option, url="https://youtu.be/dQw4w9WgXcQ"):
    status, body = app.handle("POST", "/api/youtube/summarize", {"url": url, "option": option}, H)
    if status != 200:
        return status, body
    app.wait(body["job_id"])
    return 200, app.handle("GET", f"/api/jobs/{body['job_id']}", None, H)[1]


def test_local_option_job_records_effort_and_provider(tmp_path):
    status, job = run_option(make_cloud_app(tmp_path), "local-easy")
    rec = job["result"]
    assert (rec["option"], rec["provider"], rec["effort"], rec["model"], rec["model_name"]) == \
        ("local-easy", "local", "Easy", "qwen3.5:2b", "qwen3.5:2b")
    assert "tokens_in" not in rec


def test_cloud_option_job_uses_the_cloud_client_and_records_tokens(tmp_path):
    seen = {}

    def factory(key):
        seen["key"] = key
        return FakeCloud(key)

    app = make_cloud_app(tmp_path, FakeKeystore(KEY), cloud_factory=factory)
    status, job = run_option(app, "cloud-medium")
    rec = job["result"]
    assert seen["key"] == KEY and job["status"] == "done"
    assert (rec["provider"], rec["effort"], rec["model"], rec["model_name"]) == ("cloud", "Medium", "claude-sonnet-5-5", "Sonnet 5.5")
    assert (rec["tokens_in"], rec["tokens_out"]) == (1234, 567)
    assert KEY not in json.dumps(rec) and KEY not in json.dumps(job)


def test_cloud_option_without_a_key_and_unknown_option(tmp_path):
    app = make_cloud_app(tmp_path)
    status, body = run_option(app, "cloud-easy")
    assert status == 400 and "API key on the Home page" in body["error"]
    assert run_option(app, "cloud-bogus")[0] == 400


def test_legacy_model_field_still_means_local(tmp_path):
    app = make_cloud_app(tmp_path)
    job = run_job(app, model="qwen3.5:2b")
    assert job["result"]["provider"] == "local" and job["result"]["model"] == "qwen3.5:2b"


def test_cloud_errors_and_key_scrubbing(tmp_path):
    class Boom(FakeCloud):
        def chat(self, model, messages, schema=None, token=None):
            raise RuntimeError(f"weird failure with {self.key} inside")

    class Rejected(FakeCloud):
        def chat(self, model, messages, schema=None, token=None):
            raise cloud_mod.CloudError("Anthropic is overloaded right now. Try again shortly.")

    for factory, expected in ((Boom, "Unexpected error"), (Rejected, "overloaded")):
        app = make_cloud_app(tmp_path, FakeKeystore(KEY), cloud_factory=factory)
        status, job = run_option(app, "cloud-hard")
        assert job["status"] == "error" and expected in job["error"] and KEY not in json.dumps(job)


def test_cloud_abort_discards_everything(tmp_path):
    class Gated(FakeCloud):
        gate = threading.Event()
        in_chat = threading.Event()

        def chat(self, model, messages, schema=None, token=None):
            Gated.in_chat.set()
            Gated.gate.wait(10)
            if token:
                token.check()
            return super().chat(model, messages, schema, token)

    app = make_cloud_app(tmp_path, FakeKeystore(KEY), cloud_factory=Gated)
    status, body = app.handle("POST", "/api/youtube/summarize", {"url": "https://youtu.be/dQw4w9WgXcQ", "option": "cloud-easy"}, H)
    assert Gated.in_chat.wait(3)
    assert app.handle("POST", f"/api/jobs/{body['job_id']}/abort", {}, H)[0] == 200
    Gated.gate.set()
    app.wait(body["job_id"])
    assert job(app, body["job_id"])["status"] == "aborted"
    assert app.handle("GET", "/api/history", None, H)[1] == []
```
(`run_job`, `job`, `FakeClient`, `VIDEO`, `H`, `threading` come from the existing test file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests/panel/test_server.py -q`
Expected: the new tests FAIL (unexpected keyword arguments / missing routes).

- [ ] **Step 3: Implement**

In `panel/server.py`:

1. Add imports after the existing ones:
```python
import cloud  # noqa: E402
import keystore as keystore_mod  # noqa: E402
```

2. `Job.__init__` gains the client and option: change the signature and body start to
```python
    def __init__(self, job_id, tool, model, client=None, option=None):
        self.id, self.model = job_id, model
        self.client, self.option = client, option or {}
```
(keep everything else).

3. `App.__init__`:
```python
    def __init__(self, history, client, fetch=None, keystore=None, cloud_factory=None, key_check=None):
        self.history = history
        self.client = client
        self.keystore = keystore or keystore_mod.Keystore()
        self.cloud_factory = cloud_factory or cloud.AnthropicClient
        self.key_check = key_check or cloud.check_key
        self.fetch = fetch or (lambda url: ft.fetch_video(ft.extract_video_id(url)))
        self.jobs = {}
        self.threads = {}
```

4. Add routes in `_route` (before the final `raise ApiError(404, ...)`):
```python
        if parts[:2] == ["settings", "key"] and len(parts) == 2:
            return self._key_route(method, body)
```
and the method:
```python
    def _key_route(self, method, body):
        try:
            if method == "GET":
                return 200, self.keystore.status()
            if method == "DELETE":
                self.keystore.delete_key()
                return 200, self.keystore.status()
            if method == "POST":
                key = body.get("key") if isinstance(body, dict) else None
                if not keystore_mod.valid_key_format(key):
                    raise ApiError(400, "That does not look like an Anthropic API key (it starts with sk-ant-).")
                try:
                    self.key_check(key)
                except cloud.CloudError as exc:
                    raise ApiError(400, str(exc))
                self.keystore.set_key(key)
                return 200, self.keystore.status()
        except keystore_mod.KeystoreError as exc:
            raise ApiError(500, str(exc))
        raise ApiError(404, "Not found")
```

5. Replace `_start_job` with the option-aware version:
```python
    def _resolve_option(self, body):
        option_id = body.get("option")
        if option_id:
            option = tools.get_option(option_id)
            if not option:
                raise ApiError(400, "Unknown effort option.")
            return option
        model = body.get("model") or DEFAULT_MODEL
        if not isinstance(model, str):
            raise ApiError(400, "Invalid model.")
        known = next((o for o in tools.OPTIONS if o["provider"] == "local" and o["model"] == model), None)
        return known or {"id": None, "provider": "local", "effort": None, "model": model, "name": model}

    def _start_job(self, body):
        if not isinstance(body, dict) or not isinstance(body.get("url"), str) or not body["url"].strip():
            raise ApiError(400, "Paste a YouTube link first.")
        option = self._resolve_option(body)
        if any(j.status == "running" for j in self.jobs.values()):
            raise ApiError(409, "A summary is already running. Abort it or wait for it to finish.")
        if option["provider"] == "cloud":
            try:
                key = self.keystore.get_key()
            except keystore_mod.KeystoreError as exc:
                raise ApiError(500, str(exc))
            if not key:
                raise ApiError(400, "Add your Anthropic API key on the Home page first.")
            client = self.cloud_factory(key)
        else:
            client = self.client
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id, tools.get_tool("youtube"), option["model"], client=client, option=option)
        job.set(detail="downloading captions")
        self.jobs[job_id] = job
        thread = threading.Thread(target=self._run, args=(job, body["url"].strip()), daemon=True)
        self.threads[job_id] = thread
        thread.start()
        return job_id
```

6. In `_run`, use the job's client and record the new fields, and scrub the key from error text. Replace the `sm.summarize(self.client, ...` call's first argument with `job.client`, and replace the save/except blocks with:
```python
            job.set(stage=3, detail="checking and saving")
            with job.lock:  # abort and save cannot interleave
                if job.status != "running":
                    return
                opt = job.option
                record = {
                    "video_id": video["video_id"], "title": video["title"], "summary": summary,
                    "model": job.model, "seconds": round(time.time() - started),
                    "option": opt.get("id"), "provider": opt.get("provider"),
                    "effort": opt.get("effort"), "model_name": opt.get("name"),
                }
                if opt.get("provider") == "cloud":
                    record["tokens_in"] = getattr(job.client, "tokens_in", 0)
                    record["tokens_out"] = getattr(job.client, "tokens_out", 0)
                job.finish("done", result=self.history.add(record))
        except sm.Aborted:
            pass
        except (ValueError, ft.NoCaptions, sm.OllamaDown, sm.ModelMissing, sm.SummaryFailed, cloud.CloudError) as exc:
            job.finish("error", error=self._scrub(str(exc), job))
        except Exception as exc:  # never leave a job hanging
            job.finish("error", error=self._scrub(f"Unexpected error: {exc}", job))

    @staticmethod
    def _scrub(text, job):
        key = getattr(job.client, "key", None)
        return text.replace(key, "[key]") if key else text
```

7. Abort's unload call already uses `self.client.unload(job.model)`; change it to `job.client.unload` so a cloud abort calls the no-op:
```python
            threading.Thread(target=job.client.unload, args=(job.model,), daemon=True).start()
```

8. `main()`: nothing else changes (defaults create the real `Keystore` and `AnthropicClient`).

- [ ] **Step 4: Run the full suite**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests -q`
Expected: all PASS, including every earlier server test (they construct `App(history, client, fetch)` and pass `model=`; the defaults keep them working).

---

### Task 5: Front end — Home, key card, effort dropdown, dynamic tags

**Files:**
- Modify: `panel/static/app.js`, `panel/static/style.css`

**Interfaces:**
- Consumes: `/api/tools` (now with `options`, `has_free`, `has_paid`, `default_option`), `/api/models`, `/api/settings/key` (GET/POST/DELETE), `/api/youtube/summarize {url, option}`, history records with `effort/provider/model_name/tokens_*`.
- Produces element ids for checks: `#key-input`, `#key-save`, `#key-remove`, `#key-status`, `#yt-option`, `#yt-go`, `#yt-abort`.

No automated JS tests exist; verification is `node --check` plus the browser checks in Step 4.

- [ ] **Step 1: Update `panel/static/app.js`**

a) State and pills. Replace the line `const pill = ...` (the free-pill helper) with:
```js
const state = { tools: [], models: [], key: { saved: false, last4: null } };
const pill = (kind) => el("span", { className: kind === "free" ? "pill free" : "pill paid", textContent: kind === "free" ? "Free" : "$" });
const toolPills = (t) => [t.has_free ? pill("free") : null, t.has_paid ? pill("paid") : null].filter(Boolean);
```
and delete the later line `const state = { tools: [] };` in the shell section.

b) Tag chip with a `$` mark. Replace `tagChip` with:
```js
function tagChip(tag) {
  const kids = [
    el("span", { innerHTML: tag.kind === "local" ? ICON_LOCAL : ICON_NET }),
    el("b", { textContent: tag.kind === "local" ? "Local" : "Network" }),
    el("span", { textContent: `${tag.label} · ${tag.detail}` }),
  ];
  if (tag.paid) kids.push(el("b", { className: "dollar", textContent: "$", title: "This part costs money" }));
  return el("span", { className: `tag ${tag.kind}${tag.paid ? " paid" : ""}` }, ...kids);
}
```

c) Cost line and number formatting. Replace `costLine` with:
```js
const fmtNum = (n) => Number(n || 0).toLocaleString("en-US");
function costLine(rec) {
  if (rec.provider === "cloud") {
    return `cost: $ · ${rec.model_name || rec.model} · ${fmtNum(rec.tokens_in)} in / ${fmtNum(rec.tokens_out)} out tokens · ${rec.seconds}s`;
  }
  return `cost: free · local · ${rec.effort ? rec.effort + " · " : ""}${rec.model} · ${rec.seconds}s`;
}
```

d) Replace the whole YouTube tool section (from `/* ---------- YouTube tool ---------- */` up to, but not including, `/* ---------- shell: rail, history ---------- */`) with:
```js
/* ---------- YouTube tool ---------- */
let youtubeUI = null; // built once so a running job survives navigating away

function optionRow(o) {
  const local = o.provider === "local";
  const ready = local ? state.models.includes(o.model) : state.key.saved;
  const load = local ? `${o.load} load` : "no load on your Mac";
  const mark = local ? "" : " $";
  const why = ready ? "" : (local ? " · not installed" : " · add API key on Home");
  return { ready, text: `${o.effort} · ${o.name}${mark} · ${load}${why}` };
}

function buildYoutubeUI(meta) {
  const url = el("input", { id: "yt-url", type: "url", placeholder: "Paste a YouTube link", autocomplete: "off" });
  const option = el("select", { id: "yt-option", title: "Effort and model" });
  const go = el("button", { id: "yt-go", className: "primary", textContent: "Summarize" });
  const abortBtn = el("button", { id: "yt-abort", className: "abort", textContent: "Abort", hidden: true, title: "Stop now and discard everything" });
  const tagsBox = el("div", { className: "tags" });
  const head = el("div", { className: "tool-head" });
  const status = el("p", { className: "status", role: "status" });
  const progress = progressPanel();
  const out = el("div", { id: "yt-result" });
  let running = false;
  let currentJob = null;

  const selected = () => meta.options.find((o) => o.id === option.value) || meta.options.find((o) => o.id === meta.default_option);
  const setStatus = (text, isError) => { status.className = isError ? "status error" : "status"; status.textContent = text; };

  function drawTags() {
    const opt = selected();
    const tags = meta.tags.map((t) => (t.label === "Summarizer" ? opt.tag : t));
    tagsBox.replaceChildren(...tags.map(tagChip));
    const free = !tags.some((t) => t.paid);
    head.replaceChildren(el("h2", { textContent: meta.name }), ...(free ? [pill("free")] : []));
  }

  function refreshOptions() { // rebuild the grouped dropdown from installed models + key state
    const keep = option.value || meta.default_option;
    const groups = [["local", "On this Mac (free)"], ["cloud", "Cloud ($) · Claude API"]];
    option.replaceChildren(...groups.map(([prov, title]) => {
      const g = el("optgroup", { label: title });
      meta.options.filter((o) => o.provider === prov).forEach((o) => {
        const row = optionRow(o);
        g.append(el("option", { value: o.id, disabled: !row.ready, textContent: row.text }));
      });
      return g;
    }));
    const wanted = [...option.options].find((o) => o.value === keep && !o.disabled)
      || [...option.options].find((o) => !o.disabled);
    if (wanted) option.value = wanted.value;
    drawTags();
  }
  option.onchange = drawTags;

  async function loadModels() {
    try {
      const data = await api("/api/models");
      state.models = data.models;
      if (data.error) setStatus(data.error, true);
    } catch (e) { setStatus(e.message, true); }
    refreshOptions();
  }

  // Poll one job until it ends. `out.dataset.job` says which job may render into the result area.
  async function follow(jobId) {
    running = true; currentJob = jobId;
    go.disabled = true; abortBtn.hidden = false; abortBtn.disabled = false; setStatus("");
    try {
      for (;;) {
        const job = await api(`/api/jobs/${jobId}`);
        if (job.status === "error") throw new Error(job.error);
        if (job.status === "aborted") { out.replaceChildren(); progress.hide(); setStatus("Aborted. Nothing was saved."); break; }
        if (job.status === "done") {
          progress.hide();
          if (out.dataset.job === jobId) { renderResult(out, job.result); setStatus(""); }
          else setStatus(`Finished: ${job.result.title}. Open it from History.`);
          refreshHistory();
          break;
        }
        progress.update(job);
        await sleep(1000);
      }
    } catch (e) { progress.hide(); setStatus(e.message, true); } finally {
      running = false; currentJob = null; go.disabled = false; abortBtn.hidden = true;
    }
  }

  async function run() {
    if (running) return; // Enter key or double click while a job is running
    const link = url.value.trim();
    if (!link) return setStatus("Paste a YouTube link first.", true);
    if (!option.value) return setStatus("No option available. Start Ollama, or add an API key on Home.", true);
    running = true; go.disabled = true; out.replaceChildren(); out.dataset.job = ""; setStatus("");
    let jobId;
    try {
      ({ job_id: jobId } = await api("/api/youtube/summarize", { method: "POST", body: JSON.stringify({ url: link, option: option.value }) }));
    } catch (e) { running = false; go.disabled = false; return setStatus(e.message, true); }
    out.dataset.job = jobId;
    follow(jobId);
  }

  abortBtn.onclick = async () => {
    if (!currentJob) return;
    abortBtn.disabled = true;
    try { await api(`/api/jobs/${currentJob}/abort`, { method: "POST", body: "{}" }); } catch (e) {
      abortBtn.disabled = false;
      return setStatus(e.message, true);
    }
    out.replaceChildren(); progress.hide(); setStatus("Aborted. Nothing was saved.");
  };
  go.onclick = run;
  url.onkeydown = (e) => { if (e.key === "Enter") run(); };

  refreshOptions();
  loadModels();
  return {
    root: el("div", null, head,
      el("div", { className: "form" }, url, option, go, abortBtn),
      el("p", { className: "hint", textContent: "Easy = fastest and cheapest · Hard = best quality, slowest, most load or cost. Cloud runs send the transcript to Anthropic." }),
      tagsBox, progress.root, status, out),
    show(rec) { out.dataset.job = ""; renderResult(out, rec); },
    attach(job) { out.dataset.job = job.id; follow(job.id); },
    refreshOptions,
  };
}

function youtubeView(stage, meta, record) {
  if (!youtubeUI) youtubeUI = buildYoutubeUI(meta);
  stage.replaceChildren(youtubeUI.root);
  if (record) youtubeUI.show(record);
}

/* ---------- Home: tool cards + API key card ---------- */
function keyCard() {
  const input = el("input", { id: "key-input", type: "password", placeholder: "sk-ant-…", autocomplete: "off", spellcheck: false });
  const save = el("button", { id: "key-save", className: "primary", textContent: "Test & save" });
  const remove = el("button", { id: "key-remove", textContent: "Remove", hidden: !state.key.saved });
  const status = el("p", { id: "key-status", className: "status", role: "status" });
  const draw = () => {
    remove.hidden = !state.key.saved;
    status.className = "status";
    status.textContent = state.key.saved ? `Saved · ••••${state.key.last4} · in macOS Keychain` : "No key saved. Cloud options stay disabled.";
  };
  const apply = (s) => { state.key = s; draw(); if (youtubeUI) youtubeUI.refreshOptions(); };
  save.onclick = async () => {
    const value = input.value.trim();
    if (!value) { status.className = "status error"; status.textContent = "Paste your API key first."; return; }
    save.disabled = true; status.className = "status"; status.textContent = "Checking the key with Anthropic…";
    try {
      apply(await api("/api/settings/key", { method: "POST", body: JSON.stringify({ key: value }) }));
    } catch (e) { status.className = "status error"; status.textContent = e.message; } finally {
      input.value = ""; // the key never stays in the page
      save.disabled = false;
    }
  };
  remove.onclick = async () => {
    try { apply(await api("/api/settings/key", { method: "DELETE" })); } catch (e) { status.className = "status error"; status.textContent = e.message; }
  };
  draw();
  return el("section", { className: "key-card" },
    el("h3", { textContent: "Anthropic API key" }),
    el("p", { className: "hint", textContent: "Needed only for cloud options ($). Kept in your macOS Keychain, sent only to api.anthropic.com. Use a dedicated key with a monthly spend limit." }),
    el("div", { className: "form" }, input, save, remove),
    status);
}

function homeView(stage) {
  const cards = state.tools.map((t) => {
    const card = el("button", { className: "card" }, el("span", { className: "card-title", textContent: t.name }), el("span", { className: "card-marks" }, ...toolPills(t)));
    card.onclick = () => openTool(t.id);
    return card;
  });
  stage.replaceChildren(el("h2", { textContent: "Home" }), el("div", { className: "cards" }, ...cards), keyCard());
}

```

e) Replace the shell functions `openTool` and `init`, and the rail creation, with:
```js
const VIEWS = { youtube: youtubeView };

function openTool(id, record) {
  document.querySelectorAll(".tool-btn").forEach((b) => b.classList.toggle("active", b.dataset.id === id));
  if (id === "home") return homeView(document.getElementById("stage"));
  const meta = state.tools.find((t) => t.id === id);
  if (!meta || !VIEWS[id]) return;
  VIEWS[id](document.getElementById("stage"), meta, record);
}
```
(keep `refreshHistory` unchanged except the small line below), and in `refreshHistory` change the item's detail line to:
```js
        el("small", { textContent: `${new Date(it.created).toLocaleString()} · ${it.effort ? it.effort + " · " : ""}${it.model_name || it.model}${it.provider === "cloud" ? " $" : ""}` }));
```
and `init`:
```js
async function init() {
  const rail = document.getElementById("rail");
  try {
    state.tools = await api("/api/tools");
    state.key = await api("/api/settings/key");
  } catch (e) {
    return document.getElementById("stage").replaceChildren(el("p", { className: "status error", textContent: e.message }));
  }
  const home = el("button", { className: "tool-btn" }, el("span", { textContent: "Home" }));
  home.dataset.id = "home";
  home.onclick = () => openTool("home");
  rail.replaceChildren(home, ...state.tools.map((t) => {
    const b = el("button", { className: "tool-btn" }, el("span", { textContent: t.name }), el("span", { className: "card-marks" }, ...toolPills(t)));
    b.dataset.id = t.id;
    b.onclick = () => openTool(t.id);
    return b;
  }));
  openTool("home");
  refreshHistory();
  try { // a job may still be running from before a reload or a closed tab
    const { job } = await api("/api/jobs/active");
    if (job) { openTool("youtube"); youtubeUI.attach(job); }
  } catch (e) { /* no running job to show */ }
}
init();
```
(remove the old `init` and the old `init();` call.)

- [ ] **Step 2: Update `panel/static/style.css`**

Append:
```css
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin: 12px 0 20px; }
.card { display: flex; flex-direction: column; align-items: flex-start; gap: 8px; text-align: left; padding: 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
.card:hover { border-color: var(--accent); }
.card-title { font-weight: 600; }
.card-marks { display: inline-flex; gap: 6px; }
.tag.paid { background: var(--warn-bg); color: var(--warn); }
.dollar { font-weight: 700; padding: 0 5px; border-radius: 5px; background: var(--warn); color: var(--surface); }
.key-card { border: 1px solid var(--line); border-radius: 10px; background: var(--surface); padding: 16px; max-width: 640px; }
.key-card h3 { margin: 0 0 6px; font-size: 1rem; }
.key-card .form input { font-family: var(--mono); }
.key-card button:not(.primary) { padding: 10px 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
```
(The `[hidden]{display:none!important}` rule already exists.)

- [ ] **Step 3: Syntax check**

Run: `node --check panel/static/app.js && echo JS-OK`
Expected: `JS-OK`.

- [ ] **Step 4: Browser check** (server: `pkill -f panel/server.py; PORT=8123 panel/run.sh &`, open `http://localhost:8123`)

Seed an OLD-style history record first (no effort/provider fields): use `HistoryStore("panel/data/history.json").add({...})` with `video_id`, `title`, `model`, `seconds`, `summary` only. Then verify:
- Panel opens on **Home**: a card for YouTube Summarize with both a green **Free** and an amber **$** mark; the API key card says "No key saved. Cloud options stay disabled."
- Open YouTube Summarize: the dropdown has two groups; local rows read e.g. `Medium · qwen3.5:9b · medium load` (Medium selected); cloud rows read `Easy · Haiku 4.5 $ · no load on your Mac · add API key on Home` and are disabled. Tags: Summarizer shows `Ollama qwen3.5:9b` (green Local), header shows the green **Free** pill.
- Type `not-a-key` in the key card → Test & save shows the "does not look like an Anthropic API key" message and the box is cleared; nothing is saved.
- The old-style history item opens and shows `cost: free · local · <model> · <s>s`; the sidebar line shows the model only.
- Start an **Easy (qwen3.5:2b)** local summary of `https://youtu.be/jNQXAC9IVRw`: progress bar and stages run, the result's cost line reads `cost: free · local · Easy · qwen3.5:2b · <s>s`, and the sidebar shows `Easy · qwen3.5:2b`. Then delete that test item and the seeded old record.
- Abort still works on a local Medium run (start the long video, press Abort, status "Aborted. Nothing was saved.", `ollama ps` empty a few seconds later).
Expected: all true. The cloud-selected tag/pill switching (`Claude Sonnet 5.5 $`, Free pill hidden) is checked by temporarily forcing the key state in the page: in the browser console run `state.key = {saved: true, last4: "test"}; youtubeUI.refreshOptions();` (then choose a cloud row and confirm the amber `Summarizer · Claude Sonnet 5.5 $` tag appears and the Free pill disappears), then reload.

---

### Task 6: README, project brief, final verification

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Add the cloud section to `README.md`**

Append:
```markdown
### Cloud models (optional, costs money)

The effort dropdown has two groups. **On this Mac (free)** runs Ollama: Easy = qwen3.5:2b (low load), Medium = qwen3.5:9b (default, medium load), Hard = qwen3.5:27b (high load, loudest fan). **Cloud ($)** uses Claude through the Anthropic API: Easy = Haiku 4.5, Medium = Sonnet 5.5, Hard = Opus 5.5. Cloud rows stay disabled until you save an API key, and the tags show a **$** next to the part that costs (the Free pill disappears for cloud runs).

**Add your key (once):** open the panel's **Home** page, paste your Anthropic API key (`sk-ant-…`) into the key card, press **Test & save**. Get a key at console.anthropic.com. Use a **dedicated key with a monthly spend limit**.

**Where the key lives:** in your macOS **Keychain** (not in this folder, not in history, not in logs). It is sent only to `api.anthropic.com` over HTTPS, never sent back to the page (the page only shows the last 4 characters), and passed to the Keychain on stdin so it does not appear in the process list. Keychain protects the key at rest; software running as your user could still ask for it, which is why a dedicated, capped key is recommended. **Remove** deletes it from the Keychain.

**Privacy:** cloud runs send the video's transcript to Anthropic. Local runs do not.

**Cost line:** cloud results show the tokens used (`cost: $ · Sonnet 5.5 · 12,340 in / 1,020 out tokens · 9s`), not dollars; see your usage in the Anthropic Console.
```

- [ ] **Step 2: Update `CLAUDE.md`**

Replace the "Done (…) Free tag" heading's following state with a short "Done: cloud + effort + Home" block: Home page with key card, Keychain via `security -i` (`panel/keystore.py`), `panel/cloud.py` client, six options in `panel/tools.py`, `$` tags and Free pill follow the selected option, cost line shows tokens for cloud. Note: real cloud run needs the user's own key entered in the panel (never in chat). Update the test count to the new total.

- [ ] **Step 3: Full verification**

Run: `.claude/skills/yt-summary/.venv/bin/python -W ignore -m pytest tests -q`
Expected: all PASS. Confirm no real key or Keychain item was created by the tests: `security find-generic-password -s "LearningPanel Anthropic API key" >/dev/null 2>&1; echo $?` should print `44` (nothing stored) before the user adds their key.

- [ ] **Step 4: Tell the user how to run the first cloud test themselves**

Report: start the panel, open Home, paste the key into the key card (never into chat), press Test & save, then on YouTube Summarize pick `Easy · Haiku 4.5 $`, paste a short video link, press Summarize; check the result shows the tokens cost line and the `$` tag. If a step fails, send the exact on-screen message.
