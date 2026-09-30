import json

from history import HistoryStore


def rec(title="T", vid="dQw4w9WgXcQ"):
    return {"video_id": vid, "title": title, "summary": {"tldr": "x"}, "model": "m", "seconds": 3}


def test_add_list_get_delete(tmp_path):
    h = HistoryStore(tmp_path / "h.json")
    a = h.add(rec("first"))
    b = h.add(rec("second"))
    assert len(a["id"]) == 12 and a["created"]
    listed = h.list()
    assert [r["title"] for r in listed] == ["second", "first"]  # newest first
    assert set(listed[0]) == {"id", "title", "video_id", "created", "model", "seconds", "effort", "provider", "model_name", "tool"}
    assert h.get(a["id"])["summary"] == {"tldr": "x"}
    assert h.get("nope") is None
    assert h.delete(a["id"]) is True
    assert h.delete(a["id"]) is False
    assert [r["id"] for r in h.list()] == [b["id"]]


def test_missing_file_is_empty(tmp_path):
    assert HistoryStore(tmp_path / "nope" / "h.json").list() == []


def test_corrupt_file_recovers(tmp_path):
    p = tmp_path / "h.json"
    p.write_text("{not json")
    h = HistoryStore(p)
    assert h.list() == []
    h.add(rec())
    assert len(json.loads(p.read_text())) == 1
    assert (tmp_path / "h.json.bak").exists()


def test_persists_across_instances(tmp_path):
    p = tmp_path / "h.json"
    HistoryStore(p).add(rec("kept"))
    assert HistoryStore(p).list()[0]["title"] == "kept"


def test_read_permission_error_is_not_treated_as_corruption(tmp_path, monkeypatch):
    import pathlib

    import pytest

    p = tmp_path / "h.json"
    HistoryStore(p).add(rec("precious"))

    def denied(self, *a, **k):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(pathlib.Path, "read_text", denied)
    with pytest.raises(PermissionError):
        HistoryStore(p).list()
    monkeypatch.undo()
    assert not (tmp_path / "h.json.bak").exists()
    assert HistoryStore(p).list()[0]["title"] == "precious"
