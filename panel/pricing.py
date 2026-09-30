"""Model prices from OpenRouter's public list (no key needed). Used for estimates only."""
import http.client
import json
import threading
import time


def _fetch_public():
    conn = http.client.HTTPSConnection("openrouter.ai", timeout=8)
    try:
        conn.request("GET", "/api/v1/models")
        resp = conn.getresponse()
        if resp.status != 200:
            raise OSError(f"price list returned {resp.status}")
        return json.loads(resp.read())
    finally:
        conn.close()


class PriceBook:
    def __init__(self, fetch=None, ttl=3600):
        self._fetch = fetch or _fetch_public
        self.ttl = ttl
        self._prices = None  # {model_id: (dollars_per_input_token, dollars_per_output_token)}
        self._at = 0.0
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._prices is not None and time.time() - self._at < self.ttl:
                return self._prices
            try:
                parsed = {}
                for m in self._fetch().get("data", []):
                    p = m.get("pricing") or {}
                    try:
                        parsed[m["id"]] = (float(p["prompt"]), float(p["completion"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                self._prices = parsed
            except Exception:  # offline or odd reply: keep older prices, otherwise none
                if self._prices is None:
                    self._prices = {}
            self._at = time.time()
            return self._prices

    def per_million(self, model_id):
        price = self._load().get(model_id)
        return {"in": round(price[0] * 1e6, 4), "out": round(price[1] * 1e6, 4)} if price else None

    def cost(self, model_id, tokens_in, tokens_out):
        price = self._load().get(model_id)
        return price[0] * (tokens_in or 0) + price[1] * (tokens_out or 0) if price else None
