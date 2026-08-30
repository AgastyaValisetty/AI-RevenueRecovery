"""SmartRecoveryEngine — the SARA (Smart Adaptive Revenue Agent).

Implements the RecoveryDecisionEngine protocol as a drop-in replacement for
BaselineRecoveryEngine.  The 9-step flow:

  1. Deterministic feature extraction (failures → features)
  2. Rail-health detection (reads bank_service status + failure patterns)
  3. Candidate action generation (legal actions only — no invention)
  4. Expected-value calculation (deterministic probability × amount − cost)
  5. LLM diagnosis + explanation (constrained context → typed JSON)
  6. LLM selects from controlled action menu + generates message
  7. Deterministic policy validator (checks all stop rules, budgets, consent)
  8. Schedule + execute via existing RecoveryScheduler / RecoveryActionExecutor
  9. Record outcome → audit trail → update memory/promise tracker

The LLM never directly decides settlements, budgets, retries, duplicate risk,
consent, or stop conditions — only diagnosis, explanation, and choosing from
a pre-approved action menu.  All financial decisions are enforced deterministically.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from ...config import Settings
from ..context import RecoveryContext
from ..domain import (
    RecoveryDecision,
    RecoveryDecisionEngine,
    RecoveryActionType,
)
from ..repository import RecoveryActionRepository
from .action_value import ActionValueCalculator, CandidateAction, ExpectedValue
from .audit import AuditEvent, AuditEventWriter, hash_input_snapshot
from .diagnosis import RootCauseDiagnoser, Diagnosis
from .explainer import ExplanationCard, Explainer
from .feature_store import CaseFeatures, FeatureStore
from .llm_gateway import LLMGateway, LLMResponse
from .memory import RecoveryMemoryRepository
from .planner import ActionPlanner, PlannedAction
from .policy import PolicyValidator
from .promise_tracker import PromiseTracker

logger = logging.getLogger(__name__)


class SmartRecoveryEngine(RecoveryDecisionEngine):
    """The Smart Adaptive Revenue Agent (SARA).

    A drop-in replacement for BaselineRecoveryEngine that implements
    AI-assisted recovery with deterministic policy enforcement.

    Parameters
    ----------
    recovery_repo :
        For querying prior actions (retry count, declines, duplicates).
    settings :
        Application settings (contains bank_url, llm config, thresholds).
    feature_store :
        For extracting deterministic CaseFeatures from RecoveryContext.
    calculator :
        For computing expected net value of candidate actions.
    policy :
        For validating actions against stop rules and budgets.
    planner :
        For ranking candidates and selecting the next-best action.
    diagnoser :
        For root-cause hypothesis generation.
    explainer :
        For generating human-readable explanations.
    llm_gateway :
        For LLM-based diagnosis, explanation, and message generation.
    memory_repo :
        For customer/merchant memory persistence.
    promise_tracker :
        For promise-to-pay lifecycle management.
    auditor :
        For recording audit trail events.
    run_id :
        The simulation run UUID (for audit linkage).
    """

    def __init__(
        self,
        recovery_repo: RecoveryActionRepository,
        settings: Settings,
        *,
        feature_store: Optional[FeatureStore] = None,
        calculator: Optional[ActionValueCalculator] = None,
        policy: Optional[PolicyValidator] = None,
        planner: Optional[ActionPlanner] = None,
        diagnoser: Optional[RootCauseDiagnoser] = None,
        explainer: Optional[Explainer] = None,
        llm_gateway: Optional[LLMGateway] = None,
        memory_repo: Optional[RecoveryMemoryRepository] = None,
        promise_tracker: Optional[PromiseTracker] = None,
        auditor: Optional[AuditEventWriter] = None,
        max_retries: int = 10,
        min_enpv: Decimal = Decimal("0.00"),
        run_id: Optional[UUID] = None,
    ):
        self._recovery_repo = recovery_repo
        self._settings = settings
        self._run_id = run_id

        # Build or use provided dependencies
        self._feature_store = feature_store or FeatureStore(
            recovery_repo=recovery_repo, max_retries=max_retries
        )
        self._calculator = calculator or ActionValueCalculator(max_retries=max_retries)
        self._diagnoser = diagnoser or RootCauseDiagnoser()
        self._llm_gateway = llm_gateway
        self._explainer = explainer or Explainer(llm_gateway=llm_gateway)
        self._memory_repo = memory_repo
        self._promise_tracker = promise_tracker

        self._policy = policy or PolicyValidator(
            recovery_repo=recovery_repo,
            memory_repo=memory_repo,
            promise_tracker=promise_tracker,
            max_retries=max_retries,
            min_enpv=min_enpv,
        )
        self._planner = planner or ActionPlanner(
            calculator=self._calculator,
            policy=self._policy,
        )
        self._auditor = auditor or AuditEventWriter(recovery_repo._db)

    def decide(self, context: RecoveryContext) -> RecoveryDecision:
        """Main decision entry point — implements the 9-step SARA flow.

        Returns a RecoveryDecision (RETRY / SEND_PAYMENT_LINK / SEND_NOTIFICATION / STOP)
        compatible with the existing RecoveryScheduler.
        """
        case_id = UUID(context.intent_id)

        # --- Step 1: Feature extraction ---
        features = self._feature_store.extract(context)

        # --- Step 2: Rail health detection ---
        rail_health = self._check_rail_health(context, features)

        # --- Step 3 & 4: Candidate generation + ENPV ---
        candidates = self._calculator.generate_candidates(context, features)
        candidate_evs = []
        for candidate in candidates:
            ev = self._calculator.compute(candidate, context, features)
            candidate_evs.append((candidate, ev))

        # --- Step 5: LLM diagnosis ---
        diagnosis = self._diagnose(context, features, rail_health)

        # --- Step 6: LLM selects from action menu ---
        # The LLM provides a *recommendation* — the deterministic planner
        # makes the final decision by ranking + policy validation.
        llm_recommendation = self._llm_recommend(
            context, features, diagnosis, candidate_evs, case_id
        )

        # --- Steps 6 & 7: Plan (rank + validate) ---
        planned = self._planner.plan(context, features)
        # The LLM is an agentic strategist: it may ask for a more aggressive
        # retry than the default ENPV winner.  It can only choose from the
        # typed candidate menu and the policy gate still has the final say.
        planned = self._apply_agentic_recommendation(
            planned, llm_recommendation, candidate_evs, context, features
        )

        # --- Step 7: Policy validation (already done inside planner) ---
        # The planner returns a policy-validated planned action.

        # --- Step 8: Build recovery decision ---
        recovery_decision = self._planner.to_recovery_decision(planned)

        # --- Step 9: Audit ---
        self._record_audit(
            case_id=case_id,
            context=context,
            features=features,
            diagnosis=diagnosis,
            planned=planned,
            llm_recommendation=llm_recommendation,
        )

        # Log the decision
        logger.info(
            "SARA decision for intent %s: %s at %s — %s",
            context.intent_id,
            recovery_decision.action.value,
            recovery_decision.scheduled_for,
            recovery_decision.reason,
        )

        return recovery_decision

    def _apply_agentic_recommendation(
        self, planned, recommendation, candidate_evs, context, features
    ):
        if recommendation is None or not isinstance(recommendation.content, dict):
            return planned
        requested = recommendation.content.get("action_type")
        if requested != "RETRY" or planned.candidate.action_type == "RETRY":
            return planned
        retry_pair = next(((c, ev) for c, ev in candidate_evs if c.action_type == "RETRY"), None)
        if retry_pair is None:
            return planned
        candidate, expected = retry_pair
        policy_result = self._policy.validate(candidate, context, features, expected)
        if not policy_result.allowed or policy_result.should_stop:
            return planned
        scheduled_for = self._planner._compute_schedule_time(
            candidate, expected, features, context.current_simulation_time
        )
        return PlannedAction(
            candidate=candidate,
            expected_value=expected,
            policy_result=policy_result,
            scheduled_for=scheduled_for,
            reason=f"agentic_retry:{recommendation.content.get('rationale', 'LLM selected retry')}",
        )

    def decide_with_explanation(
        self, context: RecoveryContext
    ) -> tuple[RecoveryDecision, ExplanationCard]:
        """Like ``decide`` but also returns a full explanation card.

        Used by the API endpoints that need to surface reasoning to the user.
        """
        # Run the standard decision flow
        decision = self.decide(context)

        # Rebuild components for explanation (they're cheap and deterministic)
        features = self._feature_store.extract(context)
        diagnosis = self._diagnose(
            context, features,
            self._check_rail_health(context, features)
        )
        candidates = self._calculator.generate_candidates(context, features)
        candidate_evs = [
            (c, self._calculator.compute(c, context, features))
            for c in candidates
        ]

        # Re-plan to get the full PlannedAction with policy result
        planned = self._planner.plan(context, features)

        # Find the matching expected value
        ev = None
        for c, e in candidate_evs:
            if c.action_type == planned.candidate.action_type:
                ev = e
                break

        if ev is None:
            ev = ExpectedValue(
                action_type="STOP",
                recovery_probability=0.0,
                expected_gross_recovery=Decimal("0"),
                retry_cost=Decimal("0"),
                incentive_cost=Decimal("0"),
                channel_cost=Decimal("0"),
                friction_penalty=Decimal("0"),
                risk_penalty=Decimal("0"),
                expected_net_value=Decimal("0"),
                earliest_at=planned.scheduled_for or datetime.now(timezone.utc),
            )

        if planned.candidate.action_type == "STOP":
            explanation_card = self._explainer.explain_stop(
                context, features, diagnosis, planned.reason or "unknown"
            )
        else:
            explanation_card = self._explainer.explain(
                context, features, diagnosis, planned, ev
            )

        return decision, explanation_card

    @property
    def max_retries(self) -> int:
        return self._calculator._max_retries

    @property
    def retry_interval_hours(self) -> int:
        return 1

    # ------------------------------------------------------------------ #
    # Internal steps
    # ------------------------------------------------------------------ #

    def _check_rail_health(self, context: RecoveryContext, features: CaseFeatures) -> Optional[str]:
        """Check if the payment rail is degraded.

        Uses bank_state from the context (set by RecoveryContextBuilder).
        Falls back to HTTP polling of bank_service if bank_state is None.
        """
        if context.bank_state:
            if context.bank_state in ("DEGRADED", "OUTAGE"):
                logger.info(
                    "Rail degradation detected for intent %s: %s",
                    context.intent_id,
                    context.bank_state,
                )
            return context.bank_state
        return "NORMAL"

    def _diagnose(
        self,
        context: RecoveryContext,
        features: CaseFeatures,
        rail_health: Optional[str],
    ) -> Diagnosis:
        """Step 5: Root-cause diagnosis (deterministic + LLM-enhanced).

        First runs the deterministic rule-based diagnoser, then optionally
        enhances with LLM if in live mode.
        """
        # Deterministic diagnosis (always runs)
        diagnosis = self._diagnoser.diagnose(context, features)

        # LLM-enhanced diagnosis (if available)
        if self._llm_gateway is not None and self._llm_gateway.is_live:
            try:
                llm_diag = self._llm_diagnose(context, features, diagnosis, rail_health)
                # Use LLM diagnosis if it agrees or is more confident
                if llm_diag.confidence > diagnosis.confidence:
                    return Diagnosis(
                        label=llm_diag.label if hasattr(llm_diag, 'label') else diagnosis.label,
                        confidence=llm_diag.confidence,
                        evidence_refs=diagnosis.evidence_refs,
                        competing_hypotheses=diagnosis.competing_hypotheses,
                        explanation=getattr(llm_diag, 'explanation', diagnosis.explanation),
                    )
            except Exception as exc:
                logger.warning("LLM diagnosis failed for intent %s: %s", context.intent_id, exc)

        return diagnosis

    def _llm_diagnose(
        self,
        context: RecoveryContext,
        features: CaseFeatures,
        diagnosis: Diagnosis,
        rail_health: Optional[str],
    ) -> Any:
        """Call the LLM for diagnosis enhancement."""
        input_snapshot = {
            "intent_id": context.intent_id,
            "person_id": context.person.person_id,
            "amount": str(context.intent_amount),
            "payment_method": context.intent_payment_method,
            "failure_code": context.failure_code,
            "failure_reason": context.failure_reason,
            "bank_state": context.bank_state,
            "balance": str(context.balance.current_balance),
            "is_sufficient_balance": features.is_sufficient_balance,
            "retry_count": features.retry_count,
            "failure_category": features.failure_category,
            "hours_since_failure": features.hours_since_failure,
            "determinative_diagnosis": diagnosis.label,
            "diagnosis_confidence": diagnosis.confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        system_prompt = """You are SARA, a Smart Adaptive Revenue Agent.
Diagnose why a payment failed and suggest the best recovery approach.
Respond in JSON format with a 'label', 'confidence' (0-1), 'evidence_refs',
'competing_hypotheses', and 'explanation'."""

        user_prompt = f"""A payment of ₹{context.intent_amount} via {context.intent_payment_method}
for {context.merchant.name} failed with code {context.failure_code}: {context.failure_reason}.
Bank state: {context.bank_state or 'NORMAL'}. Balance: ₹{context.balance.current_balance}.
Retries so far: {features.retry_count}. Diagnosis label: {diagnosis.label}.
Diagnose the root cause and explain your reasoning."""

        schema = {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                "competing_hypotheses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                    },
                },
                "explanation": {"type": "string"},
            },
            "required": ["label", "confidence", "evidence_refs", "competing_hypotheses", "explanation"],
        }

        resp = self._llm_gateway.diagnose(
            case_id=UUID(context.intent_id),
            prompt=user_prompt,
            system_prompt=system_prompt,
            expected_schema=schema,
            input_snapshot=input_snapshot,
        )

        content = resp.content
        return type("LLMDiagnosis", (), {
            "label": content.get("label", diagnosis.label),
            "confidence": content.get("confidence", diagnosis.confidence),
            "explanation": content.get("explanation", diagnosis.explanation),
        })()

    def _llm_recommend(
        self,
        context: RecoveryContext,
        features: CaseFeatures,
        diagnosis: Diagnosis,
        candidate_evs: list[tuple[CandidateAction, ExpectedValue]],
        case_id: UUID,
    ) -> Optional[LLMResponse]:
        """Step 6: Ask the LLM to recommend an action from the candidate menu.

        The LLM recommendation is advisory — the deterministic planner makes
        the final decision.  The LLM never overrides policy or financial checks.
        """
        if self._llm_gateway is None or not self._llm_gateway.is_live:
            return None

        candidate_menu = [
            {
                "action_type": c.action_type,
                "description": c.description,
                "expected_net_value": str(ev.expected_net_value),
                "recovery_probability": ev.recovery_probability,
            }
            for c, ev in candidate_evs
        ]

        input_snapshot = {
            "intent_id": context.intent_id,
            "person_id": context.person.person_id,
            "failure_code": context.failure_code,
            "bank_state": context.bank_state,
            "diagnosis": diagnosis.label,
            "candidate_actions": candidate_menu,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        system_prompt = """You are SARA, a Smart Adaptive Revenue Agent.
Given the context and candidate actions with their expected values,
recommend the best action. You can only choose from the provided menu.
Respond in JSON format with 'action_type' and 'rationale'."""

        user_prompt = f"""Diagnosis: {diagnosis.explanation}
Failure: {context.failure_code} ({context.failure_reason})
Bank state: {context.bank_state or 'NORMAL'}
Customer balance: ₹{context.balance.current_balance}
Retries so far: {features.retry_count}
Customer fatigue: {features.customer_fatigue_score}/100

Candidate actions:
{json.dumps(candidate_menu, indent=2)}

Which action do you recommend? You MUST choose from the candidates above."""

        try:
            return self._llm_gateway.diagnose(
                case_id=case_id,
                prompt=user_prompt,
                system_prompt=system_prompt,
                input_snapshot=input_snapshot,
            )
        except Exception as exc:
            logger.warning("LLM recommendation failed for intent %s: %s", context.intent_id, exc)
            return None

    def _record_audit(
        self,
        *,
        case_id: UUID,
        context: RecoveryContext,
        features: CaseFeatures,
        diagnosis: Diagnosis,
        planned: PlannedAction,
        llm_recommendation: Optional[LLMResponse],
    ) -> None:
        """Step 9: Record the full audit trail for this decision."""
        input_snapshot = {
            "intent_id": context.intent_id,
            "person_id": context.person.person_id,
            "merchant_id": context.merchant.merchant_id,
            "amount": str(context.intent_amount),
            "payment_method": context.intent_payment_method,
            "failure_code": context.failure_code,
            "bank_state": context.bank_state,
            "retry_count": features.retry_count,
            "failure_category": features.failure_category,
            "customer_fatigue_score": features.customer_fatigue_score,
            "salary_deposit_day": features.salary_deposit_day,
            "salary_deposit_hour": features.salary_deposit_hour,
            "diagnosis_label": diagnosis.label,
            "diagnosis_confidence": diagnosis.confidence,
            "action_type": planned.candidate.action_type,
            "expected_net_value": str(planned.expected_value.expected_net_value),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        evidence_refs = {
            "context_version": "1.0",
            "features": ["failure_category", "balance_to_amount_ratio", "retry_count"],
            "diagnosis": [diagnosis.label],
            "policy_checks": [c.name for c in planned.policy_result.checks],
        }

        decision_json = {
            "action_type": planned.candidate.action_type,
            "scheduled_for": planned.scheduled_for.isoformat() if planned.scheduled_for else None,
            "reason": planned.reason,
            "retry_number": planned.candidate.retry_number,
            "expected_net_value": str(planned.expected_value.expected_net_value),
            "recovery_probability": planned.expected_value.recovery_probability,
        }

        policy_checks_json = {
            c.name: {
                "passed": c.passed,
                "detail": c.detail,
            }
            for c in planned.policy_result.checks
        }

        if llm_recommendation is not None:
            decision_json["llm_recommendation"] = llm_recommendation.content

        audit_event = AuditEvent.build(
            case_id=case_id,
            run_id=self._run_id,
            actor="agent",
            event_type="decision",
            decision=decision_json,
            policy_checks=policy_checks_json,
            evidence_refs=evidence_refs,
            outcome=planned.candidate.action_type,
            idempotency_key=hash_input_snapshot(input_snapshot)[:32],
            input_snapshot=input_snapshot,
        )

        self._auditor.write(audit_event)
