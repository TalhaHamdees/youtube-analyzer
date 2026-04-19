---
description: Verify the active step, commit with the Step N convention, push, update CLAUDE.md + SESSIONS.md.
argument-hint: (no args — reads active step from CLAUDE.md)
---

You are closing out an iteration of the YouTube Analyzer build loop. Implementation should already be done — this command only verifies, commits, and updates the ledger.

## Steps to execute

1. Re-read `CLAUDE.md` **Current Status** to confirm the active step number + title.
2. Run the step's verification commands from `IMPLEMENTATION_PLAN.md`. If **any** check fails, STOP — report the failure, do not commit.
3. `git status` + `git diff --stat` — confirm the changed files match the step's declared deliverables. Flag anything unexpected (stray files, caches, secrets).
4. Stage only the files belonging to this step. Name them explicitly — **never** `git add -A` or `git add .`.
5. Commit using a HEREDOC with this exact shape (NO `Co-Authored-By` trailer — commits credit the user only):
   ```
   git commit -m "$(cat <<'EOF'
   Step N: <short title>

   - <bullet 1>
   - <bullet 2>
   - <bullet 3 if needed>
   EOF
   )"
   ```
6. `git push origin main`.
7. Update `CLAUDE.md` **Current Status**:
   - Mark the just-finished step DONE with its commit sha.
   - Set the next step as active, state its next action in one sentence.
   - Leave "Blockers: none" unless one applies.
8. Append a new entry to `SESSIONS.md` using the template at the top of that file (Date, Commit, Changed, Verified, Notes). Include commit sha. Only add a "Notes" line if something surprising or non-obvious happened.
9. Commit + push that ledger update as a separate commit: `Step N: Update status + log`.
10. Report completion. Suggest the user run `/clear` then `/plan-step` to begin the next iteration.

## Guardrails
- Never use `--no-verify`, `--force`, or `--amend`.
- Never batch two steps into one commit.
- If verification fails, set Current Status state to `BLOCKED` with the reason, append a BLOCKED entry to `SESSIONS.md`, and stop. Do not commit broken code.
- If `git diff` shows `.env`, tokens, or anything under `data/cache/`, **abort** — something is misconfigured in `.gitignore`.
