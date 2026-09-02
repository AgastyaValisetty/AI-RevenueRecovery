"""generate_data.py — Build an XGBoost training set from the live simulation DB.

Reads from the existing PostgreSQL `revenue_recovery` database (no service code
is touched).  Each output row = one RETRY decision from `recovery_actions`,
labeled by whether a matching `PAYMENT_SETTLED` ledger entry appears within
RECOVERY_WINDOW_HOURS of `scheduled_for`.  No synthetic data — real ground truth
only.

Run::

    cd Data_Gen
    python generate_data.py

Configure at the top of the file: ``N_ROWS``, ``RECOVERY_WINDOW_HOURS``, the
``PG_DSN`` env var, and ``OUTPUT_PATH``.  Output lands at
``Data_Gen/out/xgboost_training.csv``.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pandas as pd
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Config — edit these as needed
# ---------------------------------------------------------------------------

N_ROWS: int = 10_000              # cap on training rows we emit
RECOVERY_WINDOW_HOURS: int = 72    # label window after each RETRY's scheduled_for
BALANCE_LOOKBACK_DAYS: int = 60    # how far back to compute customer history
BATCH_SIZE: int = 500              # rows per DB roundtrip for balance/label queries

PG_DSN: str = os.getenv(
    "PG_DSN",
    "postgresql+psycopg2://simulator:simulator_dev@localhost:5433/revenue_recovery",
)

OUTPUT_PATH: Path = Path(__file__).resolve().parent / "out" / "xgboost_training.csv"

# When True, also export raw joined data without labels — useful for debugging
WRITE_DEBUG_JOIN: bool = False

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("generate_data")

# ---------------------------------------------------------------------------
# Mappings from people_service.failure_model
# ---------------------------------------------------------------------------

FAILURE_CATEGORIES: dict[str, str] = {
    "INSUFFICIENT_FUNDS": "CUSTOMER_STATE",
    "EXPIRED_PAYMENT_METHOD": "CUSTOMER_STATE",
    "AUTHENTICATION_FAILURE": "CUSTOMER_STATE",
    "CANCELLED": "CUSTOMER_STATE",
    "ISSUER_DECLINE": "BANK_DECLINE",
    "LIMIT_EXCEEDED": "BANK_DECLINE",
    "RISK_DECLINE": "BANK_DECLINE",
    "NETWORK_ERROR": "INFRASTRUCTURE",
    "TIMEOUT": "INFRASTRUCTURE",
    "BANK_DEGRADED": "INFRASTRUCTURE",
    "INVALID_DETAILS": "MERCHANT_CONFIG",
    "UNSUPPORTED_METHOD": "MERCHANT_CONFIG",
}

# Output schema — order matters for readability
OUTPUT_COLUMNS: list[str] = [
    # Meta / label
    "audit_event_id",
    "run_id",
    "engine_type",
    "recovered",
    "days_to_recovery",
    # Customer
    "customer_id",
    "customer_age",
    "customer_age_group",
    "customer_income_bracket",
    "customer_employment_type",
    "customer_salary_inr",
    "customer_salary_deposit_day",
    "customer_salary_deposit_hour",
    "customer_spending_profile_category",
    # Customer history (30d lookback)
    "num_retries_last_30d",
    "num_recovered_retries_last_30d",
    "customer_historical_success_rate",
    "customer_historical_mean_recovery_hours",
    # Balance / affordability
    "current_balance_inr",
    "balance_to_amount_ratio",
    # Salary timing
    "hours_until_next_salary",
    # Current transaction
    "amount_inr",
    "original_failure_code",
    "failure_category",
    "payment_method",
    # Merchant
    "merchant_id",
    "merchant_type",
    # Temporal
    "decision_hour_utc",
    "decision_day_of_week",
    "is_weekend",
    "is_peak_hour",
    # Retry state
    "retry_number",
    "days_since_original_failure",
    # Subscription
    "is_subscription",
    "num_consecutive_sub_failures",
    # Bank/rail
    "bank_state",
    # SARA-only
    "sara_estimated_recovery_prob",
    "sara_enpv_inr",
    "sara_idempotency_key",
]


# ---------------------------------------------------------------------------
# Single CTE: pull every RETRY row with joined features in one query
# ---------------------------------------------------------------------------

RETRY_JOIN_SQL = text("""
WITH retries AS (
    SELECT
        ra.action_id,
        ra.run_id,
        ra.scheduled_for,
        ra.executed_at,
        ra.outcome AS ra_outcome,
        ra.retry_number,
        ra.amount,
        ra.failure_code,
        ra.failure_reason,
        ra.payment_method,
        ra.metadata_json,
        pi.intent_id,
        pi.person_id,
        pi.merchant_id,
        pi.related_subscription_id,
        pi.created_at AS intent_created_at,
        pi.expires_at AS intent_expires_at
    FROM recovery_actions ra
    JOIN payment_intents pi ON pi.intent_id = ra.payment_intent_id
    WHERE ra.action_type = 'RETRY'
      AND ra.scheduled_for IS NOT NULL
      AND pi.person_id IS NOT NULL
      AND pi.merchant_id IS NOT NULL
    ORDER BY ra.scheduled_for DESC
    LIMIT :limit
)
SELECT
    r.action_id,
    r.run_id,
    r.scheduled_for,
    r.executed_at,
    r.ra_outcome,
    r.retry_number,
    r.amount,
    r.failure_code,
    r.failure_reason,
    r.payment_method,
    r.metadata_json,
    r.intent_id,
    r.person_id,
    r.merchant_id,
    r.related_subscription_id,
    r.intent_created_at,
    r.intent_expires_at,
    p.age,
    p.age_group,
    p.income_bracket,
    p.employment_type,
    p.salary,
    p.salary_deposit_day,
    p.salary_deposit_hour,
    p.spending_profile_category,
    p.primary_account_id,
    m.merchant_type,
    s.consecutive_failures AS sub_consecutive_failures
FROM retries r
JOIN persons p ON p.person_id = r.person_id
JOIN merchants m ON m.merchant_id = r.merchant_id
LEFT JOIN subscriptions s ON s.subscription_id = r.related_subscription_id
""")


# ---------------------------------------------------------------------------
# Per-row lookups: balance + 72h-settlement label
# ---------------------------------------------------------------------------

BALANCE_SQL = text("""
SELECT
    COALESCE(SUM(CASE WHEN to_account_id = :acct THEN amount ELSE 0 END), 0)
  - COALESCE(SUM(CASE WHEN from_account_id = :acct THEN amount ELSE 0 END), 0)
    AS balance
FROM ledger_entries
WHERE simulation_timestamp <= :as_of
  AND (to_account_id = :acct OR from_account_id = :acct)
""")


LABEL_SQL = text("""
SELECT
    MIN(simulation_timestamp) AS first_settled
FROM ledger_entries
WHERE event_type = 'PAYMENT_SETTLED'
  AND from_account_id = :acct
  AND amount = :amount
  AND simulation_timestamp > :as_of
  AND simulation_timestamp <= :window_end
""")


CUSTOMER_HISTORY_SQL = text("""
SELECT
    COUNT(*) AS num_retries,
    COUNT(*) FILTER (WHERE outcome = 'SUCCESS') AS num_recovered
FROM recovery_actions
WHERE person_id = :person_id
  AND action_type = 'RETRY'
  AND created_at >= :lookback_start
  AND created_at < :as_of
""")


# ---------------------------------------------------------------------------
# SARA audit join — case_id == payment_intent_id
# ---------------------------------------------------------------------------

SARA_AUDIT_SQL = text("""
SELECT case_id, decision_json, idempotency_key
FROM audit_events
WHERE event_type = 'decision'
  AND case_id = ANY(:case_ids)
""")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine():
    return create_engine(PG_DSN, pool_pre_ping=True, future=True)


def _ts(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _hours_until_next_salary(
    now: datetime, salary_day: int | None, salary_hour: int | None
) -> float | None:
    """Next salary datetime >= now, hours away (nullable)."""
    if salary_day is None or salary_hour is None:
        return None
    if not (1 <= int(salary_day) <= 31 and 0 <= int(salary_hour) <= 23):
        return None
    now = _ts(now)
    candidates: list[datetime] = []
    for delta_days in range(0, 70):
        candidate_day = (now + timedelta(days=delta_days)).date().replace(day=int(salary_day))
        if candidate_day < now.date():
            continue
        candidate = datetime.combine(
            candidate_day, datetime.min.time().replace(hour=int(salary_hour)),
            tzinfo=timezone.utc,
        )
        if candidate >= now:
            candidates.append(candidate)
    if not candidates:
        return None
    return (min(candidates) - now).total_seconds() / 3600.0


def _days_since_failure(metadata: dict | None, scheduled_for: datetime) -> float | None:
    if not metadata:
        return None
    raw = metadata.get("failure_timestamp")
    if not raw:
        return None
    try:
        ft = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if ft.tzinfo is None:
        ft = ft.replace(tzinfo=timezone.utc)
    sf = _ts(scheduled_for)
    if sf is None or ft is None:
        return None
    delta = (sf - ft).total_seconds() / 86400.0
    return max(delta, 0.0)


def _row_to_features(row: dict) -> dict:
    """Convert one joined DB row + computed fields into a CSV record."""
    scheduled_for = _ts(row["scheduled_for"])
    amount = float(row["amount"]) if row["amount"] is not None else 0.0
    balance = float(row["balance"]) if row.get("balance") is not None else 0.0
    metadata = row.get("metadata_json") or {}

    # Hours until next salary — copy from raw row (computed downstream)
    hours_to_salary = row.get("_hours_to_salary")
    customer_mean_rec_hrs = row.get("_customer_mean_recovery_hours")
    customer_success_rate = row.get("_customer_success_rate")

    decision_dow = scheduled_for.weekday() if scheduled_for else None
    decision_hour = scheduled_for.hour if scheduled_for else None

    return {
        # Meta / label
        "audit_event_id": str(row["action_id"]),
        "run_id": str(row["run_id"]) if row["run_id"] else "",
        "engine_type": row.get("_engine_type") or "",
        "recovered": int(row.get("_recovered") or 0),
        "days_to_recovery": row.get("_days_to_recovery"),
        # Customer
        "customer_id": str(row["person_id"]),
        "customer_age": int(row["age"]) if row["age"] is not None else None,
        "customer_age_group": row["age_group"],
        "customer_income_bracket": row["income_bracket"],
        "customer_employment_type": row["employment_type"],
        "customer_salary_inr": float(row["salary"]) if row["salary"] is not None else None,
        "customer_salary_deposit_day": int(row["salary_deposit_day"])
        if row["salary_deposit_day"] is not None else None,
        "customer_salary_deposit_hour": int(row["salary_deposit_hour"])
        if row["salary_deposit_hour"] is not None else None,
        "customer_spending_profile_category": row["spending_profile_category"],
        # Customer history
        "num_retries_last_30d": int(row.get("_num_retries_30d") or 0),
        "num_recovered_retries_last_30d": int(row.get("_num_recovered_30d") or 0),
        "customer_historical_success_rate": customer_success_rate,
        "customer_historical_mean_recovery_hours": customer_mean_rec_hrs,
        # Balance
        "current_balance_inr": balance,
        "balance_to_amount_ratio": (balance / amount) if amount > 0 else None,
        # Salary timing
        "hours_until_next_salary": hours_to_salary,
        # Current transaction
        "amount_inr": amount,
        "original_failure_code": row["failure_code"],
        "failure_category": FAILURE_CATEGORIES.get(row["failure_code"], "UNKNOWN"),
        "payment_method": row["payment_method"],
        # Merchant
        "merchant_id": str(row["merchant_id"]),
        "merchant_type": row["merchant_type"],
        # Temporal
        "decision_hour_utc": decision_hour,
        "decision_day_of_week": decision_dow,
        "is_weekend": bool(decision_dow is not None and decision_dow >= 5),
        "is_peak_hour": bool(decision_hour is not None and 18 <= decision_hour <= 22),
        # Retry state
        "retry_number": int(row["retry_number"]) if row["retry_number"] is not None else None,
        "days_since_original_failure": _days_since_failure(metadata, scheduled_for),
        # Subscription
        "is_subscription": bool(row["related_subscription_id"] is not None),
        "num_consecutive_sub_failures": int(row["sub_consecutive_failures"] or 0)
        if row["related_subscription_id"] is not None
        else 0,
        # Bank/rail
        "bank_state": metadata.get("bank_state"),
        # SARA-only
        "sara_estimated_recovery_prob": row.get("_sara_recovery_prob"),
        "sara_enpv_inr": row.get("_sara_enpv"),
        "sara_idempotency_key": row.get("_sara_idempotency_key"),
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def fetch_retry_rows(engine, limit: int) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(RETRY_JOIN_SQL, {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def batched(iterable, size: int):
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def attach_balance_and_label(engine, rows: list[dict]) -> None:
    """Mutates each row in-place with `balance`, `_recovered`, `_days_to_recovery`."""
    if not rows:
        return

    for chunk in batched(rows, BATCH_SIZE):
        # Balance per (person, scheduled_for) — one query per row (cheap; uses index)
        for row in chunk:
            scheduled_for = _ts(row["scheduled_for"])
            account_id = str(row["primary_account_id"])
            try:
                with engine.connect() as conn:
                    bal = conn.execute(
                        BALANCE_SQL, {"acct": account_id, "as_of": scheduled_for}
                    ).scalar_one()
            except Exception as exc:  # noqa: BLE001
                log.debug("balance lookup failed for %s: %s", account_id, exc)
                bal = Decimal("0")
            row["balance"] = bal if bal is not None else Decimal("0")

            # Label: was there a settlement from this account for this amount in (T, T+72h]?
            amount = Decimal(str(row["amount"])) if row["amount"] is not None else Decimal("0")
            window_end = scheduled_for + timedelta(hours=RECOVERY_WINDOW_HOURS)
            try:
                with engine.connect() as conn:
                    first_settled = conn.execute(
                        LABEL_SQL,
                        {
                            "acct": account_id,
                            "amount": amount,
                            "as_of": scheduled_for,
                            "window_end": window_end,
                        },
                    ).scalar_one()
            except Exception as exc:  # noqa: BLE001
                log.debug("label lookup failed for %s: %s", account_id, exc)
                first_settled = None

            if first_settled is None:
                row["_recovered"] = 0
                row["_days_to_recovery"] = None
            else:
                row["_recovered"] = 1
                row["_days_to_recovery"] = (
                    first_settled - scheduled_for
                ).total_seconds() / 86400.0


def attach_customer_history(engine, rows: list[dict]) -> None:
    """Mutates each row with `_num_retries_30d`, `_num_recovered_30d`, etc."""
    if not rows:
        return

    lookback_start_per_row: dict[str, datetime] = {}
    for row in rows:
        sf = _ts(row["scheduled_for"])
        ls = sf - timedelta(days=30) if sf else None
        try:
            with engine.connect() as conn:
                stats = conn.execute(
                    CUSTOMER_HISTORY_SQL,
                    {
                        "person_id": row["person_id"],
                        "lookback_start": ls,
                        "as_of": sf,
                    },
                ).mappings().one()
        except Exception as exc:  # noqa: BLE001
            log.debug("history lookup failed for %s: %s", row["person_id"], exc)
            stats = {"num_retries": 0, "num_recovered": 0}

        row["_num_retries_30d"] = int(stats["num_retries"] or 0)
        row["_num_recovered_30d"] = int(stats["num_recovered"] or 0)
        total = row["_num_retries_30d"]
        rec = row["_num_recovered_30d"]
        row["_customer_success_rate"] = (rec / total) if total > 0 else None

        # Mean time-to-recovery in hours (from successful settlements in same window)
        # — relies on audit-style metadata stored in recovery_actions.
        try:
            with engine.connect() as conn:
                mean_hrs = conn.execute(
                    text("""
                    SELECT
                      AVG(EXTRACT(EPOCH FROM (executed_at - (metadata_json->>'failure_timestamp')::timestamptz)) / 3600.0)
                        AS mean_hrs
                    FROM recovery_actions
                    WHERE person_id = :person_id
                      AND action_type = 'RETRY'
                      AND outcome = 'SUCCESS'
                      AND created_at >= :lookback_start
                      AND created_at < :as_of
                      AND metadata_json ? 'failure_timestamp'
                      AND executed_at IS NOT NULL
                    """),
                    {
                        "person_id": row["person_id"],
                        "lookback_start": ls,
                        "as_of": sf,
                    },
                ).scalar_one()
        except Exception:  # noqa: BLE001
            mean_hrs = None
        row["_customer_mean_recovery_hours"] = (
            float(mean_hrs) if mean_hrs is not None else None
        )


def attach_sara_audit(engine, rows: list[dict]) -> None:
    """Mutates each row with SARA-only features from `audit_events`."""
    if not rows:
        return
    case_ids = [r["intent_id"] for r in rows]
    try:
        with engine.connect() as conn:
            audit_rows = conn.execute(
                SARA_AUDIT_SQL, {"case_ids": case_ids}
            ).mappings().all()
    except Exception as exc:  # noqa: BLE001
        log.debug("audit lookup failed: %s", exc)
        audit_rows = []
    audit_map = {r["case_id"]: r for r in audit_rows}

    for row in rows:
        audit = audit_map.get(row["intent_id"])
        if audit is None:
            row["_engine_type"] = ""
            row["_sara_recovery_prob"] = None
            row["_sara_enpv"] = None
            row["_sara_idempotency_key"] = None
            continue

        row["_engine_type"] = "AI_AGENT"
        row["_sara_idempotency_key"] = audit.get("idempotency_key")
        decision = audit.get("decision_json") or {}
        ev = decision.get("expected_value") or {}
        # SARA's expected_value dict contains recovery_probability + expected_net_value
        prob = ev.get("recovery_probability")
        enpv = ev.get("expected_net_value")
        try:
            row["_sara_recovery_prob"] = float(prob) if prob is not None else None
        except (TypeError, ValueError):
            row["_sara_recovery_prob"] = None
        try:
            row["_sara_enpv"] = float(enpv) if enpv is not None else None
        except (TypeError, ValueError):
            row["_sara_enpv"] = None

    # Tag baseline rows using baseline_audit_events (separate table)
    try:
        with engine.connect() as conn:
            baseline_rows = conn.execute(
                text("""
                SELECT case_id FROM baseline_audit_events
                WHERE event_type = 'decision' AND case_id = ANY(:case_ids)
                """),
                {"case_ids": case_ids},
            ).mappings().all()
    except Exception as exc:  # noqa: BLE001
        log.debug("baseline audit lookup failed: %s", exc)
        baseline_rows = []
    baseline_ids = {r["case_id"] for r in baseline_rows}

    for row in rows:
        if row.get("_engine_type") == "AI_AGENT":
            continue
        if row["intent_id"] in baseline_ids:
            row["_engine_type"] = "BASELINE"
        else:
            row["_engine_type"] = "UNKNOWN"


def attach_salary_timing(rows: list[dict]) -> None:
    """Pure-Python — uses person row already in memory."""
    for row in rows:
        row["_hours_to_salary"] = _hours_until_next_salary(
            _ts(row["scheduled_for"]),
            row.get("salary_deposit_day"),
            row.get("salary_deposit_hour"),
        )


def build_dataframe(rows: list[dict]) -> pd.DataFrame:
    features = [_row_to_features(r) for r in rows]
    df = pd.DataFrame(features, columns=OUTPUT_COLUMNS)
    # Force dtypes
    for col in [
        "customer_age",
        "customer_salary_deposit_day",
        "customer_salary_deposit_hour",
        "retry_number",
        "num_consecutive_sub_failures",
        "decision_hour_utc",
        "decision_day_of_week",
        "num_retries_last_30d",
        "num_recovered_retries_last_30d",
        "recovered",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in [
        "customer_salary_inr",
        "amount_inr",
        "current_balance_inr",
        "balance_to_amount_ratio",
        "customer_historical_success_rate",
        "customer_historical_mean_recovery_hours",
        "hours_until_next_salary",
        "days_since_original_failure",
        "days_to_recovery",
        "sara_estimated_recovery_prob",
        "sara_enpv_inr",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df


def main() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    log.info("Connecting to %s", PG_DSN)
    engine = _engine()

    log.info("Counting RETRY rows in DB …")
    with engine.connect() as conn:
        total_retries = conn.execute(
            text("SELECT COUNT(*) FROM recovery_actions WHERE action_type='RETRY'")
        ).scalar_one()
    log.info("Found %d RETRY rows in DB.", total_retries)
    if total_retries == 0:
        log.error("No RETRY rows found. Run a simulation first (e.g. python master.py).")
        return 1

    fetch_limit = max(N_ROWS, int(N_ROWS * 1.1))  # small over-fetch to allow filter drops
    log.info("Pulling RETRY rows + joins (limit=%d) …", fetch_limit)
    t0 = time.perf_counter()
    rows = fetch_retry_rows(engine, fetch_limit)
    log.info("Pulled %d rows in %.1fs", len(rows), time.perf_counter() - t0)
    if not rows:
        log.error("Query returned no rows.")
        return 1

    # Decide final cap. If DB has fewer than N_ROWS, use everything.
    target_n = min(N_ROWS, len(rows))
    if target_n < N_ROWS:
        log.warning(
            "Requested %d rows but only %d available — using all.",
            N_ROWS, target_n,
        )

    log.info("Computing customer history features …")
    attach_customer_history(engine, rows[:target_n])
    log.info("Computing balance + 72h-settlement labels …")
    attach_balance_and_label(engine, rows[:target_n])
    log.info("Tagging SARA / baseline engine_type …")
    attach_sara_audit(engine, rows[:target_n])
    log.info("Computing salary-timing features …")
    attach_salary_timing(rows[:target_n])

    df = build_dataframe(rows[:target_n])

    log.info("Writing %d rows to %s …", len(df), OUTPUT_PATH)
    df.to_csv(OUTPUT_PATH, index=False)

    recovered = int(df["recovered"].fillna(0).sum())
    log.info(
        "Done. Wrote %d rows to %s (recovered=%d, not=%d).",
        len(df), OUTPUT_PATH, recovered, len(df) - recovered,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())