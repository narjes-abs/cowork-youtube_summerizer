import json

import fetch_transcript as ft
import server
import summarizer as sm
from history import HistoryStore

import pricing

NO_PRICES = pricing.PriceBook(fetch=lambda: {"data": []})
PRICES = pricing.PriceBook(fetch=lambda: {"data": [
    {"id": "anthropic/claude-haiku-4.5", "pricing": {"prompt": "0.000001", "completion": "0.000005"}},
    {"id": "anthropic/claude-sonnet-5.5", "pricing": {"prompt": "0.000002", "completion": "0.00001"}},
]})
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

    def unload(self, model):
        self.unloaded = getattr(self, "unloaded", []) + [model]

    def chat(self, model, messages, schema=None, token=None):
        if self.error:
            raise self.error
        return self.reply


def make_app(tmp_path, client=None, fetch=None):
    return server.App(HistoryStore(tmp_path / "h.json"), client or FakeClient(),
                      fetch or (lambda url: VIDEO),
                      keystore=FakeKeystore(), key_check=lambda key: None, pricebook=NO_PRICES)


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
    assert rec["tool"] == "youtube"  # which feature made it, so the history can show that feature's icon
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


def test_unexpected_errors_return_500_json(tmp_path):
    app = make_app(tmp_path)

    def boom():
        raise PermissionError("Operation not permitted")

    app.history.list = boom
    status, body = app.handle("GET", "/api/history", None, H)
    assert status == 500 and "Operation not permitted" in body["error"]


# ---------- progress, abort, one-at-a-time ----------
import threading
import time


class GatedClient(FakeClient):
    """chat() blocks until released, so a job can be inspected mid-run."""

    def __init__(self):
        super().__init__()
        self.gate = threading.Event()
        self.in_chat = threading.Event()

    def chat(self, model, messages, schema=None, token=None):
        self.in_chat.set()
        self.gate.wait(10)
        if token:
            token.check()
        return super().chat(model, messages, schema, token)


def start(app, model="qwen3.5:9b"):
    status, body = app.handle("POST", "/api/youtube/summarize", {"url": "https://youtu.be/dQw4w9WgXcQ", "model": model}, H)
    assert status == 200
    return body["job_id"]


def job(app, job_id):
    return app.handle("GET", f"/api/jobs/{job_id}", None, H)[1]


def test_job_reports_stage_label_detail_and_percent(tmp_path):
    client = GatedClient()
    app = make_app(tmp_path, client)
    jid = start(app)
    assert client.in_chat.wait(3)
    j = job(app, jid)
    assert j["status"] == "running" and j["stage"] == 3 and j["stage_count"] == 4
    assert j["label"] == "Summarizing" and "qwen3.5:9b" in j["detail"]
    assert 15 <= j["percent"] < 92
    client.gate.set()
    app.wait(jid)
    done = job(app, jid)
    assert done["status"] == "done" and done["percent"] == 100 and done["label"] == "Finishing"


def test_abort_discards_everything_and_unloads_the_model(tmp_path):
    client = GatedClient()
    app = make_app(tmp_path, client)
    jid = start(app)
    assert client.in_chat.wait(3)
    t0 = time.time()
    status, body = app.handle("POST", f"/api/jobs/{jid}/abort", {}, H)
    assert status == 200 and body["status"] == "aborted" and time.time() - t0 < 1
    assert job(app, jid)["status"] == "aborted"
    client.gate.set()  # the worker wakes up after the abort
    app.wait(jid)
    assert job(app, jid)["status"] == "aborted" and job(app, jid)["result"] is None
    assert app.handle("GET", "/api/history", None, H)[1] == []
    time.sleep(0.2)
    assert client.unloaded == ["qwen3.5:9b"]


def test_abort_errors(tmp_path):
    app = make_app(tmp_path)
    assert app.handle("POST", "/api/jobs/nope/abort", {}, H)[0] == 404
    jid = start(app)
    app.wait(jid)
    assert app.handle("POST", f"/api/jobs/{jid}/abort", {}, H)[0] == 409  # already finished
    assert app.handle("POST", f"/api/jobs/{jid}/abort", {}, {"Host": "localhost"})[0] == 403


def test_only_one_job_runs_at_a_time(tmp_path):
    client = GatedClient()
    app = make_app(tmp_path, client)
    jid = start(app)
    assert client.in_chat.wait(3)
    status, body = app.handle("POST", "/api/youtube/summarize", {"url": "https://youtu.be/dQw4w9WgXcQ"}, H)
    assert status == 409 and "already running" in body["error"]
    app.handle("POST", f"/api/jobs/{jid}/abort", {}, H)
    client.gate.set()
    app.wait(jid)
    assert app.handle("POST", "/api/youtube/summarize", {"url": "https://youtu.be/dQw4w9WgXcQ"}, H)[0] == 200


def test_active_job_endpoint(tmp_path):
    client = GatedClient()
    app = make_app(tmp_path, client)
    assert app.handle("GET", "/api/jobs/active", None, H) == (200, {"job": None})
    jid = start(app)
    assert client.in_chat.wait(3)
    active = app.handle("GET", "/api/jobs/active", None, H)[1]["job"]
    assert active["id"] == jid and active["status"] == "running"
    client.gate.set()
    app.wait(jid)
    assert app.handle("GET", "/api/jobs/active", None, H)[1] == {"job": None}


def test_tools_endpoint_includes_free_flag(tmp_path):
    yt = make_app(tmp_path).handle("GET", "/api/tools", None, H)[1][0]
    assert yt["free"] is True and yt["stages"][0] == "Accessing YouTube"


# ---------- key endpoints and option-based jobs ----------
import cloud as cloud_mod

KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"


class FakeKeystore:
    def __init__(self, key=None, fail=None, fail_read=None):
        self.key, self.fail, self.fail_read = key, fail, fail_read

    def get_key(self):
        return self.key

    def set_key(self, key):
        if self.fail:
            raise self.fail
        self.key = key

    def delete_key(self):
        self.key = None

    def status(self):
        if self.fail_read:
            raise self.fail_read
        return {"saved": bool(self.key), "last4": self.key[-4:] if self.key else None}


class FakeCloud(FakeClient):
    def __init__(self, key):
        super().__init__()
        self.key = key
        self.tokens_in, self.tokens_out = 1234, 567


def make_cloud_app(tmp_path, keystore=None, key_check=None, cloud_factory=None, **kw):
    return server.App(HistoryStore(tmp_path / "h.json"), kw.get("client") or FakeClient(), lambda url: VIDEO,
                      keystore=keystore or FakeKeystore(), cloud_factory=cloud_factory or FakeCloud,
                      key_check=key_check or (lambda key: None), pricebook=kw.get("pricebook", NO_PRICES))


def test_key_status_save_update_and_remove(tmp_path):
    app = make_cloud_app(tmp_path)
    assert app.handle("GET", "/api/settings/key", None, H)[1] == {"saved": False, "last4": None}
    status, body = app.handle("POST", "/api/settings/key", {"key": KEY}, H)
    assert status == 200 and body == {"saved": True, "last4": KEY[-4:]}
    assert KEY not in json.dumps(app.handle("GET", "/api/settings/key", None, H)[1])
    newer = "sk-ant-api03-ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ9999"  # updating replaces the saved key
    assert app.handle("POST", "/api/settings/key", {"key": newer}, H)[1] == {"saved": True, "last4": "9999"}
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
    status, done = run_option(make_cloud_app(tmp_path), "local-easy")
    rec = done["result"]
    assert (rec["option"], rec["provider"], rec["effort"], rec["model"], rec["model_name"]) == \
        ("local-easy", "local", "Easy", "qwen3.5:2b", "qwen3.5:2b")
    assert "tokens_in" not in rec


def test_cloud_option_job_uses_the_cloud_client_and_records_tokens(tmp_path):
    seen = {}

    def factory(key):
        seen["key"] = key
        return FakeCloud(key)

    app = make_cloud_app(tmp_path, FakeKeystore(KEY), cloud_factory=factory)
    status, done = run_option(app, "cloud-medium")
    rec = done["result"]
    assert seen["key"] == KEY and done["status"] == "done"
    assert (rec["provider"], rec["effort"], rec["model"], rec["model_name"]) == ("cloud", "Medium", "claude-sonnet-5-5", "Sonnet 5.5")
    assert (rec["tokens_in"], rec["tokens_out"]) == (1234, 567)
    assert KEY not in json.dumps(rec) and KEY not in json.dumps(done)


def test_cloud_option_without_a_key_and_unknown_option(tmp_path):
    app = make_cloud_app(tmp_path)
    status, body = run_option(app, "cloud-easy")
    assert status == 400 and "API key on the Home page" in body["error"]
    assert run_option(app, "cloud-bogus")[0] == 400


def test_legacy_model_field_still_means_local(tmp_path):
    app = make_cloud_app(tmp_path)
    done = run_job(app, model="qwen3.5:2b")
    assert done["result"]["provider"] == "local" and done["result"]["model"] == "qwen3.5:2b"


def test_cloud_errors_and_key_scrubbing(tmp_path):
    class Boom(FakeCloud):
        def chat(self, model, messages, schema=None, token=None):
            raise RuntimeError(f"weird failure with {self.key} inside")

    class Overloaded(FakeCloud):
        def chat(self, model, messages, schema=None, token=None):
            raise cloud_mod.CloudError("Anthropic is overloaded right now. Try again shortly.")

    for factory, expected in ((Boom, "Unexpected error"), (Overloaded, "overloaded")):
        app = make_cloud_app(tmp_path, FakeKeystore(KEY), cloud_factory=factory)
        status, done = run_option(app, "cloud-hard")
        assert done["status"] == "error" and expected in done["error"] and KEY not in json.dumps(done)


def test_cloud_jobs_cannot_be_aborted_but_local_jobs_can(tmp_path):
    class Gated(FakeCloud):
        gate = threading.Event()
        in_chat = threading.Event()

        def chat(self, model, messages, schema=None, token=None):
            Gated.in_chat.set()
            Gated.gate.wait(10)
            return super().chat(model, messages, schema, token)

    app = make_cloud_app(tmp_path, FakeKeystore(KEY), cloud_factory=Gated)
    status, body = app.handle("POST", "/api/youtube/summarize", {"url": "https://youtu.be/dQw4w9WgXcQ", "option": "cloud-easy"}, H)
    assert Gated.in_chat.wait(3)
    running = job(app, body["job_id"])
    assert running["status"] == "running" and running["can_abort"] is False
    status, err = app.handle("POST", f"/api/jobs/{body['job_id']}/abort", {}, H)
    assert status == 409 and "cloud" in err["error"].lower() and "can't be aborted" in err["error"]
    assert job(app, body["job_id"])["status"] == "running"       # the request carries on
    Gated.gate.set()
    app.wait(body["job_id"])
    done = job(app, body["job_id"])
    assert done["status"] == "done" and len(app.handle("GET", "/api/history", None, H)[1]) == 1  # result is kept

    client = GatedClient()
    local = make_app(tmp_path / "local", client) if (tmp_path / "local").mkdir() is None else None
    jid = start(local)
    assert client.in_chat.wait(3)
    assert job(local, jid)["can_abort"] is True
    client.gate.set()
    local.wait(jid)


def test_a_keychain_read_failure_does_not_take_the_panel_down(tmp_path):
    import keystore as ks_mod

    app = make_cloud_app(tmp_path, FakeKeystore(fail_read=ks_mod.KeystoreError("Could not read the Keychain.")))
    status, body = app.handle("GET", "/api/settings/key", None, H)
    assert status == 200 and body["saved"] is False and "Keychain" in body["error"]
    assert app.handle("GET", "/api/tools", None, H)[0] == 200          # everything else still works
    assert run_option(app, "local-easy")[1]["status"] == "done"          # local summaries still work


def test_test_helper_never_uses_the_real_keychain_or_anthropic(tmp_path):
    app = make_app(tmp_path)
    assert isinstance(app.keystore, FakeKeystore)
    assert app.key_check(KEY) is None


# ---------- OpenRouter key, routing, prices ----------
OR_KEY = "sk-or-v1-abcdefghijklmnopqrstuvwxyz0123456789abcdef"
OPENAI_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"


class RecordingCloud(FakeCloud):
    seen = []

    def chat(self, model, messages, schema=None, token=None):
        RecordingCloud.seen.append(model)
        return super().chat(model, messages, schema, token)


def test_openrouter_key_is_accepted_and_openai_key_is_refused_with_a_reason(tmp_path):
    ks = FakeKeystore()
    app = make_cloud_app(tmp_path, ks)
    assert app.handle("POST", "/api/settings/key", {"key": OR_KEY}, H)[0] == 200 and ks.key == OR_KEY
    ks2 = FakeKeystore()
    status, body = make_cloud_app(tmp_path, ks2).handle("POST", "/api/settings/key", {"key": OPENAI_KEY}, H)
    assert status == 400 and "OpenRouter" in body["error"] and "Claude" in body["error"] and ks2.key is None
    assert OPENAI_KEY not in json.dumps(body)


def test_openrouter_key_routes_to_openrouter_model_ids_and_estimates_dollars(tmp_path):
    RecordingCloud.seen = []
    app = make_cloud_app(tmp_path, FakeKeystore(OR_KEY), cloud_factory=RecordingCloud, pricebook=PRICES)
    status, done = run_option(app, "cloud-medium")
    rec = done["result"]
    assert RecordingCloud.seen and set(RecordingCloud.seen) == {"anthropic/claude-sonnet-5.5"}
    assert (rec["route"], rec["model"], rec["model_name"], rec["provider"]) == \
        ("openrouter", "anthropic/claude-sonnet-5.5", "Sonnet 5.5", "cloud")
    assert abs(rec["cost_usd"] - (1234 * 2e-6 + 567 * 1e-5)) < 1e-9
    assert OR_KEY not in json.dumps(done)


def test_anthropic_key_still_uses_anthropic_model_ids(tmp_path):
    RecordingCloud.seen = []
    app = make_cloud_app(tmp_path, FakeKeystore(KEY), cloud_factory=RecordingCloud, pricebook=PRICES)
    rec = run_option(app, "cloud-easy")[1]["result"]
    assert set(RecordingCloud.seen) == {"claude-haiku-4-5-20251001"}
    assert rec["route"] == "anthropic" and rec["model"] == "claude-haiku-4-5-20251001"
    assert abs(rec["cost_usd"] - (1234 * 1e-6 + 567 * 5e-6)) < 1e-9   # estimated from the public list price


def test_no_price_means_no_dollar_figure_not_an_error(tmp_path):
    app = make_cloud_app(tmp_path, FakeKeystore(OR_KEY), pricebook=NO_PRICES)
    rec = run_option(app, "cloud-hard")[1]["result"]
    assert "cost_usd" not in rec and rec["tokens_in"] == 1234


def test_prices_endpoint_lists_cloud_option_prices_and_survives_no_prices(tmp_path):
    prices = make_cloud_app(tmp_path, pricebook=PRICES).handle("GET", "/api/prices", None, H)
    assert prices == (200, {"cloud-easy": {"in": 1.0, "out": 5.0}, "cloud-medium": {"in": 2.0, "out": 10.0}})
    assert make_cloud_app(tmp_path, pricebook=NO_PRICES).handle("GET", "/api/prices", None, H) == (200, {})


# ---------- the optional port value of `panel/run.sh [localhost:number]` ----------
import pytest


@pytest.mark.parametrize("value,port", [
    ("8123", 8123), ("localhost:8123", 8123), ("127.0.0.1:9000", 9000), (":8080", 8080), (" localhost:8000 ", 8000),
])
def test_parse_port_accepts_a_number_or_localhost_number(value, port):
    assert server.parse_port(value) == port


@pytest.mark.parametrize("bad", ["", "abc", "localhost:", "localhost:abc", "evil.example:8000", "0", "70000", "localhost:0", "http://localhost:8000"])
def test_parse_port_rejects_everything_else_with_a_clear_message(bad):
    with pytest.raises(ValueError, match="localhost"):
        server.parse_port(bad)
