import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from random import Random
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .domain import BankStatus, FailureCode, PaymentIntent, PaymentAttempt, RecoveryAction
from .engine import IdempotencyGuard, LatencySimulator, FundsValidator, ProbabilityEngine, default_bank_policy
from .repos import LazerPayRepository
from .dependencies import get_repo
from .schema import PaymentAttemptRow

router = APIRouter(prefix="/api")


# Request/Response models

class ProcessPaymentRequest(BaseModel):
    intent_id: str
    person_id: str
    merchant_id: str
    amount: float
    payment_method: str
    source_account_id: str


class ProcessPaymentResponse(BaseModel):
    attempt_id: str
    status: str
    failure_code: str | None
    failure_reason: str | None


class RetryPaymentRequest(BaseModel):
    attempt_id: str
    person_id: str
    merchant_id: str
    amount: float
    reason: str


class RetryPaymentResponse(BaseModel):
    new_attempt_id: str
    status: str
    failure_code: str | None
    failure_reason: str | None


class AttemptStatusResponse(BaseModel):
    attempt_id: str
    intent_id: str
    person_id: str
    merchant_id: str
    amount: float
    payment_method: str
    status: str
    failure_code: str | None
    failure_reason: str | None
    authorized_at: str | None
    settled_at: str | None


class SendLinkRequest(BaseModel):
    attempt_id: str
    person_id: str
    payment_method: str


class SendLinkResponse(BaseModel):
    status: str
    message: str


# In-memory storage for rate limiting / state (will be backed by DB in production)
_lazerpy_state = {}


@router.post("/payments/process", response_model=ProcessPaymentResponse)
def process_payment(
    request: ProcessPaymentRequest, repo: LazerPayRepository = Depends(get_repo)
):
    """Process a payment intent. This is the main entry point from People Service.

    Flow: LazerPay receives intent → creates PaymentAttempt → calls Bank
    Service for authorization (FundsValidator + ProbabilityEngine) →
    records result in DB → returns to caller.
    """
    attempt_id = f"ATT_{uuid4().hex[:12]}"
    idempotency_key = IdempotencyGuard.generate_key(request.intent_id, 1)

    # Step 1: Check idempotency - if same key already processed, return existing result
    existing = repo.find_by_idempotency_key(idempotency_key)
    if existing:
        return ProcessPaymentResponse(
            attempt_id=existing.attempt_id,
            status=existing.status,
            failure_code=existing.failure_code,
            failure_reason=existing.failure_reason,
        )

    # Step 2: Create payment attempt record
    attempt = PaymentAttemptRow(
        attempt_id=attempt_id,
        intent_id=request.intent_id,
        attempt_number=1,
        person_id=request.person_id,
        merchant_id=request.merchant_id,
        amount=request.amount,
        payment_method=request.payment_method,
        source_account_id=request.source_account_id,
        destination_account_id=None,  # Merchant settlement account unknown at auth time
        idempotency_key=idempotency_key,
        status="INITIATED",
        initiated_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )

    repo.create_attempt(attempt)
    repo.record_idempotency_key(idempotency_key, attempt_id)

    # Step 3: Bank authorization
    # In production, this would be an HTTP call to bank_service:8002/api/authorize
    # For simulation, we use the local probability engine.
    rng = Random()
    source_balance = 15000.0  # Would come from bank_accounts table in production

    # Step 3a: Hard check - sufficient funds
    amount_decimal = Decimal(str(request.amount))

    if not FundsValidator.has_sufficient_funds(
        Decimal(str(source_balance)), amount_decimal
    ):
        repo.update_attempt_status(
            attempt_id, "FAILED", "INSUFFICIENT_FUNDS",
            f"Balance {source_balance} < Amount {request.amount}",
            settled_at=datetime.now(timezone.utc),
        )
        return ProcessPaymentResponse(
            attempt_id=attempt_id,
            status="FAILED",
            failure_code="INSUFFICIENT_FUNDS",
            failure_reason=f"Balance {source_balance} < Amount {request.amount}",
        )

    # Step 3b: Probabilistic bank decision
    engine = ProbabilityEngine(rng)
    bank = default_bank_policy()
    success, failure_code, failure_reason = engine.decide(bank)

    latency = LatencySimulator.simulate_response_time(rng)
    time.sleep(min(latency / 1000.0, 0.3))

    # Step 4: Process bank response
    if success:
        repo.update_attempt_status(
            attempt_id, "SETTLED",
            authorized_at=datetime.now(timezone.utc),
            settled_at=datetime.now(timezone.utc),
            gateway_processing_time_ms=latency,
        )
        return ProcessPaymentResponse(
            attempt_id=attempt_id,
            status="SETTLED",
            failure_code=None,
            failure_reason=None,
        )
    else:
        repo.update_attempt_status(
            attempt_id, "FAILED", failure_code, failure_reason,
            settled_at=datetime.now(timezone.utc),
        )
        return ProcessPaymentResponse(
            attempt_id=attempt_id,
            status="FAILED",
            failure_code=failure_code,
            failure_reason=failure_reason,
        )


@router.post("/payments/retry", response_model=RetryPaymentResponse)
def retry_payment(
    request: RetryPaymentRequest, repo: LazerPayRepository = Depends(get_repo)
):
    """Retry a failed payment. Creates a new attempt_number=2."""
    new_attempt_id = f"ATT_{uuid4().hex[:12]}"

    # Get the original attempt details
    original = repo.find_by_attempt_id(request.attempt_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Original attempt not found")

    # Check idempotency for retry
    idempotency_key = f"retry_{request.attempt_id}_{2}"

    # Create new attempt with attempt_number=2
    attempt = PaymentAttemptRow(
        attempt_id=new_attempt_id,
        intent_id=original.intent_id,
        attempt_number=2,
        person_id=original.person_id,
        merchant_id=original.merchant_id,
        amount=request.amount,
        payment_method=original.payment_method,
        source_account_id=original.source_account_id,
        destination_account_id=original.destination_account_id,
        idempotency_key=idempotency_key,
        status="INITIATED",
        initiated_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )

    repo.create_attempt(attempt)
    repo.record_idempotency_key(idempotency_key, new_attempt_id)

    # Call bank for authorization (same flow as initial)
    rng = Random()
    source_balance = 15000.0  # Would reflect updated balance after salary, etc.

    amount_decimal = Decimal(str(request.amount))

    if not FundsValidator.has_sufficient_funds(
        Decimal(str(source_balance)), amount_decimal
    ):
        repo.update_attempt_status(
            new_attempt_id, "FAILED", "INSUFFICIENT_FUNDS",
            f"Balance {source_balance} < Amount {request.amount}",
            settled_at=datetime.now(timezone.utc),
        )
        return RetryPaymentResponse(
            new_attempt_id=new_attempt_id,
            status="FAILED",
            failure_code="INSUFFICIENT_FUNDS",
            failure_reason=f"Balance {source_balance} < Amount {request.amount}",
        )

    engine = ProbabilityEngine(rng)
    bank = default_bank_policy()
    success, failure_code, failure_reason = engine.decide(bank)

    latency = LatencySimulator.simulate_response_time(rng)
    time.sleep(min(latency / 1000.0, 0.3))

    if success:
        repo.update_attempt_status(
            new_attempt_id, "SETTLED",
            authorized_at=datetime.now(timezone.utc),
            settled_at=datetime.now(timezone.utc),
            gateway_processing_time_ms=latency,
        )
        return RetryPaymentResponse(
            new_attempt_id=new_attempt_id,
            status="SETTLED",
            failure_code=None,
            failure_reason=None,
        )
    else:
        repo.update_attempt_status(
            new_attempt_id, "FAILED", failure_code, failure_reason,
            settled_at=datetime.now(timezone.utc),
        )
        return RetryPaymentResponse(
            new_attempt_id=new_attempt_id,
            status="FAILED",
            failure_code=failure_code,
            failure_reason=failure_reason,
        )


@router.get("/payments/{attempt_id}", response_model=AttemptStatusResponse)
def get_attempt_status(
    attempt_id: str, repo: LazerPayRepository = Depends(get_repo)
):
    """Get status of a specific payment attempt."""
    attempt = repo.get_attempt(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")

    return AttemptStatusResponse(
        attempt_id=attempt["attempt_id"],
        intent_id=str(attempt["intent_id"]),
        person_id=str(attempt["person_id"]),
        merchant_id=str(attempt["merchant_id"]),
        amount=attempt["amount"],
        payment_method=attempt["payment_method"],
        status=attempt["status"],
        failure_code=attempt["failure_code"],
        failure_reason=attempt["failure_reason"],
        authorized_at=attempt["authorized_at"],
        settled_at=attempt["settled_at"],
    )


@router.post("/payments/send-link", response_model=SendLinkResponse)
def send_payment_link(
    request: SendLinkRequest, repo: LazerPayRepository = Depends(get_repo)
):
    """Send a payment link to the customer for alternative payment method."""
    attempt = repo.find_by_attempt_id(request.attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")

    repo.update_attempt_status(
        request.attempt_id, "PENDING_LINK"
    )

    return SendLinkResponse(
        status="link_sent",
        message="Payment link sent to customer",
    )


@router.get("/status")
def get_gateway_status(repo: LazerPayRepository = Depends(get_repo)):
    """Gateway health check."""
    return {
        "service": "lazerpay",
        "status": "running",
        "version": "1.0.0",
    }
