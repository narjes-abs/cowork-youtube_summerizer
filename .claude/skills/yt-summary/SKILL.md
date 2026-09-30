---
name: yt-summary
description: Summarize a YouTube video into a structured, interactive artifact page (TL;DR, collapsible sections, timestamp links, Markdown copy). Use when the user runs /yt-summary <link> or asks to summarize a YouTube video for fast learning.
---

# YouTube Summary

Turn a YouTube link into an interactive summary page. Skill dir: the absolute path of `.claude/skills/yt-summary/` in the project (call it `$SKILL`; always use the absolute path so commands work from any directory).

## Steps

1. **Get the link** from the arguments. If none was given, ask for it.

2. **Record starting usage.** If the `get_usage` tool (session management; load it with ToolSearch if deferred) is available, call it now and note `context.tokensUsed` and the plan's "5-hour limit" `percentUsed`.

2b. **Set up once.** If `$SKILL/.venv` does not exist:
   ```bash
   python3 -m venv $SKILL/.venv && $SKILL/.venv/bin/python -m pip install -q -r $SKILL/requirements.txt
   ```

3. **Fetch the transcript** into the scratchpad directory:
   ```bash
   $SKILL/.venv/bin/python -W ignore $SKILL/fetch_transcript.py "<link>" --out <scratchpad>/transcript.txt > <scratchpad>/meta.json
   ```
   The command writes one JSON line to `meta.json` (`video_id`, `title`, `duration_seconds`, `chars`, `transcript_path`); read it. On failure the line is `{"error": ...}`. If it contains `"error"`, tell the user that message plainly and STOP (no fallback; do not invent a summary). If YouTube blocks the request (IP block), tell the user to see the Troubleshooting section of the README.

4. **Read the transcript** (`transcript_path`). Lines look like `[12:03] text`, roughly 50 characters each. Read it with the Read tool in chunks of 800 lines (`offset`/`limit`) until the end, jotting the key points and their timestamps after each chunk, then merge the notes into one summary. This keeps very long videos (2 hours and more) within limits; do not try to read the whole file in one call.

5. **Write the summary JSON** (after reading the transcript, call `get_usage` again to measure the run so far) to `<scratchpad>/summary.json`, exactly this shape:
   ```json
   {
     "tldr": "One sentence: what the video is and its main point.",
     "sections": [
       {"title": "Short section title", "bullets": ["concrete point", "concrete point"], "start": 0}
     ],
     "takeaways": ["The 3-6 things worth remembering"],
     "cost": "≈ 45k tokens · ~2% of 5-hour limit"
   }
   ```
   `cost` is shown at the top of the page as `cost: <value>`: tokens added to the session since step 2 (difference in `tokensUsed`) and how much the 5-hour percent rose (write `<1%` if it did not move). If `get_usage` is unavailable, omit `cost`. Dollar prices are not available, so never invent one. Rules: 3-7 sections in chronological order; `start` is an integer number of seconds taken from the transcript timestamps at the moment that section begins (convert `[1:02:05]` to 3725); bullets are concrete facts and claims, not vague descriptions; write in the transcript's language; base everything on the transcript only.

6. **Build the page:**
   ```bash
   $SKILL/.venv/bin/python $SKILL/build_page.py <scratchpad>/summary.json <scratchpad>/meta.json <scratchpad>/summary.html
   ```
   If it prints an `"error"`, fix `summary.json` accordingly and re-run.

7. **Publish** `<scratchpad>/summary.html` with the Artifact tool (`icon: "video"`, a one-sentence `description`). Timestamps in the page are links that open the video at that moment; artifacts cannot embed YouTube, so do not try to add a player.

8. **Reply** with the artifact link and a 2-line gist (the tldr plus the single most important takeaway). Do not paste the whole summary.

9. **Report cost** in one line, the same value as the page's `cost`, plus the plan's current 5-hour and weekly percent used. If usage could not be read, say so.
