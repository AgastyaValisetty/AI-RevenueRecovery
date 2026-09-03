"""Real-world failure model for the payment simulation.

Single source of truth for *how often* payments fail and *why*.

P(failure) is a multiplicative model:
    P(failure) = base_rate(method) * state_mult * amount_mult
                 * balance_mult * time_mult * load_mult

* ``base_rate`` comes from observed figures: UPI 5–7%, CARD 5–8%, NETBANKING is
  the average of SBI 6.34% / HDFC 4.64% / Axis 5.05% / ICICI 4.34% / BOI 11.04%.
* The adjusters are ~1.0 in neutral conditions and grow when the risk factor is
  elevated (bank degraded/outage, large tickets, thin balance margin, peak hours,
  heavy load), clamped so P(failure) never exceeds 0.9.

When a payment *does* fail, the reason is picked from ``COMPOSITION`` (the
conditional distribution among failures), optionally filtered by payment method
(e.g. an expired-card reason only applies to CARD) and boosted toward
``BANK_DEGRADED`` while the bank is in a degraded state.

This module deliberately does NOT change whether a payment succeeds — it only
decides the reason for failures that are already happening.
"""

from __future__ import annotations

from random import Random
from typing import Sequence

# Categories in the failure taxonomy (user-specified).
CUSTOMER_STATE = "CUSTOMER_STATE"
BANK_DECLINE = "BANK_DECLINE"
INFRASTRUCTURE = "INFRASTRUCTURE"
MERCHANT_CONFIG = "MERCHANT_CONFIG"

CATEGORY_LABELS: dict[str, str] = {
    CUSTOMER_STATE: "Customer State",
    BANK_DECLINE: "Bank Decline",
    INFRASTRUCTURE: "Infrastructure",
    MERCHANT_CONFIG: "Merchant / Config",
}

# Every code the system can emit, its human-readable reason, and its category.
# INSUFFICIENT_FUNDS is emitted deterministically (real insolvency), not via
# COMPOSITION, so it isn't listed in COMPOSITION — it's the dominant bucket by
# construction (see classify_failure).
FAILURE_TYPES: dict[str, tuple[str, str]] = {
    "INSUFFICIENT_FUNDS": (CUSTOMER_STATE, "Insufficient balance"),
    "EXPIRED_PAYMENT_METHOD": (CUSTOMER_STATE, "Payment method expired / blocked"),
    "AUTHENTICATION_FAILURE": (CUSTOMER_STATE, "Authentication failed (PIN/OTP/3DS)"),
    "CANCELLED": (CUSTOMER_STATE, "Customer cancelled / abandoned"),
    "ISSUER_DECLINE": (BANK_DECLINE, "Temporary decline by issuing bank"),
    "LIMIT_EXCEEDED": (BANK_DECLINE, "Transaction / daily limit exceeded"),
    "RISK_DECLINE": (BANK_DECLINE, "Blocked for suspected fraud / risk"),
    "NETWORK_ERROR": (INFRASTRUCTURE, "Network / connectivity failure"),
    "TIMEOUT": (INFRASTRUCTURE, "Bank response timed out / unknown outcome"),
    "BANK_DEGRADED": (INFRASTRUCTURE, "Bank under load / degraded"),
    "INVALID_DETAILS": (MERCHANT_CONFIG, "Incorrect payment details (CVV/account)"),
    "UNSUPPORTED_METHOD": (MERCHANT_CONFIG, "Payment method not supported"),
}

# Replaces the old FAILURE_REASONS dict (single source for human-readable reasons).
FAILURE_REASONS: dict[str, str] = {
    code: reason for code, (_cat, reason) in FAILURE_TYPES.items()
}

FAILURE_CATEGORIES: dict[str, str] = {
    code: cat for code, (cat, _r) in FAILURE_TYPES.items()
}

# Baseline failure rate per payment method (fraction, 0–1).
BASE_FAILURE_RATE: dict[str, float] = {
    "UPI": 0.06,        # user: 5–7%
    "CARD": 0.065,      # user: 5–8%
    "NETBANKING": 0.0628,  # avg of SBI 6.34 / HDFC 4.64 / Axis 5.05 / ICICI 4.34 / BOI 11.04
}

# Bank-state → failure multiplier applied to P(failure).
STATE_MULTIPLIERS: dict[str, float] = {
    "NORMAL": 1.0,
    "PEAK": 1.8,
    "DEGRADED": 3.5,
    "OUTAGE": 8.0,
}

# Conditional distribution among failures (the user's composition). Sums to 100.
# INSUFFICIENT_FUNDS (35%) and BANK_DEGRADED (load-driven below) are handled
# outside this list; the remaining weights therefore total 65% but are
# renormalized inside classify_failure.
COMPOSITION: list[tuple[str, float]] = [
    ("EXPIRED_PAYMENT_METHOD", 5),
    ("AUTHENTICATION_FAILURE", 4),
    ("CANCELLED", 2),
    ("ISSUER_DECLINE", 14),
    ("LIMIT_EXCEEDED", 8),
    ("RISK_DECLINE", 7),
    ("NETWORK_ERROR", 18),  # bumped 1.5x (was 12)
    ("TIMEOUT", 11),         # bumped 1.2x (was 9)
    ("INVALID_DETAILS", 3),
    ("UNSUPPORTED_METHOD", 1),
]

# Max P(failure) regardless of adjusters (a payment still usually succeeds).
MAX_FAILURE_RATE = 0.9

# Codes that only make sense for certain payment methods.  A code is eligible
# for a method only when that method is in its valid set; otherwise it is
# filtered out of the composition.  Codes not listed are valid for all methods.
_VALID_METHODS: dict[str, set[str]] = {
    "EXPIRED_PAYMENT_METHOD": {"CARD"},
    "AUTHENTICATION_FAILURE": {"UPI", "CARD"},
    "UNSUPPORTED_METHOD": {"CARD", "NETBANKING"},
}

# Legacy codes that were dummy placeholders → new taxonomy (for old DB rows).
LEGACY_CODE_MAP: dict[str, str] = {
    "HARD_DECLINE": "ISSUER_DECLINE",
    "EXPIRED_CARD": "EXPIRED_PAYMENT_METHOD",
    "FRAUD_BLOCK": "RISK_DECLINE",
    "BANK_OUTAGE": "BANK_DEGRADED",
}


def _clamp(p: float) -> float:
    return max(0.0, min(p, MAX_FAILURE_RATE))


def failure_probability(
    method: str,
    *,
    bank_state: str = "NORMAL",
    amount: float | None = None,
    balance: float | None = None,
    hour: int | None = None,
    load: float = 1.0,
) -> float:
    """Compute P(failure) for a payment.

    ``method`` is one of UPI / CARD / NETBANKING.  Optional adjusters:
    ``bank_state`` (NORMAL/PEAK/DEGRADED/OUTAGE), ``amount`` (transaction size),
    ``balance`` (account balance before the transaction), ``hour`` (0–23 local
    sim hour), ``load`` (1.0 = normal).
    """
    p = BASE_FAILURE_RATE.get(method, 0.06)

    # Bank state — biggest lever.
    p *= STATE_MULTIPLIERS.get(bank_state, 1.0)

    # Transaction amount: larger tickets carry more risk/limit exposure.
    if amount is not None and amount >= 10_000:
        p *= 1.6
    elif amount is not None and amount >= 2_000:
        p *= 1.2

    # Balance margin: thin coverage between balance and amount → more declines.
    if amount is not None and balance is not None and amount > 0:
        margin = balance / amount
        if margin < 0.5:
            p *= 1.6
        elif margin < 1.5:
            p *= 1.25

    # Peak hours: evening traffic bump.
    if hour is not None and 18 <= hour <= 22:
        p *= 1.35

    # Load — folded onto the same multiplier family as state.
    p *= load

    return _clamp(p)


def _renormalize(items: Sequence[tuple[str, float]]) -> list[tuple[str, float]]:
    total = sum(w for _c, w in items)
    if total <= 0:
        return list(items)
    return [(c, w / total * 100.0) for c, w in items]


def classifiable_codes(method: str) -> list[tuple[str, float]]:
    """COMPOSITION filtered by method (codes only valid for other methods are
    dropped), with BANK_DEGRADED excluded (handled separately).  Returns
    weighted (code, weight) pairs already renormalized."""
    eligible = [
        (c, w)
        for c, w in COMPOSITION
        if method in _VALID_METHODS.get(c, {method})
    ]
    return _renormalize(eligible)


def classify_failure(
    rng: Random,
    *,
    method: str,
    bank_state: str = "NORMAL",
) -> tuple[str, str]:
    """Pick a failure code + category for a payment that has already failed.

    INSUFFICIENT_FUNDS is chosen by the caller when there is real insolvency
    (the caller owns that decision).  Otherwise the reason is drawn from
    COMPOSITION filtered by method; while the bank is DEGRADED/OUTAGE a large
    share (60%) goes to BANK_DEGRADED.
    """
    if bank_state in ("DEGRADED", "OUTAGE"):
        # Boil over toward infra/load failure while the bank is sick.
        eligible = [(c, w) for c, w in classifiable_codes(method) if c != "BANK_DEGRADED"]
        eligible = _renormalize(eligible)
        degraded = [("BANK_DEGRADED", 60.0)]
        pool = degraded + [(c, w * 40.0 / 100.0) for c, w in eligible]
        pool = _renormalize(pool)
    else:
        pool = classifiable_codes(method)

    codes = [c for c, _w in pool]
    weights = [w for _c, w in pool]
    code = rng.choices(codes, weights=weights, k=1)[0]
    return code, FAILURE_CATEGORIES[code]


# Backward-compat alias used by tests / API before migration.
def reason_for(code: str) -> str:
    return FAILURE_REASONS.get(LEGACY_CODE_MAP.get(code, code), "Unknown error")
