import http.server
import json
import threading
import time

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

    def chat(self, model, messages, schema=None, token=None):
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


@pytest.mark.parametrize("stamp,seconds", [
    ("12:03 - 14:10", 723), ("12:03s", 723), ("around 1:02:05", 3725), ("[0:07]", 7),
])
def test_normalize_tolerates_messy_timestamp_text(stamp, seconds):
    s = {"tldr": "x", "sections": [{"title": "a", "bullets": ["b"], "start_time": stamp}], "takeaways": []}
    assert sm.normalize(s)["sections"][0]["start"] == seconds


class FnClient:
    def __init__(self):
        self.calls = []

    def chat(self, model, messages, schema=None, token=None):
        self.calls.append({"messages": messages, "schema": schema})
        if schema:
            return json.dumps(GOOD)
        text = messages[-1]["content"]
        return "n" * 3000 if "part" in text.split("\n")[1] else "r" * 1000


def test_many_notes_are_condensed_before_the_final_merge(monkeypatch):
    monkeypatch.setattr(sm, "MAX_CHUNK_CHARS", 300)
    monkeypatch.setattr(sm, "NOTES_LIMIT", 8000)
    n = len(sm.chunk_lines(TRANSCRIPT, 300))
    client = FnClient()
    msgs = []
    out = sm.summarize(client, "m", "T", TRANSCRIPT, progress=msgs.append)
    assert out["tldr"] == "A talk."
    assert len(client.calls) > n + 1                    # extra condensing calls happened
    assert "condensing notes" in msgs
    final = client.calls[-1]["messages"][-1]["content"]
    assert len(final) <= 8000 + 2000                    # notes fit the limit (+ task text)


# ---------- real local sockets: connection errors, abort, unload ----------
class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.hits.append(self.path)
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.server.mode == "404":
            self.send_response(404)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
        elif self.server.mode == "hang":
            self.server.started.set()
            self.server.release.wait(10)  # hold the connection open like a busy model
        else:
            body = json.dumps({"message": {"content": "hi"}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_ollama():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.mode, srv.hits = "ok", []
    srv.started, srv.release = threading.Event(), threading.Event()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv
    srv.release.set()
    srv.shutdown()
    srv.server_close()


MSG = [{"role": "user", "content": "x"}]


def test_ollama_down_message():
    client = sm.OllamaClient("http://127.0.0.1:1")
    with pytest.raises(sm.OllamaDown, match="ollama serve"):
        client.list_models()
    with pytest.raises(sm.OllamaDown, match="ollama serve"):
        client.chat("m", MSG)


def test_model_missing_message(fake_ollama):
    fake_ollama.mode = "404"
    with pytest.raises(sm.ModelMissing, match="ollama pull qwen9"):
        sm.OllamaClient(fake_ollama.url).chat("qwen9", MSG)


def test_chat_returns_content(fake_ollama):
    assert sm.OllamaClient(fake_ollama.url).chat("m", MSG) == "hi"


def test_cancel_interrupts_a_busy_model_immediately(fake_ollama):
    fake_ollama.mode = "hang"
    token, result = sm.CancelToken(), {}

    def call():
        try:
            sm.OllamaClient(fake_ollama.url).chat("m", MSG, token=token)
        except Exception as exc:
            result["exc"] = exc

    t = threading.Thread(target=call)
    t.start()
    assert fake_ollama.started.wait(3)
    t0 = time.time()
    token.cancel()
    t.join(3)
    assert not t.is_alive() and time.time() - t0 < 2
    assert isinstance(result["exc"], sm.Aborted)


def test_cancel_before_the_request_never_reaches_ollama(fake_ollama):
    token = sm.CancelToken()
    token.cancel()
    with pytest.raises(sm.Aborted):
        sm.OllamaClient(fake_ollama.url).chat("m", MSG, token=token)
    assert fake_ollama.hits == []


def test_unload_asks_ollama_to_free_the_model(fake_ollama):
    sm.OllamaClient(fake_ollama.url).unload("m")
    assert fake_ollama.hits == ["/api/generate"]
    sm.OllamaClient("http://127.0.0.1:1").unload("m")  # never raises


def test_summarize_stops_between_calls_when_cancelled(monkeypatch):
    monkeypatch.setattr(sm, "MAX_CHUNK_CHARS", 300)
    token = sm.CancelToken()

    class CancellingClient(FakeClient):
        def chat(self, model, messages, schema=None, token=None):
            out = super().chat(model, messages, schema, token)
            token.cancel()
            return out

    client = CancellingClient(["notes"] * 20)
    with pytest.raises(sm.Aborted):
        sm.summarize(client, "m", "T", TRANSCRIPT, token=token)
    assert len(client.calls) == 1


def test_on_step_reports_progress_for_single_and_multi_chunk(monkeypatch):
    steps = []
    sm.summarize(FakeClient([json.dumps(GOOD)]), "m", "T", TRANSCRIPT, on_step=lambda d, t: steps.append((d, t)))
    assert steps == [(0, 1)]
    monkeypatch.setattr(sm, "MAX_CHUNK_CHARS", 300)
    n = len(sm.chunk_lines(TRANSCRIPT, 300))
    steps.clear()
    client = FakeClient([f"notes {i}" for i in range(n)] + [json.dumps(GOOD)])
    sm.summarize(client, "m", "T", TRANSCRIPT, on_step=lambda d, t: steps.append((d, t)))
    assert steps == [(i, n + 1) for i in range(n + 1)]


def test_ollama_abort_that_arrives_while_connecting_never_sends_the_request(fake_ollama, monkeypatch):
    import http.client

    token = sm.CancelToken()
    real_connect = http.client.HTTPConnection.connect

    def cancel_then_connect(self):
        token.cancel()
        real_connect(self)

    monkeypatch.setattr(http.client.HTTPConnection, "connect", cancel_then_connect)
    with pytest.raises(sm.Aborted):
        sm.OllamaClient(fake_ollama.url).chat("m", MSG, token=token)
    assert fake_ollama.hits == []
