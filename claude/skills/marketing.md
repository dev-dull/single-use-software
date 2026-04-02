# Skill: Marketing

> Use this skill when building apps for marketing teams — campaign trackers,
> attribution dashboards, funnel analyzers, or any tool that works with
> marketing data.

---

## 1. Campaign Funnel Stages

Marketing funnels follow these standard stages. Use these names and ordering
in any funnel visualization or report.

| Stage | Description | Typical events |
|---|---|---|
| **Awareness** | User first encounters the brand | `page_view`, `ad_impression`, `social_view` |
| **Consideration** | User engages with content or product | `content_download`, `video_watch`, `pricing_page_view` |
| **Conversion** | User takes a desired action | `signup`, `form_submit`, `purchase`, `trial_start` |
| **Retention** | User returns and continues engaging | `login`, `feature_use`, `subscription_renewal` |

### Funnel query pattern

```sql
SELECT
  stage,
  COUNT(DISTINCT user_id) AS users
FROM events
WHERE campaign_id = :campaign_id
  AND event_time >= :start AND event_time < :end
GROUP BY stage
ORDER BY
  CASE stage
    WHEN 'awareness' THEN 1
    WHEN 'consideration' THEN 2
    WHEN 'conversion' THEN 3
    WHEN 'retention' THEN 4
  END;
```

When building funnel charts, calculate the drop-off rate between each stage:

```python
def funnel_dropoff(stages: list[dict]) -> list[dict]:
    """Add conversion_rate and dropoff_rate to each stage."""
    for i, stage in enumerate(stages):
        if i == 0:
            stage["conversion_rate"] = 1.0
        else:
            prev = stages[i - 1]["users"]
            stage["conversion_rate"] = stage["users"] / prev if prev else 0
        stage["dropoff_rate"] = 1 - stage["conversion_rate"]
    return stages
```

---

## 2. UTM Parameter Conventions

When parsing or generating UTM-tagged URLs, follow this standard:

| Parameter | Purpose | Example values |
|---|---|---|
| `utm_source` | Where the traffic comes from | `google`, `facebook`, `newsletter`, `partner_blog` |
| `utm_medium` | Marketing channel type | `cpc`, `email`, `social`, `referral`, `organic` |
| `utm_campaign` | Specific campaign name | `spring_sale_2026`, `product_launch_q1` |
| `utm_term` | Paid search keyword | `crm+software`, `project+management` |
| `utm_content` | Differentiates ad variants | `header_cta`, `sidebar_banner`, `blue_button` |

### Table schema for UTM tracking

```
page_views
  id              BIGINT PRIMARY KEY
  user_id         BIGINT
  session_id      TEXT
  url             TEXT
  utm_source      TEXT
  utm_medium      TEXT
  utm_campaign    TEXT
  utm_term        TEXT
  utm_content     TEXT
  referrer        TEXT
  viewed_at       TIMESTAMPTZ
```

### Parsing UTMs in Python

```python
from urllib.parse import urlparse, parse_qs

def extract_utms(url: str) -> dict:
    params = parse_qs(urlparse(url).query)
    return {
        "utm_source": params.get("utm_source", [None])[0],
        "utm_medium": params.get("utm_medium", [None])[0],
        "utm_campaign": params.get("utm_campaign", [None])[0],
        "utm_term": params.get("utm_term", [None])[0],
        "utm_content": params.get("utm_content", [None])[0],
    }
```

### Naming rules

- All lowercase, underscores instead of spaces: `spring_sale_2026`, not
  `Spring Sale 2026`.
- No special characters beyond underscores and hyphens.
- Campaign names should follow the pattern: `{initiative}_{quarter_or_date}`.

---

## 3. Event Taxonomy

Use these event names when building analytics or tracking tools. They follow
a `noun_verb` pattern in `snake_case`.

### Standard events

| Event name | When it fires | Required properties |
|---|---|---|
| `page_view` | User loads a page | `url`, `referrer`, `session_id` |
| `click` | User clicks a tracked element | `element_id`, `element_text`, `url` |
| `form_submit` | User submits a form | `form_id`, `form_name`, `fields_count` |
| `signup` | User creates an account | `method` (`email`, `google`, `sso`) |
| `login` | User signs in | `method` |
| `purchase` | User completes a transaction | `amount_cents`, `currency`, `product_id` |
| `trial_start` | User begins a free trial | `plan_id` |
| `content_download` | User downloads a resource | `content_id`, `content_type` |
| `video_watch` | User watches a video | `video_id`, `duration_seconds`, `percent_watched` |
| `email_open` | Recipient opens an email | `email_campaign_id` |
| `email_click` | Recipient clicks a link in email | `email_campaign_id`, `link_url` |
| `ad_impression` | Ad is displayed to a user | `ad_id`, `placement`, `campaign_id` |
| `ad_click` | User clicks an ad | `ad_id`, `placement`, `campaign_id` |

### Events table schema

```
events
  id              BIGINT PRIMARY KEY
  user_id         BIGINT
  session_id      TEXT
  event_name      TEXT          -- one of the standard event names above
  properties      JSONB         -- event-specific key-value pairs
  campaign_id     BIGINT        -- nullable, set when attributable to a campaign
  stage           TEXT          -- funnel stage: awareness, consideration, conversion, retention
  event_time      TIMESTAMPTZ
  created_at      TIMESTAMPTZ DEFAULT now()
```

---

## 4. Common Marketing Metrics

Use these formulas when a user asks for marketing KPIs.

| Metric | Formula | Display format |
|---|---|---|
| **CTR** (Click-Through Rate) | `clicks / impressions` | Percentage, 2 decimals: `2.34%` |
| **Conversion Rate** | `conversions / total_visitors` (or clicks) | Percentage, 2 decimals: `5.12%` |
| **ROAS** (Return on Ad Spend) | `revenue_from_campaign / ad_spend` | Ratio with 2 decimals: `3.45x` |
| **CPA** (Cost per Acquisition) | `total_spend / conversions` | Currency: `$42.50` |
| **CPM** (Cost per Mille) | `(total_spend / impressions) * 1000` | Currency: `$8.20` |
| **CPC** (Cost per Click) | `total_spend / clicks` | Currency: `$1.15` |
| **Bounce Rate** | `single_page_sessions / total_sessions` | Percentage, 1 decimal: `45.2%` |
| **Email Open Rate** | `unique_opens / delivered_emails` | Percentage, 1 decimal: `22.5%` |
| **Unsubscribe Rate** | `unsubscribes / delivered_emails` | Percentage, 2 decimals: `0.34%` |

### ROAS query example

```sql
SELECT
  c.name AS campaign_name,
  SUM(e.amount_cents) FILTER (WHERE e.category = 'ad_spend') AS spend_cents,
  SUM(p.amount_cents) AS revenue_cents,
  ROUND(
    SUM(p.amount_cents)::numeric
    / NULLIF(SUM(e.amount_cents) FILTER (WHERE e.category = 'ad_spend'), 0),
    2
  ) AS roas
FROM campaigns c
LEFT JOIN expenses e ON e.campaign_id = c.id
LEFT JOIN purchases p ON p.campaign_id = c.id
WHERE c.started_at >= :start AND c.started_at < :end
GROUP BY c.id, c.name
ORDER BY roas DESC;
```

---

## 5. HTMX Patterns for Marketing Dashboards

### Campaign selector with live-updating metrics

```html
<select name="campaign_id"
        hx-get="/api/campaign-metrics"
        hx-target="#metrics-panel"
        hx-trigger="change">
  {% for c in campaigns %}
  <option value="{{ c.id }}">{{ c.name }}</option>
  {% endfor %}
</select>

<div id="metrics-panel">
  {# Metrics load here via HTMX #}
</div>
```

### Date range filter

```html
<form hx-get="/api/funnel" hx-target="#funnel-chart" hx-trigger="change">
  <input type="date" name="start" value="{{ default_start }}">
  <input type="date" name="end" value="{{ default_end }}">
</form>
```

---

## 6. Common Pitfalls

- **Attribution double-counting**: A user may interact with multiple campaigns.
  Use last-touch attribution by default unless the user specifies otherwise.
- **Impressions vs. reach**: Impressions count every display. Reach counts
  unique users. Always clarify which one the user wants.
- **Mixing time windows**: CTR for a day vs. a month can look very different.
  Always show the time window in the UI.
- **Zero-division**: Guard against dividing by zero in rate calculations.
  Use `NULLIF(..., 0)` in SQL and explicit checks in Python.
- **UTM case sensitivity**: Normalize UTM values to lowercase on ingest.
  `Google` and `google` should not be treated as separate sources.
