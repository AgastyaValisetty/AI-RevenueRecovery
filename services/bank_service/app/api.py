"""Bank Service API.

Provides payment authorization to LazerPay over HTTP.

Endpoint contract:
    POST /api/authorize  — authorize a payment
    GET  /api/status     — service health and bank state metrics
    POST /api/bank-state — manually transition bank state (testing)

Authorization flow:
    1. Look up the bank (RupeeBank) and its policy
    2. Calculate source account balance from ledger_entries
    3. Hard check: if balance < amount → INSUFFICIENT_FUNDS (FAILED)
    4. Roll for delivery issues:
       - timeout_rate → unknown_outcome=True  (bank may have authorized)
       - network_error_rate → NETWORK_ERROR    (FAILED)
    5. Roll for authorization success (adjusted by bank state multiplier)
    6. If not success: pick weighted failure code
    7. Record transaction metric + maybe transition bank state
    8. Return result with simulated response_time_ms (no real sleep)
"""
import hashlib
import json
import logging
import random
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel

from .config import Settings
from .database import Database
from .domain import BankPolicy, BankState, BankStatus, FailureCode
from .repos import BankRepository

logger = logging.getLogger("bank")

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- #
# Dependency providers
# --------------------------------------------------------------------------- #

def get_bank_repo(request: Request) -> BankRepository:
    return BankRepository(request.app.state.db)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


# --------------------------------------------------------------------------- #
# Pydantic request / response models
# --------------------------------------------------------------------------- #

class AuthorizeRequest(BaseModel):
    attempt_id: str
    person_id: str
    amount: str  # decimal string for precision
    payment_method: str
    source_account_id: str
    simulation_timestamp: str | None = None
    correlation_id: str | None = None


class AuthorizeResponse(BaseModel):
    success: bool
    failure_code: str | None = None
    failure_reason: str | None = None
    response_time_ms: int
    bank_state: str
    source_balance: str
    authorized_at: str
    settlement_account_id: str | None = None
    unknown_outcome: bool = False


class BankStatusResponse(BaseModel):
    bank_id: str
    name: str
    current_state: str
    authorization_success_rate: float
    timeout_rate: float
    issuer_decline_rate: float
    network_error_rate: float
    settlement_account_id: str | None = None
    bank_balance: float = 0.0
    success_rate_1min: float = 0.0
    failure_rate_1min: float = 0.0
    transactions_last_minute: int = 0
    failures_last_minute: int = 0


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _default_bank() -> BankPolicy:
    return BankPolicy(
        bank_id=str(uuid4()),
        name="RupeeBank",
        authorization_success_rate=99.1,
        timeout_rate=0.3,
        issuer_decline_rate=0.4,
        network_error_rate=0.2,
        current_state=BankState.NORMAL,
        state_multipliers={
            "NORMAL": 1.0,
            "PEAK": 2.0,
            "DEGRADED": 5.0,
            "OUTAGE": 50.0,
        },
    )


def _derive_rng(attempt_id: str, sim_ts: str | None, person_id: str) -> random.Random:
    """Derive a deterministic RNG seed from request parameters.

    This ensures idempotent retries (same attempt_id → same result)
    while still providing randomness across different attempts.
    """
    key = f"{attempt_id}:{sim_ts or ''}:{person_id}"
    seed = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def _simulate_response_time(rng: random.Random) -> int:
    """Return simulated bank response time in milliseconds (50-500ms).

    This value is recorded numerically — no real sleep is performed.
    """
    return rng.randint(50, 500)


def _get_or_create_bank(bank_repo: BankRepository) -> BankPolicy:
    """Find the RupeeBank, creating it (with a settlement account) if missing."""
    bank = bank_repo.find_by_name("RupeeBank")
    if bank is None:
        bank = _default_bank()
        try:
            bank_repo.add(bank)
        except Exception:
            pass
    # Ensure a settlement account exists and is linked
    if bank.settlement_account_id is None:
        settlement_id = bank_repo.get_or_create_settlement_account(bank.bank_id)
        bank = bank_repo.find_by_id(bank.bank_id) or bank
    return bank


def _get_multiplier(bank: BankPolicy) -> float:
    return bank.state_multipliers.get(bank.current_state.value, 1.0)


def _maybe_transition_state(bank_repo: BankRepository, bank: BankPolicy, rng: random.Random) -> None:
    """Check if bank state should transition based on recent metrics."""
    metrics = bank_repo.status(bank.bank_id)
    sm = BankStateMachine()
    new_state = sm.bank_state_transition(
        current_state=bank.current_state,
        txn_count_last_minute=metrics.transactions_last_minute,
        failure_rate_last_minute=metrics.failure_rate,
        consecutive_failures=0,
        outage_started_at=None,
    )
    if new_state is not None and new_state != bank.current_state:
        bank_repo.update_state(bank.bank_id, new_state)
        logger.info(
            "bank_state_transition",
            extra={
                "bank_id": bank.bank_id,
                "from": bank.current_state.value,
                "to": new_state.value,
            },
        )


class BankStateMachine:
    """Manages bank state transitions based on transaction metrics."""

    @staticmethod
    def get_state_multiplier(state: BankState) -> float:
        multipliers = {
            BankState.NORMAL: 1.0,
            BankState.PEAK: 2.0,
            BankState.DEGRADED: 5.0,
            BankState.OUTAGE: 50.0,
        }
        return multipliers.get(state, 1.0)

    @staticmethod
    def bank_state_transition(
        current_state: BankState,
        txn_count_last_minute: int,
        failure_rate_last_minute: float,
        consecutive_failures: int,
        outage_started_at: datetime | None,
    ) -> BankState | None:
        """
        Returns new state if transition occurred, None if no change.
        Logic from ARCHITECTURE.md Part 3.2 / UML 10_bank_state_diagram.
        """
        now = datetime.now(timezone.utc)

        # failure_rate_last_minute is a percentage (0-100)
        if current_state == BankState.NORMAL:
            if txn_count_last_minute > 100 and failure_rate_last_minute > 1.0:
                return BankState.PEAK

        elif current_state == BankState.PEAK:
            if failure_rate_last_minute > 5.0:
                return BankState.DEGRADED
            if txn_count_last_minute < 50:
                return BankState.NORMAL

        elif current_state == BankState.DEGRADED:
            if failure_rate_last_minute > 10.0:
                return BankState.OUTAGE
            if failure_rate_last_minute < 5.0:
                return BankState.NORMAL

        elif current_state == BankState.OUTAGE:
            if outage_started_at and (now - outage_started_at).total_seconds() > 1800:
                return BankState.NORMAL

        return None


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.get("/status")
def get_status(
    request: Request,
    bank_repo: BankRepository = Depends(get_bank_repo),
):
    """Service health + bank status."""
    db = request.app.state.db
    db_ok = db.health_check()

    bank = _get_or_create_bank(bank_repo)
    metrics = bank_repo.status(bank.bank_id)

    return {
        "service": "bank",
        "status": "running" if db_ok else "degraded",
        "database_reachable": db_ok,
        "bank": {
            "bank_id": str(bank.bank_id),
            "name": bank.name,
            "current_state": bank.current_state.value,
            "authorization_success_rate": bank.authorization_success_rate,
            "timeout_rate": bank.timeout_rate,
            "issuer_decline_rate": bank.issuer_decline_rate,
            "network_error_rate": bank.network_error_rate,
            "state_multipliers": bank.state_multipliers,
            "settlement_account_id": bank.settlement_account_id,
            "bank_balance": metrics.balance,
            "success_rate_1min": metrics.success_rate,
            "failure_rate_1min": metrics.failure_rate,
            "transactions_last_minute": metrics.transactions_last_minute,
            "failures_last_minute": metrics.failures_last_minute,
        },
    }


@router.post("/authorize", response_model=AuthorizeResponse)
def authorize_payment(
    request: AuthorizeRequest,
    bank_repo: BankRepository = Depends(get_bank_repo),
    correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
):
    """Authorize a payment through the bank.

    The bank checks funds, applies state-dependent success rates, and
    simulates delivery issues (timeout, network_error).

    Returns ``unknown_outcome=True`` when the bank's response may not have
    been reliably delivered (timeout).  LazerPay must treat this as UNKNOWN,
    NOT FAILED — the bank may have actually authorized.
    """
    # Resolve bank (and ensure a settlement account exists)
    bank = _get_or_create_bank(bank_repo)

    # Derive deterministic RNG for reproducibility
    rng = _derive_rng(request.attempt_id, request.simulation_timestamp, request.person_id)
    sim_ts = _resolve_sim_ts(request.simulation_timestamp)

    # Simulated bank response time (recorded numerically, no actual sleep)
    response_time_ms = _simulate_response_time(rng)

    # Step 1: Get source account balance from ledger
    source_balance = bank_repo.get_balance(request.source_account_id)

    # Step 2: Hard funds check
    amount = Decimal(request.amount)
    if source_balance < amount:
        bank_repo.record_transaction_result(
            bank.bank_id, False, sim_ts, response_time_ms, "FAILED",
        )
        logger.info(
            "authorization_insufficient_funds",
            extra={
                "correlation_id": correlation_id,
                "attempt_id": request.attempt_id,
                "balance": str(source_balance),
                "amount": str(amount),
            },
        )
        return AuthorizeResponse(
            success=False,
            failure_code=FailureCode.INSUFFICIENT_FUNDS.value,
            failure_reason=f"Insufficient funds: balance {source_balance} < amount {amount}",
            response_time_ms=response_time_ms,
            bank_state=bank.current_state.value,
            source_balance=str(source_balance),
            authorized_at=sim_ts.isoformat(),
            settlement_account_id=bank.settlement_account_id,
            unknown_outcome=False,
        )

    # Step 3: Probabilistic authorization decision
    # Use a single roll (0-100) mapped to outcome buckets
    multiplier = _get_multiplier(bank)
    adjusted_success_rate = bank.authorization_success_rate / multiplier
    roll = rng.random() * 100.0

    # Delivery issue boundaries (not scaled by state multiplier)
    timeout_boundary = bank.timeout_rate
    network_error_boundary = timeout_boundary + bank.network_error_rate
    success_boundary = network_error_boundary + adjusted_success_rate

    logger.debug(
        "bank_authorization_roll",
        extra={
            "correlation_id": correlation_id,
            "attempt_id": request.attempt_id,
            "roll": round(roll, 4),
            "timeout_boundary": timeout_boundary,
            "network_error_boundary": network_error_boundary,
            "success_boundary": success_boundary,
            "bank_state": bank.current_state.value,
            "adjusted_success_rate": adjusted_success_rate,
        },
    )

    if roll < timeout_boundary:
        # Timeout — the bank processed the request but the response
        # did not arrive in time.  The bank ACTUALLY authorized, but
        # LazerPay cannot know this — treat as UNKNOWN.
        bank_repo.record_transaction_result(
            bank.bank_id, True, sim_ts, response_time_ms, "UNKNOWN",
        )
        _maybe_transition_state(bank_repo, bank, rng)
        return AuthorizeResponse(
            success=True,  # Bank actually authorized, but...
            failure_code=None,
            failure_reason="Bank response delayed beyond delivery window",
            response_time_ms=response_time_ms,
            bank_state=bank.current_state.value,
            source_balance=str(source_balance),
            authorized_at=sim_ts.isoformat(),
            settlement_account_id=bank.settlement_account_id,
            unknown_outcome=True,  # ...LazerPay must treat as UNKNOWN
        )

    if roll < network_error_boundary:
        # Network error — definitive failure (request may not have reached bank)
        bank_repo.record_transaction_result(
            bank.bank_id, False, sim_ts, response_time_ms, "FAILED",
        )
        _maybe_transition_state(bank_repo, bank, rng)
        return AuthorizeResponse(
            success=False,
            failure_code=FailureCode.NETWORK_ERROR.value,
            failure_reason="Network error communicating with bank",
            response_time_ms=response_time_ms,
            bank_state=bank.current_state.value,
            source_balance=str(source_balance),
            authorized_at=sim_ts.isoformat(),
            settlement_account_id=bank.settlement_account_id,
            unknown_outcome=False,
        )

    if roll < success_boundary:
        # Authorization succeeded
        bank_repo.record_transaction_result(
            bank.bank_id, True, sim_ts, response_time_ms, "SETTLED",
        )
        _maybe_transition_state(bank_repo, bank, rng)
        logger.info(
            "authorization_success",
            extra={
                "correlation_id": correlation_id,
                "attempt_id": request.attempt_id,
                "bank_state": bank.current_state.value,
                "source_balance": str(source_balance),
            },
        )
        return AuthorizeResponse(
            success=True,
            failure_code=None,
            failure_reason=None,
            response_time_ms=response_time_ms,
            bank_state=bank.current_state.value,
            source_balance=str(source_balance),
            authorized_at=sim_ts.isoformat(),
            settlement_account_id=bank.settlement_account_id,
            unknown_outcome=False,
        )

    # Otherwise: bank-side decline (issuer decline, fraud, expired card, etc.)
    failure_type = FailureCode._weighted_pick(rng)
    reason_map = {
        FailureCode.TIMEOUT.value: "Bank did not respond in time",
        FailureCode.HARD_DECLINE.value: "Bank declined transaction (issuer check)",
        FailureCode.EXPIRED_CARD.value: "Card has expired",
        FailureCode.FRAUD_BLOCK.value: "Transaction blocked by fraud detection",
        FailureCode.NETWORK_ERROR.value: "Network error communicating with bank",
    }
    reason = reason_map.get(failure_type, "Declined by bank")

    bank_repo.record_transaction_result(
        bank.bank_id, False, sim_ts, response_time_ms, "FAILED",
    )
    _maybe_transition_state(bank_repo, bank, rng)

    logger.info(
        "authorization_declined",
        extra={
            "correlation_id": correlation_id,
            "attempt_id": request.attempt_id,
            "failure_code": failure_type,
            "bank_state": bank.current_state.value,
        },
    )
    return AuthorizeResponse(
        success=False,
        failure_code=failure_type,
        failure_reason=reason,
        response_time_ms=response_time_ms,
        bank_state=bank.current_state.value,
        source_balance=str(source_balance),
        authorized_at=sim_ts.isoformat(),
        unknown_outcome=False,
    )


def _resolve_sim_ts(sim_ts_str: str | None) -> datetime:
    """Resolve simulation timestamp, falling back to wall clock."""
    if sim_ts_str:
        try:
            return datetime.fromisoformat(sim_ts_str)
        except ValueError:
            return _utcnow()
    return _utcnow()


@router.post("/bank-state")
def set_bank_state(
    state: str,
    bank_repo: BankRepository = Depends(get_bank_repo),
):
    """Manually set the bank's state (for testing / simulation control)."""
    try:
        new_state = BankState(state.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid bank state: {state}")

    bank = _get_or_create_bank(bank_repo)

    bank_repo.update_state(bank.bank_id, new_state)
    return {
        "message": f"Bank state set to {new_state.value}",
        "bank_id": str(bank.bank_id),
        "current_state": new_state.value,
    }
