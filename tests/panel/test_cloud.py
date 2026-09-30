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


def test_abort_that_arrives_while_connecting_never_sends_the_request(fake_anthropic, monkeypatch):
    import http.client

    token = sm.CancelToken()
    real_connect = http.client.HTTPConnection.connect

    def cancel_then_connect(self):  # the user presses Abort before the socket exists
        token.cancel()
        real_connect(self)

    monkeypatch.setattr(http.client.HTTPConnection, "connect", cancel_then_connect)
    with pytest.raises(sm.Aborted):
        client(fake_anthropic).chat("m", MSGS, token=token)
    assert fake_anthropic.requests == []  # nothing was sent, so nothing is billed


def test_401_message_does_not_point_at_a_page_the_user_is_already_on(fake_anthropic):
    fake_anthropic.mode = "401"
    with pytest.raises(cloud.CloudError) as exc:
        client(fake_anthropic).chat("m", MSGS)
    assert "Home page" not in str(exc.value) and "rejected" in str(exc.value)


# ---------- OpenRouter ----------
OR_KEY = "sk-or-v1-abcdefghijklmnopqrstuvwxyz0123456789abcdef"


def or_client(srv, key=OR_KEY):
    return cloud.OpenRouterClient(key, host="127.0.0.1", port=srv.port, secure=False)


def test_openrouter_text_call_shape_headers_and_tokens(fake_openrouter):
    c = or_client(fake_openrouter)
    assert c.chat("anthropic/claude-haiku-4.5", MSGS) == "some notes"
    req = fake_openrouter.requests[0]
    assert req["path"] == "/api/v1/chat/completions" and req["method"] == "POST"
    assert req["headers"]["Authorization"] == "Bearer " + OR_KEY
    body = req["body"]
    assert body["model"] == "anthropic/claude-haiku-4.5" and body["max_tokens"] > 0
    assert body["messages"] == MSGS  # OpenAI style keeps the system message inline
    assert "tools" not in body
    assert (c.tokens_in, c.tokens_out) == (1100, 250)


def test_openrouter_schema_uses_a_forced_function_call(fake_openrouter):
    c = or_client(fake_openrouter)
    out = json.loads(c.chat("m", MSGS, schema=sm.SUMMARY_SCHEMA))
    assert out["tldr"] == "T"
    body = fake_openrouter.requests[0]["body"]
    fn = body["tools"][0]["function"]
    assert body["tools"][0]["type"] == "function" and fn["parameters"] == sm.SUMMARY_SCHEMA
    assert body["tool_choice"] == {"type": "function", "function": {"name": fn["name"]}}
    c.chat("m", MSGS, schema=sm.SUMMARY_SCHEMA)
    assert (c.tokens_in, c.tokens_out) == (2200, 500)


@pytest.mark.parametrize("mode,expected", [
    ("401", "rejected"), ("402", "out of credit"), ("403", "not allowed"), ("404", "could not find"),
    ("429", "rate"), ("500", "overloaded"), ("503", "overloaded"), ("error200", "overloaded"),
])
def test_openrouter_errors_are_plain_and_never_contain_the_key(fake_openrouter, mode, expected):
    fake_openrouter.mode, fake_openrouter.echo = mode, OR_KEY
    with pytest.raises(cloud.CloudError) as exc:
        or_client(fake_openrouter).chat("m", MSGS)
    assert expected in str(exc.value).lower() and OR_KEY not in str(exc.value)


def test_openrouter_check_key(fake_openrouter):
    or_client(fake_openrouter).check()
    assert fake_openrouter.requests[0]["path"] == "/api/v1/key" and fake_openrouter.requests[0]["method"] == "GET"
    fake_openrouter.mode = "401"
    with pytest.raises(cloud.CloudError, match="rejected"):
        or_client(fake_openrouter).check()


def test_openrouter_network_down_and_abort_before_connect(fake_openrouter, monkeypatch):
    import http.client

    with pytest.raises(cloud.CloudError, match="internet"):
        cloud.OpenRouterClient(OR_KEY, host="127.0.0.1", port=1, secure=False).chat("m", MSGS)
    token = sm.CancelToken()
    real = http.client.HTTPConnection.connect

    def cancel_then_connect(self):
        token.cancel()
        real(self)

    monkeypatch.setattr(http.client.HTTPConnection, "connect", cancel_then_connect)
    with pytest.raises(sm.Aborted):
        or_client(fake_openrouter).chat("m", MSGS, token=token)
    assert fake_openrouter.requests == []


def test_make_client_picks_the_provider_from_the_key_prefix():
    assert isinstance(cloud.make_client(KEY), cloud.AnthropicClient)
    assert isinstance(cloud.make_client(OR_KEY), cloud.OpenRouterClient)
    with pytest.raises(cloud.CloudError):
        cloud.make_client("sk-proj-abcdefghijklmnopqrstuvwxyz0123")
