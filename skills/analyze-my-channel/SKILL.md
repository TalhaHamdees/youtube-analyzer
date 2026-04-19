---
name: analyze-my-channel
description: Audit your YouTube channel from a Studio CSV export — rank videos by views/CTR/AVD, surface what the top performers share, and recommend 5 next topics that fit the winning pattern. Use when the user asks "what's working on my channel" or points you at a Studio CSV.
---

# analyze-my-channel

## When to use
- User says "audit my channel", "which of my videos are doing best", "what should I make next", or similar.
- User has a YouTube Studio CSV export in `data/csv_exports/` (or provides an absolute path).
- Do NOT use this for someone else's channel — that's `clone-competitor`. This one reads the user's own data.

## Required tools (from `youtube-analyzer` MCP server)
- `load_studio_csv(path)` — parse the Studio export.
- `rank_videos(metric, top_n, source=None)` — sort the loaded frame.
- `get_video_details(video_id)` *(optional)* — hydrate winners with API stats if the user has a `YOUTUBE_API_KEY` configured and the CSV's `video_id` column was populated.
- `get_thumbnail(video_id, size="hqdefault")` *(optional)* — pull thumbs for visual pattern work on winners.
- `get_transcript(video_id, lang="en")` *(optional)* — open the top-3 scripts to identify hooks that worked.
- `save_report(name, markdown)` — persist the final audit.

## Inputs
- `csv_path` — path to a Studio CSV. If the user doesn't give one, look in `data/csv_exports/` and pick the most recent `.csv`.

## Steps

1. **Load the export.** Call `load_studio_csv(csv_path)`. If it returns `{"error": ...}`, report which error and stop (common: `file_not_found`, `parse_failed`, `empty_report` on save later, `write_failed` on save). On success, note the `rows` count and `columns` list — if a column you want isn't there, either the CSV is from a different Studio view or the locale is non-English; adapt.

2. **Rank three ways.** Pass `source=csv_path` explicitly so the ranker pulls from the exact CSV you just loaded rather than the "most recent" pointer (matters if the user has loaded multiple files in one session):
   - `rank_videos("views", top_n=10, source=csv_path)` → save as "top by views"
   - `rank_videos("ctr", top_n=10, source=csv_path)` → save as "top by CTR"
   - `rank_videos("avd_seconds", top_n=10, source=csv_path)` → save as "top by retention"

3. **Find the true winners.** Compute the set of videos appearing in ≥ 2 of the three lists. These are the channel's real hits — strong on discovery AND retention, not just one metric. Typical result: 2–5 videos.

4. **Describe each winner concretely.** For each winner, state: title, view count, CTR (%), AVD (mm:ss), publish date. Do not editorialize here — just the numbers.

5. **Open the winners** (skip if `YOUTUBE_API_KEY` is not configured — then work from CSV alone):
   - For each winner: `get_video_details(video_id)` for description + tags.
   - For each winner: `get_thumbnail(video_id, size="hqdefault")` — then read the thumbnail (you have vision). Note: face presence, text overlay, dominant color, composition (centered subject? rule-of-thirds? split-screen?).
   - For the top 3 winners only: `get_transcript(video_id)` — read the first 45 seconds (segments where `t < 45`). Note the hook type (question / bold claim / story / stat / curiosity gap).

6. **Name the patterns** across winners. Three buckets:
   - **Title pattern** — length bucket, numbers/brackets, power words, question vs statement.
   - **Thumbnail pattern** — the visual rules that repeat.
   - **Topic pattern** — the common subject, format (tutorial? review? list? essay?), or audience problem.
   Each pattern claim must be backed by ≥ 2 winner video_ids.

7. **Recommend 5 next videos.** Each recommendation includes:
   - A proposed **title** in the winning title shape (fill-in-the-blank template from step 6).
   - **Why it fits** — which pattern(s) it matches, citing the winners' video_ids.
   - **Estimated effort** — small / medium / large based on whether the video can be made from existing footage, needs new scripting, or needs new filming.

8. **Surface underperformers to revisit.** From the bottom quartile by views *that also have solid CTR (≥ the median CTR across the **full loaded CSV**, not just the top 10)*, list up to 5. These are "good hook, weak topic/retention" — candidates for a re-cut or a title/thumbnail refresh.

9. **Save.** Call `save_report(name="my-channel-audit", markdown="<full report below>")`. Return the path to the user.

## Output format (the report body)

```
# My Channel Audit
_Source: {csv filename} · {row count} videos · generated {date}_

## Top 10 tables

### By views
| # | Title | video_id | Views | CTR | AVD |
| - | ----- | -------- | ----- | --- | --- |
...

### By CTR
...

### By retention (AVD)
...

## True winners (appear in ≥2 lists)
- **{title}** ({video_id}) — {views} views · {ctr}% · {avd}
...

## Winning patterns
- **Titles:** {concrete rule} — e.g. {example-title-1}, {example-title-2}
- **Thumbnails:** {concrete rule} — example video_ids {ids...}
- **Topics:** {concrete rule} — example video_ids {ids...}

## 5 next-video recommendations
1. **"{proposed title}"** — fits title-pattern + thumbnail-pattern. Effort: {small/medium/large}. Based on: {ids}.
2. ...

## Underperformers to revisit
- **{title}** ({video_id}) — CTR is fine ({ctr}%) but AVD is {avd}. Try: {one concrete intervention}.
- ...

## Notes & caveats
- _Anything surprising in the data: outliers, missing columns, low sample size, etc._
```

## Quality bar — before saving

- Every "winning pattern" claim has ≥ 2 winner video_ids cited next to it. No generic advice ("be engaging").
- Every recommendation is concrete enough to assign to a video idea list — title string, effort tag, and the pattern(s) it's betting on.
- If the channel has fewer than 10 videos, shrink the top_n and say so in the "Notes & caveats" section.
- If `YOUTUBE_API_KEY` isn't configured, work from CSV alone and state this in the caveats — don't invent API-derived details.

## Example invocation
```
/analyze-my-channel data/csv_exports/my-studio-export.csv
```
