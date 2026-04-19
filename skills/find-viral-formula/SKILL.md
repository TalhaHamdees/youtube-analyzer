---
name: find-viral-formula
description: Research what's going viral in a niche right now — not one channel, the whole topic. Given a niche keyword, surveys the top videos across many channels from the last 90 days and extracts the dominant title pattern, thumbnail pattern, and the handful of channels dominating the space. Use when the user asks "what's working in <niche>" or "what should I copy".
---

# find-viral-formula

## When to use
- User names a niche / keyword / topic — "productivity on Notion", "AI coding tools", "travel vlogs in Japan" — and wants to know what's actually performing.
- User is researching *before* deciding on their next video, not auditing their own channel (that's `analyze-my-channel`).
- User has accepted this will consume YouTube Data API quota (`search_niche` costs 100 units per call, and we always try the cache first).

## Required tools (from `youtube-analyzer` MCP server)
- `search_niche(query, region, order, limit, published_after_days, refresh)` — niche cohort lookup. **Expensive**: 100 quota units per fresh call. Default 24 h cache; pass `refresh=True` only if the user explicitly wants fresh data.
- `get_video_details(video_id)` — hydrate winners. The cohort returned by `search_niche` is already hydrated, but call this for any video whose stats look stale or missing.
- `get_thumbnail(video_id, size="hqdefault")` — for visual pattern clustering on the top 10.
- `get_transcript(video_id, lang="en")` — top 5 only, to catch hook patterns.
- `save_report(name, markdown)` — write the final formula doc.

## Inputs
- `niche` — keyword or phrase. Required.
- `region` — ISO country code (default `"US"`). Optional.
- `limit` — cohort size (default 25). Cap at 50 to stay under one `search.list` call.
- `published_after_days` — recency window (default 90). Shrink to 30 for fast-moving niches (AI, news), expand to 180 for evergreen topics (tutorials).

## Steps

1. **Fetch the cohort.** Call `search_niche(query=niche, region=region, order="viewCount", limit=limit, published_after_days=published_after_days)`. Expect `{"videos": [...], "count": N, ...}`. On any `error` result, report + stop. Cache-hit is fine (skip-and-reuse within 24 h).

2. **Drop the tail.** Filter the cohort to videos with `views >= max(100_000, median(views_of_cohort))`. This removes videos that snuck onto the list via sparse competition and would distort the pattern analysis. If the filter leaves < 5 videos, lower the threshold to `max(10_000, median)` and note it in the caveats.

3. **Cluster the titles.** For each surviving video, tag the title along these axes:
   - **Length bucket**: ≤30 / 31–45 / 46–60 / 60+ characters.
   - **Number or bracket present**: e.g. "7 ways", "[2026]", "#3".
   - **Hook shape**: question / list / bold claim / how-to / comparison / vlog-narrative.
   - **Power words**: superlatives ("best", "worst", "ultimate"), forbidden ("secret", "banned", "truth"), emotional ("insane", "shocking").
   - **CAPS ratio**: percent of letters that are uppercase.
   Then count each axis. Report the clusters with ≥ 3 members as "title patterns" — ignore the long tail.

4. **Cluster the thumbnails.** For each of the top 10 videos by views, call `get_thumbnail(video_id, size="hqdefault")` and vision-read the image. Tag:
   - **Face in frame?** Prominent / small / none.
   - **Text overlay?** If yes: 1–4 words typical, font weight, color vs background.
   - **Dominant color palette** — name 2–3 colors.
   - **Composition** — centered subject / split-screen / arrow-pointing / object-as-hero.
   - **Expression** (if face): surprise / anger / neutral / smile / exaggerated.
   Report patterns that repeat across ≥ 3 thumbnails.

5. **Identify the dominating channels.** Group the surviving cohort by `channel_id`; any channel appearing ≥ 3 times is a "dominator". List up to 5, each with: channel title, count of videos in the cohort, their total view count across those videos, and one representative video_id.

6. **Catch the hook DNA.** For each of the top 5 videos only, call `get_transcript(video_id)` and read segments where `t < 30`. Tag the first-30-seconds hook type (question / stat / bold claim / story / curiosity gap / demo). Report which hook type repeats.

7. **Save.** Call `save_report(name="{slug(niche)}-formula", markdown=<body below>)`. Return the path.

## Output format

```
# The Viral Formula for "{niche}"
_Region: {region} · published_after: {published_after}_
_Cohort: {filtered_count} of {raw_count} videos — median views {median} · top video {top_views}_

## The formula in one sentence
{A single claim. "In this niche right now, the winning videos are <length> titles with <hook shape>, thumbs that <visual rule>, hosted on <N> channels."}

## Title formula
- **Pattern A ({count} videos):** {shape} — examples:
  - "{example title 1}"
  - "{example title 2}"
  - "{example title 3}"
- **Pattern B ({count} videos):** ...

## Thumbnail formula
- **Rule 1:** {e.g. "centered face, surprise expression, 2-word yellow text overlay"} — examples: {video_ids}
- **Rule 2:** ...

## Hook formula (top-5 only)
- **Dominant hook type:** {question / stat / bold claim / etc} — {count}/5 videos
- Example hook lines:
  - [0:00 video_id] "{verbatim opening line}"
  - [0:00 video_id] "..."

## Dominators — who's winning this niche
1. **{channel title}** — {n} videos in cohort · {total_views} total · e.g. {video_id}
2. ...

## Caveats
- _Cohort filtering decisions that could bias the pattern_
- _Small-sample notes (e.g. fewer than 15 surviving videos)_
- _Quota notes (was this a cache hit? refresh=True needed?)_
```

## Quality bar — before saving

- Every pattern claim backs with ≥ 3 video_ids from the cohort.
- The "formula in one sentence" must be specific enough that a creator could start a video tonight — "face + yellow text + question-title" is useful; "engaging thumbnails" is not.
- Flag when the cohort is too small (< 10 after filtering) — the user needs to know the signal is thin.
- Never include advice that doesn't come directly from the cohort data.

## Example invocation
```
/find-viral-formula notion productivity
/find-viral-formula "ai coding agents" region=US published_after_days=30
```
