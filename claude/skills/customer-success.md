# Skill: Customer Success

> Use this skill when building apps for customer success teams — health score
> dashboards, NPS trackers, support ticket analyzers, or renewal forecasting
> tools.

---

## 1. Satisfaction Score Definitions

### NPS (Net Promoter Score)

Survey question: *"On a scale of 0-10, how likely are you to recommend us?"*

| Group | Score range |
|---|---|
| Detractors | 0-6 |
| Passives | 7-8 |
| Promoters | 9-10 |

**Formula**: `NPS = %promoters - %detractors`

Result ranges from -100 to +100. Display as a signed integer (`+42`, `-15`).

```sql
SELECT
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE score >= 9) / NULLIF(COUNT(*), 0)
    - 100.0 * COUNT(*) FILTER (WHERE score <= 6) / NULLIF(COUNT(*), 0),
    0
  ) AS nps
FROM nps_responses
WHERE submitted_at >= :period_start
  AND submitted_at < :period_end;
```

### CSAT (Customer Satisfaction Score)

Survey question: *"How satisfied were you with your experience?"* (1-5 scale)

**Formula**: `CSAT = (responses_of_4_or_5 / total_responses) * 100`

Display as a percentage: `87%`.

```sql
SELECT
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE rating >= 4) / NULLIF(COUNT(*), 0),
    0
  ) AS csat_percent
FROM csat_responses
WHERE submitted_at >= :period_start
  AND submitted_at < :period_end;
```

### CES (Customer Effort Score)

Survey question: *"How easy was it to resolve your issue?"* (1-7 scale)

**Formula**: `CES = average of all responses`

Lower is better (less effort). Display with one decimal: `2.3`.

```sql
SELECT ROUND(AVG(effort_score)::numeric, 1) AS ces
FROM ces_responses
WHERE submitted_at >= :period_start
  AND submitted_at < :period_end;
```

---

## 2. Table Schemas

### Survey responses

```
nps_responses
  id              BIGINT PRIMARY KEY
  customer_id     BIGINT REFERENCES customers(id)
  score           INTEGER       -- 0-10
  comment         TEXT
  submitted_at    TIMESTAMPTZ

csat_responses
  id              BIGINT PRIMARY KEY
  customer_id     BIGINT REFERENCES customers(id)
  ticket_id       BIGINT        -- nullable, links to the interaction
  rating          INTEGER       -- 1-5
  comment         TEXT
  submitted_at    TIMESTAMPTZ

ces_responses
  id              BIGINT PRIMARY KEY
  customer_id     BIGINT REFERENCES customers(id)
  ticket_id       BIGINT
  effort_score    INTEGER       -- 1-7
  comment         TEXT
  submitted_at    TIMESTAMPTZ
```

### Support tickets

```
support_tickets
  id              BIGINT PRIMARY KEY
  customer_id     BIGINT REFERENCES customers(id)
  assigned_to     BIGINT        -- CSM user ID
  subject         TEXT
  category        TEXT          -- see categorization below
  priority        TEXT          -- 'low', 'medium', 'high', 'urgent'
  status          TEXT          -- 'open', 'pending', 'resolved', 'closed'
  channel         TEXT          -- 'email', 'chat', 'phone', 'self_service'
  first_response_at TIMESTAMPTZ
  resolved_at     TIMESTAMPTZ
  created_at      TIMESTAMPTZ
```

---

## 3. Customer Segmentation

Segment customers using ARR tiers. Use these defaults unless the user
provides different thresholds.

| Segment | ARR range | Typical characteristics |
|---|---|---|
| **Enterprise** | >= $100,000 | Dedicated CSM, custom contracts, quarterly business reviews |
| **Mid-Market** | $10,000 - $99,999 | Pooled CSM, standard contracts, semi-annual check-ins |
| **SMB** | < $10,000 | Tech-touch only, self-service, automated outreach |

### Segmentation query

```sql
SELECT
  c.id,
  c.name,
  SUM(s.mrr_cents) * 12 AS arr_cents,
  CASE
    WHEN SUM(s.mrr_cents) * 12 >= 10000000 THEN 'enterprise'   -- $100k+
    WHEN SUM(s.mrr_cents) * 12 >= 1000000  THEN 'mid_market'   -- $10k+
    ELSE 'smb'
  END AS segment
FROM customers c
JOIN subscriptions s ON s.customer_id = c.id AND s.status = 'active'
GROUP BY c.id, c.name;
```

### Segment-specific defaults

When building CS dashboards, tailor the default view by segment:

- **Enterprise**: Show individual account details, contact history, renewal
  date, and expansion opportunities.
- **Mid-Market**: Show account lists sorted by health score with batch
  action capabilities.
- **SMB**: Show aggregate metrics — cohort health, churn trends, automated
  campaign performance.

---

## 4. Health Score

A customer health score predicts churn risk. Use a weighted composite of
these signals.

| Component | Weight | Calculation | Good | At risk |
|---|---|---|---|---|
| **Product usage** | 30% | `active_days_last_30 / 30` | >= 0.6 | < 0.3 |
| **Support sentiment** | 20% | Average CSAT over last 90 days, normalized 0-1 | >= 0.8 | < 0.5 |
| **NPS** | 15% | Latest NPS response, normalized 0-1 (`(score) / 10`) | >= 0.8 | < 0.6 |
| **Contract status** | 15% | 1 if renewal > 90 days out, 0.5 if 30-90 days, 0 if < 30 days | 1.0 | 0 |
| **Support ticket volume** | 10% | Inverse: `1 - min(open_tickets / 5, 1)` | >= 0.8 | < 0.4 |
| **Engagement** | 10% | `logins_last_30 / expected_logins` capped at 1.0 | >= 0.7 | < 0.3 |

**Overall score**: Weighted sum, scaled 0-100.

```python
def health_score(
    usage_ratio: float,
    avg_csat: float,       # 0-1 normalized
    nps_score: int,        # 0-10
    days_to_renewal: int,
    open_tickets: int,
    login_ratio: float,
) -> int:
    components = {
        "product_usage": min(usage_ratio, 1.0) * 30,
        "support_sentiment": min(avg_csat, 1.0) * 20,
        "nps": (nps_score / 10) * 15,
        "contract_status": (
            15 if days_to_renewal > 90
            else 7.5 if days_to_renewal > 30
            else 0
        ),
        "ticket_volume": max(1 - open_tickets / 5, 0) * 10,
        "engagement": min(login_ratio, 1.0) * 10,
    }
    return round(sum(components.values()))
```

### Display conventions

| Score range | Label | Color |
|---|---|---|
| 80-100 | Healthy | `text-green-600` / `bg-green-50` |
| 50-79 | Needs attention | `text-yellow-600` / `bg-yellow-50` |
| 0-49 | At risk | `text-red-600` / `bg-red-50` |

---

## 5. Support Ticket Categorization

Use these standard categories for classifying support tickets.

| Category | Description | Examples |
|---|---|---|
| `bug_report` | Something is broken | "Dashboard won't load", "Export gives wrong numbers" |
| `feature_request` | Customer wants new functionality | "Can we add a Slack integration?" |
| `how_to` | Customer needs help using the product | "How do I set up SSO?" |
| `billing` | Invoice, payment, or plan questions | "Can we switch to annual billing?" |
| `account_management` | User access, permissions, settings | "Add a new admin user" |
| `data_issue` | Incorrect, missing, or delayed data | "My report shows zero revenue for March" |
| `integration` | Third-party connection problems | "Salesforce sync is failing" |
| `performance` | Slowness or timeout complaints | "Reports take 30 seconds to load" |
| `security` | Security or compliance concerns | "We need SOC 2 documentation" |
| `other` | Does not fit the above | Anything else |

### Ticket volume by category query

```sql
SELECT
  category,
  COUNT(*) AS ticket_count,
  ROUND(AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600)::numeric, 1)
    AS avg_resolution_hours
FROM support_tickets
WHERE created_at >= :period_start
  AND created_at < :period_end
GROUP BY category
ORDER BY ticket_count DESC;
```

---

## 6. Common Pitfalls

- **NPS sample bias**: Low response rates skew NPS. Always display the
  response count alongside the score so users know if it is meaningful.
- **Health score stale data**: If a component has no recent data (e.g., no
  CSAT responses in 90 days), flag it rather than using an old value. Show
  "No data" instead of a misleading number.
- **Segment threshold changes**: When a customer's ARR crosses a segment
  boundary, their CSM assignment and touchpoint cadence should change.
  Surface these transitions in the UI.
- **First response time**: Measure from ticket creation to the first
  **human** response, not automated acknowledgments.
- **Renewal date accuracy**: Always pull renewal dates from the subscription
  system, not from manually entered fields that may be stale.
