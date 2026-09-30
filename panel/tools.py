"""Server-side registry of the panel's tools: info tags, progress stages, summarizer options."""

_LOCAL = [("Easy", "qwen3.5:2b", "low"), ("Medium", "qwen3.5:9b", "medium"), ("Hard", "qwen3.5:27b", "high")]
_CLOUD = [  # (effort, Anthropic model id, display name, OpenRouter model id)
    ("Easy", "claude-haiku-4-5-20251001", "Haiku 4.5", "anthropic/claude-haiku-4.5"),
    ("Medium", "claude-sonnet-5-5", "Sonnet 5.5", "anthropic/claude-sonnet-5.5"),
    ("Hard", "claude-opus-5-5", "Opus 5.5", "anthropic/claude-opus-5.5"),
]

OPTIONS = [
    {"id": f"local-{effort.lower()}", "provider": "local", "effort": effort, "model": model, "name": model,
     "load": load, "openrouter_model": None,
     "tag": {"label": "Summarizer", "detail": f"Ollama {model}", "kind": "local"}}
    for effort, model, load in _LOCAL
] + [
    {"id": f"cloud-{effort.lower()}", "provider": "cloud", "effort": effort, "model": model, "name": name,
     "load": None, "openrouter_model": or_model,
     "tag": {"label": "Summarizer", "detail": f"Claude {name}", "kind": "network", "paid": True}}
    for effort, model, name, or_model in _CLOUD
]
DEFAULT_OPTION = "local-medium"

_BASE_TAGS = [
    {"label": "YouTube captions", "detail": "youtube-transcript-api", "kind": "network"},
    {"label": "Summarizer", "detail": "Ollama", "kind": "local"},
    {"label": "Video title", "detail": "YouTube oEmbed", "kind": "network"},
]

TOOLS = [
    {
        "id": "youtube",
        "name": "YouTube Summarize",
        "icon": "youtube",
        "tags": _BASE_TAGS,
        # progress stages shown to the user, and the percent range each one covers
        "stages": ["Accessing YouTube", "Reading captions", "Summarizing", "Finishing"],
        "bounds": [[0, 8], [8, 15], [15, 92], [92, 100]],
        "options": OPTIONS,
        "default_option": DEFAULT_OPTION,
    },
]


def get_option(option_id):
    return next((o for o in OPTIONS if o["id"] == option_id), None)


def is_free(tool):
    """A tool (a dict with tags) is free when none of its tags is marked paid."""
    return not any(t.get("paid") for t in tool.get("tags", []))


def option_is_free(tool, option):
    tags = [option["tag"] if t["label"] == "Summarizer" else t for t in tool["tags"]]
    return is_free({"tags": tags})


def list_tools():
    out = []
    for t in TOOLS:
        item = {**t, "free": is_free(t)}
        if "options" in t:
            item["has_free"] = any(option_is_free(t, o) for o in t["options"])
            item["has_paid"] = any(not option_is_free(t, o) for o in t["options"])
        out.append(item)
    return out


def get_tool(tool_id):
    return next((t for t in list_tools() if t["id"] == tool_id), None)
