"""Local panel server: JSON API + static files, bound to 127.0.0.1."""
import json
import mimetypes
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
SKILL_DIR = ROOT.parent / ".claude" / "skills" / "yt-summary"
for _p in (str(SKILL_DIR), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cloud  # noqa: E402
import fetch_transcript as ft  # noqa: E402
import keystore as keystore_mod  # noqa: E402
import pricing  # noqa: E402
import summarizer as sm  # noqa: E402
import tools  # noqa: E402
from history import HistoryStore  # noqa: E402

STATIC = ROOT / "static"
DEFAULT_MODEL = "qwen3.5:9b"
ALLOWED_HOSTS = ("localhost", "127.0.0.1")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class Job:
    """One background run, with stage/percent progress and a cancel token."""

    def __init__(self, job_id, tool, model, client=None, option=None):
        self.id, self.model = job_id, model
        self.client, self.option = client, option or {}
        self.stages, self.bounds = tool["stages"], tool["bounds"]
        self.status = "running"  # running | done | error | aborted
        self.stage, self.detail, self.fraction = 0, "", 0.0
        self.result = self.error = None
        self.token = sm.CancelToken()
        self.lock = threading.RLock()

    @property
    def can_abort(self):
        """Local runs can be stopped for real. A cloud request cannot be cancelled once it is sent
        (the provider may keep generating and bill for it), so no Abort is offered for it."""
        return self.option.get("provider") != "cloud"

    def set(self, stage=None, detail=None, fraction=None):
        with self.lock:
            if self.status != "running":
                return
            if stage is not None and stage != self.stage:
                self.stage, self.fraction = stage, 0.0
            if detail is not None:
                self.detail = detail
            if fraction is not None:
                self.fraction = max(0.0, min(1.0, fraction))

    def finish(self, status, result=None, error=None):
        with self.lock:
            if self.status != "running":
                return False
            self.status, self.result, self.error = status, result, error
            return True

    def abort(self):
        with self.lock:
            if self.status != "running":
                return False
            self.status = "aborted"
            self.token.cancel()
            return True

    def to_dict(self):
        with self.lock:
            lo, hi = self.bounds[self.stage]
            percent = 100 if self.status == "done" else round(lo + (hi - lo) * self.fraction)
            label = self.stages[self.stage]
            return {
                "id": self.id, "status": self.status, "stage": self.stage + 1,
                "stage_count": len(self.stages), "label": label, "detail": self.detail,
                "percent": percent, "can_abort": self.can_abort,
                "progress": f"{label} · {self.detail}" if self.detail else label,
                "result": self.result, "error": self.error,
            }


class App:
    def __init__(self, history, client, fetch=None, keystore=None, cloud_factory=None, key_check=None, pricebook=None):
        self.history = history
        self.client = client
        self.keystore = keystore or keystore_mod.Keystore()
        self.cloud_factory = cloud_factory or cloud.make_client
        self.pricebook = pricebook or pricing.PriceBook()
        self.key_check = key_check or cloud.check_key
        self.fetch = fetch or (lambda url: ft.fetch_video(ft.extract_video_id(url)))
        self.jobs = {}
        self.threads = {}

    def handle(self, method, path, body=None, headers=None):
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        host = headers.get("host", "").split(":")[0]
        if host not in ALLOWED_HOSTS:
            return 403, {"error": "Forbidden host"}
        if method != "GET" and headers.get("x-panel") != "1":
            return 403, {"error": "Missing X-Panel header"}
        try:
            return self._route(method, urlparse(path).path, body)
        except ApiError as exc:
            return exc.status, {"error": exc.message}
        except Exception as exc:
            return 500, {"error": f"Server error: {exc}"}

    def _route(self, method, path, body):
        parts = [p for p in path.split("/") if p]
        if parts[:1] != ["api"]:
            raise ApiError(404, "Not found")
        parts = parts[1:]
        if method == "GET" and parts == ["tools"]:
            return 200, tools.list_tools()
        if method == "GET" and parts == ["models"]:
            try:
                return 200, {"models": self.client.list_models(), "default": DEFAULT_MODEL}
            except sm.OllamaDown as exc:
                return 200, {"models": [], "default": DEFAULT_MODEL, "error": str(exc)}
        if method == "GET" and parts == ["prices"]:
            out = {}
            for o in tools.OPTIONS:
                price = self.pricebook.per_million(o["openrouter_model"]) if o.get("openrouter_model") else None
                if price:
                    out[o["id"]] = price
            return 200, out
        if method == "POST" and parts == ["youtube", "summarize"]:
            return 200, {"job_id": self._start_job(body)}
        if method == "GET" and parts == ["jobs", "active"]:
            running = [j for j in self.jobs.values() if j.status == "running"]
            return 200, {"job": running[-1].to_dict() if running else None}
        if method == "GET" and len(parts) == 2 and parts[0] == "jobs":
            return 200, self._job(parts[1]).to_dict()
        if method == "POST" and len(parts) == 3 and parts[0] == "jobs" and parts[2] == "abort":
            job = self._job(parts[1])
            if not job.can_abort:
                raise ApiError(409, "A cloud request can't be aborted once it is sent. Wait for it to finish.")
            if not job.abort():
                raise ApiError(409, "That job already finished.")
            threading.Thread(target=job.client.unload, args=(job.model,), daemon=True).start()
            return 200, {"status": "aborted"}
        if parts[:1] == ["history"]:
            if method == "GET" and len(parts) == 1:
                return 200, self.history.list()
            if len(parts) == 2:
                if method == "GET":
                    rec = self.history.get(parts[1])
                    if not rec:
                        raise ApiError(404, "No such history item.")
                    return 200, rec
                if method == "DELETE":
                    if not self.history.delete(parts[1]):
                        raise ApiError(404, "No such history item.")
                    return 200, {"deleted": parts[1]}
        if parts[:2] == ["settings", "key"] and len(parts) == 2:
            return self._key_route(method, body)
        raise ApiError(404, "Not found")

    def _key_route(self, method, body):
        try:
            if method == "GET":
                try:
                    return 200, self.keystore.status()
                except keystore_mod.KeystoreError as exc:  # e.g. locked Keychain: report it, don't break the panel
                    return 200, {"saved": False, "last4": None, "error": str(exc)}
            if method == "DELETE":
                self.keystore.delete_key()
                return 200, self.keystore.status()
            if method == "POST":
                key = body.get("key") if isinstance(body, dict) else None
                error = keystore_mod.key_format_error(key)
                if error:
                    raise ApiError(400, error)
                try:
                    self.key_check(key)
                except cloud.CloudError as exc:
                    raise ApiError(400, str(exc))
                self.keystore.set_key(key)
                return 200, self.keystore.status()
        except keystore_mod.KeystoreError as exc:
            raise ApiError(500, str(exc))
        raise ApiError(404, "Not found")

    def _job(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            raise ApiError(404, "Unknown job (the server may have restarted).")
        return job

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
            route = keystore_mod.provider_of(key) or "anthropic"
            model_id = option["openrouter_model"] if route == "openrouter" else option["model"]
            option = {**option, "route": route}
        else:
            client, model_id = self.client, option["model"]
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id, tools.get_tool("youtube"), model_id, client=client, option=option)
        job.set(detail="downloading captions")
        self.jobs[job_id] = job
        thread = threading.Thread(target=self._run, args=(job, body["url"].strip()), daemon=True)
        self.threads[job_id] = thread
        thread.start()
        return job_id

    def _run(self, job, url):
        started, token = time.time(), job.token
        try:
            video = self.fetch(url)
            token.check()
            transcript = ft.format_transcript(video["segments"])
            job.set(stage=1, detail=f"{len(video['segments'])} caption lines")
            token.check()
            job.set(stage=2, detail=f"with {job.model}", fraction=0.0)
            summary = sm.summarize(
                job.client, job.model, video["title"], transcript,
                progress=lambda msg: job.set(detail=f"{msg} · {job.model}"),
                on_step=lambda done, total: job.set(fraction=done / total),
                token=token)
            job.set(stage=3, detail="checking and saving")
            with job.lock:  # abort and save cannot interleave
                if job.status != "running":
                    return
                opt = job.option
                record = {
                    "tool": "youtube",
                    "video_id": video["video_id"], "title": video["title"], "summary": summary,
                    "model": job.model, "seconds": round(time.time() - started),
                    "option": opt.get("id"), "provider": opt.get("provider"),
                    "effort": opt.get("effort"), "model_name": opt.get("name"),
                }
                if opt.get("provider") == "cloud":
                    record["route"] = opt.get("route")
                    record["tokens_in"] = getattr(job.client, "tokens_in", 0)
                    record["tokens_out"] = getattr(job.client, "tokens_out", 0)
                    priced = self.pricebook.cost(opt.get("openrouter_model"), record["tokens_in"], record["tokens_out"]) \
                        if opt.get("openrouter_model") else None
                    if priced is not None:
                        record["cost_usd"] = round(priced, 6)
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

    def wait(self, job_id, timeout=10):
        self.threads[job_id].join(timeout)


def serve_static(path):
    rel = unquote(urlparse(path).path)
    rel = "index.html" if rel in ("", "/") else rel.lstrip("/")
    if rel.startswith("static/"):
        rel = rel[len("static/"):]
    target = (STATIC / rel).resolve()
    if STATIC.resolve() not in target.parents or not target.is_file():
        return 404, b"Not found", "text/plain"
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
        ctype += "; charset=utf-8"
    return 200, target.read_bytes(), ctype


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, ctype="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method):
            if method == "GET" and not self.path.startswith("/api/"):
                return self._send(*serve_static(self.path))
            body = None
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    body = json.loads(self.rfile.read(length))
                except ValueError:
                    return self._send(400, json.dumps({"error": "Invalid JSON"}).encode())
            status, obj = app.handle(method, self.path, body, dict(self.headers))
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def log_message(self, fmt, *args):
            pass

    return Handler


def parse_port(value):
    """Accepts `8123`, `:8123`, `localhost:8123` or `127.0.0.1:8123`. The server always listens on localhost."""
    host, _, port = str(value).strip().rpartition(":")
    if host in ("", "localhost", "127.0.0.1") and port.isdigit() and 1 <= int(port) <= 65535:
        return int(port)
    raise ValueError(f"Not a valid port: {value!r}. Use a number or localhost:number, for example localhost:8123.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        port = parse_port(argv[0]) if argv else parse_port(os.environ.get("PORT", "8000"))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)
    app = App(HistoryStore(ROOT / "data" / "history.json"), sm.OllamaClient())
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"Learning Panel running at http://localhost:{port}  (Ctrl+C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
