# YouTube Analyzer

A Python MCP server + Claude Code skills that analyze YouTube data to drive content strategy. Flagship workflow: point it at a competitor channel and get back a reproducible SOP — title templates, thumbnail rules, and a script skeleton — so you can ship videos in that channel's proven format.

**Status:** in build. See `CLAUDE.md` for the step-by-step build plan and current progress. Full design in `IMPLEMENTATION_PLAN.md`.

## Planned capabilities
- **`clone-competitor`** — reverse-engineer a channel's winning formula into a concrete playbook.
- **`analyze-my-channel`** — audit your Studio CSV exports; surface what's working and recommend next topics.
- **`find-viral-formula`** — research a niche across many channels; report the dominant title / thumbnail pattern.
- **`summarize-video`** — structured digest of any video from its URL.

## Repo layout (once scaffolded)
```
mcp_server/   # FastMCP server + tools (studio_csv, youtube_api, transcripts, thumbnails, analytics)
skills/       # Claude Code skills orchestrating multi-step workflows
data/         # CSV drops, caches, generated reports (gitignored)
config/       # .env.example, mcp.json registration snippet
tests/
```

Detailed usage, install, and first-run walkthrough land in Step 10.
