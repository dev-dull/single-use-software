# Skill: Getting Started with SUS

> This is an example guidance skill. Domain experts can create similar files
> in `claude/skills/` to teach Claude about team-specific conventions,
> data sources, and business logic.

---

## What is a SUS app?

A SUS (Single Use Software) app is a lightweight, disposable tool built for
a specific task. Apps are created through a conversational Claude Code
session — no coding experience required.

## Platform conventions

- **One app, one directory.** Each app lives at `apps/{team}/{app-slug}/`.
- **Default stack is Python + HTMX.** FastAPI serves the backend; HTMX
  handles interactivity without a JavaScript build step.
- **`sus.json` is required.** Every app directory must include metadata
  describing the app, its owner, team, and visibility.
- **Git is invisible.** Users never run git commands. Claude handles
  branching, committing, and publishing automatically.

## Creating a new app

When a user asks to build something, Claude should:

1. Scaffold the directory under `apps/{team}/{app-slug}/`.
2. Create `sus.json` with the correct metadata.
3. Generate a working `main.py` and `requirements.txt`.
4. Start the runner agent so the user sees a live preview immediately.
5. Iterate based on user feedback until they are satisfied.
6. On publish, invoke the auditor agent and open a PR.

## Tips for skill authors

- Keep skills focused on one domain (e.g., finance, marketing, support).
- Include concrete examples: table names, column definitions, KPI formulas.
- Use plain language — skills are read by Claude, not compiled.
- Submit new skills via a PR to `claude/skills/` in the monorepo.
