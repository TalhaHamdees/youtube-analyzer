---
name: clone-competitor
description: Reverse-engineer a successful YouTube channel into a reproducible SOP — title templates, thumbnail rules, and a timed script skeleton you can shoot to next week. Use when the user names a competitor channel and wants to ship videos in that channel's winning format.
---

# clone-competitor (flagship)

## When to use
- User names a channel and wants to "copy what's working" / "learn their formula" / "make something like X".
- User wants output they can act on, not a vibe-analysis — a playbook with fill-in-the-blank title strings, concrete thumbnail rules with citations, and a timed script skeleton.
- User has a `YOUTUBE_API_KEY` configured. (Without it, this skill cannot run — own-channel tools don't cover competitors.)

## Required tools (from `youtube-analyzer` MCP server)
- `get_channel_videos(channel, limit, refresh)` — pulls the top uploads with stats. Resolves handles / URLs / raw channel IDs.
- `get_video_details(video_id)` — hydrate detail when `get_channel_videos` skipped fields.
- `get_thumbnail(video_id, size="maxresdefault")` — required for visual pattern extraction. Falls through to smaller sizes automatically.
- `get_transcript(video_id)` — top 10 videos only (quota-friendly); for the script-skeleton beats.
- `save_report(name, markdown)` — writes `{channel_slug}-SOP.md` to `data/reports/`.

## Inputs
- `channel` — handle (`@mkbhd`), full URL (`https://www.youtube.com/@mkbhd`), or raw channel ID (`UC...`). Required.
- `top_n` — how many videos to analyze (default 20, cap 30 — past that the pattern analysis plateaus and quota cost climbs).

## Steps

1. **Resolve and pull.** Call `get_channel_videos(channel, limit=top_n)`. On error stop and report. Realistic codes: `invalid_channel`, `channel_not_found`, `missing_api_key`, `quota_exceeded`, `rate_limited`, `invalid_api_key`. On success, expect `{"channel_id", "channel_title", "count", "videos": [...]}`. **Sort the `videos` list by `views` descending regardless of input order** — top videos drive patterns; recent uploads muddy them. **If `count < 10`**, warn the user, lower the "≥3 videos for a pattern" threshold to 2, and set a weaker-confidence flag in Caveats.

2. **Fetch thumbnails.** For each of the top `top_n` videos, call `get_thumbnail(video_id, size="maxresdefault")`. The tool falls back to `sddefault` / `hqdefault` when maxres isn't produced — that's fine. On `{"error": "thumbnail_unavailable"}` for a specific video, skip it in the visual-pattern analysis but keep it in the title/transcript analysis; note the skip in Caveats. Save the returned `path` values; you'll read them as images.

3. **Read every thumbnail (vision).** For each thumbnail you fetched, read the image and record along these axes:
   - **Face in frame** — prominent / small / none. If prominent, expression (surprise / neutral / smile / "pointing-at-something").
   - **Text overlay** — yes/no. If yes: word count, font weight (bold/regular), color vs background, positioning (top / center / bottom / corner).
   - **Color palette** — 2–3 dominant colors.
   - **Composition** — centered subject / split-screen (before-after) / arrow-or-circle-highlight / product-as-hero / scene-only.
   - **"Must-have" vs "must-not-have" signals** — after reading all of them, call out rules where ≥ 3 thumbnails share a trait (the rule) and ≥ 3 do NOT have a competing trait (the must-not).

4. **Cluster the titles.** For each of the top `top_n` titles, tag:
   - Length bucket: ≤30 / 31–45 / 46–60 / 61+ chars.
   - Has number (5 ways / top 10 / $1,000): yes/no.
   - Has brackets / parentheses: yes/no — what goes in them (year, qualifier).
   - Hook shape: question / bold claim / how-to / list / comparison / curiosity gap / review.
   - CAPS ratio: % uppercase among letters.
   - Power words: emotional ("shocking", "insane"), authority ("ultimate", "definitive"), curiosity ("secret", "no one tells you").
   Report buckets with ≥ 3 members as a "title pattern" — ignore the long tail.

5. **Read the top 10 scripts.** For each of the top 10 by views, call `get_transcript(video_id)`. Build a beat-by-beat from the transcript segments:
   - Hook (0:00–0:30) — type (question / bold claim / story opener / stat / demo).
   - "Here's what you'll learn" promise — the timestamp where the creator tells the viewer what the video is about. Record the second-mark.
   - Intro length — seconds until the main content starts.
   - CTA placement — early (before 30s) / middle / end / multiple.
   - Transition cadence — how often topics shift (seconds between explicit segues).
   - Closing — subscribe prompt / "watch this next" / call-to-action / soft ending.
   Aggregate: report the median of each numeric field across the 10 scripts, plus the modal hook type and CTA placement.

6. **Synthesize three reproducible templates:**
   - **Title template(s)** — 2–4 fill-in-the-blank strings derived from title-pattern clusters. Example: `"[N] [Thing] That [Surprising Verb] [Audience Outcome]"`. Include 3 example fills per template drawn from the channel's actual titles.
   - **Thumbnail ruleset** — 5–10 concrete rules. Each rule must include the video_ids that prove it. Split into "must-haves" and "must-avoids".
   - **Script skeleton** — a timed beat sheet derived from step 5. Include seconds markers and example transcripts. Provide at least 6 beats — do **not** truncate with `...`. Example:
     ```
     0:00–0:08   Hook ({modal hook type}). Example: [00:05] (video_id) "…"
     0:08–0:20   Promise — "here's what you'll learn". Example: [00:15] (video_id) "…"
     0:20–0:45   Setup / stakes. Example: [00:30] (video_id) "…"
     0:45–3:00   First beat — main argument or demo. Example: [01:30] (video_id) "…"
     3:00–5:30   Second beat — counterpoint / depth. Example: [04:15] (video_id) "…"
     5:30–6:15   CTA ({modal placement}). Example: [05:50] (video_id) "…"
     6:15–end    Close — {subscribe / watch-next / soft}. Example: [06:30] (video_id) "…"
     ```

7. **"Do this next week."** Three concrete video ideas in this channel's format. Each includes: proposed title (using one of the title templates), which thumbnail rules apply, and which script skeleton beat is the hook. These must feel specific enough to shoot tomorrow.

8. **Save.** Call `save_report(name="{channel_slug}-SOP", markdown=<body below>)`. Report the absolute path.

## Output format (the report body)

```
# {channel_title} — Reproducible SOP
_Top {top_n} videos · analyzed {date} · channel_id {channel_id}_

## Top {top_n} table
| # | Title | Views | Published | video_id |
| - | ----- | ----- | --------- | -------- |
...

## Title patterns
### Template 1: {template string}
- Sample fills from {channel_title}:
  - "{actual title 1}" ({video_id})
  - "{actual title 2}" ({video_id})
  - "{actual title 3}" ({video_id})

### Template 2: ...

## Thumbnail ruleset
**Must have:**
- Rule: {e.g. "bold 2-word text overlay, yellow on dark background, top-right quadrant"} — proof: {video_ids}
- Rule: ...

**Must avoid:**
- Rule: {e.g. "no plain screenshots / no background clutter"} — proof: {video_ids in the channel that DON'T do this, confirming the anti-pattern}
- Rule: ...

## Script skeleton
(Median across top-10 scripts unless noted.)
- **0:00–{hook_end}**  Hook — {modal hook type}. Example: "{verbatim opening from video_id}"
- **{hook_end}–{promise_end}**  Promise. Example: "{verbatim "here's what you'll learn" line from video_id}"
- ...
- **{cta_start}–end**  CTA — {modal placement}. Example: "{verbatim CTA line from video_id}"

## Script invariants (from the channel's data)
- Median intro length: {seconds}
- Modal CTA placement: {early/middle/end}
- Transition cadence: {seconds} between explicit segues
- Closing style: {subscribe prompt / watch-next / soft}

## Do this next week — 3 concrete video ideas
1. **"{proposed title}"** — uses Template {n}, lean into thumbnail rules {rule-ids}, hook from skeleton beat 0.
2. ...

## Caveats
- _Anything about the channel that doesn't fit the pattern — a hit driven by a guest, news topicality, algorithm anomaly_
- _Small-sample notes if top_n < 20_
- _Missing transcripts for any of the top 10 (list them) and what you inferred despite the gap_
```

## Quality bar — before saving

- **Every claim cites ≥ 3 specific video_ids.** If you can't name three videos that demonstrate a rule, it's not a rule — it's a vibe.
- The title templates are fill-in-the-blank strings you can act on. "Use strong titles" is not a template.
- The thumbnail ruleset contains "must-avoid" rules too, not just must-haves. A reproducible SOP tells you what NOT to do.
- The script skeleton has real timestamps drawn from the top 10, not placeholder times.
- If the channel has a hit driven by an *outlier* (guest appearance, viral news, collab), **exclude it from pattern counts** (not just flag it in Caveats). The patterns must describe the *reproducible* winners.
- If `get_transcript` fails for > 5 of the top 10, say so in Caveats and weaken the script-skeleton confidence accordingly — don't fake depth.

## Quota estimate (for the user's awareness)

- `get_channel_videos(limit=20)`: ~2 units (handle resolution) + 1 (channel lookup) + 1 (playlistItems) + 1 (videos hydration) = ~5 units.
- 20 × `get_thumbnail`: 0 API units (img.youtube.com is free).
- 10 × `get_transcript`: 0 API units (youtube-transcript-api is free).
- Second run within 7 days hits cache, zero units consumed.

## Example invocation
```
/clone-competitor @mkbhd
/clone-competitor https://www.youtube.com/@veritasium top_n=25
```
