"""Summarize a timestamped transcript with a local Ollama model."""
import http.client
import json
import re
import socket
import threading
from urllib.parse import urlparse

from build_page import validate_summary

OLLAMA_URL = "http://localhost:11434"
MAX_CHUNK_CHARS = 12000

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "tldr": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "start_time": {"type": "string"},
                },
                "required": ["title", "bullets", "start_time"],
            },
        },
        "takeaways": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tldr", "sections", "takeaways"],
}

SYSTEM = (
    "You summarize YouTube video transcripts for fast learning. "
    "Use only the transcript. Be concrete, not vague."
)
SUMMARY_TASK = (
    "Write the summary as JSON: tldr (one sentence: what the video is and its main point); "
    "3-7 sections in chronological order, each with a title, 2-5 concrete bullets, and start_time = "
    "the timestamp, copied exactly as written in the transcript (like 12:03 or 1:02:05), where the "
    "section begins; and 3-6 takeaways worth remembering."
)
TIME_RE = re.compile(r"^\[(?:(\d+):)?(\d+):(\d{2})\]", re.M)
STAMP_RE = re.compile(r"(?:(\d+):)?(\d+):(\d{2})")
NOTES_LIMIT = 24000
DOWN_MSG = "Ollama is not reachable. Start it (`ollama serve`) and try again."


class OllamaDown(Exception):
    pass


class ModelMissing(Exception):
    pass


class SummaryFailed(Exception):
    pass


class Aborted(Exception):
    pass


class CancelToken:
    """Lets another thread stop a running job: closing the socket makes Ollama stop generating."""

    def __init__(self):
        self.cancelled = False
        self._conn = None
        self._lock = threading.Lock()

    @staticmethod
    def _close(conn):
        try:
            if conn.sock:
                conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass

    def bind(self, conn):
        with self._lock:
            self._conn = conn
            already = self.cancelled
        if already:
            self._close(conn)

    def cancel(self):
        with self._lock:
            self.cancelled = True
            conn = self._conn
        if conn is not None:
            self._close(conn)

    def check(self):
        if self.cancelled:
            raise Aborted("Aborted.")


class OllamaClient:
    def __init__(self, base=OLLAMA_URL):
        parsed = urlparse(base)
        self.host, self.port = parsed.hostname, parsed.port or 80

    def _request(self, method, path, payload=None, timeout=900, model=None, token=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            if token:
                token.check()
            conn.connect()  # open the socket first so an Abort can always close it
            if token:
                token.bind(conn)  # closes the socket at once if Abort arrived while connecting
                token.check()
            body = None if payload is None else json.dumps(payload).encode("utf-8")
            conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status == 404 and model:
                raise ModelMissing(f"Model {model} is not installed. Run: ollama pull {model}")
            if resp.status >= 400:
                raise OllamaDown(f"Ollama returned an error ({resp.status}).")
            return json.loads(raw)
        except (OSError, http.client.HTTPException) as exc:  # refused, timeout, closed by abort
            if token and token.cancelled:
                raise Aborted("Aborted.") from exc
            raise OllamaDown(DOWN_MSG) from exc
        except ValueError as exc:
            if token and token.cancelled:
                raise Aborted("Aborted.") from exc
            raise OllamaDown("Ollama sent a reply that could not be read.") from exc
        finally:
            conn.close()

    def list_models(self):
        data = self._request("GET", "/api/tags", timeout=5)
        return [m["name"] for m in data.get("models", [])]

    def chat(self, model, messages, schema=None, token=None):
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2, "num_ctx": 16384},
        }
        if schema:
            payload["format"] = schema
        data = self._request("POST", "/api/chat", payload, model=model, token=token)
        return data.get("message", {}).get("content", "")

    def unload(self, model):
        """Free the model from memory (stops the fan). Never raises."""
        try:
            self._request("POST", "/api/generate", {"model": model, "keep_alive": 0}, timeout=10)
        except Exception:
            pass


def transcript_times(text):
    return [
        int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        for m in TIME_RE.finditer(text)
    ]


def chunk_lines(text, max_chars=MAX_CHUNK_CHARS):
    chunks, cur, size = [], [], 0
    for line in text.split("\n"):
        extra = len(line) + (1 if cur else 0)
        if cur and size + extra > max_chars:
            chunks.append("\n".join(cur))
            cur, size = [], 0
            extra = len(line)
        cur.append(line)
        size += extra
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def normalize(summary):
    if isinstance(summary, dict):
        for sec in summary.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            stamp = sec.pop("start_time", None)
            if isinstance(stamp, str):
                m = STAMP_RE.search(stamp)
                if m:
                    sec["start"] = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            start = sec.get("start")
            try:
                if not isinstance(start, bool):
                    sec["start"] = max(0, int(float(start)))
            except (TypeError, ValueError):
                pass
    return summary


def snap_starts(summary, times):
    if times:
        for sec in summary["sections"]:
            sec["start"] = min(times, key=lambda t: abs(t - sec["start"]))
    return summary


def _ask(client, model, token, messages, schema=None):
    if token:
        token.check()
    return client.chat(model, messages, schema=schema, token=token)


def _user(title, label, body):
    return {
        "role": "user",
        "content": f"Video title: {title}\n\n{label}:\n{body}\n\n{SUMMARY_TASK}",
    }


def condense_notes(client, model, title, notes, progress, token=None):
    """Shrink the per-part notes until they fit NOTES_LIMIT (keeps the final prompt inside the context)."""
    for _ in range(6):
        if len("\n".join(notes)) <= NOTES_LIMIT or len(notes) < 2:
            break
        groups, cur, size = [], [], 0
        for note in notes:
            if cur and size + len(note) > NOTES_LIMIT:
                groups.append(cur)
                cur, size = [], 0
            cur.append(note)
            size += len(note)
        groups.append(cur)
        if len(groups) == len(notes):
            break  # every note already fills a group; cannot combine further
        progress("condensing notes")
        notes = [
            g[0] if len(g) == 1 else _ask(client, model, token, [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": (
                    f"Video title: {title}\nCondense these notes into at most 40 short bullet lines. "
                    "Keep the most important points and keep each line's [m:ss] timestamp.\n\n"
                    + "\n".join(g))},
            ])
            for g in groups
        ]
    return notes


def summarize(client, model, title, transcript, progress=None, on_step=None, token=None):
    progress = progress or (lambda msg: None)
    on_step = on_step or (lambda done, total: None)
    chunks = chunk_lines(transcript, MAX_CHUNK_CHARS)
    total = len(chunks) + 1 if len(chunks) > 1 else 1
    if len(chunks) == 1:
        on_step(0, 1)
        message = _user(title, "Transcript (lines start with [m:ss] timestamps)", chunks[0])
    else:
        notes = []
        for i, chunk in enumerate(chunks, 1):
            progress(f"reading part {i} of {len(chunks)}")
            on_step(i - 1, total)
            notes.append(_ask(client, model, token, [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": (
                    f"Video title: {title}\nThis is part {i} of {len(chunks)} of the transcript "
                    "(lines start with [m:ss] timestamps). List the key points as short bullet "
                    "lines, each starting with its [m:ss] timestamp.\n\n" + chunk)},
            ]))
        notes = condense_notes(client, model, title, notes, progress, token)
        on_step(len(chunks), total)
        message = _user(title, "Notes from every part of the video, in order", "\n".join(notes))
    progress("writing summary")
    for _ in range(2):
        raw = _ask(client, model, token, [{"role": "system", "content": SYSTEM}, message], SUMMARY_SCHEMA)
        try:
            summary = normalize(json.loads(raw))
            validate_summary(summary)
        except ValueError:
            continue
        return snap_starts(summary, transcript_times(transcript))
    raise SummaryFailed("The model returned an unusable summary. Try a larger model.")
