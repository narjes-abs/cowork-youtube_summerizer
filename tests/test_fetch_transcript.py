import json

import pytest

import fetch_transcript as ft

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&t=90s",
    f"https://youtu.be/{VID}?si=abc123",
    f"https://m.youtube.com/watch?v={VID}",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"  {VID}  ",
])
def test_extract_video_id_variants(url):
    assert ft.extract_video_id(url) == VID


@pytest.mark.parametrize("bad", ["", "https://example.com/watch?v=" + VID, "hello", "https://www.youtube.com/watch"])
def test_extract_video_id_rejects_garbage(bad):
    with pytest.raises(ValueError, match="Not a valid YouTube link"):
        ft.extract_video_id(bad)


def test_format_timestamp():
    assert ft.format_timestamp(0) == "0:00"
    assert ft.format_timestamp(65.9) == "1:05"
    assert ft.format_timestamp(3600) == "1:00:00"
    assert ft.format_timestamp(3725) == "1:02:05"


def test_format_transcript_lines():
    segs = [{"start": 0.0, "text": "hi"}, {"start": 3700.0, "text": "late"}]
    assert ft.format_transcript(segs) == "[0:00] hi\n[1:01:40] late"


def test_main_invalid_url_prints_json_error(capsys, tmp_path):
    code = ft.main(["nonsense", "--out", str(tmp_path / "t.txt")])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert "Not a valid YouTube link" in out["error"]


@pytest.mark.parametrize("url", [
    f"youtube.com/watch?v={VID}",
    f"www.youtube.com/watch?v={VID}",
    f"youtu.be/{VID}",
])
def test_extract_video_id_accepts_scheme_less_urls(url):
    assert ft.extract_video_id(url) == VID


def test_ip_block_is_reported_as_blocking_not_missing_captions(monkeypatch):
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import IpBlocked

    def boom(self, video_id):
        raise IpBlocked(video_id)

    monkeypatch.setattr(YouTubeTranscriptApi, "list", boom)
    with pytest.raises(ft.NoCaptions) as exc:
        ft.fetch_video(VID)
    assert "blocking" in str(exc.value)
    assert "no retrievable captions" not in str(exc.value)


def test_network_error_prints_json_error(monkeypatch, capsys, tmp_path):
    def boom(video_id):
        raise ConnectionError("offline")

    monkeypatch.setattr(ft, "fetch_video", boom)
    code = ft.main([VID, "--out", str(tmp_path / "t.txt")])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert "offline" in out["error"]
