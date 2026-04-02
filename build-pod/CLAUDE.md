# SUS Build Pod — Claude Code Instructions

You are running inside a SUS (Single Use Software) build pod. Follow these rules strictly.

## Default Stack

- **Python + HTMX** unless the user explicitly requests otherwise.
- Use FastAPI for the backend, Jinja2 templates with HTMX for the frontend.
- Keep dependencies minimal. Add them to `requirements.txt`.

## Git Workflow

You manage all git operations. The user never touches git directly.

| Event | Git action |
|---|---|
| New app session | `git checkout -b {user_id}/{app-slug}/{date}` |
| Resume session | `git checkout {existing_branch}` |
| Every 5 minutes of active editing | Auto-commit: `chore: autosave` |
| User clicks **Save** | Named commit with a summary of changes |
| User clicks **Publish** | Open a PR, run auditor, auto-merge to main |
| Merge conflict on publish | Resolve automatically; notify user in plain English if unresolvable |

## Sub-Agents

Sub-agent skill definitions are located in `/repo/claude/skills/`. Load them at
session start.

1. **Runner agent** (`/repo/claude/skills/runner.md`) — executes the app, tails
   logs, reports errors in plain English. **Starts automatically** when the
   build session begins — do not wait for the user to ask.
2. **Auditor agent** (`/repo/claude/skills/auditor.md`) — invoked automatically
   before every publish. Checks code quality, security (hardcoded secrets, SQL
   injection, SSRF, etc.), and actions affecting systems outside the monorepo.
   Blocks publish if issues are found and explains them to the user.
3. **Safety rules** (`/repo/claude/skills/safety.md`) — non-negotiable safety
   constraints that apply at all times. Always active.

## Safety Rules

- Never modify files outside `apps/{team}/` unless explicitly constructing shared skills.
- Never make outbound network calls except to pre-approved MCP server endpoints.
- Never write credentials or secrets to files — use environment variables injected at runtime.
- No access to production environments under any circumstance.

## Working Directory

All work happens under `/repo`. The monorepo is cloned here at session start.
