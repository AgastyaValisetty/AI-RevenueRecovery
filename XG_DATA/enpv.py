"""ENPV — Expected Net Present Value of attempting a recovery retry.

The formula mirrors the ExpectedValue dataclass in
services/people_service/app/domain.py:

    ENPV = P_hat * amount
         - retry_cost
         - incentive_cost
         - channel_cost
         - friction_penalty
         - risk_penalty

All cost constants are tunable here. The defaults are calibrated against
SARA's most recent parallel experiment
(services/people_service/experiments/parallel_77e96112_20260903_102558.txt):
the Smart Agent run reported total_cost = 222.50 INR across 89 retries
(2.50 INR per retry on average), so RETRY_COST is the only non-zero component.
INCOME_BRACKET-multiplied incentives, outreach channels, and risk/friction
penalties are placeholders that can be wired up as SARA grows those engines.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Union

# --------------------------------------------------------------------------- #
# Cost constants (all Decimal so amount math stays exact).
# --------------------------------------------------------------------------- #

# Per-retry gateway/processing cost. Default 2.50 INR matches the Smart Agent
# experiment's reported per-retry average.
RETRY_COST: Decimal = Decimal("2.50")

# Discount / coupon offered to a customer to nudge recovery. SARA does not yet
# emit incentives (always 0 in the experiment reports), so this stays at zero.
INCENTIVE_COST: Decimal = Decimal("0.00")

# Outreach-channel cost (SMS, WhatsApp, IVR, email). SARA currently does not
# call SEND_PAYMENT_LINK or SEND_NOTIFICATION, so this stays at zero.
CHANNEL_COST: Decimal = Decimal("0.00")

# Penalty for customer annoyance / opt-out risk. Placeholder for the day SARA
# starts tracking customer_fatigue.
FRICTION_PENALTY: Decimal = Decimal("0.00")

# Penalty for risk-of-decline or chargeback. Placeholder for the day SARA
# starts tracking fraud_or_dispute_flags.
RISK_PENALTY: Decimal = Decimal("0.00")


Number = Union[int, float, str, Decimal]


def compute_enpv(predicted_probability: Number, amount: Number) -> Decimal:
    """Compute ENPV for one transaction.

    Parameters
    ----------
    predicted_probability:
        P_hat from the XGBoost regressor. Anything outside [0, 1] is clipped
        to the valid range so a misbehaving model cannot produce nonsense
        ENPVs.
    amount:
        Original failed transaction amount in INR.

    Returns
    -------
    Decimal
        Expected net value in INR. Positive = net-positive to attempt a
        retry; negative = net-negative (do not retry).
    """
    # Clip probability into [0, 1].
    try:
        p = float(predicted_probability)
    except (TypeError, ValueError):
        raise ValueError(
            f"predicted_probability must be numeric, got {predicted_probability!r}"
        )
    if p < 0.0:
        p = 0.0
    elif p > 1.0:
        p = 1.0

    # Cast amount to Decimal for exact arithmetic.
    amount_dec = amount if isinstance(amount, Decimal) else Decimal(str(amount))

    gross = Decimal(str(p)) * amount_dec
    return gross - RETRY_COST - INCENTIVE_COST - CHANNEL_COST - FRICTION_PENALTY - RISK_PENALTY


__all__ = [
    "RETRY_COST",
    "INCENTIVE_COST",
    "CHANNEL_COST",
    "FRICTION_PENALTY",
    "RISK_PENALTY",
    "compute_enpv",
]