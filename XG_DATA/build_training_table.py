"""Step 1 of the XG_DATA pipeline: drive a SARA simulation, then dump the
results into one CSV row per original failed transaction.

Usage (from repo root):

    # 1. Boot the stack
    python master.py

    # 2. Build the training CSV
    python XG_DATA/build_training_table.py
    #   --people 100 --days 365 --seed 42 --skip-run
    #       # reuse the simulation that is already running
    #   --output XG_DATA/sara_recovery_training.csv

What this script does:

1. POST /api/simulation/run with people=100, days=365, seed=42 (the user's
   target scale). The SARA stack generates ~hundreds of failed payments
   + recovery actions into PostgreSQL.

2. Connect to the PostgreSQL database (`DB_HOST=localhost, DB_PORT=5433` —
   matches master.py).

3. Run a single SQL query that joins payment_attempts, persons, banks,
   merchants, subscriptions and aggregates recovery_actions into one wide
   row per ORIGINAL failed transaction. The "original" qualifier means:
   status = 'FAILED' on the first attempt that hit the bank (i.e. the
   attempt SARA's recovery loop is reacting to).

4. Compute derived features (balance margin, time-of-day, amount buckets,
   bank-state multipliers, etc.) using ``feature_store``.

5. Write the result to ``sara_recovery_training.csv`` and print a summary.

The pipeline is read-only against the database (SELECT only).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Iterable

import httpx
import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

from feature_store import (
    AGE_GROUPS,
    AMOUNT_BUCKET_LABELS,
    BANK_STATES,
    BILLING_CYCLES,
    DAY_OF_WEEK,
    EMPLOYMENT_TYPES,
    FAILURE_CATEGORIES,
    INCOME_BRACKETS,
    MERCHANT_TYPES,
    PAYMENT_METHODS,
    SPENDING_PROFILES,
    add_amount_features,
    add_balance_features,
    add_bank_features,
    add_failure_features,
    add_payment_preference_features,
    add_subscription_features,
    add_time_features,
    one_hot,
)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_PEOPLE_URL = os.environ.get("PEOPLE_SERVICE_URL", "http://localhost:8000")
DEFAULT_DB_HOST = os.environ.get("DB_HOST", "localhost")
DEFAULT_DB_PORT = int(os.environ.get("DB_PORT", "5433"))
DEFAULT_DB_USER = os.environ.get("DB_USER", "simulator")
DEFAULT_DB_PASSWORD = os.environ.get("DB_PASSWORD", "simulator_dev")
DEFAULT_DB_NAME = os.environ.get("DB_NAME", "revenue_recovery")

DEFAULT_PEOPLE = 100
DEFAULT_DAYS = 365
DEFAULT_SEED = 42
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "sara_recovery_training.csv"


# --------------------------------------------------------------------------- #
# SQL: one wide row per original FAILED payment intent.
#
# SARA's offline simulator processes payments inline via the ledger — it does
# NOT write rows to payment_attempts (that table is only populated by the
# LazerPay HTTP path in api.py::process_payment, which is a separate code
# path). The source of truth for "an original payment failed" is therefore
# payment_intents WHERE status = 'FAILED', joined to its matching
# ledger_entries row (event_type = 'PAYMENT_FAILED') for the failure_code /
# failure_reason / failure_category / payment_method metadata.
#
# We treat each payment_intents row with status='FAILED' as a single
# "original failed transaction". SARA's recovery_actions rows join to the
# same intent_id, so recovery_agg is keyed off intent_id directly.
# --------------------------------------------------------------------------- #

BASE_QUERY = """
WITH failed_intents AS (
    SELECT
        pi.intent_id,
        pi.person_id,
        pi.merchant_id,
        pi.related_subscription_id,
        pi.amount,
        pi.payment_method,
        pi.created_at        AS intent_created_at,
        pi.expires_at        AS intent_expires_at
    FROM payment_intents pi
    WHERE pi.status = 'FAILED'
),
intent_failures AS (
    -- Pick the matching PAYMENT_FAILED ledger entry to get failure_code,
    -- failure_reason, failure_category, bank_state and the authoritative
    -- simulation_timestamp. The orchestrator writes metadata_json with
    -- {failure_code, failure_reason, failure_category, payment_method,
    -- settled_inline: true} on every inline failure.
    SELECT
        fi.intent_id,
        fi.person_id,
        fi.merchant_id,
        fi.related_subscription_id,
        fi.amount           AS intent_amount,
        fi.payment_method   AS intent_payment_method,
        le.entry_id         AS ledger_entry_id,
        le.simulation_timestamp,
        le.metadata_json    AS ledger_metadata,
        le.from_account_id  AS source_account_id,
        le.to_account_id    AS destination_account_id,
        le.metadata_json ->> 'failure_code'     AS failure_code,
        le.metadata_json ->> 'failure_reason'   AS failure_reason,
        le.metadata_json ->> 'failure_category' AS failure_category,
        COALESCE(le.metadata_json ->> 'bank_state', 'NORMAL') AS bank_state
    FROM failed_intents fi
    JOIN LATERAL (
        SELECT le.entry_id, le.simulation_timestamp, le.from_account_id,
               le.to_account_id, le.metadata_json
        FROM ledger_entries le
        WHERE le.event_type = 'PAYMENT_FAILED'
          AND le.metadata_json ->> 'settled_inline' = 'true'
          AND le.metadata_json ->> 'person_id' = fi.person_id::text
          AND le.metadata_json ->> 'merchant_id' = fi.merchant_id::text
          AND le.amount = fi.amount
        ORDER BY le.simulation_timestamp ASC
        LIMIT 1
    ) le ON TRUE
),
recovery_agg AS (
    SELECT
        ra.payment_intent_id,
        MAX(CASE WHEN ra.outcome = 'SUCCESS' THEN 1 ELSE 0 END) AS ground_truth_recovered,
        COUNT(*) AS num_retries_taken,
        MIN(CASE WHEN ra.outcome = 'SUCCESS' THEN ra.executed_at END) -
            MIN(ra.scheduled_for) AS time_to_recover_hours,
        (ARRAY_AGG(ra.outcome ORDER BY ra.executed_at ASC NULLS LAST))[1] AS first_retry_outcome
    FROM recovery_actions ra
    WHERE ra.payment_intent_id IS NOT NULL
      AND ra.action_type = 'RETRY'
    GROUP BY ra.payment_intent_id
),
history_30d AS (
    -- Self-join all intents to compute rolling per-person stats.
    -- `pi` = the current (failed) intent, `pi2` = a prior intent (settled or failed)
    -- for the same person in the [ts-30d, ts) window.
    SELECT
        pi.intent_id                AS cur_intent_id,
        SUM(CASE WHEN pi2.status = 'FAILED'  THEN 1 ELSE 0 END) AS prev_failures_30d,
        SUM(CASE WHEN pi2.status = 'SETTLED' THEN 1 ELSE 0 END) AS prev_successes_30d,
        SUM(CASE
            WHEN pi2.status = 'FAILED' AND pi2.payment_method = pi.intent_payment_method
            THEN 1 ELSE 0 END) AS prev_failures_same_method_30d,
        MAX(CASE WHEN pi2.status = 'FAILED' THEN le2.simulation_timestamp END)
            AS last_failure_ts
    FROM intent_failures pi
    LEFT JOIN payment_intents pi2
        ON pi2.person_id = pi.person_id
        AND pi2.created_at < pi.simulation_timestamp
        AND pi2.created_at >= pi.simulation_timestamp - INTERVAL '30 days'
    LEFT JOIN LATERAL (
        SELECT le2.simulation_timestamp
        FROM ledger_entries le2
        WHERE le2.event_type IN ('PAYMENT_FAILED', 'PAYMENT_SETTLED')
          AND le2.metadata_json ->> 'person_id' = pi2.person_id::text
          AND le2.amount = pi2.amount
        ORDER BY le2.simulation_timestamp DESC
        LIMIT 1
    ) le2 ON TRUE
    GROUP BY pi.intent_id
),
balance_at_failure AS (
    -- Approximate "current balance" as cumulative SUM of ledger entries for
    -- this person's primary account up to (but excluding) the failure ts.
    -- Credits: SALARY_DEPOSIT + PAYMENT_SETTLED into the account.
    -- Debits:  PAYMENT_SETTLED out of the account (failed payments do NOT
    -- debit — see orchestrator.py:913-915).
    SELECT
        pi.intent_id,
        COALESCE(SUM(
            CASE
                WHEN le.event_type IN ('SALARY_DEPOSIT') AND le.to_account_id = p.primary_account_id::text
                    THEN le.amount
                WHEN le.event_type = 'PAYMENT_SETTLED' AND le.to_account_id = p.primary_account_id::text
                    THEN le.amount
                WHEN le.event_type = 'PAYMENT_SETTLED' AND le.from_account_id = p.primary_account_id::text
                    THEN -le.amount
                ELSE 0
            END
        ), 0) AS current_balance
    FROM intent_failures pi
    JOIN persons p ON p.person_id = pi.person_id
    LEFT JOIN ledger_entries le
        ON (le.from_account_id = p.primary_account_id::text
            OR le.to_account_id = p.primary_account_id::text)
        AND le.simulation_timestamp < pi.simulation_timestamp
    GROUP BY pi.intent_id, p.primary_account_id
)
SELECT
    fi.intent_id,
    fi.ledger_entry_id    AS attempt_id,
    fi.person_id,
    fi.merchant_id,
    fi.source_account_id,
    fi.destination_account_id,
    fi.simulation_timestamp,
    fi.intent_amount       AS amount,
    pi2.payment_method     AS payment_method,
    fi.failure_code,
    fi.failure_reason,
    fi.failure_category,
    fi.bank_state,
    p.salary,
    p.income_bracket,
    p.age_group,
    p.employment_type,
    p.spending_profile_category,
    p.salary_deposit_day,
    p.payment_preferences_json,
    b.bank_id,
    b.name AS bank_name,
    m.merchant_type,
    s.subscription_id AS related_subscription_id,
    s.billing_cycle,
    s.consecutive_failures AS subscription_consecutive_failures,
    s.amount AS subscription_amount,
    s.next_billing_date,
    CAST((s.next_billing_date - DATE(fi.simulation_timestamp)) AS INTEGER) AS days_until_next_billing,
    baf.current_balance,
    COALESCE(h30.prev_failures_30d, 0) AS prev_failures_30d,
    COALESCE(h30.prev_successes_30d, 0) AS prev_successes_30d,
    COALESCE(h30.prev_failures_same_method_30d, 0) AS prev_failures_same_method_30d,
    h30.last_failure_ts,
    COALESCE(ra.ground_truth_recovered, 0) AS ground_truth_recovered,
    COALESCE(ra.num_retries_taken, 0) AS num_retries_taken,
    ra.first_retry_outcome,
    EXTRACT(EPOCH FROM ra.time_to_recover_hours) / 3600.0 AS time_to_recover_hours
FROM intent_failures fi
JOIN persons p ON p.person_id = fi.person_id
JOIN banks b ON b.bank_id = p.primary_bank_id
JOIN payment_intents pi2 ON pi2.intent_id = fi.intent_id
LEFT JOIN merchants m ON m.merchant_id = fi.merchant_id
LEFT JOIN subscriptions s ON s.subscription_id = fi.related_subscription_id
LEFT JOIN history_30d h30 ON h30.cur_intent_id = fi.intent_id
LEFT JOIN balance_at_failure baf ON baf.intent_id = fi.intent_id
LEFT JOIN recovery_agg ra ON ra.payment_intent_id = fi.intent_id
ORDER BY fi.simulation_timestamp;
"""


# --------------------------------------------------------------------------- #
# Simulation driver
# --------------------------------------------------------------------------- #

def trigger_simulation(
    base_url: str,
    people_count: int,
    days: int,
    seed: int,
    *,
    timeout_s: float = 60 * 30.0,  # 30 min — 100 ppl × 365 days can take a while
) -> dict:
    """POST /api/simulation/run. Long-running; respect the configured timeout."""
    payload = {
        "people_count": people_count,
        "days": days,
        "hours": 0,
        "seed": seed,
        "enable_recovery": True,
    }
    print(f"[xgdata] Triggering simulation: {payload} (timeout {timeout_s:.0f}s)")
    with httpx.Client(timeout=timeout_s) as client:
        response = client.post(f"{base_url}/api/simulation/run", json=payload)
        response.raise_for_status()
        data = response.json()
    print(f"[xgdata] Simulation finished. status={data.get('status')}")
    summary = data.get("summary", {})
    if summary:
        print(
            f"[xgdata]   people={summary.get('people_count', '?')} "
            f"hours_run={summary.get('hours_run', '?')} "
            f"failed_payments={summary.get('total_failed_payments', summary.get('failed_payments', '?'))}"
        )
    return data


def wait_for_service(base_url: str, *, timeout_s: float = 60.0) -> None:
    """Poll /api/simulation/status until the service responds."""
    print(f"[xgdata] Waiting for {base_url} to be reachable (≤{timeout_s:.0f}s)")
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{base_url}/api/simulation/status")
                if r.status_code == 200:
                    print("[xgdata] Service is up.")
                    return
        except Exception as exc:  # network errors during boot — fine, retry
            last_err = exc
            time.sleep(1.0)
    raise RuntimeError(
        f"People Service at {base_url} never responded within {timeout_s:.0f}s. "
        f"Last error: {last_err!r}"
    )


# --------------------------------------------------------------------------- #
# Database access
# --------------------------------------------------------------------------- #

def fetch_dataframe(
    db_host: str,
    db_port: int,
    db_user: str,
    db_password: str,
    db_name: str,
    query: str,
) -> pd.DataFrame:
    """Run `query` and return the result as a pandas DataFrame."""
    print(f"[xgdata] Connecting to PostgreSQL {db_host}:{db_port}/{db_name} as {db_user}")
    conn = psycopg2.connect(
        host=db_host, port=db_port, user=db_user,
        password=db_password, dbname=db_name,
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        print("[xgdata] WARNING: query returned 0 rows. Run the simulation first.")
    df = pd.DataFrame.from_records(rows)
    print(f"[xgdata] Loaded {len(df)} raw rows from PostgreSQL")
    return df


# --------------------------------------------------------------------------- #
# Feature engineering
# --------------------------------------------------------------------------- #

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the full feature-engineering pipeline."""
    df = df.copy()

    # Normalise numeric columns (Decimal from psycopg2 → float).
    for col in ("amount", "salary", "subscription_amount", "current_balance"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = add_time_features(df, ts_col="simulation_timestamp")
    df = add_amount_features(df)
    df = add_bank_features(df)
    # failure_category comes from the SQL query (ledger metadata). Only derive
    # it from failure_code if the column is missing.
    if "failure_category" not in df.columns:
        df = add_failure_features(df)
    df = add_balance_features(df)
    df = add_payment_preference_features(df)
    df = add_subscription_features(df)

    # days_since_last_failure: -1 sentinel for first-ever failure.
    df["days_since_last_failure"] = (
        (df["simulation_timestamp"] - df["last_failure_ts"])
        .dt.total_seconds() / 86400.0
    ).fillna(-1.0)

    # days_since_last_salary: based on person's salary_deposit_day.
    if "salary_deposit_day" in df.columns:
        # Use the most recent prior month whose day-of-month = salary_deposit_day.
        sim = pd.to_datetime(df["simulation_timestamp"]).dt.tz_localize(None)
        last_salary_day = sim.dt.day - (
            (sim.dt.day < df["salary_deposit_day"]).astype(int) * sim.dt.daysinmonth
        )
        last_salary = sim - pd.to_timedelta(sim.dt.day - last_salary_day, unit="D")
        df["days_since_last_salary"] = (sim - last_salary).dt.days.fillna(0).astype(int)
    else:
        df["days_since_last_salary"] = -1

    # recovery_rate_30d (NaN-safe fill at 0.5 — neutral prior).
    prev_total = df["prev_failures_30d"] + df["prev_successes_30d"]
    df["recovery_rate_30d"] = np.where(
        prev_total > 0, df["prev_successes_30d"] / prev_total, 0.5
    )

    # Normalise merchant_type: missing → "other".
    if "merchant_type" in df.columns:
        df["merchant_type"] = (
            df["merchant_type"].fillna("other").where(
                df["merchant_type"].isin(MERCHANT_TYPES), "other"
            )
        )

    # One-hot encode every categorical.
    for col, cats in (
        ("income_bracket", INCOME_BRACKETS),
        ("age_group", AGE_GROUPS),
        ("employment_type", EMPLOYMENT_TYPES),
        ("spending_profile_category", SPENDING_PROFILES),
        ("payment_method", PAYMENT_METHODS),
        ("failure_category", FAILURE_CATEGORIES),
        ("bank_state", BANK_STATES),
        ("amount_bucket", AMOUNT_BUCKET_LABELS),
        ("merchant_type", MERCHANT_TYPES),
        ("subscription_billing_cycle", BILLING_CYCLES),
        ("day_of_week", DAY_OF_WEEK),
    ):
        df = one_hot(df, col, cats)

    # Days-since-failure may be negative for the first failure (-1 sentinel).
    df["days_since_last_failure"] = df["days_since_last_failure"].fillna(-1.0)

    # Normalise booleans / ints.
    bool_cols = ["is_subscription", "is_low_balance", "is_peak_hour",
                 "is_salary_day", "is_degraded_or_outage"]
    for c in bool_cols:
        if c in df.columns:
            df[c] = df[c].fillna(0).astype(int)

    return df


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #

def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the XGBoost training CSV from a live SARA simulation.",
    )
    parser.add_argument("--people", type=int, default=DEFAULT_PEOPLE,
                        help=f"People count (default {DEFAULT_PEOPLE}).")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"Days to simulate (default {DEFAULT_DAYS}).")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"RNG seed (default {DEFAULT_SEED}).")
    parser.add_argument("--base-url", default=DEFAULT_PEOPLE_URL,
                        help=f"People Service base URL (default {DEFAULT_PEOPLE_URL}).")
    parser.add_argument("--db-host", default=DEFAULT_DB_HOST)
    parser.add_argument("--db-port", type=int, default=DEFAULT_DB_PORT)
    parser.add_argument("--db-user", default=DEFAULT_DB_USER)
    parser.add_argument("--db-password", default=DEFAULT_DB_PASSWORD)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--skip-run", action="store_true",
                        help="Don't POST /api/simulation/run; just query the DB.")
    parser.add_argument("--timeout-s", type=float, default=60 * 30.0,
                        help="HTTP timeout for the simulation run (default 1800s).")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="CSV output path (default XG_DATA/sara_recovery_training.csv).")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.skip_run:
        wait_for_service(args.base_url, timeout_s=60.0)
        trigger_simulation(
            args.base_url,
            args.people, args.days, args.seed,
            timeout_s=args.timeout_s,
        )
    else:
        print("[xgdata] --skip-run passed; trusting the database has a fresh run")

    df = fetch_dataframe(
        args.db_host, args.db_port, args.db_user, args.db_password, args.db_name,
        BASE_QUERY,
    )
    if df.empty:
        print("[xgdata] ERROR: no failed transactions found. Did the simulation run?")
        return 1

    df = engineer_features(df)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)

    recovered = int(df["ground_truth_recovered"].sum())
    total = len(df)
    pct = (recovered / total) * 100 if total else 0.0
    print(
        f"[xgdata] Wrote {args.output} — {total} rows. "
        f"Recovered: {recovered} ({pct:.1f}%). "
        f"Failed-only: {total - recovered} ({100 - pct:.1f}%)."
    )
    print(f"[xgdata] Columns: {list(df.columns)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())