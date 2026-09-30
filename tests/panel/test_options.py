import tools


def yt():
    return tools.get_tool("youtube")


def test_six_options_with_exact_models():
    got = {o["id"]: (o["provider"], o["effort"], o["model"], o["name"], o["load"]) for o in tools.OPTIONS}
    assert got == {
        "local-easy": ("local", "Easy", "qwen3.5:2b", "qwen3.5:2b", "low"),
        "local-medium": ("local", "Medium", "qwen3.5:9b", "qwen3.5:9b", "medium"),
        "local-hard": ("local", "Hard", "qwen3.5:27b", "qwen3.5:27b", "high"),
        "cloud-easy": ("cloud", "Easy", "claude-haiku-4-5-20251001", "Haiku 4.5", None),
        "cloud-medium": ("cloud", "Medium", "claude-sonnet-5-5", "Sonnet 5.5", None),
        "cloud-hard": ("cloud", "Hard", "claude-opus-5-5", "Opus 5.5", None),
    }
    assert tools.DEFAULT_OPTION == "local-medium"
    assert tools.get_option("nope") is None


def test_summarizer_tag_per_option():
    local = tools.get_option("local-hard")["tag"]
    assert local == {"label": "Summarizer", "detail": "Ollama qwen3.5:27b", "kind": "local"}
    cloud = tools.get_option("cloud-medium")["tag"]
    assert cloud == {"label": "Summarizer", "detail": "Claude Sonnet 5.5", "kind": "network", "paid": True}


def test_free_only_for_local_options():
    tool = yt()
    assert all(tools.option_is_free(tool, o) for o in tools.OPTIONS if o["provider"] == "local")
    assert not any(tools.option_is_free(tool, o) for o in tools.OPTIONS if o["provider"] == "cloud")


def test_tool_summary_flags():
    tool = yt()
    assert tool["has_free"] is True and tool["has_paid"] is True
    assert tool["default_option"] == "local-medium" and tool["free"] is True
    assert len(tool["options"]) == 6
    assert {t["label"] for t in tool["tags"]} == {"YouTube captions", "Summarizer", "Video title"}


def test_cloud_options_carry_their_openrouter_model_ids():
    ids = {o["id"]: o.get("openrouter_model") for o in tools.OPTIONS}
    assert ids["cloud-easy"] == "anthropic/claude-haiku-4.5"
    assert ids["cloud-medium"] == "anthropic/claude-sonnet-5.5"
    assert ids["cloud-hard"] == "anthropic/claude-opus-5.5"
    assert all(ids[i] is None for i in ("local-easy", "local-medium", "local-hard"))
