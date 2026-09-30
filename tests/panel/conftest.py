import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "panel", ROOT / ".claude" / "skills" / "yt-summary"):
    sys.path.insert(0, str(p))


# ---------- fake Anthropic server ----------
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


# ---------- fake OpenRouter server (OpenAI-style API) ----------
class _OpenRouterHandler(http.server.BaseHTTPRequestHandler):
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
        if mode in ("401", "402", "403", "404", "429", "500", "503"):
            return self._reply(int(mode), {"error": {"message": "problem " + srv.echo, "code": int(mode)}})
        if mode == "error200":  # OpenRouter can report a provider failure inside a 200 reply
            return self._reply(200, {"error": {"message": "upstream failed " + srv.echo, "code": 502}})
        if self.path.endswith("/key"):
            return self._reply(200, {"data": {"label": "test", "limit": 5, "usage": 0.1}})
        usage = {"prompt_tokens": 1100, "completion_tokens": 250}
        if body and body.get("tools"):
            fn = body["tools"][0]["function"]["name"]
            call = {"id": "c1", "type": "function", "function": {"name": fn, "arguments": json.dumps(srv.tool_input)}}
            return self._reply(200, {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}], "usage": usage})
        return self._reply(200, {"choices": [{"message": {"role": "assistant", "content": "some notes"}}], "usage": usage})

    do_GET = do_POST = _handle

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_openrouter():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OpenRouterHandler)
    srv.mode, srv.requests, srv.echo = "ok", [], ""
    srv.tool_input = {"tldr": "T", "sections": [{"title": "A", "bullets": ["a"], "start_time": "0:05"}], "takeaways": ["t"]}
    srv.started, srv.release = threading.Event(), threading.Event()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.port = srv.server_address[1]
    yield srv
    srv.release.set()
    srv.shutdown()
    srv.server_close()
