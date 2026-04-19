# YouTube Analyzer

A Python MCP server + Claude Code skills that analyze YouTube data to drive content strategy. Flagship workflow: point it at a competitor channel → get back a reproducible SOP — title templates, thumbnail rules, and a timed script skeleton — so you can ship videos in that channel's proven format.

## What you get

| Skill | What it does |
|---|---|
| `/summarize-video <url>` | Structured digest of any YouTube video — TL;DR, hook quote, main claims with `[mm:ss]` timestamps, best lines, CTA. |
| `/analyze-my-channel <csv>` | Audit your YouTube Studio export — rank by views/CTR/AVD, intersect to find true winners, surface the pattern they share, recommend 5 next videos. |
| `/find-viral-formula <niche>` | Research what's going viral across many channels in a niche — title and thumbnail formulas backed by cohort data plus the channels dominating the space. |
| `/clone-competitor @channel` | **Flagship.** Reverse-engineer a channel into a reproducible playbook — fill-in-the-blank title templates, must-have/must-avoid thumbnail rules with citations, a 7-beat timed script skeleton, and three "do this next week" ideas. |

Reports land in `data/reports/`. All tool responses cache to `data/cache/` so re-runs burn zero API quota.

## Install

### 1. Prereqs

- **Python 3.11+** (3.12 and 3.13 also tested).
- **Claude Code** (CLI, desktop, or web) with MCP support enabled.
- A **Google Cloud project** with the **YouTube Data API v3** enabled. Quota defaults to 10 000 units/day — enough for ~100 `search_niche` calls or ~2 000 `get_channel_videos` calls before you refresh the cache.
- (Optional, own-channel analytics only) **OAuth 2.0 client credentials** — type "Desktop app" — to authorize the `get_my_analytics` tool against YouTube Analytics v2.

### 2. Clone and install the package

```bash
git clone https://github.com/TalhaHamdees/youtube-analyzer.git
cd youtube-analyzer
pip install -e ".[dev]"     # or: uv pip install -e ".[dev]"
```

### 3. Configure secrets

```bash
cp config/.env.example config/.env
# edit config/.env and fill in at minimum:
#   YOUTUBE_API_KEY=<your API key>
# OAuth is optional; only needed for get_my_analytics:
#   OAUTH_CLIENT_ID=<your OAuth client id>
#   OAUTH_CLIENT_SECRET=<your OAuth client secret>
```

`config/.env` is gitignored — it will never be committed.

### 4. Register the MCP server with Claude Code

**Option A — one-liner with `claude mcp add`:**

```bash
claude mcp add youtube-analyzer -- python -m mcp_server.server
```

Run from the repo root so the server inherits the right `cwd`. Verify registration:

```bash
claude mcp list
# expected: youtube-analyzer  ✓
```

**Option B — paste the snippet** from `config/mcp.json` into your Claude config under `mcpServers`. Expand the `${YOUTUBE_ANALYZER_DIR}` template to the absolute path of your clone before saving.

### 5. Install the skills

Skills are the Claude Code markdown files in `skills/` that drive multi-tool workflows. Install all four to your Claude skills directory:

```bash
# user-scoped (available in every project):
cp -r skills/* ~/.claude/skills/
# or project-scoped (only here):
mkdir -p .claude/skills && cp -r skills/* .claude/skills/
```

Verify they load:

```bash
claude skills list | grep -E 'summarize-video|analyze-my-channel|find-viral-formula|clone-competitor'
```

## First SOP in 5 minutes

Open a Claude Code session in this repo, then:

```
/clone-competitor @mkbhd
```

Claude will:

1. Resolve the handle to a channel ID (cached forever afterwards).
2. Pull the top 20 uploads with view stats.
3. Download all 20 thumbnails and vision-read them.
4. Fetch transcripts for the top 10.
5. Cluster titles, thumbnails, and script beats into reproducible rules.
6. Write `data/reports/mkbhd-SOP.md`.

Open the report. You should see concrete fill-in-the-blank title templates with 3 example fills each, a must-have/must-avoid thumbnail ruleset where every rule cites ≥3 specific video_ids, a 7-beat timed script skeleton with verbatim examples, and three proposed video ideas.

If the output feels generic, that's a bug — every claim is supposed to cite specific video_ids. Re-run with `top_n=25` or pick a different channel to validate.

## Other quick wins

- **Audit your own channel**: export your Studio CSV (YouTube Studio → Analytics → Advanced mode → Export), drop it in `data/csv_exports/`, and run `/analyze-my-channel <path>`.
- **Research a niche**: `/find-viral-formula "notion productivity"` — pulls 25 cohort videos, filters to the high-view survivors, and names the formula.
- **Summarize a video**: `/summarize-video https://www.youtube.com/watch?v=<id>` — fastest value out of the four skills; no API key needed (uses `youtube-transcript-api` only).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `missing_api_key` | `config/.env` missing or the server process can't see it. Check the MCP server's `cwd` is the repo root. |
| `quota_exceeded` | You hit the 10 000 units/day cap. The cache covers most re-runs for free (7 days for video/channel data, 24 hours for search). Retry tomorrow or enable a second project's key. |
| `no_transcript` / `transcripts_disabled` | Video doesn't have captions. `summarize-video` falls back to the description; `clone-competitor` notes the skip in Caveats. |
| `oauth_not_configured` | `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` not set. Only `get_my_analytics` needs OAuth; every other tool works with just an API key. |
| Browser didn't open for OAuth consent | First run of `get_my_analytics` needs a local display. Run once interactively; the cached token is silent thereafter. |
| `thumbnail_unavailable` | The video has no thumbnail at *any* YouTube-served size — rare. The skill skips it and keeps going. |

## Development

```bash
python -m pytest          # 105 tests, all mocked, no network
python -m ruff check mcp_server tests
python -m mcp_server.server       # run the MCP server on stdio
mcp dev mcp_server/server.py       # or run it with the MCP inspector
```

## Repo layout

```
mcp_server/                 # FastMCP server
├── server.py              # entrypoint, registers all tools
├── paths.py               # shared filesystem roots
├── cache.py               # shared disk-cache helpers
├── errors.py              # shared HttpError translation
├── auth/
│   └── oauth.py           # Google OAuth 2.0 installed-app flow
└── tools/
    ├── studio_csv.py      # parse Studio CSV exports
    ├── analytics.py       # rank_videos over loaded CSVs
    ├── transcripts.py     # get_transcript via youtube-transcript-api
    ├── youtube_api.py     # Data API v3: channels, videos, search
    ├── my_analytics.py    # Analytics v2: get_my_analytics (OAuth)
    ├── thumbnails.py      # download + cache thumbnails
    └── reports.py         # save_report → data/reports/
skills/                    # Claude Code skills
├── summarize-video/
├── analyze-my-channel/
├── find-viral-formula/
└── clone-competitor/
data/                      # all runtime data (gitignored)
├── csv_exports/          # drop Studio CSVs here
├── cache/                # API / transcript / thumbnail / OAuth caches
└── reports/              # generated SOPs + audits
config/
├── .env.example          # template — copy to .env and fill
└── mcp.json              # MCP server registration snippet
tests/                    # pytest, 105 tests, all mocked
```

## Credits

Built by [Talha Hamdees](https://github.com/TalhaHamdees). Design and build log in `SESSIONS.md`; per-step plan in `IMPLEMENTATION_PLAN.md`; working agreement in `CLAUDE.md`.
