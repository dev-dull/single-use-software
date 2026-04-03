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

## Auto-Runner (port 3000)

A background runner process in the entrypoint watches `/repo` every 5 seconds
and automatically starts the appropriate server on **port 3000**:

- `requirements.txt` with `fastapi`/`uvicorn` -> `uvicorn main:app` with `--reload`
- `package.json` -> `npm start` (or `node server.js`)
- `index.html` -> `python3 -m http.server 3000`

**You do NOT need to manually start the server.** Just create the application
files (e.g., `main.py`, `requirements.txt`) and the runner will detect them and
start serving automatically. The preview pane in the browser will pick it up.

If the stack changes (e.g., switching from a static site to FastAPI), the runner
kills the old server and starts the correct one. If the server crashes, the
runner restarts it automatically.

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

## Discovering and Loading Team-Specific Skills

At the start of every build session, load relevant guidance skills from
`/repo/claude/skills/`. Skills teach Claude about domain-specific conventions,
table schemas, KPI formulas, and display patterns.

### Loading rules

1. **Always load the baseline skill**: Read `/repo/claude/skills/example.md`
   into context at session start. It contains platform-wide conventions that
   apply to every app.

2. **Match skills to the user's team**: When a user is working on an app in
   `apps/{team}/`, check if `/repo/claude/skills/{team}.md` exists. If it
   does, load it. For example:
   - `apps/finance/budget-tracker/` → load `claude/skills/finance.md`
   - `apps/marketing/campaign-dashboard/` → load `claude/skills/marketing.md`
   - `apps/customer-success/health-scores/` → load `claude/skills/customer-success.md`

3. **Load multiple skills when relevant**: If the app spans multiple domains
   (e.g., a finance app that also uses marketing attribution data), load all
   applicable skills. Use the app description in `sus.json` and the user's
   requests to determine relevance.

4. **Skills are read-only context**: Do not modify skill files during a build
   session. They are reference material, not runtime configuration.

5. **Skill authoring**: If a user wants to create or edit a skill, direct
   them to follow the guide at `/repo/claude/skills/AUTHORING.md` and submit
   a PR to `claude/skills/`.

---

## Working Directory

All work happens under `/repo`. The monorepo is cloned here at session start.
