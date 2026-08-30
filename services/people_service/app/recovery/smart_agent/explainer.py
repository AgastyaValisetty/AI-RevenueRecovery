"""Explainer — generates human-readable explanation cards for recovery decisions.

Composes structured explanation from:
  1. Deterministic features (failure category, ENPV, retry count, fatigue).
  2. LLM-generated root-cause diagnosis and natural-language message.
  3. Policy check results (why an action was allowed or blocked).

Output is a structured dict that can be rendered in the UI or API response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from ...domain import ConsentState
from ..context import RecoveryContext
from .action_value import ExpectedValue, CandidateAction
from .diagnosis import Diagnosis
from .feature_store import CaseFeatures
from .policy import PolicyResult
from .planner import PlannedAction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExplanationCard:
    """Structured explanation of a recovery decision.

    Parameters
    ----------
    case_id :
        The associated recovery case UUID.
    timestamp :
        When this explanation was generated.
    diagnosis :
        Root-cause diagnosis from the LLM diagnosis engine.
    why_this_action :
        Human-readable explanation of why this action was chosen.
    key_factors :
        List of weighted factors that influenced the decision.
    policy_summary :
        Summary of policy checks (passed/failed).
    action_details :
        Details about the chosen action (type, cost, expected value).
    customer_message :
        Optional customer-facing message (if action involves outreach).
    """

    case_id: UUID
    timestamp: datetime
    diagnosis: Optional[Diagnosis]
    why_this_action: str
    key_factors: list[dict[str, Any]]
    policy_summary: dict[str, Any]
    action_details: dict[str, Any]
    customer_message: Optional[str] = None


class Explainer:
    """Generates explanation cards for recovery decisions.

    Parameters
    ----------
    llm_gateway :
        Optional LLM gateway for generating natural-language explanations.
        If None, uses deterministic explanations only.
    """

    def __init__(self, llm_gateway=None):
        self._llm = llm_gateway

    def explain(
        self,
        context: RecoveryContext,
        features: CaseFeatures,
        diagnosis: Diagnosis,
        planned: PlannedAction,
        ev: ExpectedValue,
    ) -> ExplanationCard:
        """Build a full explanation card for the chosen action."""
        now_ts = datetime.now(planned.scheduled_for.tzinfo) if planned.scheduled_for else datetime.now()

        # Build key factors — ordered by importance
        key_factors = self._build_key_factors(context, features, ev, diagnosis)

        # Build policy summary
        policy_summary = self._build_policy_summary(planned.policy_result)

        # Build action details
        action_details = self._build_action_details(planned.candidate, ev, features)

        # Build why-this-action explanation
        why_this = self._build_why_this_action(diagnosis, planned, features, ev)

        # Build customer message (if outreach action)
        customer_message = self._build_customer_message(
            context, features, diagnosis, planned, now_ts
        )

        return ExplanationCard(
            case_id=UUID(context.intent_id),
            timestamp=now_ts,
            diagnosis=diagnosis,
            why_this_action=why_this,
            key_factors=key_factors,
            policy_summary=policy_summary,
            action_details=action_details,
            customer_message=customer_message,
        )

    def explain_stop(
        self,
        context: RecoveryContext,
        features: CaseFeatures,
        diagnosis: Diagnosis,
        stop_reason: str,
    ) -> ExplanationCard:
        """Build an explanation card for a STOP decision."""
        now_ts = datetime.now()
        key_factors = self._build_key_factors(context, features, None, diagnosis)

        stop_ev = ExpectedValue(
            action_type="STOP",
            recovery_probability=0.0,
            expected_gross_recovery=__import__("decimal").Decimal("0"),
            retry_cost=__import__("decimal").Decimal("0"),
            incentive_cost=__import__("decimal").Decimal("0"),
            channel_cost=__import__("decimal").Decimal("0"),
            friction_penalty=__import__("decimal").Decimal("0"),
            risk_penalty=__import__("decimal").Decimal("0"),
            expected_net_value=__import__("decimal").Decimal("0"),
            earliest_at=now_ts,
        )

        candidate = CandidateAction(
            action_type="STOP",
            description=f"Stop recovery — {stop_reason}",
            amount=features.amount,
        )

        policy_result = PolicyResult(
            allowed=False,
            should_stop=True,
            stop_reason=stop_reason,
            checks=[],
        )

        return ExplanationCard(
            case_id=UUID(context.intent_id),
            timestamp=now_ts,
            diagnosis=diagnosis,
            why_this_action=f"Recovery stopped: {stop_reason}",
            key_factors=key_factors,
            policy_summary=self._build_policy_summary(policy_result),
            action_details=self._build_action_details(candidate, stop_ev, features),
            customer_message=None,
        )

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_key_factors(
        context: RecoveryContext,
        features: CaseFeatures,
        ev: Optional[ExpectedValue],
        diagnosis: Diagnosis,
    ) -> list[dict[str, Any]]:
        """Build a list of key factors influencing the decision, with weights."""
        factors: list[dict[str, Any]] = []

        # Diagnosis confidence
        factors.append({
            "factor": "root_cause",
            "value": diagnosis.label,
            "confidence": diagnosis.confidence,
            "weight": 0.30,
        })

        # Failure category
        factors.append({
            "factor": "failure_category",
            "value": features.failure_category,
            "weight": 0.15,
        })

        # Balance sufficiency
        factors.append({
            "factor": "balance_sufficient",
            "value": features.is_sufficient_balance,
            "weight": 0.10,
        })

        # Retry count
        factors.append({
            "factor": "retry_count",
            "value": features.retry_count,
            "max": features.max_retries,
            "weight": 0.10,
        })

        # Bank state / rail health
        factors.append({
            "factor": "bank_state",
            "value": features.bank_state or "NORMAL",
            "weight": 0.15,
        })

        # Customer fatigue
        factors.append({
            "factor": "customer_fatigue",
            "value": features.customer_fatigue_score,
            "threshold": 5,
            "weight": 0.10,
        })

        # Expected value (if available)
        if ev is not None:
            factors.append({
                "factor": "expected_net_value",
                "value": str(ev.expected_net_value),
                "recovery_probability": ev.recovery_probability,
                "weight": 0.20,
            })

        return factors

    @staticmethod
    def _build_policy_summary(policy_result: PolicyResult) -> dict[str, Any]:
        """Summarize policy check results."""
        passed = sum(1 for c in policy_result.checks if c.passed)
        failed = sum(1 for c in policy_result.checks if not c.passed)
        return {
            "allowed": policy_result.allowed,
            "should_stop": policy_result.should_stop,
            "stop_reason": policy_result.stop_reason,
            "checks_passed": passed,
            "checks_failed": failed,
            "total_checks": len(policy_result.checks),
            "details": [c.name for c in policy_result.checks if not c.passed],
        }

    @staticmethod
    def _build_action_details(
        candidate: CandidateAction, ev: ExpectedValue, features: CaseFeatures
    ) -> dict[str, Any]:
        """Build details about the chosen action."""
        return {
            "action_type": candidate.action_type,
            "description": candidate.description,
            "retry_number": candidate.retry_number,
            "retry_after_hours": candidate.retry_after_hours,
            "amount": str(candidate.amount),
            "expected_gross_recovery": str(ev.expected_gross_recovery),
            "recovery_probability": ev.recovery_probability,
            "retry_cost": str(ev.retry_cost),
            "incentive_cost": str(ev.incentive_cost),
            "channel_cost": str(ev.channel_cost),
            "friction_penalty": str(ev.friction_penalty),
            "risk_penalty": str(ev.risk_penalty),
            "expected_net_value": str(ev.expected_net_value),
            "earliest_at": ev.earliest_at.isoformat() if ev.earliest_at else None,
            "payment_method": features.payment_method,
            "failure_code": features.failure_code,
            "bank_state": features.bank_state,
        }

    @staticmethod
    def _build_why_this_action(
        diagnosis: Diagnosis, planned: PlannedAction, features: CaseFeatures, ev: ExpectedValue
    ) -> str:
        """Build a human-readable explanation of why this action was chosen."""
        parts = []

        parts.append(f"Root cause: {diagnosis.label} (confidence {diagnosis.confidence:.0%}).")

        if planned.candidate.action_type == "RETRY":
            parts.append(
                f"Retry #{planned.candidate.retry_number} chosen — "
                f"expected net value of {ev.expected_net_value} INR "
                f"({ev.recovery_probability:.1%} recovery probability)."
            )
            if ev.earliest_at is not None:
                parts.append(
                    f"Scheduled for {ev.earliest_at.isoformat()} to respect "
                    f"retry delay and rail health."
                )
        elif planned.candidate.action_type == "SEND_PAYMENT_LINK":
            parts.append("Payment link sent — customer can pay directly, bypassing the failed method.")
        elif planned.candidate.action_type == "SEND_NOTIFICATION":
            parts.append("Notification sent — soft nudge to update payment method.")
        else:
            parts.append(f"Action chosen: {planned.candidate.action_type}.")

        if features.customer_fatigue_score > 0:
            parts.append(
                f"Customer fatigue score: {features.customer_fatigue_score:.0f}/100 "
                f"(higher → fewer contacts preferred)."
            )

        return " ".join(parts)

    def _build_customer_message(
        self,
        context: RecoveryContext,
        features: CaseFeatures,
        diagnosis: Diagnosis,
        planned: PlannedAction,
        now_ts: datetime,
    ) -> Optional[str]:
        """Build a customer-facing message for outreach actions.

        If LLM is available (live mode), generate a personalized message.
        Otherwise, use a deterministic template.
        """
        if planned.candidate.action_type not in ("SEND_PAYMENT_LINK", "SEND_NOTIFICATION"):
            return None

        # Try LLM for message generation
        if self._llm is not None and self._llm.is_live:
            try:
                input_snapshot = {
                    "intent_id": context.intent_id,
                    "person_id": context.person.person_id,
                    "amount": str(context.intent_amount),
                    "failure_code": context.failure_code,
                    "diagnosis": diagnosis.label,
                    "tone": "polite",
                    "current_time": now_ts.isoformat(),
                }
                llm_resp = self._llm.generate_message(
                    case_id=UUID(context.intent_id),
                    prompt=self._build_message_prompt(context, features, diagnosis),
                    system_prompt=self._build_message_system_prompt(),
                    input_snapshot=input_snapshot,
                )
                return llm_resp.content.get("message")
            except Exception as exc:
                logger.warning("LLM message generation failed: %s — using fallback", exc)

        # Deterministic fallback
        return self._fallback_message(context, features, diagnosis, planned)

    @staticmethod
    def _build_message_system_prompt() -> str:
        return (
            "You are a polite, professional payment recovery assistant. "
            "Generate a brief, friendly message (1-2 sentences) asking the customer "
            "to resolve a payment issue. Do not mention internal system details. "
            "Use the JSON format: {\"message\": \"...\"}."
        )

    @staticmethod
    def _build_message_prompt(
        context: RecoveryContext, features: CaseFeatures, diagnosis: Diagnosis
    ) -> str:
        return (
            f"A payment of {context.intent_amount} INR for "
            f"{context.merchant.name} could not be processed. "
            f"Reason: {diagnosis.explanation}. "
            f"Please update your payment method or use the payment link to complete this payment."
        )

    @staticmethod
    def _fallback_message(
        context: RecoveryContext, features: CaseFeatures, diagnosis: Diagnosis, planned: PlannedAction
    ) -> str:
        if planned.candidate.action_type == "SEND_PAYMENT_LINK":
            return (
                f"We noticed a payment issue with your recent {context.merchant.name} "
                f"transaction of {context.intent_amount}. "
                f"Please use the payment link to complete your payment."
            )
        return (
            f"This is a reminder about a pending payment of {context.intent_amount} "
            f"for {context.merchant.name}. Please update your payment method to continue."
        )
