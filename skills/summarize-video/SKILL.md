---
name: summarize-video
description: Produce a structured digest of any YouTube video from its URL — TL;DR, hook quote, main claims with timestamps, best lines, and the CTA. Use when the user shares a YouTube link and wants a fast read-through without watching.
---

# summarize-video

## When to use
- User pastes a YouTube URL (or bare 11-char video_id) and asks for a summary, notes, or "what's this video about".
- User wants timestamps they can jump to, not just prose.
- User wants the creator's hook and CTA extracted for their own writing/video work.

## Required tools
- `get_video_details(video_id)` — from the `youtube-analyzer` MCP server.
- `get_transcript(video_id, lang="en")` — from the `youtube-analyzer` MCP server.

## Inputs
- `url` — full YouTube URL, shortlink (`youtu.be/<id>`), Shorts URL, or a bare 11-char video_id.

## Steps

1. **Extract the video_id.**
   - Regex match against the input: `(?:youtu\.be/|v=|shorts/|/vi/|/embed/)([A-Za-z0-9_-]{11})` — capture group 1.
   - If the input is already 11 chars and matches `^[A-Za-z0-9_-]{11}$`, use it directly.
   - If no id can be extracted, stop and tell the user the URL is not a YouTube video link.

2. **Call `get_video_details(video_id)`.**
   - Use its `title`, `channel_title`, and `published_at` for the header line.
   - If the call returns `{"error": "..."}`, report the error and stop. Realistic codes:
     - `invalid_video_id` → the regex let through something malformed.
     - `not_found` (or `video_not_found`) → the video is private, deleted, or the id is wrong.
     - `quota_exceeded` / `rate_limited` → YouTube Data API quota / rate window; advise retry tomorrow or a second key.
     - `missing_api_key` → user has not configured `YOUTUBE_API_KEY`; tell them how to fix in `config/.env`.
     - `forbidden` / `api_error` → surface the `detail` field verbatim.

3. **Call `get_transcript(video_id)`.**
   - On `{"error": "transcripts_disabled"}`, `{"error": "no_transcript", ...}`, or `{"error": "age_restricted"}`, produce the summary from `description` alone and label the output "**Transcript unavailable — summary from metadata**". Do **not** invent content.
   - On `{"error": "request_blocked"}`, report the rate/IP block and stop.
   - On any other error, report it verbatim and stop.

4. **Produce the summary** directly from transcript segments so you can cite timestamps. Use `[mm:ss]` format — compute from `segment.t` (seconds).

## Output format

```
# {title}
**{channel_title}** · published {published_at (date only)}

## TL;DR
{2 sentences — what the video actually teaches / shows / argues}

## Hook (0:00–0:30)
> "{verbatim first lines from the transcript}"

## Main claims
- [mm:ss] (video_id) {claim 1}
- [mm:ss] (video_id) {claim 2}
- [mm:ss] (video_id) {claim 3}
- (3–7 bullets; each must be a claim or step, not a topic)

## Best quotes
- [mm:ss] (video_id) "{verbatim 1-2 sentence line}"
- [mm:ss] (video_id) "{verbatim 1-2 sentence line}"

## CTA / next step
{what the creator asks the viewer to do — subscribe, buy, click, visit, nothing}
```

## Quality bar — before returning

- Every bullet in **Main claims** must have a timestamp you can defend from the transcript (within ±5 seconds of the cited line).
- Quotes are verbatim, not paraphrased.
- If the transcript is auto-generated (`is_generated: true`), note this at the bottom in an italic line so the user knows punctuation and capitalization may be off.
- Do not invent a CTA. If the creator never asks for anything, write "none".
- Never include info from the video description that contradicts the transcript.

## Example invocation
```
/summarize-video https://www.youtube.com/watch?v=dQw4w9WgXcQ
```
