# Skill: Finance

> Use this skill when building apps for finance teams — dashboards, reporting
> tools, forecasting models, or anything that touches financial data.

---

## 1. Common Financial KPIs

When a user asks for a financial metric, use these definitions unless they
specify otherwise.

| KPI | Formula | Notes |
|---|---|---|
| **Revenue** | Sum of all closed invoices in the period | Always use the invoice `closed_at` date, not `created_at` |
| **MRR** (Monthly Recurring Revenue) | Sum of active subscriptions' monthly value at period end | Normalize annual plans: `annual_price / 12` |
| **ARR** (Annual Recurring Revenue) | `MRR * 12` | Snapshot metric — use the last day of the period |
| **Net New MRR** | `new_mrr + expansion_mrr - contraction_mrr - churned_mrr` | Break this down in the UI so users see the components |
| **Churn Rate** | `lost_customers_in_period / customers_at_start_of_period` | Express as a percentage. Use customer count, not revenue, unless the user says "revenue churn" |
| **Revenue Churn** | `lost_mrr_in_period / mrr_at_start_of_period` | Distinct from logo churn — always clarify which one is being used |
| **CAC** (Customer Acquisition Cost) | `total_sales_and_marketing_spend / new_customers_acquired` | Period must match — same month/quarter for spend and acquisition |
| **LTV** (Lifetime Value) | `average_revenue_per_account / revenue_churn_rate` | Simple model. For cohort-based LTV, sum revenue per cohort over time |
| **LTV:CAC Ratio** | `ltv / cac` | Healthy benchmark is 3:1 or higher |
| **Gross Margin** | `(revenue - cogs) / revenue` | Express as a percentage |
| **Burn Rate** | `cash_balance_start - cash_balance_end` over the period | Monthly burn is the standard unit |
| **Runway** | `current_cash_balance / monthly_burn_rate` | Express in months |

---

## 2. Table and Column Naming Conventions

Use these table and column names when generating SQL or building schemas for
finance apps. This keeps things consistent across the platform.

### Core tables

```
subscriptions
  id              BIGINT PRIMARY KEY
  customer_id     BIGINT REFERENCES customers(id)
  plan_id         BIGINT REFERENCES plans(id)
  status          TEXT        -- 'active', 'canceled', 'past_due', 'trialing'
  mrr_cents       INTEGER     -- monthly value in cents (avoid floats for money)
  started_at      TIMESTAMPTZ
  canceled_at     TIMESTAMPTZ
  current_period_start TIMESTAMPTZ
  current_period_end   TIMESTAMPTZ

invoices
  id              BIGINT PRIMARY KEY
  customer_id     BIGINT REFERENCES customers(id)
  subscription_id BIGINT REFERENCES subscriptions(id)
  amount_cents    INTEGER
  currency        TEXT        -- ISO 4217: 'USD', 'EUR', 'GBP'
  status          TEXT        -- 'draft', 'open', 'paid', 'void', 'uncollectible'
  issued_at       TIMESTAMPTZ
  paid_at         TIMESTAMPTZ
  closed_at       TIMESTAMPTZ

plans
  id              BIGINT PRIMARY KEY
  name            TEXT
  interval        TEXT        -- 'month', 'year'
  amount_cents    INTEGER
  currency        TEXT

expenses
  id              BIGINT PRIMARY KEY
  category        TEXT        -- 'payroll', 'marketing', 'infrastructure', 'other'
  amount_cents    INTEGER
  currency        TEXT
  incurred_at     TIMESTAMPTZ
  department      TEXT
```

### Naming rules

- Store monetary values as **integers in cents** (`amount_cents`). Never use
  floats for money.
- Always include a `currency` column — never assume USD.
- Timestamps use `TIMESTAMPTZ` and end with `_at`.
- Status columns use lowercase text enums, not integer codes.

---

## 3. Common Join Patterns

### MRR by month

```sql
SELECT
  date_trunc('month', s.current_period_start) AS month,
  SUM(s.mrr_cents) AS total_mrr_cents
FROM subscriptions s
WHERE s.status = 'active'
GROUP BY 1
ORDER BY 1;
```

### Revenue by customer for a period

```sql
SELECT
  c.id AS customer_id,
  c.name,
  SUM(i.amount_cents) AS revenue_cents
FROM invoices i
JOIN customers c ON c.id = i.customer_id
WHERE i.status = 'paid'
  AND i.paid_at >= :period_start
  AND i.paid_at < :period_end
GROUP BY c.id, c.name
ORDER BY revenue_cents DESC;
```

### CAC calculation

```sql
SELECT
  date_trunc('month', c.created_at) AS cohort_month,
  SUM(e.amount_cents) FILTER (WHERE e.category IN ('marketing', 'sales'))
    AS acquisition_spend_cents,
  COUNT(DISTINCT c.id) AS new_customers,
  SUM(e.amount_cents) FILTER (WHERE e.category IN ('marketing', 'sales'))
    / NULLIF(COUNT(DISTINCT c.id), 0) AS cac_cents
FROM customers c
LEFT JOIN expenses e
  ON date_trunc('month', e.incurred_at) = date_trunc('month', c.created_at)
WHERE c.created_at >= :period_start
  AND c.created_at < :period_end
GROUP BY 1
ORDER BY 1;
```

---

## 4. Formatting Currency and Percentages in HTMX Apps

### Currency

In Jinja2 templates, format money like this:

```jinja2
{# Convert cents to dollars and format with commas #}
${{ "{:,.2f}".format(amount_cents / 100) }}
```

For multi-currency support, pass the currency code and use a helper:

```python
def format_currency(amount_cents: int, currency: str = "USD") -> str:
    symbols = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}
    symbol = symbols.get(currency, currency + " ")
    return f"{symbol}{amount_cents / 100:,.2f}"
```

### Percentages

- Churn, margins, and rates: display with one decimal place (`4.2%`).
- Growth rates: display with one decimal place and a `+`/`-` prefix
  (`+12.3%`, `-2.1%`).

```jinja2
{{ "{:+.1f}%".format(growth_rate * 100) }}
```

### Color conventions

- **Green** for positive changes (revenue up, churn down).
- **Red** for negative changes (revenue down, churn up).
- Use Tailwind classes: `text-green-600` / `text-red-600`.

```jinja2
<span class="{{ 'text-green-600' if delta >= 0 else 'text-red-600' }}">
  {{ "{:+.1f}%".format(delta * 100) }}
</span>
```

---

## 5. Common Pitfalls

- **Float arithmetic on money**: Never do it. Always store and compute in
  cents, convert to dollars only at display time.
- **Timezone confusion**: Financial reports must use a consistent timezone.
  Default to UTC unless the user specifies a reporting timezone.
- **MRR vs. revenue**: MRR is a snapshot of recurring subscription value.
  Revenue is what was actually invoiced and paid. Do not mix them.
- **Churn denominator**: Use the customer count at the **start** of the
  period, not the end. Using the end count under-reports churn.
- **Annualizing monthly data**: Only annualize full months. If the current
  month is partial, exclude it or clearly label it as a projection.
