"""JSON-file history of saved summaries."""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

LIST_KEYS = ("id", "title", "video_id", "created", "model", "seconds", "effort", "provider", "model_name", "tool")


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            raise ValueError("history file is not a list")
        except FileNotFoundError:
            return []
        except ValueError:  # corrupt content; OS errors (permissions) propagate instead
            try:
                os.replace(self.path, self.path.with_name(self.path.name + ".bak"))
            except OSError:
                pass
            return []

    def _save(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, record):
        with self._lock:
            items = self._load()
            stored = {
                **record,
                "id": uuid.uuid4().hex[:12],
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            items.append(stored)
            self._save(items)
            return stored

    def list(self):
        with self._lock:
            items = self._load()
        return [{k: r.get(k) for k in LIST_KEYS} for r in reversed(items)]

    def get(self, record_id):
        with self._lock:
            return next((r for r in self._load() if r.get("id") == record_id), None)

    def delete(self, record_id):
        with self._lock:
            items = self._load()
            kept = [r for r in items if r.get("id") != record_id]
            if len(kept) == len(items):
                return False
            self._save(kept)
            return True
