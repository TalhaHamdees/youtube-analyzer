# YouTube Analyzer — Detailed Implementation Plan

Companion to `CLAUDE.md` and `C:\Users\Pc\.claude\plans\delegated-launching-lamport.md`.
This file breaks each step from the step table into concrete file lists, code sketches, dependencies, and acceptance checks. Work one step per session; commit + push after each.

---

## Guiding Principles

- **Cache-first.** Every external call writes through `data/cache/` keyed by a stable ID (video_id, channel_id, query hash). Re-runs must be free.
- **Fail loud, fail early.** Tools return structured errors (`{"error": "...", "code": "..."}`), never silent `None`.
- **Thin tools, rich skills.** MCP tools do one job. Orchestration and judgment live in skill markdown.
- **No secrets in git.** `.env` is gitignored, `.env.example` is committed.
- **Windows path safety.** Use `pathlib.Path`; never hardcode `/` or `\`.

---

## Step 0 — Repo Bootstrap

### Deliverables
- `.gitignore` (Python + venv + `.env` + `data/cache/` + `data/reports/*.md` except `.gitkeep`)
- `README.md` (one-paragraph purpose + "status: in build" note; full usage added in Step 10)
- `pyproject.toml` (project metadata, deps pinned by minor version)
- `.env.example` in `config/`
- Folder tree (empty + `.gitkeep` files):
  ```
  mcp_server/tools/
  mcp_server/auth/
  skills/
  data/csv_exports/
  data/cache/transcripts/
  data/cache/thumbnails/
  data/cache/api/
  data/cache/oauth/
  data/reports/
  config/
  tests/
  ```
- GitHub repo `TalhaHamdees/youtube-analyzer` created via `gh repo create --public --source=. --remote=origin`
- First commit on `main`, pushed.

### `pyproject.toml` dependency seed
```toml
[project]
name = "youtube-analyzer"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.2",
    "pandas>=2.2",
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "youtube-transcript-api>=0.6",
    "google-api-python-client>=2.140",
    "google-auth-oauthlib>=1.2",
    "google-auth-httplib2>=0.2",
    "pillow>=10.4",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "ruff>=0.6"]
```

### Verification
- `git log --oneline` shows one commit.
- `gh repo view` returns the repo URL.
- `python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"` parses without error.

### Commit
`Step 0: Repo bootstrap`

---

## Step 1 — MCP Server Skeleton + CSV Tools

### Deliverables

**`mcp_server/server.py`** — FastMCP entrypoint.
```python
from mcp.server.fastmcp import FastMCP
from mcp_server.tools import studio_csv, analytics

mcp = FastMCP("youtube-analyzer")

mcp.tool()(studio_csv.load_studio_csv)
mcp.tool()(analytics.rank_videos)

if __name__ == "__main__":
    mcp.run()
```

**`mcp_server/tools/studio_csv.py`**
- `load_studio_csv(path: str) -> dict` — reads the CSV with pandas, normalizes column names (Studio exports use `Video title`, `Views`, `Impressions click-through rate (%)`, `Average view duration`, etc.), coerces types, returns `{"rows": [...], "source": path, "loaded_at": iso}`.
- Stash the DataFrame in a module-level `_LOADED: dict[str, pd.DataFrame]` keyed by source path so `rank_videos` can reuse it without re-parsing.
- Handle the BOM + `%` signs + `hh:mm:ss` AVD → seconds conversion.

**`mcp_server/tools/analytics.py`**
- `rank_videos(metric: str, top_n: int = 10, source: str | None = None) -> list[dict]` — pulls the last loaded frame (or the one matching `source`), sorts by `metric` (whitelist: `views`, `ctr`, `avd_seconds`, `impressions`, `watch_time_hours`), returns rows trimmed to useful fields.
- Raise `ValueError` with the allowed metric list on bad input — MCP surfaces this cleanly.

### Verification
- `mcp dev mcp_server/server.py` opens the MCP inspector.
- Drop a real Studio CSV into `data/csv_exports/`, call `load_studio_csv` then `rank_videos(metric="ctr", top_n=5)`, confirm results match what Studio UI shows for the same sort.
- Add `tests/test_studio_csv.py` with a hand-crafted 5-row CSV fixture covering the column-name quirks.

### Commit
`Step 1: MCP server skeleton + Studio CSV tools`

---

## Step 2 — Transcript Tool

### Deliverables

**`mcp_server/tools/transcripts.py`**
- `get_transcript(video_id: str, lang: str = "en") -> dict` — wraps `youtube_transcript_api.YouTubeTranscriptApi.get_transcript`.
- Returns `{"video_id": ..., "lang": ..., "segments": [{"t": 0.0, "text": "..."}, ...], "text": "<joined>"}`.
- Cache path: `data/cache/transcripts/{video_id}.{lang}.json`. On cache hit, skip the network.
- Fallback: if the requested lang is unavailable, try `list_transcripts` and pick the first generated/translated track; include `"used_lang"` in the response so the caller knows.
- Graceful error: return `{"error": "no_transcript", "video_id": ...}` for `TranscriptsDisabled` / `NoTranscriptFound` — do not raise.

Register in `server.py`: `mcp.tool()(transcripts.get_transcript)`.

### Verification
- `get_transcript("dQw4w9WgXcQ")` returns non-empty `text`.
- Delete and recreate the cache file once; second call is silent (network off).
- `get_transcript("___nonexistent___")` returns the structured error, not a stack trace.

### Commit
`Step 2: Transcript tool with disk cache`

---

## Step 3 — YouTube Data API (API-Key Path)

### Deliverables

**`config/.env.example`**
```
YOUTUBE_API_KEY=
OAUTH_CLIENT_ID=
OAUTH_CLIENT_SECRET=
```

**`mcp_server/tools/youtube_api.py`**
- Lazy-build `youtubeClient()` using `googleapiclient.discovery.build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"])`. Load `.env` at import time via `python-dotenv`.
- `get_channel_videos(channel_handle: str, limit: int = 20) -> list[dict]`
  - Resolve handle → channel_id via `channels().list(forHandle=...)` (new field) with a fallback to `search().list(q=handle, type="channel")`.
  - Get the channel's `uploads` playlist ID from `contentDetails.relatedPlaylists.uploads`.
  - Page `playlistItems().list` until `limit` items collected.
  - Batch-fetch stats via `videos().list(id=",".join(ids), part="snippet,statistics,contentDetails")`.
- `get_video_details(video_id: str) -> dict` — single-video version of the above (reuses the cache if populated by `get_channel_videos`).
- `search_niche(query: str, region: str = "US", order: str = "viewCount", limit: int = 25) -> list[dict]` — `search().list(q=query, type="video", order=order, regionCode=region, publishedAfter=iso_90d_ago)` then hydrate with `videos().list`.
- **Caching.** Every call writes JSON to `data/cache/api/` keyed by the call signature (e.g. `channel_videos__{channel_id}__{limit}.json`). Default TTL: channel/video details = 7 days, search = 24 hours. A `refresh: bool = False` arg bypasses cache.
- **Quota guard.** Wrap every API call in a helper that raises `QuotaExceededError` on 403 `quotaExceeded` so skills can surface it without retry loops.

### Verification
- `get_channel_videos("@mkbhd", limit=5)` returns 5 rows with non-zero view counts.
- Re-run the same call; the second invocation touches no network (log the cache hit).
- `search_niche("productivity tips", limit=5)` returns 5 hydrated rows.
- Unset the env var → tool returns a clear "missing YOUTUBE_API_KEY" error.

### Commit
`Step 3: YouTube Data API tools with cache + quota guard`

---

## Step 4 — OAuth Path (Optional Own-Channel)

### Deliverables

**`mcp_server/auth/oauth.py`**
- `get_credentials(scopes: list[str]) -> google.oauth2.credentials.Credentials`.
- Token stored at `data/cache/oauth/token.json`. On load: refresh if expired. If missing or invalid, run `InstalledAppFlow.from_client_config(...).run_local_server(port=0)`.
- Client config built in-memory from `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` env vars (do not commit a client_secrets.json).
- Scopes default: `["https://www.googleapis.com/auth/yt-analytics.readonly", "https://www.googleapis.com/auth/youtube.readonly"]`.

**Wire into `youtube_api.py`**
- Add an `auth: Literal["key","oauth"] = "key"` kwarg to the client builder. OAuth path builds via `build("youtube", "v3", credentials=get_credentials(...))`.
- New tool `get_my_analytics(start_date, end_date, metrics)` using `youtubeAnalytics` service (only available via OAuth).

### Verification
- First call triggers a browser consent screen; token written to `data/cache/oauth/token.json`.
- Restart the Python process and call again — no browser, silent auth.
- Delete the token file → browser pops again.
- Guardrail: the OAuth tool errors cleanly (`"oauth_not_configured"`) if `OAUTH_CLIENT_ID` is unset.

### Commit
`Step 4: OAuth flow for own-channel analytics`

---

## Step 5 — Thumbnails + Vision Prep

### Deliverables

**`mcp_server/tools/thumbnails.py`**
- `get_thumbnail(video_id: str, size: str = "maxres") -> dict`
  - Size map: `default` → 120×90, `mqdefault` → 320×180, `hqdefault` → 480×360, `sddefault` → 640×480, `maxresdefault` → 1280×720.
  - URL: `https://img.youtube.com/vi/{video_id}/{size}default.jpg`. Fall back to `hqdefault` if `maxres` 404s (common for older/less-popular videos).
  - Save to `data/cache/thumbnails/{video_id}_{size}.jpg`.
  - Return `{"video_id": ..., "path": "<absolute>", "width": ..., "height": ..., "size": ...}`. Use `PIL.Image.open` to read dimensions after download.

Register in `server.py`.

### Verification
- `get_thumbnail("dQw4w9WgXcQ", "maxres")` returns a path. `Image.open(path).size == (1280, 720)`.
- Ask Claude (in the MCP inspector's chat with vision) to describe the returned path → gets an accurate description.
- Second call skips the download (file exists).

### Commit
`Step 5: Thumbnail downloader with fallback and cache`

---

## Step 6 — Skill: `summarize-video`

### Deliverables

**`skills/summarize-video/SKILL.md`**
```markdown
---
name: summarize-video
description: Summarize any YouTube video from its URL. Returns structured hook/claims/takeaways + key quotes with timestamps. Use when the user shares a YouTube link and wants a digest.
---

## Inputs
- `url` — full YouTube URL or bare video_id.

## Steps
1. Extract video_id from the URL (regex: `(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})`).
2. Call `get_video_details(video_id)` for title/channel/publish date.
3. Call `get_transcript(video_id)`. If it returns `{"error": "no_transcript"}`, abort with a user-friendly message.
4. Produce the summary (below) directly from the transcript segments so you can cite timestamps.

## Output format
- **Title + channel + date** (one line)
- **TL;DR** — 2 sentences
- **Hook (0:00–0:30)** — quote the opening
- **Main claims** — 3–7 bullets, each with `[mm:ss]` timestamp
- **Best quotes** — 2–3 verbatim lines with timestamps
- **CTA / next steps** — what the creator asks of the viewer
```

### Verification
- Run on a real tutorial URL → output has all sections, timestamps are plausible (within ±5s of the quoted line).
- Run on a video with transcripts disabled → graceful "no transcript available" message, no stack trace.

### Commit
`Step 6: summarize-video skill`

---

## Step 7 — Skill: `analyze-my-channel`

### Deliverables

**`skills/analyze-my-channel/SKILL.md`**
```markdown
---
name: analyze-my-channel
description: Audit a YouTube channel from its Studio CSV exports. Ranks videos by CTR/AVD/views, surfaces patterns in the top performers, recommends next topics. Use when the user wants "what's working on my channel".
---

## Inputs
- `csv_path` — file in `data/csv_exports/` (or absolute path).

## Steps
1. `load_studio_csv(csv_path)`.
2. `rank_videos(metric="views", top_n=10)` → save as "top by views".
3. `rank_videos(metric="ctr", top_n=10)` → "top by CTR".
4. `rank_videos(metric="avd_seconds", top_n=10)` → "top by retention".
5. Find the intersection (videos appearing in ≥2 lists) — these are the true winners.
6. For each winner, fetch `get_video_details` + `get_thumbnail` + (optional) `get_transcript` so you can look at titles/thumbs/hooks directly.
7. Name the patterns across winners: title shape, thumbnail style, topic cluster.
8. Recommend 5 next video ideas that match the winning pattern.
9. `save_report("my-channel-audit.md", <markdown>)`.

## Output sections
- Top performers table (title | views | CTR | AVD)
- Winning patterns (titles / thumbs / topics) — concrete, not "be engaging"
- 5 next-video recommendations — each with a proposed title and why it fits the pattern
- Underperformers to deprecate or revisit
```

### Verification
- Run on a real Studio export; the recommended topics clearly map back to patterns you can point at in the data.

### Commit
`Step 7: analyze-my-channel skill`

---

## Step 8 — Skill: `find-viral-formula`

### Deliverables

**`skills/find-viral-formula/SKILL.md`**
```markdown
---
name: find-viral-formula
description: Research the dominant viral formula for a niche keyword across many channels. Use when the user wants "what's working in <niche> right now" — not one channel, the whole topic.
---

## Inputs
- `niche` — keyword or phrase.
- `region` — default `US`.
- `limit` — default 25.

## Steps
1. `search_niche(niche, region=region, order="viewCount", limit=limit)`.
2. Filter to videos published in the last 90 days with ≥100k views (skills should drop the tail that skews averages).
3. For each survivor: `get_video_details` + `get_thumbnail`. Pull transcripts only for the top 5 (quota / cost).
4. Cluster by title pattern (numbers, brackets, hook verbs, length bucket). Report cluster sizes.
5. Cluster by thumbnail pattern (face yes/no, text overlay, color palette, composition).
6. Identify the top-5 channels surfacing repeatedly — they are the reference set.
7. `save_report("{niche-slug}-formula.md", <markdown>)`.

## Output sections
- Cohort summary (N videos, median views, date range)
- Title formula (with 3 example titles per pattern)
- Thumbnail formula (visual rules + 2–3 example URLs)
- Top 5 channels dominating the niche
- One sentence: "the formula is…"
```

### Verification
- Run on `"notion productivity"` or similar → report names real patterns you can verify by clicking the example URLs.

### Commit
`Step 8: find-viral-formula skill`

---

## Step 9 — Skill: `clone-competitor` (flagship)

### Deliverables

**`skills/clone-competitor/SKILL.md`**
```markdown
---
name: clone-competitor
description: Reverse-engineer a successful YouTube channel into a reproducible SOP covering title patterns, thumbnail rules, and script skeleton. Use when the user names a competitor and wants to replicate what's working.
---

## Inputs
- `channel` — handle (e.g. `@mkbhd`) or channel URL.
- `top_n` — default 20.

## Steps
1. `get_channel_videos(channel, limit=top_n)` sorted by views.
2. For each video: `get_video_details` + `get_thumbnail(size="maxres")`.
3. Read each thumbnail (vision) and record: face? text overlay? color palette? composition? emotion?
4. `get_transcript` for the top 10 (quota-friendly). For each: note hook type (question / stat / bold claim / story), promise timing (seconds to "here's what you'll learn"), CTA placement, intro length, transition cadence.
5. Cluster titles: length buckets, number/bracket use, power words, curiosity-gap shape, CAPS ratio.
6. Synthesize three reproducible templates:
   - **Title template(s)** — fill-in-the-blank strings with variables.
   - **Thumbnail ruleset** — must-haves and must-avoids with concrete examples.
   - **Script skeleton** — timed beats (0:00 hook / 0:15 promise / 0:45 setup / …).
7. `save_report("{channel_slug}-SOP.md", <markdown>)`.

## Output format
- Top 20 table (title | views | CTR-proxy | publish date)
- Title patterns (3–5 named templates with example fills)
- Thumbnail ruleset (5–10 rules, each with the example video_ids that prove it)
- Script skeleton (timed, concrete — "0:00 hook is a question or bold claim", not "start strong")
- "Do this next week" — 3 concrete video ideas in this competitor's format

## Guardrails
- If any step returns `{"error": ...}`, degrade gracefully: SOP notes which section is thin and why.
- Cite at least 3 specific video_ids per pattern — "because I say so" is not allowed.
```

### Verification
- Run on a channel you know well; verify every pattern in the SOP by clicking back to cited video_ids.
- The SOP must contain concrete fill-in-the-blank templates, not generic advice like "use strong titles".

### Commit
`Step 9: clone-competitor flagship skill`

---

## Step 10 — MCP Registration + Docs

### Deliverables

**`config/mcp.json`** — snippet a user can paste into their Claude settings.
```json
{
  "mcpServers": {
    "youtube-analyzer": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "D:/Youtube Automation tools/Youtube Analyzer",
      "env": {
        "YOUTUBE_API_KEY": "${YOUTUBE_API_KEY}"
      }
    }
  }
}
```

**`README.md` (expanded)**
- What it does (one paragraph, the "flagship = clone-competitor" pitch).
- Prereqs (Python 3.11+, a Google Cloud project with YouTube Data API v3 enabled, an API key).
- Install: `git clone` → `uv pip install -e .` (or `pip install -e .`) → copy `config/.env.example` to `config/.env`, fill in keys.
- Register the MCP server: `claude mcp add youtube-analyzer -- python -m mcp_server.server` (or point at `config/mcp.json`).
- First run walkthrough: "get your first competitor SOP in 5 minutes" — invoke `/clone-competitor @somechannel` and open `data/reports/somechannel-SOP.md`.
- Troubleshooting section (quota exceeded, no transcript, OAuth browser didn't open).

### Verification
- `claude mcp list` shows `youtube-analyzer` after registration.
- A fresh clone on a different machine (or directory) gets to "first SOP" using only the README — no verbal hand-holding.

### Commit
`Step 10: MCP registration and README walkthrough`

---

## Post-Build Checklist

- [ ] Every tool has a cache path and documented TTL.
- [ ] Every skill cites sources (video_ids / row numbers) in its output.
- [ ] `.env` is gitignored; `.env.example` is present.
- [ ] `README.md` takes a newcomer from clone to first SOP without asking for help.
- [ ] `SESSIONS.md` has one entry per step with commit SHA + verification note.

## Risk Log

| Risk | Mitigation |
|---|---|
| YouTube Data API daily quota (10k units) burns during development | Aggressive cache + `refresh=False` default + a dev flag that raises before calling live API |
| `youtube-transcript-api` breaks when YouTube changes the HTML (known history) | Pin a known-good version; add a weekly CI check that calls `get_transcript("dQw4w9WgXcQ")` |
| Thumbnails 404 on older videos at `maxres` | Size fallback chain (maxres → sd → hq) baked into `get_thumbnail` |
| OAuth client secret leakage | Load from env only; never read a `client_secrets.json` from disk; `.env` is gitignored |
| Vision analysis cost on 20 thumbs per flagship run | Cache Claude-generated thumbnail descriptions keyed by video_id — re-runs are free |
