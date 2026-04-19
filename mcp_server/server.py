"""FastMCP entrypoint for the YouTube Analyzer server.

Each tool module exposes a register(mcp) function; this file is the only
place that knows about the concrete FastMCP instance. Launch via:

    python -m mcp_server.server         # stdio transport (production)
    mcp dev mcp_server/server.py        # inspector UI (development)
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_server.tools import (
    analytics,
    my_analytics,
    studio_csv,
    thumbnails,
    transcripts,
    youtube_api,
)

mcp = FastMCP("youtube-analyzer")

studio_csv.register(mcp)
analytics.register(mcp)
transcripts.register(mcp)
youtube_api.register(mcp)
my_analytics.register(mcp)
thumbnails.register(mcp)


if __name__ == "__main__":
    mcp.run()
