# Session Log

Append one entry per completed step. Newest at the bottom. Keep entries short — this is a ledger, not documentation.

Entry template:
```
## Step N — <title>
- **Date:** YYYY-MM-DD
- **Commit:** <sha> — `<message>`
- **Changed:** <files>
- **Verified:** <how it was tested>
- **Notes:** <anything surprising worth remembering; skip if none>
```

---

## Step 2 — Transcript tool
- **Date:** 2026-04-19
- **Commit:** `de189b2` — `Step 2: Transcript tool with disk cache + structured errors`
- **Changed:** `mcp_server/paths.py` (new shared filesystem roots), `mcp_server/tools/transcripts.py`, `mcp_server/server.py` (registers the new tool), `tests/test_transcripts.py`.
- **Verified:** 39/39 pytest green (16 new mocked transcript tests); `ruff check` clean; `mcp.list_tools()` returns `load_studio_csv`, `rank_videos`, `get_transcript`; code-review subagent findings applied (taxonomy for format-vs-upstream `invalid_video_id`, mirrored cache under used_lang after fallback, `logging.warning` on cache-write failure, signature-verified library exception instantiation, tests for every error path including `request_blocked`, `ip_blocked`, `video_unplayable`, generic `YouTubeTranscriptApiException`, per-lang cache keys, and the used-lang alias).
- **Notes:** `youtube-transcript-api` 1.x+ deprecated the static `get_transcript` function; using the instance API `YouTubeTranscriptApi().fetch(video_id, languages=...)` → `FetchedTranscript` with `.snippets`/`.language_code`/`.is_generated`. `.fetch()` picks the first-matching language from the provided tuple, not a best fuzzy match — commented to prevent reviewer confusion. No real YouTube calls in CI; if the user wants a live sanity check, `get_transcript("dQw4w9WgXcQ")` in a REPL suffices.

## Step 1 — MCP server skeleton + CSV tools
- **Date:** 2026-04-19
- **Commit:** `9fe0027` — `Step 1: MCP server skeleton + Studio CSV tools`
- **Changed:** `mcp_server/{__init__,server}.py`, `mcp_server/tools/{__init__,studio_csv,analytics}.py`, `tests/{__init__,conftest,test_studio_csv,test_analytics}.py`; removed obsolete `mcp_server/tools/.gitkeep`.
- **Verified:** 23/23 pytest green; `ruff check` clean; `mcp.list_tools()` returns `load_studio_csv` + `rank_videos`; code-review subagent findings applied (scored fuzzy matcher, `pd.isna` null check, JSON-safe preview, Total-only empty-export test, narrowed exception catch).
- **Notes:** Studio exports are UTF-16 LE + tab despite `.csv` extension — confirmed this ship via web research, parser sniffs BOM and delimiter so no per-user config needed. Real-export verification will land when the user drops a file into `data/csv_exports/`. Ruff ignored `ambiguous variable` style warnings because none tripped. Assumed US-style numbers (comma thousands, dot decimal); non-US locales would need a separate parser path — documented in `_coerce_numeric` docstring.

## Step 0 — Repo bootstrap
- **Date:** 2026-04-19
- **Commit:** `d92eb1d` — `Step 0: Repo bootstrap`
- **Changed:** `.gitignore`, `README.md`, `pyproject.toml`, `CLAUDE.md`, `SESSIONS.md`, `IMPLEMENTATION_PLAN.md`, `config/.env.example`, folder tree with `.gitkeep` markers (mcp_server/, skills/, data/cache/{transcripts,thumbnails,api,oauth}/, data/{csv_exports,reports}/, tests/).
- **Verified:** `git log` shows the initial commit on `main`; `gh repo view TalhaHamdees/youtube-analyzer` resolves to https://github.com/TalhaHamdees/youtube-analyzer; `python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"` parses cleanly (9 deps).
- **Notes:** Initial `.gitignore` `**` negation pattern was too broad (matched `.gitkeep` files out). Switched to `data/cache/*/*` + `!data/cache/*/.gitkeep` which works with git's path resolution. Also added `IMPLEMENTATION_PLAN.md` (detailed per-step breakdown) alongside the plan.
