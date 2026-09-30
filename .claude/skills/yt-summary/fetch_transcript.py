"""Fetch a YouTube video's captions and write a timestamped transcript file."""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class NoCaptions(Exception):
    """Raised when a video has no retrievable captions."""


def extract_video_id(url: str) -> str:
    url = url.strip()
    if ID_RE.match(url):
        return url
    if "://" not in url:
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    vid = None
    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            vid = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
        else:
            m = re.match(r"^/(shorts|embed|live|v)/([^/?]+)", parsed.path)
            if m:
                vid = m.group(2)
    if vid and ID_RE.match(vid):
        return vid
    raise ValueError(f"Not a valid YouTube link: {url!r}")


def format_timestamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def format_transcript(segments: list) -> str:
    return "\n".join(f"[{format_timestamp(s['start'])}] {s['text']}" for s in segments)


def _fetch_title(video_id: str) -> str:
    url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(
        f"https://www.youtube.com/watch?v={video_id}", safe=""
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.load(resp)["title"]
    except Exception:
        return video_id


def fetch_video(video_id: str) -> dict:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        CouldNotRetrieveTranscript,
        NoTranscriptFound,
        RequestBlocked,
        YouTubeRequestFailed,
    )

    try:
        transcripts = YouTubeTranscriptApi().list(video_id)
        try:
            transcript = transcripts.find_transcript(["en"])
        except NoTranscriptFound:
            transcript = next(iter(transcripts))
        fetched = transcript.fetch()
    except (RequestBlocked, YouTubeRequestFailed) as exc:
        raise NoCaptions(
            "YouTube is blocking requests from this network (common on VPNs and cloud IPs). "
            "Turn off the VPN or try again later."
        ) from exc
    except (CouldNotRetrieveTranscript, StopIteration) as exc:
        raise NoCaptions(
            "This video has no retrievable captions (disabled, private, or unavailable)."
        ) from exc
    segments = [
        {"start": float(sn.start), "text": " ".join(sn.text.split())} for sn in fetched
    ]
    if not segments:
        raise NoCaptions("The caption track for this video is empty.")
    last = fetched[-1]
    return {
        "video_id": video_id,
        "title": _fetch_title(video_id),
        "duration_seconds": int(last.start + last.duration),
        "segments": segments,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--out", required=True, help="where to write the transcript text")
    args = parser.parse_args(argv)
    try:
        video = fetch_video(extract_video_id(args.url))
    except Exception as exc:  # ValueError, NoCaptions, network errors: always one JSON line
        print(json.dumps({"error": str(exc) or type(exc).__name__}))
        return 1
    text = format_transcript(video["segments"])
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(json.dumps({
        "video_id": video["video_id"],
        "title": video["title"],
        "duration_seconds": video["duration_seconds"],
        "chars": len(text),
        "transcript_path": args.out,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
