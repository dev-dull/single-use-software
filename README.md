<p align="center" style="font-size: 80px;">

# 🤨

# SUS — Single Use Software

</p>

**Build apps by describing what you want.** SUS is a self-hosted platform that lets anyone — regardless of technical background — build, publish, and run lightweight web applications using Claude Code in the browser.

No coding required. Describe your app in plain language, watch it appear in a live preview, click Publish, and share it.

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [k3d](https://k3d.io/) (`brew install k3d`)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [Helm](https://helm.sh/docs/intro/install/)
- An [Anthropic API key](https://console.anthropic.com/settings/keys)

### 1. Fork the starter pack

Fork [**sus-starter-pack**](https://github.com/dev-dull/sus-starter-pack) — this is where your apps will be stored.

### 2. Start the cluster

```bash
git clone https://github.com/dev-dull/single-use-software.git
cd single-use-software
make dev
```

This creates a local k3d Kubernetes cluster, builds the container images, and deploys SUS.

### 3. Access SUS

```bash
kubectl port-forward -n sus svc/sus-landing 9090:80
```

Open [http://localhost:9090](http://localhost:9090)

### 4. Complete setup

Click the **Setup** link and configure:

1. **App Repository** — your forked `sus-starter-pack` URL
2. **Anthropic API Key** — from [console.anthropic.com](https://console.anthropic.com/settings/keys)
3. **Git Access Token** — a [personal access token](https://github.com/settings/tokens/new) with `repo` permissions

### 5. Build your first app

Click **+ Create New App**, give it a name and description, and start chatting with Claude. Your app appears in the live preview as you build it.

---

## How It Works

```
Browser
  |
  v
Landing Page Pod (FastAPI, Kubernetes)
  |-- Catalog: reads apps from your git repo
  |-- Build mode: spins up a build pod with Claude Code + ttyd
  |-- Run mode: proxies to build pods or serves static apps from the repo
  |-- Setup: API key, git token, repo URL stored as K8s secrets/configmaps
  |
  v
Build Pods (per-session, on demand)
  |-- Claude Code CLI via ttyd (browser terminal)
  |-- Auto-runner: detects app files, serves on port 3000
  |-- Git: commits to branch, pushes on save, merges to main on publish
  |
  v
App Repository (your fork of sus-starter-pack)
  |-- {category}/{app-slug}/sus.json + app files
  |-- Published apps are merged to main
  |-- Saved work-in-progress lives on branches
```

---

## Configuration

SUS can be configured two ways:

| Setting | Setup Page | Helm Value |
|---------|-----------|------------|
| App repo URL | `/setup` | `--set gitRepo.url=...` |
| Anthropic API key | `/setup` | K8s secret `sus-anthropic-api-key` |
| Git access token | `/setup` | K8s secret `sus-git-token` |
| Build pod resources | — | `buildPod.resources` in `values.yaml` |
| Landing page resources | — | `landing.resources` in `values.yaml` |

See [`charts/sus/values.yaml`](charts/sus/values.yaml) for all Helm values.

---

## Makefile Targets

```
make dev          # Full setup: cluster + build + deploy
make build        # Build all container images
make push         # Push images to local registry
make deploy       # Install Helm chart
make upgrade      # Upgrade Helm release
make teardown     # Delete the cluster
make status       # Show pods and services
make logs         # Tail landing page logs
make redeploy     # Rebuild + upgrade + restart
```

---

## Operator Tools

- `/setup` — Configure API key, git token, and repo URL
- `/analytics` — Usage dashboard (page views, build sessions)
- `/skills` — Manage guidance skills for Claude
- `/debug/build-chain/{team}/{app}` — Diagnostic endpoint that tests the full build pipeline
- `/debug/env` — Show configured environment variables
- `/api/secrets` — Manage K8s secrets (used by apps via the SUS Platform API)

---

## Links

- [Starter Pack](https://github.com/dev-dull/sus-starter-pack) — fork this for your apps
- [Design Document](SUS%20-%20Platform%20Design.md) — detailed architecture and design decisions
- [Issues](https://github.com/dev-dull/single-use-software/issues) — bugs, features, and discussion

---

## License

[MIT](LICENSE)
