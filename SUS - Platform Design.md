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

Earlier iterations assumed a Google Cloud Identity-Aware Proxy (IAP) in front of SUS. That doesn't fit a self-hosted / homelab audience, so the recommended strategy is **reverse-proxy forward-auth** running entirely in-cluster.

#### Recommended default: reverse-proxy forward-auth

Place a forward-auth gateway behind the Kubernetes Ingress and have it authenticate every request before it reaches the landing pod. **Authelia** is the reference implementation for a homelabber — mature, single-purpose, small attack surface, and easy to stand up with a file-based user store and its own login portal. SUS ships a bundled, opt-in Authelia (`--set auth.enabled=true`) as the turnkey path; a Traefik forward-auth middleware gates the SUS UI and Authelia returns the identity as `Remote-*` headers.

Alternatives that drop into the same forward-auth slot: **tinyauth** (even lighter, newer project) for minimal setups; **oauth2-proxy** as a thin connector when the operator already runs an OIDC provider; and **Authentik** as a full IdP when SAML, LDAP, or multiple upstream providers are needed.

This is the only approach that satisfies all of SUS's constraints at once:

* **No cloud dependency** — runs on the operator's own cluster.
* **WebSocket-safe** — the auth check happens once at the HTTP layer, *before* the ttyd WebSocket upgrade, so the long-lived terminal socket is never re-challenged or broken. Traefik (the k3s/k3d default) passes upgrade headers transparently; nginx-ingress needs `proxy-read-timeout`/`proxy-send-timeout` raised to ~3600s (already documented for ttyd in the README).
* **Gate *and* identity** — forward-auth both keeps strangers out and forwards the authenticated user to the backend as trusted headers (`Remote-User`, `Remote-Email`, `Remote-Groups`, `Remote-Name` for Authelia; `X-authentik-*` for Authentik). That is exactly what SUS needs to attribute build sessions to a user and eventually isolate pods/branches per user.

The identity provider is configured via a single setting in the SUS config file, making it easy to swap without changing application code. Providers:

* **Trusted-header (recommended)** — read `Remote-User` / `Remote-Email` (or `X-Forwarded-User` / `X-Forwarded-Email`) from the forward-auth proxy. See the hardening rules below before trusting these.
* **Local user database** — username/password stored in SQLite, session cookies. The no-proxy fallback for a single operator who wants named login without running an auth stack.
* **OIDC / OAuth2** — delegate to a self-hosted IdP (Keycloak, Authentik, Pocket ID, Dex). Heavier; use when an IdP already exists.

**Simplest LAN-only option:** don't expose SUS publicly at all — bind it to the LAN and reach it over Tailscale/WireGuard. This is a network-layer gate (need "keep strangers out") but not per-user identity; pair it with the local-database provider if named users are still wanted. It composes cleanly with forward-auth added later.

#### Footgun: trusted headers require a locked-down backend

Trusted-header auth is only as strong as the guarantee that the headers came from the proxy and nothing else. The backend sees the *proxy's* source IP, so it must trust identity headers **only** from the specific proxy address — trusting a whole Pod CIDR or flat network is exploitable: any compromised or malicious pod in that network can forge `Remote-User: admin` and bypass authentication entirely.

For SUS this is not hypothetical. Build and run pods already call the landing service at `SUS_API_URL`, and the apps running in them are semi-untrusted (LLM-generated). If SUS naively trusts a `Remote-User` header, a built app can send `Remote-User: admin` to `SUS_API_URL` and impersonate the operator — the same app→platform boundary tracked in the platform-API hardening issues (see #79 unauthenticated `/api/secrets`, #80 unvalidated `pod_ip` proxying). Forward-auth therefore **must compose with network isolation, not replace it.** Three requirements hold together, each now implemented when `auth.enabled=true`:

1. **NetworkPolicy** on the landing pod's HTTP port (`charts/sus/templates/networkpolicy.yaml`). It admits the ingress controller (authenticated UI traffic) plus the workloads and platform namespaces. The workloads allowance is deliberate — build/run pods legitimately call the platform API on that port — which means an in-cluster app pod can still reach the API surface directly. Closing that residual vector is #79 (authenticate the API) / #80 (validate `pod_ip`), not this control.
2. **`ProxyHeaderProvider` ignores identity headers unless the request's raw socket peer is within `identity_options.trusted_proxies`** (`landing/app/identity.py`); anything else resolves to an anonymous guest. The peer IP is the real socket address, not a forwardable header — uvicorn must not be run with a wildcard `--forwarded-allow-ips`.
3. **The Traefik forward-auth middleware overwrites (not appends)** the `Remote-*` headers from Authelia's response on every request, so a client-supplied copy can't survive (`charts/sus/templates/authelia/middleware.yaml`).

Additionally, keep the ingress patched (e.g. Traefik ≥ v2.11.43 / v3.6.14 for the `X-Forwarded-Prefix` ForwardAuth fix) and strip client-supplied `X-Forwarded-*` at the edge.

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

