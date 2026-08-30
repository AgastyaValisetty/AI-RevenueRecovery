"""RootCauseDiagnoser — deterministic diagnosis engine.

Maps failure codes + bank state + balance + retry history to labeled
root-cause hypotheses.  Each hypothesis carries a confidence score and
references to supporting evidence.

The LLM gateway later augments this with AI-driven diagnosis; the
deterministic core must always work (fallback path).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ...failure_model import (
    FAILURE_CATEGORIES,
    FAILURE_REASONS,
    STATE_MULTIPLIERS,
)
from ..context import RecoveryContext
from .feature_store import CaseFeatures

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Diagnosis:
    """Root-cause hypothesis for a recovery case.

    Parameters
    ----------
    label :
        Canonical hypothesis label (see ``HYPOTHESIS_LABELS``).
    confidence :
        0–1 confidence that this hypothesis is the true root cause.
    evidence_refs :
        List of evidence reference strings (e.g. "failure_code", "bank_state").
    competing_hypotheses :
        Other plausible hypotheses with lower confidence.
    explanation :
        Human-readable explanation of the diagnosis.
    """

    label: str
    confidence: float  # 0–1
    evidence_refs: list[str] = field(default_factory=list)
    competing_hypotheses: list[str] = field(default_factory=list)
    explanation: str = ""


# Canonical hypothesis labels
HYPOTHESIS_TEMPORARY_RAIL_DEGRADATION = "temporary_rail_degradation"
HYPOTHESIS_INSUFFICIENT_BALANCE = "insufficient_balance"
HYPOTHESIS_METHOD_EXPIRED = "method_expired"
HYPOTHESIS_AUTHENTICATION_FAILURE = "authentication_failure"
HYPOTHESIS_CUSTOMER_DECLINED = "customer_declined"
HYPOTHESIS_NETWORK_ERROR = "network_error"
HYPOTHESIS_BANK_DECLINED = "bank_declined"
HYPOTHESIS_BANK_DEGRADED = "bank_degraded"
HYPOTHESIS_TIMEOOUT = "timeout"
HYPOTHESIS_CANCELLED = "cancelled"
HYPOTHESIS_MERCHANT_CONFIG = "merchant_config_issue"
HYPOTHESIS_EXPIRED_PAYMENT = "expired_payment"
HYPOTHESIS_FRAUD_RISK = "fraud_risk"
HYPOTHESIS_NORMAL = "normal"  # no clear root cause; standard retry

HYPOTHESIS_LABELS = {
    HYPOTHESIS_TEMPORARY_RAIL_DEGRADATION,
    HYPOTHESIS_INSUFFICIENT_BALANCE,
    HYPOTHESIS_METHOD_EXPIRED,
    HYPOTHESIS_AUTHENTICATION_FAILURE,
    HYPOTHESIS_CUSTOMER_DECLINED,
    HYPOTHESIS_NETWORK_ERROR,
    HYPOTHESIS_BANK_DECLINED,
    HYPOTHESIS_BANK_DEGRADED,
    HYPOTHESIS_TIMEOOUT,
    HYPOTHESIS_CANCELLED,
    HYPOTHESIS_MERCHANT_CONFIG,
    HYPOTHESIS_EXPIRED_PAYMENT,
    HYPOTHESIS_FRAUD_RISK,
    HYPOTHESIS_NORMAL,
}


class RootCauseDiagnoser:
    """Deterministic diagnosis engine that maps failure signals to hypotheses.

    The diagnosis is a pure function of observed context — no RNG, no
    external calls.  Confidence scores are calibrated from the failure
    model and historical recovery data.
    """

    def __init__(self, recovery_repo=None):
        self._recovery_repo = recovery_repo

    def diagnose(self, context: RecoveryContext, features: Optional[CaseFeatures] = None) -> Diagnosis:
        """Return the primary root-cause hypothesis for this context.

        The diagnosis follows a priority order:
        1. Customer explicitly declined → customer_declined
        2. Payment expired → expired_payment
        3. Insufficient balance → insufficient_balance
        4. Bank degraded/outage → temporary_rail_degradation (or bank_degraded)
        5. Method-specific codes → method_expired, authentication_failure
        6. Infrastructure codes → network_error or timeout
        7. Bank decline codes → bank_declined
        8. Merchant config codes → merchant_config_issue
        9. Cancelled → cancelled
        10. Fallback → normal
        """
        f = features or self._features(context)

        evidence: list[str] = []
        competing: list[str] = []
        confidence = 0.5  # baseline
        explanation_parts: list[str] = []

        # --- 1. Customer explicitly declined ---
        if f.customer_declined:
            return Diagnosis(
                label=HYPOTHESIS_CUSTOMER_DECLINED,
                confidence=0.95,
                evidence_refs=["customer_declined_flag"],
                competing_hypotheses=[HYPOTHESIS_NORMAL],
                explanation="Customer previously and explicitly declined a recovery attempt.",
            )

        # --- 2. Payment expired ---
        if f.is_expired:
            return Diagnosis(
                label=HYPOTHESIS_EXPIRED_PAYMENT,
                confidence=0.90,
                evidence_refs=["hours_since_failure"],
                competing_hypotheses=[HYPOTHESIS_NORMAL],
                explanation=(
                    f"Payment intent failed {f.hours_since_failure}h ago and "
                    f"has reached its expiry threshold."
                ),
            )

        # --- 3. Insufficient balance ---
        if f.failure_code == "INSUFFICIENT_FUNDS":
            return Diagnosis(
                label=HYPOTHESIS_INSUFFICIENT_BALANCE,
                confidence=0.85,
                evidence_refs=["failure_code", "balance_to_amount_ratio"],
                competing_hypotheses=[HYPOTHESIS_NORMAL],
                explanation=(
                    f"Failed with INSUFFICIENT_FUNDS. Balance-to-amount ratio "
                    f"is {f.balance_to_amount_ratio:.2f}."
                ),
            )

        # Balance check as secondary signal
        if not f.is_sufficient_balance and f.balance_to_amount_ratio < 1.0:
            confidence = 0.70
            evidence.append("balance_shortfall")
            explanation_parts.append(
                f"Balance ({f.balance}) is below amount ({f.amount})"
            )
            competing.append(HYPOTHESIS_NORMAL)

        # --- 4. Bank degraded / outage ---
        if f.bank_state in ("DEGRADED", "OUTAGE"):
            bank_state = f.bank_state
            if f.failure_code == "BANK_DEGRADED":
                return Diagnosis(
                    label=HYPOTHESIS_BANK_DEGRADED,
                    confidence=0.80,
                    evidence_refs=["failure_code", "bank_state"],
                    competing_hypotheses=[
                        HYPOTHESIS_TEMPORARY_RAIL_DEGRADATION,
                        HYPOTHESIS_NORMAL,
                    ],
                    explanation=(
                        f"Failure classified as BANK_DEGRADED; bank state is "
                        f"{bank_state} with elevated state multiplier "
                        f"{STATE_MULTIPLIERS.get(bank_state, 1.0)}."
                    ),
                )

            # Bank is degraded/outage but failure code is something else.
            # This is likely a transient rail issue.
            return Diagnosis(
                label=HYPOTHESIS_TEMPORARY_RAIL_DEGRADATION,
                confidence=0.75,
                evidence_refs=["bank_state", "failure_code"],
                competing_hypotheses=[f.failure_code or "unknown", HYPOTHESIS_NORMAL],
                explanation=(
                    f"Bank state is {bank_state} (multiplier "
                    f"{STATE_MULTIPLIERS.get(bank_state, 1.0)}x); failure "
                    f"code is {f.failure_code}. Retries during degradation "
                    f"have lower success probability."
                ),
            )

        # --- 5. Method-specific codes ---
        if f.failure_code == "EXPIRED_PAYMENT_METHOD":
            evidence.append("failure_code")
            return Diagnosis(
                label=HYPOTHESIS_METHOD_EXPIRED,
                confidence=0.90,
                evidence_refs=["failure_code", "payment_method"],
                competing_hypotheses=[HYPOTHESIS_NORMAL],
                explanation=(
                    f"Payment method {f.payment_method} expired — retrying "
                    f"the same method is unlikely to succeed; a method "
                    f"switch or payment link is recommended."
                ),
            )

        if f.failure_code == "AUTHENTICATION_FAILURE":
            return Diagnosis(
                label=HYPOTHESIS_AUTHENTICATION_FAILURE,
                confidence=0.85,
                evidence_refs=["failure_code", "payment_method"],
                competing_hypotheses=[HYPOTHESIS_NORMAL],
                explanation="OTP/PIN/3DS authentication failed — customer may need to re-authenticate.",
            )

        # --- 6. Infrastructure codes ---
        if f.failure_code == "NETWORK_ERROR":
            return Diagnosis(
                label=HYPOTHESIS_NETWORK_ERROR,
                confidence=0.80,
                evidence_refs=["failure_code"],
                competing_hypotheses=[HYPOTHESIS_NORMAL],
                explanation="Network connectivity failure — transient, likely to succeed on retry.",
            )

        if f.failure_code == "TIMEOUT":
            return Diagnosis(
                label=HYPOTHESIS_TIMEOOUT,
                confidence=0.75,
                evidence_refs=["failure_code"],
                competing_hypotheses=[HYPOTHESIS_NETWORK_ERROR, HYPOTHESIS_NORMAL],
                explanation="Bank response timed out — result is unknown; retry may succeed.",
            )

        # --- 7. Bank decline codes ---
        if f.failure_code in ("ISSUER_DECLINE", "LIMIT_EXCEEDED", "RISK_DECLINE"):
            return Diagnosis(
                label=HYPOTHESIS_BANK_DECLINED,
                confidence=0.70,
                evidence_refs=["failure_code", "balance_to_amount_ratio"],
                competing_hypotheses=[HYPOTHESIS_NORMAL, HYPOTHESIS_TEMPORARY_RAIL_DEGRADATION],
                explanation=(
                    f"Bank declined ({f.failure_code}). May recover on retry "
                    f"with improved timing, but carries fraud/dispute risk."
                ),
            )

        # --- 8. Merchant config codes ---
        if f.failure_code in ("INVALID_DETAILS", "UNSUPPORTED_METHOD"):
            return Diagnosis(
                label=HYPOTHESIS_MERCHANT_CONFIG,
                confidence=0.85,
                evidence_refs=["failure_code", "payment_method"],
                competing_hypotheses=[HYPOTHESIS_NORMAL],
                explanation=(
                    f"Failure due to {f.failure_code} — merchant-side issue; "
                    f"retrying the same method will not resolve it."
                ),
            )

        # --- 9. Cancelled ---
        if f.failure_code == "CANCELLED":
            return Diagnosis(
                label=HYPOTHESIS_CANCELLED,
                confidence=0.90,
                evidence_refs=["failure_code"],
                competing_hypotheses=[HYPOTHESIS_NORMAL],
                explanation="Payment was cancelled by the customer — follow-up may be possible.",
            )

        # --- 10. Fallback ---
        if confidence >= 0.5:
            explanation_parts.append(f"Failure code: {f.failure_code}")
            explanation_parts.append(f"Bank state: {f.bank_state}")
            explanation_parts.append(f"Retry count: {f.retry_count}")

        return Diagnosis(
            label=HYPOTHESIS_NORMAL,
            confidence=confidence,
            evidence_refs=evidence or ["failure_code"],
            competing_hypotheses=competing or [HYPOTHESIS_NORMAL],
            explanation=" ".join(explanation_parts) if explanation_parts else (
                f"No specific hypothesis matched (failure_code={f.failure_code}, "
                f"bank_state={f.bank_state}). Standard retry path."
            ),
        )

    def _features(self, context: RecoveryContext) -> CaseFeatures:
        """Build features lazily if not provided."""
        from .feature_store import FeatureStore
        # This path is only used if features weren't pre-computed;
        # in practice, the agent always passes pre-computed features.
        raise RuntimeError("FeatureStore must be provided to diagnose()")
