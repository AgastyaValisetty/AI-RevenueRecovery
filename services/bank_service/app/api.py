from datetime import datetime, timezone
from decimal import Decimal
import random
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .database import Database
from .domain import BankPolicy, BankState, BankAccount, FailureCode
from .engine import FundsValidator, LatencySimulator, ProbabilityEngine, BankStateMachine
from .repos import BankRepository

router = APIRouter(prefix="/api")


def get_bank_repo(request: Request) -> BankRepository:
    db: Database = request.app.state.db
    return BankRepository(db)


class AuthorizeRequest(BaseModel):
    attempt_id: str
    person_id: str
    amount: float
    payment_method: str
    source_account_id: str


class AuthorizeResponse(BaseModel):
    success: bool
    failure_code: str | None
    failure_reason: str | None
    response_time_ms: int
    bank_state: str
    source_balance: float


class BankStatusResponse(BaseModel):
    bank_id: str
    name: str
    current_state: str
    success_rate: float
    failure_rate: float
    transactions_last_minute: int
    failures_last_minute: int
    balance: float


@router.post("/authorize", response_model=AuthorizeResponse)
def authorize_payment(
    request: AuthorizeRequest, bank_repo: BankRepository = Depends(get_bank_repo)
) -> AuthorizeResponse:
    rng = random.Random()
    start = time.time()

    bank = bank_repo.find_by_name("RupeeBank")
    if bank is None:
        bank = _default_bank()
        bank_repo.add(bank)
        bank_repo.record_transaction_result(bank.bank_id, False, datetime.now(timezone.utc))
        _simulate_latency(start)
        raise HTTPException(status_code=503, detail="Bank not initialized")

    # Step 1: Get source account balance
    source_balance = bank_repo.get_balance(request.source_account_id)

    # Step 2: Hard check - sufficient funds
    amount = Decimal(str(request.amount))

    if not FundsValidator.has_sufficient_funds(Decimal(str(source_balance)), amount):
        latency = LatencySimulator(rng).simulate_response_time()
        bank_repo.record_transaction_result(bank.bank_id, False, datetime.now(timezone.utc))
        _maybe_transition_state(bank_repo, bank, rng)
        return AuthorizeResponse(
            success=False,
            failure_code="INSUFFICIENT_FUNDS",
            failure_reason=f"Balance {source_balance} < Amount {amount}",
            response_time_ms=latency,
            bank_state=bank.current_state.value,
            source_balance=source_balance,
        )

    # Step 3: Probabilistic decision
    engine = ProbabilityEngine(rng)
    success, failure_code, failure_reason = engine.decide(bank)

    latency = LatencySimulator(rng).simulate_response_time()
    bank_repo.record_transaction_result(bank.bank_id, success, datetime.now(timezone.utc))
    _maybe_transition_state(bank_repo, bank, rng)

    return AuthorizeResponse(
        success=success,
        failure_code=failure_code,
        failure_reason=failure_reason,
        response_time_ms=latency,
        bank_state=bank.current_state.value,
        source_balance=source_balance,
    )


@router.get("/status", response_model=BankStatusResponse)
def get_status(bank_repo: BankRepository = Depends(get_bank_repo)) -> BankStatusResponse:
    bank = bank_repo.find_by_name("RupeeBank")
    if bank is None:
        bank = _default_bank()
        bank_repo.add(bank)
    status = bank_repo.status(bank.bank_id)
    # Also get balance from the first person's account as an example
    # In production, this would be per-account tracking
    example_balance = 0.0
    return BankStatusResponse(
        bank_id=str(status.bank_id),
        name=status.name,
        current_state=status.current_state.value,
        success_rate=status.success_rate,
        failure_rate=status.failure_rate,
        transactions_last_minute=status.transactions_last_minute,
        failures_last_minute=status.failures_last_minute,
        balance=example_balance,
    )


@router.post("/state/transition")
def transition_state(bank_repo: BankRepository = Depends(get_bank_repo)):
    bank = bank_repo.find_by_name("RupeeBank")
    if bank is None:
        bank = _default_bank()
        bank_repo.add(bank)

    rng = random.Random()
    _maybe_transition_state(bank_repo, bank, rng)
    return {"message": "State transition evaluated", "current_state": bank.current_state.value}


def _default_bank() -> BankPolicy:
    from uuid import uuid4
    return BankPolicy(
        bank_id=str(uuid4()),
        name="RupeeBank",
        authorization_success_rate=99.1,
        timeout_rate=0.3,
        issuer_decline_rate=0.4,
        network_error_rate=0.2,
        current_state=BankState.NORMAL,
        state_multipliers={
            BankState.NORMAL.value: 1.0,
            BankState.PEAK.value: 2.0,
            BankState.DEGRADED.value: 5.0,
            BankState.OUTAGE.value: 50.0,
        },
    )


def _maybe_transition_state(bank_repo: BankRepository, bank: BankPolicy, rng: random.Random) -> None:
    """Check if bank state should transition based on recent metrics."""
    metrics = bank_repo.status(bank.bank_id)
    sm = BankStateMachine(rng)
    new_state = sm.bank_state_transition(
        current_state=bank.current_state,
        txn_count_last_minute=metrics.transactions_last_minute,
        failure_rate_last_minute=metrics.failure_rate,
        consecutive_failures=0,
        outage_started_at=None,
    )
    if new_state is not None and new_state != bank.current_state:
        bank_repo.update_state(bank.bank_id, new_state)


def _simulate_latency(start_time: float) -> None:
    """Simulate network latency (50-500ms as per latency model)."""
    rng = random.Random()
    target_latency = rng.randint(50, 500) / 1000.0
    elapsed = time.time() - start_time
    remaining = target_latency - elapsed
    if remaining > 0:
        time.sleep(remaining)
