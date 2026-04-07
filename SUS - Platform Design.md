# 🤨 **SUS (Single Use Software) — Platform Design**

Background: Inspired by Intercom's internal tool that gave Claude Code to non-engineers. Reference: [https://ideas.fin.ai/p/we-gave-claude-code-to-everyone-at](https://ideas.fin.ai/p/we-gave-claude-code-to-everyone-at)

---

## **Overview**

SUS is a self-hosted platform that lets anyone — regardless of technical background — build, publish, and run disposable, lightweight applications using Claude Code. It is designed to run on a local machine or homelab with no external auth dependencies. A pluggable identity interface is provided so that authentication can be added later (e.g., via a reverse proxy, OIDC provider, or local user database).

The platform has two modes:

* **build** — create or modify an application in a live Claude Code session
* **run** — use the published version of an application

---

## **Architecture**

### **Components**

```
Browser
  └── Landing Page Pod (FastAPI, Kubernetes)
        ├── Resolves user identity via identity provider interface (default: single-user, no auth)
        ├── Serves catalog of applications
        ├── build mode: creates build pods via Kubernetes API + proxies traffic
        ├── run mode: creates run pods via Kubernetes API + proxies traffic
        └── Uses in-cluster ServiceAccount with RBAC to manage pods in sus-workloads namespace
```

### **Landing Page Pod**

A FastAPI application running as a long-lived pod in the cluster. It:

* Resolves user identity via a pluggable identity provider interface (see Access Control)
* Serves the catalog of applications
* Acts as a reverse proxy (HTTP \+ WebSocket) to user pods (build) or published app containers (run)
* Calls the Kubernetes API (via in-cluster client) to create and manage build and run pods

The landing page pod runs with a dedicated ServiceAccount that has RBAC permissions to create, list, get, and delete pods within a designated namespace (e.g., `sus-workloads`). This is how it orchestrates both build and run pods without requiring a CRD — it uses the Kubernetes API directly to manage standard pod resources.

```yaml
# Example RBAC setup
apiVersion: v1
kind: ServiceAccount
metadata:
  name: sus-landing
  namespace: sus
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: sus-pod-manager
  namespace: sus-workloads
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "services"]
    verbs: ["create", "get", "list", "watch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: sus-landing-binding
  namespace: sus-workloads
subjects:
  - kind: ServiceAccount
    name: sus-landing
    namespace: sus
roleRef:
  kind: Role
  name: sus-pod-manager
  apiGroup: rbac.authorization.k8s.io
```

### **User Pods (build mode)**

Each active editing session gets a dedicated Kubernetes pod containing:

* Claude Code CLI (pre-authenticated)
* Git client \+ SSH credentials for the monorepo
* Python runtime \+ HTMX tooling (default app stack)
* Pre-configured MCP servers (see Access Control)
* The immutable CLAUDE.md instruction set

Pod lifecycle:

* Spun up on demand when a user enters build mode
* Kept alive by a heartbeat ping from the browser (every 30s)
* Torn down after 10 minutes of idle (no heartbeat)
* Session state (user → pod \+ branch) persisted in SQLite so users can resume

### **Live Claude Session in the Browser**

The pod runs Claude Code CLI as the primary process. The landing page proxies a WebSocket connection from the browser to the pod. The browser renders the terminal using **xterm.js**, giving users a full Claude Code interface embedded in the page.

The UI is a split pane:

* **Left**: Claude Code terminal (served via ttyd as a WebSocket terminal)
* **Right**: Live preview of the app (iframe proxied from the pod's port 3000, auto-refreshes on content change)

This approach preserves all of Claude Code's capabilities (agentic loops, file editing, MCP tool use, sub-agents) without reimplementing them.

### **Run Mode**

When an app is published, the build pod's changes are committed and pushed to the app repo's main branch. Run mode serves published apps by:

1. Proxying to the build pod (if still running) — for immediate access after publish
2. Serving static files from the app repo clone — for apps that don't need a server
3. The landing page periodically pulls the app repo to stay in sync

---

## **Repository Structure**

SUS uses two separate repositories:

* **Platform repo** (`single-use-software`) — the SUS platform code, Helm chart, Dockerfiles, CLAUDE.md, skills
* **App repo** (`sus-starter-pack` or user's own fork) — all published apps, configured via `SUS_GIT_REPO_URL`

The app repo layout:

```
{category}/
  {app-slug}/
    sus.json             # app metadata (see below)
    main.py              # entry point (Python + HTMX by default)
    requirements.txt
    index.html           # or static site
    ...
```

Categories are chosen when creating a new app and organize the catalog. Users can create new categories or pick existing ones.

This separation means users can update SUS without merge conflicts with their apps.

**sus.json schema:**

```
{
  "name": "Global Marketing Calendar",
  "description": "Integrates campaign events with pipeline metrics",
  "owner": "alice@company.com",
  "team": "marketing",
  "created_at": "2026-03-24",
  "visibility": ["marketing", "leadership"],
  "default_stack": "python+htmx"
}
```

**Why apps/{team}/{app-slug}/?** Team-based top-level grouping keeps apps organized and, when auth is enabled, maps naturally to group-based permissions. It's browsable and self-documenting — no opaque hashing.

### **Git Workflow (fully automated by Claude)**

Non-engineer users never touch git. Claude handles it all, instructed via CLAUDE.md:

| Event | Git action |
| :---- | :---- |
| User starts editing a new app | git checkout \-b {user\_id}/{app-slug}/{date} |
| User resumes an existing session | git checkout {existing\_branch} |
| Every 5 minutes of active editing | Auto-commit: chore: autosave |
| User clicks **Save** | Named commit using Claude's summary of changes |
| User clicks **Publish** | PR opened → auditor runs → auto-merged to main |
| Merge conflict on publish | Claude resolves automatically; user notified with plain-English summary if unresolvable |

---

## **CLAUDE.md — Immutable Instructions**

CLAUDE.md is baked into the container image at /repo/claude/CLAUDE.md with permissions 444. It cannot be edited by users or by Claude itself. It defines:

1. **Default stack**: Python \+ HTMX unless the user explicitly requests otherwise  
2. **Git workflow**: the rules above — Claude manages all git operations silently  
3. **Sub-agents** (always active):  
   * **Runner agent**: executes the app, tails logs, reports errors back in plain English  
   * **Auditor agent**: invoked before every publish; checks for code quality, security issues (hardcoded secrets, SQL injection, SSRF, etc.), and any actions that could affect systems outside the monorepo. Blocks publish if issues are found and explains them to the user.  
4. **Safety rules**:  
   * Never modify files outside apps/{team}/ unless explicitly constructing shared skills  
   * Never make outbound network calls except to pre-approved MCP server endpoints  
   * Never write credentials or secrets to files — use environment variables injected at runtime  
   * No access to production environments under any circumstance

---

## **Guidance Skills**

Domain-specific knowledge packs that auto-load into Claude based on the user's team. Stored in claude/skills/ in the monorepo so domain experts can contribute them directly.

Examples:

* skills/finance.md — maps financial KPIs to the correct Snowflake tables and join logic  
* skills/marketing.md — defines campaign funnel stages, UTM conventions, event taxonomies  
* skills/customer-success.md — NPS/CSAT definitions, customer segment logic

Skills are plain Markdown files. Claude is instructed to discover and apply relevant skills automatically. Any employee can propose new skills or corrections via a PR — creating a self-improving knowledge base.

---

## **Access Control**

### **Identity**

SUS uses a pluggable identity provider interface. By default, it runs in **single-user mode** — no login required, and the local operator is treated as the owner with full access.

To add authentication later, implement the `IdentityProvider` interface, which returns a user identity (ID, display name, and optional group memberships) from an incoming request. Example providers that could be added:

* **Reverse proxy headers** — trust `X-Forwarded-User` / `X-Forwarded-Email` from an upstream proxy (Authelia, Authentik, Caddy, etc.)
* **Local user database** — username/password stored in SQLite, session cookies
* **OIDC / OAuth2** — delegate to a local or external identity provider (Keycloak, Dex, etc.)

The identity provider is configured via a single setting in the SUS config file, making it easy to swap without changing application code.

### **Policy Model**

In single-user mode, the operator has full access to all apps and data sources — no policy filtering is applied.

When an identity provider is configured that supports group memberships, a policy table (stored in SQLite) can map groups to capabilities:

| Group | Catalog visibility | Data sources |
| :---- | :---- | :---- |
| default | all apps | all configured sources |

Rules enforced at two layers:

1. **Catalog layer**: the landing page filters apps by the user's group policy (if auth is enabled)
2. **Pod layer**: MCP servers are provisioned per-pod with credentials scoped to the group's allowed data sources. Claude cannot access data sources that aren't mounted as MCP servers.

---

## **Session Resumption**

A SQLite sessions table stores:

```
{
  "user_id": "default",
  "pod_name": "build-pod-alice-abc123",
  "branch": "alice/marketing-calendar/2026-03-24",
  "last_seen": "2026-03-24T14:32:00Z",
  "app_slug": "marketing/global-calendar"
}
```

On build mode entry:

1. Look up user in sessions
2. If pod is still running → proxy to existing pod
3. If pod is gone but branch exists → spin up new pod, git checkout {branch}, resume
4. If no session → spin up new pod, new branch

---

## **Current Status**

### **Implemented**

* Landing page with catalog, search, tags, and category-based organization
* Build mode: Helm chart deployable to any cluster, build pod lifecycle, ttyd terminal, split-pane preview
* Separate app repo (`sus-starter-pack`) with git-based publish flow
* Save pushes working branch; publish merges to main and pushes
* Session resumption via SQLite session store + git branches
* Auto-runner detects app stack and serves on port 3000
* Preview auto-refresh on content change with spinner loading state
* **Dedicated run pods** created on publish using build pod image with `run-entrypoint.sh`
* **Auto-create run pods** on first Run request if app exists in repo but no pod is running
* **Loading page** with spinner while run pod starts (5-min timeout with error)
* Setup page for API key, Git token, and repo URL (K8s secrets/configmap)
* Optional Helm Ingress template with WebSocket annotation examples
* SUS Platform API for secrets management (`/api/secrets`, apps can manage credentials)
* Pluggable identity provider interface (defaults to single-user)
* Guidance skills framework with authoring guide
* Usage analytics and version history tracking
* CLAUDE.md with comprehensive environment/user context
* GitHub Actions CI/CD: multi-arch Docker images and Helm chart published to GHCR
* k3d-based dev environment with Makefile targets

### **Known Limitations**

* Claude Code consent prompts (API key + bypass) require 2 manual clicks (#48)
* No image paste or visual feedback in browser terminal (#66, #67)
* All users are "anonymous" — no real identity or access gating (#64)
* SQLite databases are ephemeral (lost on landing page pod restart) — see #68
* Auditor agent is advisory only, not enforced programmatically (#19)
* All browser caching disabled (#59)

### **Open Questions**

1. **Auditor enforcement**: Should publish be gated on automated audit results? (#19)
2. **Pod resource tuning**: Current limits work for single-user. Multi-user needs profiling. (#20)
3. **App runtime isolation**: Should run mode use a separate namespace? (#21)
4. **Caching strategy**: All caching is disabled. Need to evaluate what's safe to re-enable. (#59)
5. **User identity**: How to identify users and gate access for multi-user deployments. (#64)
6. **Persistent storage**: SQLite + emptyDir is ephemeral. Need PostgreSQL sidecar or platform API. (#68)

