import tools


def test_youtube_tool_and_tags():
    listed = tools.list_tools()
    yt = next(t for t in listed if t["id"] == "youtube")
    assert yt["name"] == "YouTube Summarize"
    tags = {t["label"]: t for t in yt["tags"]}
    assert tags["YouTube captions"]["kind"] == "network"
    assert tags["Summarizer"]["kind"] == "local"
    assert tags["Video title"]["kind"] == "network"
    assert tags["Video title"]["detail"] == "YouTube oEmbed"
    assert tags["YouTube captions"]["detail"] == "youtube-transcript-api"


def test_captions_tag_is_network_because_download_goes_to_youtube():
    yt = tools.list_tools()[0]
    tags = {t["label"]: t for t in yt["tags"]}
    assert tags["YouTube captions"]["kind"] == "network"
    assert tags["Summarizer"]["kind"] == "local"


def test_youtube_is_free_and_declares_stages_and_bounds():
    yt = tools.list_tools()[0]
    assert yt["free"] is True
    assert yt["stages"] == ["Accessing YouTube", "Reading captions", "Summarizing", "Finishing"]
    b = yt["bounds"]
    assert len(b) == 4 and b[0][0] == 0 and b[-1][1] == 100
    assert all(b[i][1] == b[i + 1][0] for i in range(3))


def test_a_tool_with_a_paid_tag_is_not_free():
    paid = {"id": "x", "name": "X", "tags": [{"label": "API", "detail": "d", "kind": "network", "paid": True}]}
    assert tools.is_free(paid) is False
    assert tools.is_free({"id": "y", "name": "Y", "tags": []}) is True


def test_tools_declare_an_icon_name():
    assert tools.list_tools()[0]["icon"] == "youtube"
