"""Feature engineering helpers for the SARA recovery-prediction pipeline.

Every constant in here is mirrored from a single source of truth in
services/people_service/. Keeping XG_DATA standalone (no `from app import ...`)
means the pipeline can be moved or vendored without dragging the people_service
package along.

Sources:
    - failure_model.BASE_FAILURE_RATE      (services/people_service/app/failure_model.py)
    - failure_model.STATE_MULTIPLIERS      (same)
    - failure_model.FAILURE_CATEGORIES     (same)
    - sim_calibration.json::spending.low_balance_threshold
    - sim_calibration.json::salary.deposit_days_range
    - failure_model._clamp / peak-hour window (18-22)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

import pandas as pd


# --------------------------------------------------------------------------- #
# Constants (mirrored from people_service/app/failure_model.py)
# --------------------------------------------------------------------------- #

# BASE_FAILURE_RATE per payment method (UPI 5-7%, CARD 5-8%, NETBANKING avg of
# SBI/HDFC/Axis/ICICI/BOI = 6.28%).
METHOD_BASE_RATE: dict[str, float] = {
    "UPI": 0.06,
    "CARD": 0.065,
    "NETBANKING": 0.0628,
}

# STATE_MULTIPLIERS — bank-state → failure multiplier.
BANK_STATE_MULTIPLIER: dict[str, float] = {
    "NORMAL": 1.0,
    "PEAK": 1.8,
    "DEGRADED": 3.5,
    "OUTAGE": 8.0,
}

# Category each failure_code belongs to (from failure_model.FAILURE_TYPES).
FAILURE_CODE_CATEGORY: dict[str, str] = {
    "INSUFFICIENT_FUNDS":       "CUSTOMER_STATE",
    "EXPIRED_PAYMENT_METHOD":   "CUSTOMER_STATE",
    "AUTHENTICATION_FAILURE":   "CUSTOMER_STATE",
    "CANCELLED":                "CUSTOMER_STATE",
    "ISSUER_DECLINE":           "BANK_DECLINE",
    "LIMIT_EXCEEDED":           "BANK_DECLINE",
    "RISK_DECLINE":             "BANK_DECLINE",
    "NETWORK_ERROR":            "INFRASTRUCTURE",
    "TIMEOUT":                  "INFRASTRUCTURE",
    "BANK_DEGRADED":            "INFRASTRUCTURE",
    "INVALID_DETAILS":          "MERCHANT_CONFIG",
    "UNSUPPORTED_METHOD":       "MERCHANT_CONFIG",
}

# Sim-calibration thresholds (sim_calibration.json::spending.*).
LOW_BALANCE_THRESHOLD: float = 2000.0

# Peak-hour window matches failure_probability()'s `18 <= hour <= 22` rule.
PEAK_HOUR_START: int = 18
PEAK_HOUR_END: int = 22  # inclusive

# Salary deposit days come from sim_calibration.json::salary.deposit_days_range.
SALARY_DAYS: tuple[int, ...] = (1, 2, 3, 4, 5)

# Reference simulation start (matches sim_calibration.json::time.start_datetime).
# Marked UTC so it's tz-aware — PostgreSQL returns tz-aware datetimes from
# DateTime(timezone=True) columns.
SIM_START_DATETIME: datetime = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Bucket boundaries — mirrored from sim_calibration.json::ecommerce.order_value_dist
# and the amount-based failure adjusters in failure_model.py.
# --------------------------------------------------------------------------- #

AMOUNT_BUCKETS: tuple[tuple[str, float, float], ...] = (
    # (label, lower_inclusive, upper_inclusive)
    ("low",      0.0,     2_000.0),
    ("medium",   2_000.0, 8_000.0),
    ("high",     8_000.0, 25_000.0),
    ("luxury",  25_000.0, float("inf")),
)


# --------------------------------------------------------------------------- #
# Categorical vocabularies (used for one-hot encoding).
# Deterministic ordering keeps training/eval column sets stable.
# --------------------------------------------------------------------------- #

INCOME_BRACKETS: tuple[str, ...] = ("low", "lower_middle", "middle", "upper_middle", "high")
AGE_GROUPS: tuple[str, ...] = ("18-24", "25-34", "35-44", "45-54", "55-64", "65+")
EMPLOYMENT_TYPES: tuple[str, ...] = (
    "salaried", "self_employed", "student", "retired", "unemployed"
)
SPENDING_PROFILES: tuple[str, ...] = (
    "student", "young_professional", "family", "high_income", "retired"
)
PAYMENT_METHODS: tuple[str, ...] = ("UPI", "CARD", "NETBANKING")
FAILURE_CATEGORIES: tuple[str, ...] = (
    "CUSTOMER_STATE", "BANK_DECLINE", "INFRASTRUCTURE", "MERCHANT_CONFIG"
)
BANK_STATES: tuple[str, ...] = ("NORMAL", "PEAK", "DEGRADED", "OUTAGE")
AMOUNT_BUCKET_LABELS: tuple[str, ...] = ("low", "medium", "high", "luxury")
MERCHANT_TYPES: tuple[str, ...] = ("subscription", "ecommerce", "other")
BILLING_CYCLES: tuple[str, ...] = ("MONTHLY", "ONE_TIME")
DAY_OF_WEEK: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_OF_WEEK_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# --------------------------------------------------------------------------- #
# Per-row helpers
# --------------------------------------------------------------------------- #

def amount_to_label(amount: float) -> str:
    """Bucket a transaction amount into low/medium/high/luxury."""
    for label, lo, hi in AMOUNT_BUCKETS:
        if lo <= amount < hi:
            return label
    # amount is exactly equal to the upper bound of the last real bucket
    # (e.g. amount == 25000), fall back to the highest bucket
    return AMOUNT_BUCKET_LABELS[-1]


def method_base_rate(method: str) -> float:
    """Return the base failure rate for a payment method (default 0.06)."""
    return METHOD_BASE_RATE.get(method, 0.06)


def bank_state_multiplier(bank_state: str) -> float:
    """Return the failure multiplier for a bank state (default 1.0)."""
    return BANK_STATE_MULTIPLIER.get(bank_state, 1.0)


def failure_category_for(failure_code: str) -> str:
    """Map a failure code to its category (default UNKNOWN)."""
    return FAILURE_CODE_CATEGORY.get(failure_code, "UNKNOWN")


def is_peak_hour(hour: int) -> int:
    return int(PEAK_HOUR_START <= hour <= PEAK_HOUR_END)


def is_salary_day(day_of_month: int) -> int:
    return int(day_of_month in SALARY_DAYS)


def simulation_day(sim_timestamp: pd.Series) -> pd.Series:
    """Days elapsed since SIM_START_DATETIME (0-based)."""
    return (pd.to_datetime(sim_timestamp) - pd.Timestamp(SIM_START_DATETIME)).dt.days


def day_of_week_name(sim_timestamp: pd.Series) -> pd.Series:
    return pd.to_datetime(sim_timestamp).dt.day_name().str.lower().str[:3]


def hour_of_day(sim_timestamp: pd.Series) -> pd.Series:
    return pd.to_datetime(sim_timestamp).dt.hour


def day_of_month(sim_timestamp: pd.Series) -> pd.Series:
    return pd.to_datetime(sim_timestamp).dt.day


# --------------------------------------------------------------------------- #
# Vectorised feature transforms
# --------------------------------------------------------------------------- #

def add_amount_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add `amount_bucket` (categorical string) column."""
    df = df.copy()
    df["amount_bucket"] = df["amount"].apply(amount_to_label)
    return df


def add_time_features(df: pd.DataFrame, ts_col: str = "simulation_timestamp") -> pd.DataFrame:
    """Add derived time columns from a timestamp column."""
    df = df.copy()
    sim = pd.to_datetime(df[ts_col])
    df["hour_of_day"] = sim.dt.hour
    df["is_peak_hour"] = (df["hour_of_day"] >= PEAK_HOUR_START) & (df["hour_of_day"] <= PEAK_HOUR_END)
    df["is_peak_hour"] = df["is_peak_hour"].astype(int)
    df["day_of_week"] = sim.dt.day_name().str.lower().str[:3]
    df["day_of_month"] = sim.dt.day
    df["is_salary_day"] = df["day_of_month"].apply(is_salary_day)
    df["simulation_day"] = (sim - pd.Timestamp(SIM_START_DATETIME)).dt.days
    return df


def add_bank_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add bank-state-derived columns."""
    df = df.copy()
    df["method_base_rate"] = df["payment_method"].apply(method_base_rate)
    df["bank_state_multiplier"] = df["bank_state"].apply(bank_state_multiplier)
    df["is_degraded_or_outage"] = df["bank_state"].isin(("DEGRADED", "OUTAGE")).astype(int)
    return df


def add_failure_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add `failure_category` column from `failure_code`."""
    df = df.copy()
    df["failure_category"] = df["failure_code"].apply(failure_category_for)
    return df


def add_balance_features(
    df: pd.DataFrame, balance_col: str = "current_balance", amount_col: str = "amount"
) -> pd.DataFrame:
    """Add balance-related derived columns.

    `current_balance` is the person's primary-account balance at the time of the
    failure. The training script materialises this from ledger entries via a SQL
    subquery — if it's missing (NaN) we treat the person as low-balance.
    """
    df = df.copy()
    bal = pd.to_numeric(df[balance_col], errors="coerce").fillna(0.0)
    amt = pd.to_numeric(df[amount_col], errors="coerce").fillna(0.0)
    margin = (bal / amt.replace(0, pd.NA)).astype(float)
    df["balance_margin"] = margin.clip(lower=0.0, upper=5.0).fillna(0.0)
    df["is_low_balance"] = (bal < LOW_BALANCE_THRESHOLD).astype(int)
    return df


def add_payment_preference_features(df: pd.DataFrame) -> pd.DataFrame:
    """Expand `payment_preferences_json` into per-method numeric columns."""
    df = df.copy()
    prefs = df["payment_preferences_json"].apply(_safe_json_dict)
    for method in PAYMENT_METHODS:
        key = method.lower() + "_pref"
        df[key] = prefs.apply(lambda d, m=method: float(d.get(m, 0.0) if isinstance(d, dict) else 0.0))
    return df


def add_subscription_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add subscription-related derived columns.

    `is_subscription` is 1 if `related_subscription_id` is set.
    `subscription_billing_cycle` defaults to "ONE_TIME" when missing.
    `days_until_next_billing` is set to -1 when there is no subscription.
    """
    df = df.copy()
    df["is_subscription"] = df["related_subscription_id"].notna().astype(int)
    cycle = df["billing_cycle"].fillna("ONE_TIME")
    cycle = cycle.where(cycle.isin(BILLING_CYCLES), "ONE_TIME")
    df["subscription_billing_cycle"] = cycle
    df["days_until_next_billing"] = pd.to_numeric(
        df["days_until_next_billing"], errors="coerce"
    ).fillna(-1).astype(int)
    df["subscription_consecutive_failures"] = pd.to_numeric(
        df["subscription_consecutive_failures"], errors="coerce"
    ).fillna(0).astype(int)
    df["subscription_amount"] = pd.to_numeric(
        df["subscription_amount"], errors="coerce"
    )
    return df


# --------------------------------------------------------------------------- #
# One-hot encoding (deterministic column ordering)
# --------------------------------------------------------------------------- #

def one_hot(
    df: pd.DataFrame,
    column: str,
    categories: Iterable[str],
    prefix: str | None = None,
) -> pd.DataFrame:
    """One-hot-encode `column` using the supplied (ordered) `categories`.

    Categories that appear in `df` but not in `categories` are still encoded
    in alphabetical order at the end so we never silently drop data. Missing
    values get all-zero rows.
    """
    df = df.copy()
    prefix = prefix or column
    series = df[column].astype("string").fillna("__MISSING__")
    cats = list(categories) + sorted(
        c for c in series.unique() if c not in categories and c != "__MISSING__"
    )
    for cat in cats:
        col_name = f"{prefix}_{cat}"
        df[col_name] = (series == cat).astype(int)
    return df


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

def _safe_json_dict(value) -> dict:
    """Best-effort: accept a dict or a JSON string, return a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        import json
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


__all__ = [
    # constants
    "METHOD_BASE_RATE",
    "BANK_STATE_MULTIPLIER",
    "FAILURE_CODE_CATEGORY",
    "LOW_BALANCE_THRESHOLD",
    "PEAK_HOUR_START",
    "PEAK_HOUR_END",
    "SALARY_DAYS",
    "SIM_START_DATETIME",
    "AMOUNT_BUCKETS",
    "INCOME_BRACKETS",
    "AGE_GROUPS",
    "EMPLOYMENT_TYPES",
    "SPENDING_PROFILES",
    "PAYMENT_METHODS",
    "FAILURE_CATEGORIES",
    "BANK_STATES",
    "AMOUNT_BUCKET_LABELS",
    "MERCHANT_TYPES",
    "BILLING_CYCLES",
    "DAY_OF_WEEK",
    # helpers
    "amount_to_label",
    "method_base_rate",
    "bank_state_multiplier",
    "failure_category_for",
    "is_peak_hour",
    "is_salary_day",
    "simulation_day",
    "day_of_week_name",
    "hour_of_day",
    "day_of_month",
    "add_amount_features",
    "add_time_features",
    "add_bank_features",
    "add_failure_features",
    "add_balance_features",
    "add_payment_preference_features",
    "add_subscription_features",
    "one_hot",
]