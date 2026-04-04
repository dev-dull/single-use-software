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

* **Left**: Claude Code terminal (xterm.js)  
* **Right**: Live preview of the app (iframe proxied from the pod's secondary port)

This approach preserves all of Claude Code's capabilities (agentic loops, file editing, MCP tool use, sub-agents) without reimplementing them.

### **Run Pods (run mode)**

When an app is published, a container image is built from the app's directory in the monorepo and registered in the catalog. In run mode, the landing page pod creates a run pod from that image in the `sus-workloads` namespace and proxies user traffic to it. Run pods are read-only — no Claude session, no editing.

---

## **Repository Structure**

SUS uses two separate repositories:

* **Platform repo** (`single-use-software`) — the SUS platform code, Helm chart, Dockerfiles, CLAUDE.md, skills
* **App repo** (`sus-starter-pack` or user's own fork) — all published apps, configured via `SUS_GIT_REPO_URL`

The app repo layout:

```
{team}/
  {app-slug}/
    sus.json             # app metadata (see below)
    main.py              # entry point (Python + HTMX by default)
    requirements.txt
    index.html           # or static site
    ...
```

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

## **Key Open Questions for Team Discussion**

1. **MCP server catalogue**: Which data sources do we support first? What's the configuration UX for connecting new sources?
2. **Skill authorship process**: Who owns and reviews guidance skill PRs? Propose a lightweight review process (e.g., team lead approval).
3. **Pod resource limits**: What CPU/memory allocation per pod? What's the max concurrent pods we want to support?
4. **Auditor strictness**: Should the auditor block publish on warnings, or only hard errors? What's the escalation path if a user disagrees with the auditor?
5. **App runtime isolation**: Should published apps in run mode run in a separate namespace or cluster? (Affects blast radius if an app has a bug.)
6. **Rollback**: If a published app breaks, how does a non-engineer roll back? Propose: a **Revert** button in the catalog that restores the previous main commit for that app's directory.

---

## **Phased Rollout**

### **Phase 1 — Foundation**

* Landing page with catalog (single-user mode, no auth)
* build mode: pod lifecycle, WebSocket terminal proxy, xterm.js UI, split-pane preview
* Monorepo setup with CLAUDE.md, runner \+ auditor agents
* Git automation (branch, commit, publish flow)

### **Phase 2 — Intelligence**

* Guidance skills
* MCP server integrations for local data sources
* Session resumption
* Pluggable identity provider interface \+ optional auth support

### **Phase 3 — Scale**

* Self-service skill authorship  
* Catalog search \+ tagging  
* Usage analytics (who's building what, weekly active users)  
* App versioning \+ rollback UI

