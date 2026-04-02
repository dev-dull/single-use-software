# Authoring Guidance Skills

This guide explains how to write a guidance skill for the SUS platform.
Skills are Markdown files that teach Claude about a specific domain so it
can build better apps for teams working in that area.

---

## What is a skill?

A skill is a plain Markdown file in `claude/skills/` that Claude loads into
context when building apps for a particular team or domain. Skills contain
concrete conventions, formulas, table schemas, and patterns that Claude
follows when generating code.

Skills are **not** code libraries or configuration files. They are
instructions written in natural language with embedded examples.

---

## When does Claude use skills?

- When a user starts a build session, Claude checks for skills that match
  the user's team (e.g., `apps/finance/` maps to `claude/skills/finance.md`).
- `claude/skills/example.md` is always loaded as baseline context.
- If multiple skills are relevant, Claude loads all of them.
- Skills supplement Claude's general knowledge with company-specific
  conventions.

---

## File format and naming

| Rule | Convention |
|---|---|
| Location | `claude/skills/` in the monorepo root |
| File name | `{domain}.md` — lowercase, hyphens for multi-word names |
| Format | Markdown with a level-1 heading, blockquote summary, and numbered sections |
| Encoding | UTF-8, LF line endings |

**File name examples**: `finance.md`, `marketing.md`, `customer-success.md`,
`data-engineering.md`, `sales-ops.md`.

---

## Anatomy of a skill

Every skill should follow this structure:

```markdown
# Skill: {Domain Name}

> One-line summary of when to use this skill.

---

## 1. {Core Concepts}

Define the key terms, KPIs, or domain objects. Use tables for structured
definitions. Include formulas where applicable.

## 2. {Table and Column Conventions}

Provide concrete table schemas with column names, types, and comments.
This is what Claude will use when generating SQL or building data models.

## 3. {Common Query Patterns}

SQL snippets or join patterns that come up frequently in this domain.
Use parameterized queries (`:param_name`), not hardcoded values.

## 4. {UI and Display Conventions}

How to format values in HTMX templates — currency, percentages, dates,
color coding. Include Jinja2 snippets.

## 5. {Common Pitfalls}

Mistakes Claude should avoid. Be specific: "Never use floats for money"
is useful; "Be careful with data" is not.
```

The section names and count can vary — the structure above is a guideline,
not a rigid requirement.

---

## What makes a good skill

A good skill is **specific enough that Claude can follow it mechanically**.
It answers: "If Claude encounters this situation, what exactly should it do?"

### Good examples

- "Store monetary values as integers in cents (`amount_cents`). Never use
  floats for money."
- "NPS = %promoters - %detractors, where promoters score 9-10 and
  detractors score 0-6."
- "UTM parameters should be normalized to lowercase on ingest."
- "The `subscriptions` table has columns: `id`, `customer_id`, `plan_id`,
  `status`, `mrr_cents`, `started_at`, `canceled_at`."

### Bad examples

- "Make sure the data is accurate." (Too vague — how?)
- "Follow best practices for financial reporting." (Which practices?)
- "Be careful with customer data." (Not actionable)
- "Use good SQL." (Meaningless without specifics)

The test: if you removed the skill, would Claude generate noticeably
different (worse) code? If not, the skill is not specific enough.

---

## What NOT to put in a skill

| Do not include | Why |
|---|---|
| Code implementations (full modules, classes) | Skills are guidance, not libraries. Claude generates the code. |
| Credentials, API keys, secrets | Secrets are injected as environment variables at runtime. Never write them to files. |
| Runtime configuration (ports, hostnames, env vars) | These belong in deployment config, not skill files. |
| Personal opinions or preferences | Skills should reflect team conventions, not individual taste. |
| Lengthy prose without examples | Claude learns better from concrete patterns than from paragraphs of explanation. |
| Duplicates of existing skills | Check what already exists in `claude/skills/` before writing a new one. |

---

## Template for a new skill

Copy this skeleton and fill in the sections:

```markdown
# Skill: {Domain Name}

> Use this skill when building apps for {team/domain} — {brief list of
> app types this skill covers}.

---

## 1. Key Metrics and Definitions

| Metric | Formula | Display format |
|---|---|---|
| **{Metric name}** | `{formula}` | {e.g., percentage, currency, integer} |

## 2. Table and Column Conventions

{Provide CREATE TABLE-style schema blocks with column names, types,
and inline comments explaining each column.}

## 3. Common Query Patterns

{SQL snippets for the most frequent queries in this domain. Use
`:param_name` for parameters.}

## 4. Display and Formatting

{Jinja2/HTMX patterns for rendering domain-specific values.}

## 5. Common Pitfalls

- **{Pitfall name}**: {Specific explanation of what to avoid and what
  to do instead.}
```

---

## How to submit a skill

1. Create a branch: `git checkout -b skills/{domain-name}`.
2. Add your file at `claude/skills/{domain-name}.md`.
3. Follow the conventions in this guide.
4. Open a PR to `main` targeting the `claude/skills/` directory.
5. In the PR description, explain what team or use case the skill serves.
6. A reviewer will check that the skill is specific, actionable, and does
   not contain any of the "do not include" items listed above.

---

## Reviewing skills

When reviewing a skill PR, check for:

- [ ] File is in `claude/skills/` with a lowercase, hyphenated `.md` name
- [ ] Has a level-1 heading and blockquote summary
- [ ] Includes concrete table schemas, formulas, or query patterns
- [ ] Does not contain credentials, secrets, or runtime config
- [ ] Does not duplicate an existing skill
- [ ] Pitfalls section is specific and actionable
- [ ] Examples use parameterized queries, not hardcoded values
