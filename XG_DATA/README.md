# XG_DATA — XGBoost training pipeline for SARA recovery prediction

This folder is a **standalone** training pipeline for predicting the probability
that a SARA Smart-Agent retry will succeed, plus the Expected Net Present
Value (ENPV) of attempting the retry.

It does NOT modify any file under `services/` — it drives the live SARA
simulation, reads the PostgreSQL database, and writes two CSV files + one
XGBoost model file.

## Files

| File | Role |
|---|---|
| `build_training_table.py` | Step 1: simulation → `sara_recovery_training.csv` |
| `train_xgb_model.py`      | Step 2: CSV → `sara_recovery_scored.csv` + `xgb_model.json` |
| `enpv.py`                 | ENPV formula + tunable cost constants |
| `feature_store.py`        | Shared feature engineering helpers (mirrored from `failure_model.py` + `sim_calibration.json`) |
| `requirements_xgdata.txt` | `pip install -r XG_DATA/requirements_xgdata.txt` |

Generated outputs (gitignored — produced by running the pipeline):

- `sara_recovery_training.csv` — one row per **original** failed transaction
  with features + ground-truth label.
- `sara_recovery_scored.csv` — same rows plus `predicted_probability_of_recovery`
  and `enpv`.
- `xgb_model.json` — portable XGBoost model.

## End-to-end usage

From the repo root (`D:\Work\AI-RevenueRecovery`):

```bash
# 1. Install XG_DATA extras (SARA service deps already installed by master.py)
pip install -r XG_DATA/requirements_xgdata.txt

# 2. Boot the SARA stack (postgres + 3 services)
python master.py

# 3. Wait until the API responds, then build the training CSV
python XG_DATA/build_training_table.py \
    --people 100 --days 365 --seed 42
#   → writes XG_DATA/sara_recovery_training.csv

# 4. Train XGBoost + write predicted_probability_of_recovery + enpv
python XG_DATA/train_xgb_model.py
#   → writes XG_DATA/sara_recovery_scored.csv + XG_DATA/xgb_model.json
```

Both scripts accept CLI flags — run with `--help` for the full list. The
most useful ones:

```bash
# Reuse an already-running simulation, just re-query the DB:
python XG_DATA/build_training_table.py --skip-run

# Tweak model hyperparameters:
python XG_DATA/train_xgb_model.py --max-depth 8 --learning-rate 0.03
```

## What gets written to the CSV

**One row per original failed payment attempt.** Retries (later attempts
on the same `intent_id`) are NOT separate rows — they're aggregated into
recovery-side columns (`num_retries_taken`, `time_to_recover_hours`,
`first_retry_outcome`).

### Identifier columns (kept for traceability, dropped before training)

`attempt_id`, `intent_id`, `person_id`, `merchant_id`,
`source_account_id`, `destination_account_id`, `correlation_id`,
`bank_id`, `bank_name`, `related_subscription_id`, `simulation_timestamp`,
`last_failure_ts`, `next_billing_date`.

### Raw feature columns

- **From-account (person):** `current_balance`, `salary`, `salary_deposit_day`,
  `payment_preferences_json` (expanded into `upi_pref`/`card_pref`/`netbanking_pref`)
- **To-account (merchant):** `merchant_type`, `billing_cycle`,
  `subscription_consecutive_failures`, `subscription_amount`,
  `days_until_next_billing`
- **Transaction:** `amount`, `payment_method`, `failure_code`, `failure_reason`,
  `bank_state`
- **History (30-day rolling):** `prev_failures_30d`, `prev_successes_30d`,
  `prev_failures_same_method_30d`, `last_failure_ts`

### Derived feature columns (computed in `feature_store.py`)

- **Balance:** `balance_margin` (= `current_balance / amount`, clipped to [0, 5]),
  `is_low_balance` (1 if `current_balance < 2000`)
- **Time:** `hour_of_day`, `is_peak_hour` (1 if 18 ≤ hour ≤ 22), `day_of_week`,
  `day_of_month`, `is_salary_day` (1 if day ∈ {1..5}), `simulation_day`,
  `days_since_last_salary`
- **Amount bucket:** `amount_bucket` ∈ {`low`, `medium`, `high`, `luxury`}
  (boundaries 0–2k / 2k–8k / 8k–25k / 25k+)
- **Bank/rail:** `method_base_rate`, `bank_state_multiplier`,
  `is_degraded_or_outage` (1 if state ∈ {DEGRADED, OUTAGE})
- **Failure:** `failure_category` ∈ {CUSTOMER_STATE, BANK_DECLINE,
  INFRASTRUCTURE, MERCHANT_CONFIG}
- **Subscription:** `is_subscription`, `subscription_billing_cycle` (MONTHLY /
  ONE_TIME)
- **History aggregation:** `recovery_rate_30d` (NaN → 0.5),
  `days_since_last_failure` (-1 if no prior failure)
- **One-hot variants** of every categorical column (e.g. `payment_method_UPI`,
  `payment_method_CARD`, `bank_state_NORMAL`, `failure_category_INFRASTRUCTURE`,
  `day_of_week_mon`, …) — total ~75 columns after encoding.

### Target / label columns

- `ground_truth_recovered` ∈ {0, 1} — 1 iff at least one
  `recovery_actions` row exists for this `intent_id` with
  `outcome = 'SUCCESS'` and `action_type = 'RETRY'`.
- `num_retries_taken` — count of SARA retry actions on this intent.
- `time_to_recover_hours` — float, time from original failure to first
  successful retry's `executed_at`; NaN if never recovered.
- `first_retry_outcome` — string (SUCCESS / FAILED / STOPPED / PENDING / UNKNOWN).

### Model output columns (added by `train_xgb_model.py`)

- `predicted_probability_of_recovery` — XGBoost regressor output, clipped
  to [0, 1].
- `enpv` — computed via `enpv.compute_enpv(prob, amount)`.

## ENPV formula

```python
# enpv.py
ENPV = P_hat * amount
     - RETRY_COST          # 2.50 INR
     - INCENTIVE_COST      # 0 (SARA does not yet emit incentives)
     - CHANNEL_COST        # 0 (SARA does not yet send notifications/links)
     - FRICTION_PENALTY    # 0 (placeholder for customer-annoyance cost)
     - RISK_PENALTY        # 0 (placeholder for fraud/dispute risk)
```

Tune any of the five cost constants in `enpv.py`. They are `Decimal` so
amount math stays exact.

## Where the constants come from

`feature_store.py` deliberately re-declares (rather than imports from)
the simulation's source of truth so XG_DATA stays standalone. The mirror
sources are:

- **Failure rates / bank-state multipliers** — `services/people_service/app/failure_model.py`
  (`BASE_FAILURE_RATE`, `STATE_MULTIPLIERS`)
- **Peak-hour window (18–22)** — same file, `failure_probability()`
- **Low-balance threshold (₹2000)** — `services/people_service/app/sim_calibration.json`
  (`spending.low_balance_threshold`)
- **Salary days (1–5)** — `sim_calibration.json::salary.deposit_days_range`
- **Amount bucket boundaries** — `sim_calibration.json::ecommerce.order_value_dist`
- **Failure-code → category map** — `failure_model.py::FAILURE_TYPES`

If any of those change upstream, update the mirror in `feature_store.py`
to match.

## Expected dataset shape

For 100 people × 365 days with the current failure model (~6% base rate
× bank-state/amount/balance/peak/load multipliers), expect:

- **Total original failed transactions:** a few hundred to ~2000 rows
- **Recovered fraction:** ~50–80% (SARA's last 720h parallel run: 82/107
  ≈ 76.6%)
- **Final column count:** ~75–90 (depending on how many one-hot variants
  actually fire)

If `ground_truth_recovered` ends up all-zero, the simulation produced no
successful recoveries — re-run with more days / people.

## Verification checklist

After running the pipeline:

```bash
# CSV is non-empty and has both labels
python -c "import pandas as pd; df = pd.read_csv('XG_DATA/sara_recovery_training.csv'); \
print(df.shape, df['ground_truth_recovered'].value_counts().to_dict())"

# Scored CSV has the new columns
python -c "import pandas as pd; df = pd.read_csv('XG_DATA/sara_recovery_scored.csv'); \
print('predicted_probability_of_recovery:', df['predicted_probability_of_recovery'].notna().sum()); \
print('enpv:', df['enpv'].notna().sum())"

# Model reloads cleanly
python -c "import xgboost as xgb; m = xgb.XGBRegressor(); m.load_model('XG_DATA/xgb_model.json'); print('OK')"

# ENPV unit check
python -c "from XG_DATA.enpv import compute_enpv; from decimal import Decimal; \
print(compute_enpv(0.5, Decimal('1000')))"   # → 497.50
```

## Sanity checks (the script prints them automatically)

`train_xgb_model.py` prints:

- Train and eval metrics: **AUC**, **log-loss**, **Brier score**, mean
  predicted probability.
- Top-10 feature importances (gain).

A reasonable model on this dataset should hit AUC > 0.55 and Brier
< 0.25. If you see AUC < 0.55, the dataset is too small (run more days
or more people) or the failure context isn't varying enough (rerun with
a different seed).

## Wiring into the SARA retry ledger (next step, not in this pipeline)

The user wants `probability` and `enpv` to show in the SARA retry ledger
(see `dummy-frontend-2/src/components/SaraAttemptsView.jsx`). This task
ships the CSV ready, but exposing the predictions in the live UI is a
follow-up:

**Option A — new API endpoint:**

Add `GET /api/recovery/predictions` to `services/people_service/app/api.py`
that joins `recovery_actions` with `predicted_probability_of_recovery`
and `enpv` from `sara_recovery_scored.csv` (or a Postgres table mirror).

**Option B — embed the model in the service:**

Move `xgb_model.json` into `services/people_service/app/recovery/` and
load it at service start. Score on demand per `/api/recovery/actions`.

**Option C — nightly batch + cached CSV:**

A cron-driven mirror of `sara_recovery_scored.csv` into a Postgres table,
read by the existing `/api/recovery/actions` endpoint.

The training pipeline itself doesn't depend on which option is chosen.

## Troubleshooting

- **`psycopg2.OperationalError: could not connect`** — `master.py` not
  running, or `DB_HOST`/`DB_PORT` env vars not matching. Defaults are
  `localhost:5433`.
- **`404 from /api/simulation/run`** — `master.py` booted the wrong
  service on port 8000. Check `master.py::SERVICES` ports (people=8000).
- **`ground_truth_recovered` column missing** — the SQL query's
  `recovery_actions` join returned nothing. Check that SARA actually
  emitted retries (try `GET /api/recovery/metrics`).
- **`ModuleNotFoundError: No module named 'xgboost'`** — run
  `pip install -r XG_DATA/requirements_xgdata.txt`.

## What this pipeline does NOT do

- Modify anything under `services/` or `dummy-frontend-2/`.
- Train on multi-bank data (only RupeeBank today; schema is ready for
  more banks when added).
- Update the live SARA retry ledger UI (future hook — see above).
- Calibrate `FRICTION_PENALTY` / `RISK_PENALTY` (currently 0; the
  Smart Agent's `customer_fatigue_score` and `fraud_or_dispute_flags`
  could feed in once those engines exist).
- Run hyperparameter search or cross-validation (one 80/20 split).