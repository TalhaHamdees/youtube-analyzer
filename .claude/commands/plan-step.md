---
description: Plan the current active step from CLAUDE.md before implementing.
argument-hint: (no args — reads active step from CLAUDE.md)
---

You are starting a fresh iteration of the YouTube Analyzer build loop. **Do not write any code yet.** Your only job here is to produce a plan and wait for approval.

## Steps to execute

1. Read `CLAUDE.md` → find the active step number + title in the **Current Status** section.
2. Read the matching step's section in `IMPLEMENTATION_PLAN.md` for deliverables, code sketches, and verification checks.
3. Skim the last 1–2 entries in `SESSIONS.md` for continuity.
4. If prior steps produced files you will touch or import, read them first so your plan is grounded in the real code — not just the plan doc, which may be stale.
5. Produce a **concrete implementation plan** for the active step, formatted as:
   - **Step N — &lt;title&gt;** (one sentence on the goal)
   - **Files to create / edit** — ordered list, each with a one-line purpose
   - **Key decisions needing your approval** — naming, library choice, edge-case handling (skip this section if none)
   - **Verification** — the exact commands or MCP inspector calls you will run before committing
   - **Draft commit message** — in the `Step N: <title>` format from `CLAUDE.md`
6. **STOP.** Wait for the user to approve, redirect, or edit the plan. Do not call Write, Edit, or Bash beyond the read-only exploration above.

After the user approves, implement the plan. When implementation + verification pass, the user will run `/finalize-step` to commit, push, and advance `CLAUDE.md`.
