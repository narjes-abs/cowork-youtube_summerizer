"""Anthropic Messages API client with the same chat() interface as the Ollama client."""
import http.client
import json

import summarizer as sm

import keystore

API_HOST = "api.anthropic.com"
OPENROUTER_HOST = "openrouter.ai"
API_VERSION = "2023-06-01"


class CloudError(Exception):
    """Plain-language error. Never contains the API key."""


def _message_for(status, raw):
    text = raw.decode("utf-8", "replace").lower() if isinstance(raw, bytes) else str(raw).lower()
    if status == 401:
        return "Anthropic rejected this API key. Check the key and try again."
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
            conn.connect()  # open the socket first so an Abort can always close it
            if token:
                token.bind(conn)  # closes the socket at once if Abort arrived while connecting
                token.check()
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


def _openrouter_message(status):
    if status == 401:
        return "OpenRouter rejected this API key. Check the key and try again."
    if status == 402:
        return "Your OpenRouter account is out of credit."
    if status == 403:
        return "This API key is not allowed to use that model."
    if status == 404:
        return "OpenRouter could not find that model for this key."
    if status in (408, 429):
        return "OpenRouter is rate limiting requests. Try again shortly."
    if status in (500, 502, 503, 504, 529):
        return "OpenRouter is overloaded right now. Try again shortly."
    return f"OpenRouter returned an error ({status})."


class OpenRouterClient:
    """OpenAI-style chat completions through OpenRouter, same chat() interface as the others."""

    def __init__(self, key, host=OPENROUTER_HOST, port=443, secure=True, prefix="/api/v1"):
        self.key, self.host, self.port, self.secure, self.prefix = key, host, port, secure, prefix
        self.tokens_in = self.tokens_out = 0

    def _request(self, method, path, payload=None, token=None, timeout=300):
        cls = http.client.HTTPSConnection if self.secure else http.client.HTTPConnection
        conn = cls(self.host, self.port, timeout=timeout)
        try:
            if token:
                token.check()
            conn.connect()  # open the socket first so an Abort can always close it
            if token:
                token.bind(conn)
                token.check()
            headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json", "X-Title": "Learning Panel"}
            body = None if payload is None else json.dumps(payload).encode("utf-8")
            conn.request(method, self.prefix + path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
        except (OSError, http.client.HTTPException) as exc:
            if token and token.cancelled:
                raise sm.Aborted("Aborted.") from exc
            raise CloudError("Could not reach OpenRouter. Check your internet connection.") from exc
        finally:
            conn.close()
        if resp.status >= 400:
            raise CloudError(_openrouter_message(resp.status))
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise CloudError("OpenRouter sent a reply that could not be read.") from exc
        err = data.get("error") if isinstance(data, dict) else None
        if err:  # OpenRouter can report a provider failure inside a 200 reply
            code = err.get("code") if isinstance(err, dict) else None
            if isinstance(code, int) and code >= 400:
                raise CloudError(_openrouter_message(code))
            raise CloudError("OpenRouter reported an error. Try again shortly.")
        return data

    def check(self):
        self._request("GET", "/key", timeout=15)

    def chat(self, model, messages, schema=None, token=None):
        payload = {"model": model, "max_tokens": 4096, "messages": messages}
        if schema:
            payload["tools"] = [{"type": "function", "function": {
                "name": "submit_summary", "description": "Submit the finished summary.", "parameters": schema}}]
            payload["tool_choice"] = {"type": "function", "function": {"name": "submit_summary"}}
        data = self._request("POST", "/chat/completions", payload, token=token)
        usage = data.get("usage") or {}
        self.tokens_in += usage.get("prompt_tokens") or 0
        self.tokens_out += usage.get("completion_tokens") or 0
        message = ((data.get("choices") or [{}])[0]).get("message") or {}
        if schema:
            calls = message.get("tool_calls") or []
            if calls:
                return calls[0].get("function", {}).get("arguments", "")
        elif message.get("content"):
            return message["content"]
        raise CloudError("OpenRouter returned an empty answer.")

    def unload(self, model):
        """Nothing to free for a cloud model."""


def make_client(key):
    provider = keystore.provider_of(key)
    if provider == "anthropic":
        return AnthropicClient(key)
    if provider == "openrouter":
        return OpenRouterClient(key)
    raise CloudError("This key is not an Anthropic or OpenRouter key.")


def check_key(key):
    make_client(key).check()
