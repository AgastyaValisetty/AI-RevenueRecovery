# Data_Gen — XGBoost training data builder

`generate_data.py` reads the live `revenue_recovery` PostgreSQL database and emits a single CSV (`out/xgboost_training.csv`) where **each row = one RETRY decision** and **the label = whether the underlying payment settled within 72 hours**.

No files under `services/` are modified. Only this folder is touched.

---

## Run

```bash
# Make sure the stack is running (PostgreSQL must be reachable).
python master.py                 # in another terminal — boots postgres + 3 services

# Generate the dataset.
cd Data_Gen
python generate_data.py
```

Output: `Data_Gen/out/xgboost_training.csv`.

---

## Configuration

Edit the top of `generate_data.py`:

| Constant | Default | Meaning |
|---|---|---|
| `N_ROWS` | `10_000` | Cap on output rows. If the DB has fewer RETRY rows, you get fewer rows. |
| `RECOVERY_WINDOW_HOURS` | `72` | Ground-truth label window after each RETRY's `scheduled_for`. |
| `BALANCE_LOOKBACK_DAYS` | `60` | (Reserved — currently unused; history lookback is fixed at 30d.) |
| `BATCH_SIZE` | `500` | Rows per DB roundtrip for balance/label queries. |
| `PG_DSN` | env `PG_DSN` or `postgresql+psycopg2://simulator:simulator_dev@localhost:5433/revenue_recovery` | Database connection string. |
| `OUTPUT_PATH` | `Data_Gen/out/xgboost_training.csv` | Where to write the CSV. |

Override the DSN at runtime with the `PG_DSN` env var:

```bash
PG_DSN='postgresql+psycopg2://user:pass@host:5432/db' python generate_data.py
```

---

## Output schema

Column order in the CSV is fixed (see `OUTPUT_COLUMNS` in the script):

### Label
- `recovered` (0/1) — was there a `PAYMENT_SETTLED` ledger entry with the right `from_account_id` and `amount` in `(scheduled_for, scheduled_for + 72h]`?
- `days_to_recovery` (float, NaN if not recovered) — `first_settled - scheduled_for` in days.
- `audit_event_id` — the `recovery_actions.action_id` UUID (one row per RETRY).
- `run_id` — the simulation run UUID the RETRY came from.
- `engine_type` — `AI_AGENT` (SARA), `BASELINE`, or `UNKNOWN`.

### Customer features (point-in-time at retry decision)
- `customer_id`, `customer_age`, `customer_age_group`, `customer_income_bracket`, `customer_employment_type`
- `customer_salary_inr`, `customer_salary_deposit_day`, `customer_salary_deposit_hour`
- `customer_spending_profile_category`

### Customer history (30-day lookback pre-decision)
- `num_retries_last_30d`, `num_recovered_retries_last_30d`
- `customer_historical_success_rate` (NaN if no history)
- `customer_historical_mean_recovery_hours` (NaN if no successes)

### Balance / affordability (snapshot at decision time)
- `current_balance_inr` — net of all ledger debits/credits ≤ `scheduled_for` for the person's primary account.
- `balance_to_amount_ratio` — `current_balance / amount` (NaN if amount is zero).

### Salary timing
- `hours_until_next_salary` — hours from `scheduled_for` to the next projected salary credit (NaN if person has no salary schedule).

### Current transaction
- `amount_inr`, `original_failure_code`, `failure_category` (one of `CUSTOMER_STATE / BANK_DECLINE / INFRASTRUCTURE / MERCHANT_CONFIG`), `payment_method`.

### Merchant
- `merchant_id`, `merchant_type`.

### Temporal (at decision time)
- `decision_hour_utc`, `decision_day_of_week` (0 = Monday), `is_weekend`, `is_peak_hour` (18:00–22:00 UTC).

### Retry state
- `retry_number`, `days_since_original_failure` (from `recovery_actions.metadata_json.failure_timestamp`).

### Subscription (if applicable)
- `is_subscription` (True if the intent is tied to a subscription)
- `num_consecutive_sub_failures`

### Bank/rail
- `bank_state` — `NORMAL / PEAK / DEGRADED / OUTAGE` at the time of the original failure (from `recovery_actions.metadata_json`).

### SARA-only (NULL for baseline rows)
- `sara_estimated_recovery_prob` — the `expected_value.recovery_probability` SARA wrote into the audit trail.
- `sara_enpv_inr` — SARA's expected net present value (`expected_value.expected_net_value`).
- `sara_idempotency_key` — the audit row's idempotency key (for traceability).

---

## Sanity-check the output

```python
import pandas as pd
df = pd.read_csv("Data_Gen/out/xgboost_training.csv")
print(df.shape)
print(df["recovered"].value_counts())
print(df.isna().sum().sort_values(ascending=False).head(10))
print(df.head())
```

Expected:
- ~7k–10k rows (whatever is in `recovery_actions` for `action_type='RETRY'`).
- ~12–20 % positive label rate (matches the user's earlier observation: 1255 / 7859 ≈ 16 %).
- `sara_*` columns are NaN for baseline rows, populated for `AI_AGENT` rows.

---

## Where the data comes from

The script is read-only and touches these existing tables:

| Table | Use |
|---|---|
| `recovery_actions` | one row per training example |
| `payment_intents` | join on `intent_id` for `person_id`, `merchant_id`, `amount`, `payment_method`, `related_subscription_id` |
| `persons` | customer demographics + `primary_account_id` |
| `merchants` | merchant type |
| `subscriptions` | consecutive failures (LEFT JOIN on `payment_intents.related_subscription_id`) |
| `ledger_entries` | balance snapshot + 72h settlement label |
| `audit_events` | SARA's `decision_json` (recovery probability, ENPV) |
| `baseline_audit_events` | tag baseline rows for `engine_type='BASELINE'` |

The mapping `failure_code → failure_category` is taken from `services/people_service/app/failure_model.py` (the taxonomy the existing services already use), so downstream models stay consistent with SARA's own categorisation.