# YouTube Analyzer — Session Continuity

**This file is auto-loaded at the start of every Claude Code session.** Read it first, then read `SESSIONS.md` for the detailed log. Resume from the **Current Status** section.

## Project Goal
Python MCP server + Claude Code skills that analyze YouTube data to drive content strategy. Flagship feature: feed it a competitor channel → get back a reproducible SOP (titles, thumbnails, script structure). Full plan: `C:\Users\Pc\.claude\plans\delegated-launching-lamport.md`.

## Repo
- Local: `D:\Youtube Automation tools\Youtube Analyzer`
- GitHub: `TalhaHamdees/youtube-analyzer` (created in Step 0)
- Branch: `main` — commit + push after **every** completed step.

## Working Agreement
1. At session start: read this file + `SESSIONS.md`, then continue from Current Status.
2. **Autonomous mode** (granted 2026-04-19): work Steps 1→10 straight through without pausing for per-step approval. Still research best practices before design decisions, still run verification + a code-review subagent over the diff before finalizing.
3. After each step: run tests/verification → spawn a code-review subagent on the diff → commit with message `Step N: <title>` → `git push` → update the **Current Status** block below + append to `SESSIONS.md`. Never batch-commit multiple steps.
4. Hard-stop only on real blockers: missing user-provided credentials, a test that requires a real artifact the user hasn't supplied, or failing verification. Mark the step `BLOCKED` in Current Status, explain what's needed, continue with later steps if independent.
5. Never use `--no-verify`, `--force`, or amend pushed commits. Commits carry no `Co-Authored-By` trailer — all attribution to the user.

## Implementation Steps

| # | Title | Deliverables | Verification |
|---|---|---|---|
| 0 | **Repo bootstrap** | `.gitignore`, `README.md`, `pyproject.toml`, empty folder tree, GitHub repo created, first push | `git log` shows initial commit on `main`; repo visible on github.com |
| 1 | **MCP server skeleton + CSV tools** | `mcp_server/server.py` (FastMCP), `tools/studio_csv.py`, `tools/analytics.py`, `load_studio_csv` + `rank_videos` tools | `mcp dev mcp_server/server.py` loads; tools callable via MCP inspector on a sample CSV |
| 2 | **Transcript tool** | `tools/transcripts.py`, `get_transcript` MCP tool, cache to `data/cache/transcripts/` | `get_transcript("dQw4w9WgXcQ")` returns non-empty text; re-run hits cache |
| 3 | **YouTube Data API (API-key path)** | `tools/youtube_api.py`, `get_channel_videos`, `get_video_details`, `search_niche`; `.env` with `YOUTUBE_API_KEY` | Fetches public data for a known channel; cached responses reused |
| 4 | **OAuth path (optional for own-channel)** | `auth/oauth.py`, token caching in `data/cache/oauth/` | First call opens browser, token cached, second call silent |
| 5 | **Thumbnails + vision prep** | `tools/thumbnails.py`, `get_thumbnail` MCP tool, download to `data/cache/thumbnails/` | Returned local path is readable by Claude as an image |
| 6 | **Skill: `summarize-video`** | `skills/summarize-video/SKILL.md` | Running the skill on a real URL produces structured summary |
| 7 | **Skill: `analyze-my-channel`** | `skills/analyze-my-channel/SKILL.md` | Skill ranks real Studio CSV and recommends topics |
| 8 | **Skill: `find-viral-formula`** | `skills/find-viral-formula/SKILL.md` | Skill pulls niche top videos and reports dominant formula |
| 9 | **Skill: `clone-competitor` (flagship)** | `skills/clone-competitor/SKILL.md`, uses all prior tools | Generates `{channel}-SOP.md` with title patterns, thumbnail rules, script skeleton — concrete, not generic |
| 10 | **MCP registration + docs** | `config/mcp.json` snippet, README usage section | `claude mcp list` shows the server; README walks a new user from clone to first SOP |

## Current Status
- **Active step:** Step 10 — MCP registration + README
- **State:** NOT STARTED (Step 9 DONE — commit `44b1044`, all four skills shipped with review fixes applied).
- **Next action:** Write `config/mcp.json` snippet users can paste into Claude settings, and expand `README.md` into a real install + first-SOP walkthrough (clone → `.env` → `claude mcp add` → `/clone-competitor @channel` → inspect report).
- **Blockers:** Step 3/4 live smokes still pending user `YOUTUBE_API_KEY` / OAuth credentials — not blocking the README since the README documents *how* to configure them, and the mocked test suite (105 tests) demonstrates the system works end-to-end without them.

## Commit Convention
```
Step N: <short title>

<1-3 bullets of what changed and why>
```
**No** `Co-Authored-By: Claude ...` trailer — commits are attributed solely to the user.
