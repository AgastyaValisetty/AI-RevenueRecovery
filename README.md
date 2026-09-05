# 💰 AI-RevenueRecovery

A distributed microservices ecosystem that **simulates a payment platform end-to-end** (people → merchants → gateway → bank) and runs an **AI recovery agent (SARA)** on top of it to recover failed subscription/one-time payments.

The stack models realistic payment failure modes (network errors, bank declines, insufficient funds, expired cards, fraud blocks, etc.) and lets a Smart Recovery Agent decide *what to do* about each failed intent — retry, send a payment link, send a notification, or stop — using an **Expected Net Present Value (ENPV)** calculation.

---

## 🧭 TL;DR — start it

**Just run one command:**

```bash
docker compose up --build
```

That brings up PostgreSQL + the 3 backend services + the Vite/React frontend, runs `pip install -r requirements.txt` inside every backend on **every** `up`, and auto-seeds 100 simulated people with `seed=42` so the UI is populated the moment it loads. No need to start each service by hand.

Open the app: **http://localhost:5173**

Override the seed:

```bash
SEED=7 docker compose up --build
PEOPLE_COUNT=250 docker compose up --build
```

Or change the seed from the UI — every screen that runs a simulation (Simulation Runner, Comparison, Smart Agent) has a Seed input.

Hit any service directly:

| Service        | URL                                    |
|----------------|----------------------------------------|
| **Frontend (UI)**    | `http://localhost:5173`                       |
| People         | `http://localhost:8000/api/simulation/status` |
| LazerPay       | `http://localhost:8001/api/status`     |
| RupeeBank      | `http://localhost:8002/api/status`     |
| Postgres (docker) | `localhost:5433` (`simulator` / `simulator_dev` / `revenue_recovery`) |

`Ctrl+C` cleanly tears down everything. `docker compose down -v` also wipes the Postgres volume (fresh DB on next `up`). See [🚀 Startup commands](#-startup-commands) for the full list of options and the `master.py` / manual alternatives.

---

## 🏗️ Architecture

```
                ┌────────────────────┐
                │   People Service   │  port 8000
                │   (Orchestrator +  │  - generates people, merchants, subscriptions
                │    Simulation)     │  - hourly loop: salary → spend → pay
                └─────────┬──────────┘  - calls LazerPay for every payment
                          │ HTTP
                          ▼
                ┌────────────────────┐
                │   LazerPay         │  port 8001
                │   (Gateway)        │  - routes to bank, idempotency, retries
                └─────────┬──────────┘  - writes PAYMENT_SETTLED / PAYMENT_FAILED ledger entries
                          │ HTTP
                          ▼
                ┌────────────────────┐
                │   RupeeBank        │  port 8002
                │   (Bank simulator) │  - balance check, probabilistic auth
                └────────────────────┘  - state machine: NORMAL → PEAK → DEGRADED → OUTAGE
                          │
                          ▼
                ┌────────────────────┐
                │  PostgreSQL 15     │  port 5433 (docker)
                │  (shared ledger)   │  - banks, persons, accounts, merchants,
                └────────────────────┘    products, subscriptions, payment_intents,
                                          payment_attempts, ledger_entries,
                                          recovery_actions, audit_events, ...
```

All three services share the **same PostgreSQL schema** (People owns DDL; Bank/LazerPay read/write compatible ORM mappings). Balances are **derived** from `ledger_entries` — never stored as a column.

On top of that sits **SARA — Smart Agent for Revenue Automation** (lives inside People Service), which picks recovery actions for every failed intent and compares against a `BaselineRecoveryEngine` in parallel experiments.

---

## 🔌 Port assignments

| Service           | Port  | Owner                | Depends on     |
|-------------------|-------|----------------------|----------------|
| **frontend**       | 5173  | Vite/React UI (docker) | people_service   |
| **people_service** | 8000  | simulation + SARA    | postgres, lazerpay |
| **lazerpay_service** | 8001 | payment gateway      | postgres, bank     |
| **bank_service** (RupeeBank) | 8002 | bank simulator | postgres           |
| **postgres**       | 5433  | shared DB (docker)   | —                |

The bank ↔ lazerpay URL is wired through the `BANK_URL` env var (`http://bank_service:8002` in docker, `http://localhost:8002` in `master.py`). People → LazerPay uses `LAZERPAY_URL`. The frontend's Vite proxy points at `VITE_API_TARGET` (`http://people_service:8000` in docker, `http://localhost:8000` for native `npm run dev`).

---

## 🚀 Startup commands

### ✅ One command — `docker compose up --build` (use this)

This is the **recommended way to run the whole stack**. PostgreSQL + the 3 backends + the React/Vite frontend all come up together, and the `auto-seed` sidecar populates 100 simulated people with `seed=42` so the UI shows real data the moment it loads. No need to start each service by hand.

```bash
# from the repo root
docker compose up --build                  # postgres + 3 backends + frontend, auto-seed=42

# common overrides
SEED=7 docker compose up --build           # different random seed
PEOPLE_COUNT=250 docker compose up --build # seed 250 people instead of 100
docker compose down -v                     # tear down + wipe DB volume (fresh start next time)
docker compose logs -f people_service      # tail logs of one service
```

What happens under the hood:
- Each backend container's `command:` wrapper runs `python /tools/pip_install.py` before uvicorn, so `pip install -r requirements.txt` runs on **every** `up` — no stale-image surprises.
- The frontend is a `node:20-alpine` container running `npm run dev -- --host 0.0.0.0 --port 5173`. Its Vite proxy points at `http://people_service:8000` (via `VITE_API_TARGET`) so `/api` calls hit the docker DNS name.
- The `auto-seed` sidecar waits for `people_service` to be ready, then calls `POST /api/simulation/run` with the configured seed. It's idempotent — on subsequent `up`s it sees the population already exists and exits without re-seeding.

Open `http://localhost:5173` once `up` finishes — the dashboard, ledger, recovery, and comparison views are already populated. To change the seed from the UI, every screen that runs a simulation (Simulation Runner, Comparison, Smart Agent) has a Seed input — edit it and click Run.

---

### 🪟 Alternative: `master.py` (native, no Docker for backends)

> If you specifically want to run the FastAPI services on the host (no Docker for the backends — Postgres still runs in Docker), `master.py` does it in one command on Windows. Most people should not need this — prefer `docker compose up --build` above.

```bash
python master.py                    # boot + seed 100 people
python master.py --init 250         # boot + seed 250 people
python master.py --init 0           # boot only, no seeding
```

`master.py` automatically:
- Starts the `postgres` docker compose service if it's not already up on `5433`
- Launches each FastAPI service in its own subprocess with the right env vars
- On Windows, binds them into a Job Object so Ctrl+C / process death kills all children
- Seeds an initial simulation run via `POST /api/simulation/run`

For the frontend under `master.py`, open a separate terminal and run `cd Frontend && npm install && npm run dev` — it will connect to `http://localhost:8000` by default.

---

### 🛠 Manual (for debugging individual services)

```bash
# terminal 1
cd services/bank_service && uvicorn app.main:app --port 8002

# terminal 2
cd services/lazerpay_service && \
  BANK_URL=http://localhost:8002 LAZERPAY_PORT=8001 \
  uvicorn app.main:app --port 8001

# terminal 3
cd services/people_service && \
  LAZERPAY_URL=http://localhost:8001 \
  uvicorn app.main:app --port 8000
```

Use this only when you need to attach a debugger to a single service. The `docker compose up --build` path covers the normal case.

---

## 📡 API Endpoints

All endpoints below are **FastAPI**; JSON in / JSON out. Times are ISO-8601; money is `Decimal` serialized as strings to preserve precision.

### People Service — `http://127.0.0.1:8000/api`

#### Simulation lifecycle

| Method | Path | Body / Params | Purpose |
|---|---|---|---|
| `POST` | `/simulation/run` | `{"people_count": 100, "days": 0, "hours": 0, "seed": 42, "enable_recovery": true}` | Initialize + run a simulation. Returns a `summary` block with `run_id`, people count, and the orchestrator state. |
| `GET` | `/simulation/status` | — | Current orchestrator summary (clock, counters, etc.). |
| `GET` | `/simulation/runs` | `?limit=50` | Recent simulation runs. |
| `GET` | `/simulation/runs/{run_id}` | — | Single run detail (config snapshot, hours run, status). |
| `POST` | `/simulation/nuke` | — | **Drop ALL tables and recreate empty** — also wipes parallel-experiment schemas and report files. |

#### People, merchants, ledger, subscriptions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/people` | List all people with balances. |
| `GET` | `/people/{person_id}` | One person (profile + balance). |
| `GET` | `/merchants` | List merchants. |
| `POST` | `/merchants` | `{"name": "...", "merchant_type": "...", "products": [{"name": "...", "price": "99.00", "product_type": "SUBSCRIPTION"}]}` — add merchant + products (also persists to `merchant_catalog.json`). |
| `GET` | `/ledger` | `?limit=500` — recent ledger entries. |
| `GET` | `/subscriptions` | `?limit=500` — recent subscriptions. |

#### Payments

| Method | Path | Body / Params | Purpose |
|---|---|---|---|
| `POST` | `/payments/process` | `{"person_id", "merchant_id", "product_id", "amount", "payment_method", "related_subscription_id?", "source_account_id?", "simulation_timestamp?"}` | Calls LazerPay, returns `{attempt_id, status, failure_code, failure_reason}`. |
| `POST` | `/payments/process-all` | — | Drains every `PENDING` `PaymentIntent` through LazerPay; falls back to inline settlement if LazerPay is down. |
| `GET` | `/payments/failures` | — | Failure analytics: rate, breakdown by reason (with category), recent failures. |
| `GET` | `/payments/{attempt_id}` | — | Look up attempt status from the ledger. |

#### Revenue analytics

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/revenue` | Aggregate revenue: total GMV, LazerPay's 2% cut, per-merchant lifetime + monthly + recent transactions. |
| `GET` | `/revenue/{merchant_id}` | Single-merchant revenue detail + every settled transaction. |

> **LazerPay fee**: flat **2%** of every settled transaction, taken from the merchant side (`LAZERPAY_FEE_RATE = "0.02"` in `domain.py`).

#### Recovery (baseline + SARA)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/recovery/actions` | `?limit=500&outcome=&action_type=&engine_type=` — list of `RecoveryAction` records. |
| `GET` | `/recovery/actions/intent/{intent_id}` | Full recovery history for one failed intent. |
| `GET` | `/recovery/metrics` | `?run_id=&engine_type=` — aggregated metrics (counts, GMV recovered, rates, breakdowns). |
| `GET` | `/recovery/runs` | Recent recovery runs (strategy, seed, outcomes). |
| `GET` | `/recovery/audit/{case_id}` | Immutable audit trail for one recovery case. |
| `GET` | `/recovery/insights/rail-health` | `?method=` — current rail health per payment method. |

#### SARA (Smart Recovery Agent) endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/recovery/smart/run` | `{"intent_ids"?: [], "seed"?: 42}` — trigger SARA on failed intents; returns decisions + explanations. |
| `GET` | `/recovery/smart/cases` | `?limit=100&status=` — ranked action queue (cases awaiting action). |
| `GET` | `/recovery/smart/cases/{case_id}` | Full case detail: diagnosis, candidate ENPVs, policy checks, audit trail. |
| `POST` | `/recovery/smart/cases/{case_id}/simulate` | `{"scenarios"?: [...]}` — run counterfactual "what-if" scenarios, ranked by ENPV. |
| `POST` | `/recovery/smart/cases/{case_id}/approve` | Manually approve a recommended action (audit only in simulation mode). |

#### Experiments (baseline vs SARA)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/recovery/experiments/compare` | Paired experiment: baseline vs SARA on cloned DB state. |
| `POST` | `/recovery/experiments/parallel/run` | `?keep_schemas=true` — run **both engines in parallel on isolated PostgreSQL schemas** (identical seed). Returns lift report. |
| `GET` | `/recovery/experiments/parallel/list` | `?limit=20` — list saved parallel experiment reports. |
| `GET` | `/recovery/experiments/parallel/{experiment_id}/cases` | `?engine=baseline|smart&limit=100&status=` — cases from a preserved schema. |
| `GET` | `/recovery/experiments/parallel/{experiment_id}/metrics` | `?engine=baseline|smart` — lifetime metrics from a preserved schema. |
| `GET` | `/recovery/experiments/parallel/{experiment_id}/retries` | `?engine=&limit=` — RETRY actions enriched with ML `predicted_p_recovery` + `predicted_enpv`. |
| `GET` | `/recovery/experiments/parallel/{experiment_id}/cases/{case_id}` | Single case detail from preserved schema. |
| `GET` | `/recovery/experiments/parallel/{experiment_id}/audit` | Immutable audit stream for `baseline` or `smart`. |

#### ML inference

| Method | Path | Body | Purpose |
|---|---|---|---|
| `POST` | `/ml/predict` | `{"features": {"amount": 499, "retry_number": 1, "action_type": "RETRY", "payment_method": "UPI", "failure_code": "INSUFFICIENT_FUNDS", "customer_declined": false}}` | Predict `P(recovery)` and ENPV from the XGBoost model trained by `XG_DATA/train.py`. Returns `{has_model, p_recovery, enpv}` (or `null`s if model isn't trained). |

---

### LazerPay Service — `http://127.0.0.1:8001/api`

| Method | Path | Body / Params | Purpose |
|---|---|---|---|
| `GET` | `/status` | — | Gateway health: DB reachable, Bank reachable, pending attempts. |
| `POST` | `/payments/process` | `{intent_id, person_id, merchant_id, amount, payment_method, source_account_id?, simulation_timestamp?, correlation_id?}` | Process a payment. Lifecycle: `INITIATED → ROUTING → (AUTHORIZED → SETTLED | FAILED | UNKNOWN)`. |
| `POST` | `/payments/retry` | `{attempt_id, amount?, payment_method?, simulation_timestamp?, correlation_id?}` | Retry a failed/unknown attempt. Creates a NEW attempt with `attempt_number = original + 1`. |
| `GET` | `/payments/{attempt_id}` | — | Full attempt detail incl. all lifecycle timestamps + every attempt for the same intent. |
| `POST` | `/payments/send-link` | `{attempt_id, person_id?, payment_method?}` | Send a payment link to the customer (auditable, **does not charge**). |

Attempt status constants: `INITIATED`, `ROUTING`, `AUTHORIZED`, `SETTLED`, `FAILED`, `UNKNOWN`, `PENDING_LINK`.

Ledger event types emitted: `PAYMENT_SETTLED`, `PAYMENT_FAILED`, `PAYMENT_UNKNOWN`, `LINK_SENT`.

---

### RupeeBank Service — `http://127.0.0.1:8002/api`

| Method | Path | Body / Params | Purpose |
|---|---|---|---|
| `GET` | `/status` | — | Bank status: name, current state, success/failure rates, settlement account id, recent 1-min success/failure. |
| `POST` | `/authorize` | `{attempt_id, person_id, amount, payment_method, source_account_id, simulation_timestamp?, correlation_id?}` | Authorize a payment. Returns `{success, failure_code?, failure_reason?, response_time_ms, bank_state, source_balance, authorized_at, settlement_account_id?, unknown_outcome}`. |
| `POST` | `/bank-state` | `{state: "NORMAL" | "PEAK" | "DEGRADED" | "OUTAGE"}` | Manually transition bank state (testing). |

Bank state machine: `NORMAL → PEAK → DEGRADED → OUTAGE → NORMAL`, driven by recent transaction failure rate (see `BankStateMachine.bank_state_transition`). State multipliers applied to base `authorization_success_rate`: NORMAL=1.0, PEAK=2.0, DEGRADED=5.0, OUTAGE=50.0.

---

## 💡 Failure model (one-paragraph version)

`P(failure) = base_rate(method) × state_mult × amount_mult × balance_mult × time_mult × load_mult`, clamped to ≤ 0.9.

- **Base rates**: UPI 6%, CARD 6.5%, NETBANKING 6.28% (SBI/HDFC/Axis/ICICI/BOI average).
- **State multipliers**: PEAK 1.8×, DEGRADED 3.5×, OUTAGE 8×.
- When a payment fails, the **reason** is drawn from a calibrated composition split (`COMPOSITION` in `failure_model.py`): `NETWORK_ERROR 18%, ISSUER_DECLINE 14%, TIMEOUT 11%, LIMIT_EXCEEDED 8%, RISK_DECLINE 7%, EXPIRED_PAYMENT_METHOD 5%, AUTHENTICATION_FAILURE 4%, INVALID_DETAILS 3%, CANCELLED 2%, UNSUPPORTED_METHOD 1%` — plus a deterministic `INSUFFICIENT_FUNDS` bucket for real insolvency.

Failure taxonomy categories: `CUSTOMER_STATE` (insufficient funds, expired, auth, cancelled), `BANK_DECLINE` (issuer decline, limit, risk), `INFRASTRUCTURE` (network error, timeout, bank degraded), `MERCHANT_CONFIG` (invalid details, unsupported method).

---

## 🧮 ENPV — Expected Net Present Value

ENPV is the **decision currency** SARA uses to rank candidate recovery actions. For each legal action, the calculator (`services/people_service/app/recovery/smart_agent/action_value.py`) computes:

```
ENPV(action) = P(recovery | context, action) × amount
             − retry_cost
             − incentive_cost
             − channel_cost
             − friction_penalty
             − risk_penalty
```

Only candidates with **ENPV > 0** are considered for execution; the highest-ENPV action wins (subject to policy gates).

### The components

| Term | Meaning | Default (INR) |
|---|---|---|
| `P(recovery \| context, action)` | Probability the action succeeds in recovering the payment, conditioned on the case features (method, amount, balance, bank state, failure code, retry count, fatigue, decline history). | computed |
| `amount` | Revenue at risk for the case. | — |
| `retry_cost` | Gateway fee per retry attempt. | `2.50` |
| `link_cost` | Payment-link generation + delivery. | `1.00` |
| `notification_cost` | SMS / push notification. | `0.50` |
| `incentive_cost` | Merchant-funded incentive (off by default). | `0` |
| `friction_penalty` | Customer-annoyance cost, scaled by `customer_fatigue_score`. | up to `5.00` |
| `risk_penalty` | Fraud / duplicate / outage risk added when retrying on a degraded rail or after a bank decline. | up to `~7.00` |

### P(recovery) per action type

- **`RETRY`** — uses `failure_model.failure_probability(...)` adjusted by retry number. Transient infrastructure failures get a `min(0.95, 0.85 + 0.05 × (retry_n − 1))` curve. Issuer declines decay as `base × 0.4 × 0.6^(retry_n − 1)`. Insufficient-funds retries are reserved for the next post-salary window and get a `max(0.70, …)` floor.
- **`SEND_PAYMENT_LINK`** — `behavior_profile.response_rate`, then multiplied by ×8 for rail/method failures, ×3 for customer-state issues (×2 if balance still thin), ×0.6 for transient, ×1.5 if balance is sufficient, ×0.1 if the customer previously declined, ×0.3 if fatigue > 70. Capped at 0.95.
- **`SEND_NOTIFICATION`** — 50% of `SEND_PAYMENT_LINK`'s probability (softer nudge, lower friction cost).
- **`STOP`** — always 0 (the policy validator may pick STOP when every other candidate has ENPV ≤ 0).

### Where it shows up

- `/recovery/smart/cases/{case_id}` returns the **per-action ENPV** the agent picked from.
- `/recovery/smart/cases/{case_id}/simulate` runs **counterfactual scenarios** (different delays, action types) and returns them ranked by ENPV.
- `predicted_enpv` from `POST /ml/predict` is the XGBoost model's estimate of ENPV for a candidate retry, trained on `sara_recovery_actions.csv` (see `XG_DATA/train.py`).

---

## 🗃️ Database tables (shared PostgreSQL schema)

Owner is **People Service** (creates on startup); Bank & LazerPay use `__table_args__ = {"extend_existing": True}` to map to the same physical tables.

### Core entities (created by People Service)

#### `banks`
| Column | Type | Notes |
|---|---|---|
| `bank_id` | UUID PK | |
| `name` | VARCHAR(64) UNIQUE | e.g. `"RupeeBank"` |
| `authorization_success_rate` | NUMERIC(6,2) | % success, e.g. `99.10` |
| `timeout_rate` | NUMERIC(6,2) | % that time out |
| `issuer_decline_rate` | NUMERIC(6,2) | % issuer declines |
| `network_error_rate` | NUMERIC(6,2) | % network errors |
| `current_state` | VARCHAR(32) | `NORMAL` / `PEAK` / `DEGRADED` / `OUTAGE` |
| `state_multipliers_json` | JSONB | state → multiplier |
| `settlement_account_id` | VARCHAR(64) NULL | non-UUID id written by Bank Service |
| `created_at` | TIMESTAMPTZ | |

#### `bank_accounts`
| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID PK | |
| `person_id` | UUID NULL | FK → `persons.person_id` (deferrable) |
| `bank_id` | UUID | FK → `banks.bank_id` |
| `created_at` | TIMESTAMPTZ | |

> Balance is **not** stored here — it's computed by summing `ledger_entries` per account.

#### `persons`
| Column | Type | Notes |
|---|---|---|
| `person_id` | UUID PK | |
| `name` | VARCHAR(128) | |
| `age` | INT | |
| `salary` | NUMERIC(12,2) | |
| `salary_deposit_day` | INT | day-of-month for salary credit |
| `salary_deposit_hour` | INT (default 9) | hour-of-day |
| `spending_profile_category` | VARCHAR(64) | `student` / `young_professional` / `family` / `high_income` / `retired` |
| `spending_profile_json` | JSONB | detailed spend mix |
| `payment_preferences_json` | JSONB | method preferences |
| `income_bracket` | VARCHAR(32) | `low` / `lower_middle` / `middle` / `upper_middle` / `high` |
| `age_group` | VARCHAR(32) | `18-24` / `25-34` / ... |
| `employment_type` | VARCHAR(32) | `salaried` / `self_employed` / `student` / ... |
| `primary_bank_id` | UUID | FK → `banks.bank_id` |
| `primary_account_id` | UUID | FK → `bank_accounts.account_id` (deferrable) |
| `created_at` | TIMESTAMPTZ | |

#### `merchants`
| Column | Type | Notes |
|---|---|---|
| `merchant_id` | UUID PK | |
| `name` | VARCHAR(64) | |
| `merchant_type` | VARCHAR(32) | `SUBSCRIPTION` / `ECOMMERCE` / ... |
| `settlement_bank_id` | UUID | FK → `banks.bank_id` |
| `created_at` | TIMESTAMPTZ | |

#### `products`
| Column | Type | Notes |
|---|---|---|
| `product_id` | UUID PK | |
| `merchant_id` | UUID | FK → `merchants.merchant_id` |
| `name` | VARCHAR(128) | |
| `price` | NUMERIC(12,2) | |
| `product_type` | VARCHAR(32) | `SUBSCRIPTION` / `ONE_TIME` |
| `billing_cycle` | VARCHAR(16) NULL | `MONTHLY` / `YEARLY` (for subscriptions) |
| `created_at` | TIMESTAMPTZ | |

#### `subscriptions`
| Column | Type | Notes |
|---|---|---|
| `subscription_id` | UUID PK | |
| `person_id` | UUID | FK → `persons.person_id` |
| `merchant_id` | UUID | FK → `merchants.merchant_id` |
| `product_id` | UUID | FK → `products.product_id` |
| `amount` | NUMERIC(12,2) | |
| `billing_cycle` | VARCHAR(16) | |
| `status` | VARCHAR(32) | `ACTIVE` / `CANCELLED` / ... |
| `next_billing_date` | DATE | |
| `last_successful_payment_date` | DATE NULL | |
| `consecutive_failures` | INT (default 0) | |
| `created_at` | TIMESTAMPTZ | |
| `cancelled_at` | TIMESTAMPTZ NULL | |

#### `payment_intents`
| Column | Type | Notes |
|---|---|---|
| `intent_id` | UUID PK | |
| `person_id` | UUID | FK → `persons.person_id` |
| `merchant_id` | UUID | FK → `merchants.merchant_id` |
| `product_id` | UUID | FK → `products.product_id` |
| `amount` | NUMERIC(12,2) | |
| `payment_method` | VARCHAR(32) | `UPI` / `CARD` / `NETBANKING` |
| `status` | VARCHAR(32) | `PENDING` / `SETTLED` / `FAILED` |
| `related_subscription_id` | UUID NULL | FK → `subscriptions.subscription_id` |
| `created_at` | TIMESTAMPTZ | |
| `expires_at` | TIMESTAMPTZ | |

Indexes: `status`.

#### `payment_attempts` *(shared between People & LazerPay)*
| Column | Type | Notes |
|---|---|---|
| `attempt_id` | VARCHAR(64) PK | e.g. `ATT_<12hex>` |
| `intent_id` | UUID | FK → `payment_intents.intent_id` |
| `attempt_number` | INT (default 1) | retry count for this intent |
| `person_id` | UUID | FK → `persons.person_id` |
| `merchant_id` | UUID | FK → `merchants.merchant_id` |
| `amount` | NUMERIC(12,2) | |
| `payment_method` | VARCHAR(32) | |
| `source_account_id` | UUID NULL | FK → `bank_accounts.account_id` |
| `destination_account_id` | UUID NULL | FK → `bank_accounts.account_id` |
| `idempotency_key` | VARCHAR(128) UNIQUE | format: `idem_<intent_id>_<n>` for first attempt, `idem_retry_<attempt_id>_<n>` for retries |
| `status` | VARCHAR(32) | `INITIATED` / `ROUTING` / `AUTHORIZED` / `SETTLED` / `FAILED` / `UNKNOWN` / `PENDING_LINK` |
| `failure_code` | VARCHAR(50) NULL | |
| `failure_reason` | TEXT NULL | |
| `related_attempt_id` | VARCHAR(64) NULL | FK → self (parent attempt) |
| `initiated_at` / `routed_at` / `authorized_at` / `settled_at` / `failed_at` / `unknown_at` | TIMESTAMPTZ NULL | lifecycle stamps |
| `bank_response_time_ms` | INT NULL | |
| `gateway_latency_ms` | INT NULL | |
| `bank_state` | VARCHAR(32) NULL | |
| `simulation_timestamp` | TIMESTAMPTZ NULL | |
| `correlation_id` | VARCHAR(64) NULL | also indexed |
| `retry_for_attempt_id` | VARCHAR(64) NULL | FK → self (the attempt this one retries) |
| `created_at` | TIMESTAMPTZ | |

Indexes: `status`, `failure_code`, `idempotency_key`, `correlation_id`.

#### `ledger_entries` *(shared; immutable source-of-truth)*
| Column | Type | Notes |
|---|---|---|
| `entry_id` | UUID PK | |
| `event_type` | VARCHAR(32) | `SALARY_DEPOSIT` / `LIVING_COST` / `PAYMENT_SETTLED` / `PAYMENT_FAILED` / `PAYMENT_UNKNOWN` / `ORDER_PURCHASE` / `INCOME_TAX` / `GST` / `LINK_SENT` |
| `from_account_id` | VARCHAR(64) NULL | |
| `to_account_id` | VARCHAR(64) NULL | |
| `amount` | NUMERIC(12,2) | |
| `related_attempt_id` | VARCHAR(64) NULL | FK → `payment_attempts.attempt_id` |
| `related_subscription_id` | UUID NULL | FK → `subscriptions.subscription_id` |
| `simulation_timestamp` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | |
| `metadata_json` | JSONB (default `{}`) | |

Indexes: `event_type`, `simulation_timestamp`, `from_account_id`, `to_account_id`.

---

### Recovery & simulation tracking (People Service owns)

#### `recovery_actions`
| Column | Type | Notes |
|---|---|---|
| `action_id` | UUID PK | |
| `run_id` | UUID NULL | FK → `simulation_runs.run_id` |
| `related_attempt_id` | VARCHAR(64) NULL | FK → `payment_attempts.attempt_id` |
| `payment_intent_id` | UUID NULL | FK → `payment_intents.intent_id` |
| `action_type` | VARCHAR(32) | `RETRY` / `SEND_PAYMENT_LINK` / `SEND_NOTIFICATION` / `STOP` |
| `reason` | TEXT NULL | |
| `schedule_reason` | TEXT NULL | |
| `scheduled_for` | TIMESTAMPTZ NULL | |
| `executed_at` | TIMESTAMPTZ NULL | |
| `outcome` | VARCHAR(32) NULL | `PENDING` / `SUCCESS` / `FAILED` / `UNKNOWN` / `STOPPED` |
| `cost` | NUMERIC(12,2) NULL | |
| `expected_recovery` | NUMERIC(12,2) NULL | |
| `retry_number` | INT NULL | 1, 2, 3, ... |
| `amount` | NUMERIC(12,2) NULL | original failed payment |
| `payment_method` | VARCHAR(32) NULL | |
| `failure_code` | VARCHAR(50) NULL | |
| `failure_reason` | TEXT NULL | |
| `retry_attempt_id` | VARCHAR(64) NULL | new attempt id from LazerPay |
| `customer_declined` | BOOL (default false) | |
| `metadata_json` | JSONB (default `{}`) | |
| `created_at` | TIMESTAMPTZ | |

Indexes: `related_attempt_id`, `payment_intent_id`, `outcome`, `scheduled_for`.

#### `simulation_runs`
| Column | Type | Notes |
|---|---|---|
| `run_id` | UUID PK | |
| `seed` | INT | for reproducibility |
| `config_snapshot` | JSONB | full config used |
| `people_count` | INT NULL | |
| `hours_run` | INT (default 0) | |
| `status` | VARCHAR(32) | `PENDING` / `RUNNING` / `COMPLETED` / `FAILED` |
| `error_message` | TEXT NULL | |
| `started_at` / `completed_at` / `created_at` | TIMESTAMPTZ | |

---

### Smart Agent (SARA) tables (People Service owns)

#### `customer_recovery_memory`
Per-customer memory for SARA's `memory.py` module.

| Column | Type | Notes |
|---|---|---|
| `person_id` | UUID PK | FK → `persons.person_id` |
| `preferred_channel` | VARCHAR(32) NULL | |
| `preferred_language` | VARCHAR(16) NULL | |
| `best_contact_window` | JSONB NULL | e.g. `{"start_hour": 18, "end_hour": 22}` |
| `fatigue_count` | INT (default 0) | |
| `last_message` | TEXT NULL | |
| `consent_status` | VARCHAR(32) (default `PENDING`) | `GRANTED` / `DENIED` / `PENDING` / `EXPIRED` |
| `contact_consent` | BOOL (default false) | |
| `last_interaction_at` | TIMESTAMPTZ NULL | |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

#### `promise_to_pay`
Records a customer's promise-to-pay lifecycle.

| Column | Type | Notes |
|---|---|---|
| `promise_id` | UUID PK | |
| `case_id` | UUID NOT NULL | agent-generated; not an FK to a `RecoveryCase` table |
| `person_id` | UUID | FK → `persons.person_id` |
| `amount` | NUMERIC(12,2) | |
| `due_at` | TIMESTAMPTZ | |
| `source` | VARCHAR(64) | `SIMULATED_RESPONSE` / `API` / `CHAT` |
| `confidence` | FLOAT (default 1.0) | 0–1 |
| `status` | VARCHAR(32) (default `ACTIVE`) | `ACTIVE` / `FULFILLED` / `MISSED` / `CANCELLED` |
| `created_at` / `fulfilled_at` | TIMESTAMPTZ | |

Indexes: `case_id`, `person_id`, `status`.

#### `audit_events` *(SARA — smart agent)*
Immutable audit trail of every smart-agent decision and execution.

| Column | Type | Notes |
|---|---|---|
| `event_id` | UUID PK | |
| `case_id` | UUID NULL | |
| `run_id` | UUID NULL | FK → `simulation_runs.run_id` |
| `timestamp` | TIMESTAMPTZ | |
| `agent_version` | VARCHAR(64) | |
| `policy_version` | VARCHAR(64) | |
| `actor` | VARCHAR(32) | `system` / `agent` / `human` |
| `event_type` | VARCHAR(64) | e.g. `decision`, `llm_diagnosis`, `execution` |
| `input_snapshot_hash` | VARCHAR(128) | |
| `evidence_refs` | JSONB (default `{}`) | |
| `decision_json` | JSONB (default `{}`) | |
| `policy_checks` | JSONB (default `{}`) | |
| `idempotency_key` | VARCHAR(128) NULL | indexed |
| `execution_result` | JSONB NULL | |
| `outcome` | VARCHAR(32) NULL | |

Indexes: `case_id`, `run_id`, `event_type`, `timestamp`.

#### `baseline_audit_events` *(Baseline engine — control)*
Same column shape as `audit_events`, but a **separate physical table** so control decisions can never be confused with SARA decisions when an experiment is reviewed.

---

### Bank Service-owned table

#### `bank_metrics` *(Bank Service only)*
Drives the bank state machine transitions.

| Column | Type | Notes |
|---|---|---|
| `metric_id` | VARCHAR(64) PK | UUID-string |
| `bank_id` | VARCHAR(64) | indexed |
| `timestamp` | TIMESTAMPTZ | indexed |
| `success` | INT | 0 or 1 |
| `response_time_ms` | INT (default 0) | |
| `outcome` | VARCHAR(32) (default `UNKNOWN`) | `SETTLED` / `FAILED` / `UNKNOWN` |

Indexes: `timestamp`, `(bank_id, timestamp)`, `outcome`.

---

### LazerPay Service-owned table

#### `idempotency_keys` *(LazerPay only)*
| Column | Type | Notes |
|---|---|---|
| `key` | VARCHAR(128) PK | the idempotency key |
| `attempt_id` | VARCHAR(64) UNIQUE | indexed — links key → attempt |
| `created_at` | TIMESTAMPTZ | |

---

## 🧩 Cross-service schema gotcha

`settlement_account_id` on `banks` is a **non-UUID string** like `"settlement-<hex12>"`. The People Service column is `VARCHAR(64)`; the Bank Service column is also `VARCHAR(64)`. If you see `InvalidTextRepresentation` or UUID-cast errors at boot, that's the cause — `master.py` and `docker-compose.yml` both wire the same DB user so this is consistent.

---

## 🛠️ Useful extras

- **Reset the world**: `POST http://127.0.0.1:8000/api/simulation/nuke` — drops everything (including parallel-experiment schemas), rebuilds a fresh orchestrator.
- **Run a parallel experiment from the UI**: `POST http://127.0.0.1:8000/api/recovery/experiments/parallel/run` with `{"people_count": 100, "hours": 24, "seed": 42}`. Pass `?keep_schemas=false` to auto-clean schemas.
- **Train the ENPV model**: `python XG_DATA/train.py` (separate, optional — produces a model `infer.predict` will pick up).
- **Logs**: `master.py` prefixes each line with `[people]`, `[bank]`, `[lazerpay]`, `[postgres]` so a single terminal shows everything.

---

## 📚 Related docs

- `ARCHITECTURE.md` — full microservices specification with state diagrams.
- `UML_Design.md` — UML diagrams referenced by the architecture.
- `services/people_service/app/recovery/smart_agent/` — SARA source: `action_value.py` (ENPV), `policy.py` (gates), `agent.py` (orchestration), `audit.py`, `counterfactual.py`, `experiment_runner.py`, `parallel_runner.py`.
