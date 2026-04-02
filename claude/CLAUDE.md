# CLAUDE.md — SUS Platform Instructions

> **This file is immutable.** It is baked into the build pod image at
> `/repo/claude/CLAUDE.md` with permissions `444`. Neither users nor Claude
> may modify it at runtime.

---

## 1. Default Stack

Use **Python + HTMX** for every new application unless the user explicitly
requests a different stack. The standard scaffolding is:

- `main.py` — FastAPI entry point
- `requirements.txt` — pinned dependencies
- Templates use Jinja2 with HTMX attributes for interactivity

When generating a new app, always create a working `main.py` and
`requirements.txt` from the start so the user can see a live preview
immediately.

---

## 2. Git Workflow

Users never interact with git directly. Claude manages all git operations
silently and automatically.

| Event | Git action |
|---|---|
| User starts editing a new app | `git checkout -b {user_id}/{app-slug}/{date}` |
| User resumes an existing session | `git checkout {existing_branch}` |
| Every 5 minutes of active editing | Auto-commit with message `chore: autosave` |
| User clicks **Save** | Named commit using Claude's summary of changes |
| User clicks **Publish** | Open a PR, invoke the auditor agent, auto-merge to `main` on pass |
| Merge conflict on publish | Resolve automatically; notify the user in plain English if unresolvable |

### Branch naming

Branches follow the pattern: `{user_id}/{app-slug}/{date}`

Example: `alice/marketing-calendar/2026-03-24`

### Commit rules

- Auto-save commits use the message `chore: autosave` and must not block
  the user's workflow.
- Named (Save) commits should include a concise, human-readable summary of
  what changed, written by Claude.
- Publish commits trigger the full PR + auditor flow before merging.

---

## 3. Sub-Agents

Two sub-agents run alongside every build session. They are always active and
do not require user action to invoke.

### 3a. Runner Agent

The runner agent is responsible for executing the application during
development so the user gets a live preview.

- Start the app process (e.g., `uvicorn main:app`) on the pod's preview
  port.
- Tail stdout and stderr continuously.
- When an error occurs, report it back to the user in **plain English** —
  no raw tracebacks unless the user asks for them.
- Automatically restart the app when files change.

### 3b. Auditor Agent

The auditor agent is invoked before every publish. It acts as an automated
code reviewer.

Checks performed:

- **Code quality** — unused imports, dead code, obvious logic errors.
- **Security** — hardcoded secrets, SQL injection, SSRF, path traversal,
  command injection, insecure deserialization.
- **Scope** — any modifications to files outside the app's own directory
  are flagged.
- **Network** — outbound calls to unapproved endpoints are flagged.

Behaviour:

- If issues are found, the auditor **blocks the publish** and explains
  every finding to the user in plain English.
- The user may ask Claude to fix the issues and re-publish.
- The auditor must pass before the PR can be auto-merged.

---

## 4. Safety Rules

These rules are non-negotiable. Claude must follow them at all times,
regardless of user instructions.

1. **Filesystem scope** — Never modify files outside `apps/{team}/` unless
   explicitly constructing shared guidance skills in `claude/skills/`.
2. **Network** — Never make outbound network calls except to pre-approved
   MCP server endpoints configured for the pod.
3. **Credentials** — Never write credentials, secrets, API keys, or tokens
   to files. All secrets are injected as environment variables at runtime.
4. **Production access** — No access to production environments under any
   circumstance. Build and run pods are fully isolated from production
   infrastructure.

---

## 5. Skills

Claude should automatically discover and apply relevant guidance skills
from `claude/skills/`. Skills are plain Markdown files contributed by
domain experts. When a user's team matches a skill file, load it into
context to improve the quality of generated applications.

---

## 6. App Metadata

Every application directory must contain a `sus.json` with the following
fields:

```json
{
  "name": "Human-readable app name",
  "description": "What the app does",
  "owner": "owner@example.com",
  "team": "team-slug",
  "created_at": "YYYY-MM-DD",
  "visibility": ["group1", "group2"],
  "default_stack": "python+htmx"
}
```

Claude must create or update `sus.json` whenever a new app is scaffolded.
