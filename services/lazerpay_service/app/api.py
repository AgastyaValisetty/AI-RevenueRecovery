"""LazerPay Service API.

Implements the payment gateway endpoints.  LazerPay communicates
with the Bank Service over HTTP for authorization decisions.

Payment attempt lifecycle (from UML 11_attempt_state_diagram):
    INITIATED → ROUTING → AUTHORIZED → SETTLED
    INITIATED → ROUTING → FAILED
    INITIATED → ROUTING → UNKNOWN
    AUTHORIZED → FAILED (settlement failure)
"""
import logging
import time
import uuid as uuid_lib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel

from .config import Settings
from .repos import LazerPayRepository
from .schema import PaymentAttemptRow

logger = logging.getLogger("lazerpay")

router = APIRouter(prefix="/api")

# Payment attempt status constants (state machine from UML)
S_INITIATED = "INITIATED"
S_ROUTING = "ROUTING"
S_AUTHORIZED = "AUTHORIZED"
S_SETTLED = "SETTLED"
S_FAILED = "FAILED"
S_UNKNOWN = "UNKNOWN"
S_PENDING_LINK = "PENDING_LINK"

# Ledger event types
E_PAYMENT_SETTLED = "PAYMENT_SETTLED"
E_PAYMENT_FAILED = "PAYMENT_FAILED"
E_PAYMENT_UNKNOWN = "PAYMENT_UNKNOWN"

# HTTP timeout for Bank Service calls — operational boundary, NOT simulated latency
DEFAULT_HTTP_TIMEOUT = 10.0


# --------------------------------------------------------------------------- #
# Dependency providers
# --------------------------------------------------------------------------- #

def get_repo(request: Request) -> LazerPayRepository:
    return LazerPayRepository(request.app.state.db)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


# --------------------------------------------------------------------------- #
# Pydantic request / response models
# --------------------------------------------------------------------------- #

class ProcessPaymentRequest(BaseModel):
    """POST /api/payments/process request body.

    Matches what the People Service sends when calling LazerPay.
    """
    intent_id: str
    person_id: str
    merchant_id: str
    amount: float
    payment_method: str
    source_account_id: Optional[str] = None
    simulation_timestamp: Optional[str] = None


class ProcessPaymentResponse(BaseModel):
    attempt_id: str
    status: str
    failure_code: Optional[str] = None
    failure_reason: Optional[str] = None
    correlation_id: Optional[str] = None


class GatewayStatusResponse(BaseModel):
    service: str
    status: str
    version: str
    database_reachable: bool
    bank_service_reachable: bool
    pending_attempts: int


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _generate_correlation_id() -> str:
    return uuid4().hex[:32]


def _attempt_id() -> str:
    return f"ATT_{uuid4().hex[:12]}"


def _idempotency_key(intent_id: str, attempt_number: int) -> str:
    return f"idem_{intent_id}_{attempt_number}"


def _retry_idempotency_key(original_attempt_id: str, attempt_number: int) -> str:
    return f"idem_retry_{original_attempt_id}_{attempt_number}"


def _resolve_sim_ts(sim_ts_str: Optional[str], fallback: datetime) -> datetime:
    if sim_ts_str:
        try:
            return datetime.fromisoformat(sim_ts_str)
        except ValueError:
            return fallback
    return fallback


def _call_bank_service(
    bank_url: str,
    request_body: dict,
    correlation_id: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT,
) -> dict | None:
    """Send an authorization request to the Bank Service via HTTP.

    Returns the JSON response dict, or None if the Bank Service is
    unreachable or times out.  When None is returned the caller treats
    the outcome as UNKNOWN — LazerPay did not receive a definitive
    answer from the bank.
    """
    try:
        resp = httpx.post(
            f"{bank_url}/api/authorize",
            json=request_body,
            headers={"X-Correlation-ID": correlation_id},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
        logger.warning(
            "bank_authorization_failed",
            extra={
                "correlation_id": correlation_id,
                "attempt_id": request_body.get("attempt_id"),
                "error": str(exc),
            },
        )
        return None


def _process_attempt(
    repo: LazerPayRepository,
    payload: ProcessPaymentRequest,
    settings: Settings,
    attempt_number: int,
    idempotency_key: str,
    related_attempt_id: Optional[str] = None,
) -> PaymentAttemptRow:
    """Core attempt processing — shared by process and retry.

    Returns the PaymentAttemptRow after Bank Service authorization
    (SETTLED, FAILED, or UNKNOWN).
    """
    corr_id = _generate_correlation_id()
    sim_ts = _resolve_sim_ts(payload.simulation_timestamp, _utcnow())
    now_ts = _utcnow()
    attempt_id = _attempt_id()

    # Step 1: Idempotency check — return existing attempt if key already processed
    existing = repo.find_by_idempotency_key(idempotency_key)
    if existing:
        logger.info(
            "idempotent_duplicate_request",
            extra={
                "correlation_id": corr_id,
                "intent_id": payload.intent_id,
                "attempt_id": existing.attempt_id,
            },
        )
        return existing

    # Step 2: Create attempt record (INITIATED)
    attempt = PaymentAttemptRow(
        attempt_id=attempt_id,
        intent_id=str(payload.intent_id),
        attempt_number=attempt_number,
        person_id=str(payload.person_id),
        merchant_id=str(payload.merchant_id),
        amount=Decimal(str(payload.amount)),
        payment_method=payload.payment_method,
        source_account_id=payload.source_account_id,
        destination_account_id=None,
        idempotency_key=idempotency_key,
        status=S_INITIATED,
        initiated_at=now_ts,
        simulation_timestamp=sim_ts,
        correlation_id=corr_id,
        related_attempt_id=related_attempt_id,
        created_at=now_ts,
    )
    repo.create_attempt(attempt)

    # Step 3: Transition to ROUTING and call Bank Service
    repo.update_attempt(
        attempt_id,
        status=S_ROUTING,
        routed_at=_utcnow(),
    )

    logger.info(
        "bank_authorization_start",
        extra={
            "correlation_id": corr_id,
            "attempt_id": attempt_id,
            "intent_id": str(payload.intent_id),
            "amount": str(payload.amount),
            "payment_method": payload.payment_method,
        },
    )

    # Build Bank Service authorization request
    bank_request = {
        "attempt_id": attempt_id,
        "person_id": str(payload.person_id),
        "amount": str(Decimal(str(payload.amount))),
        "payment_method": payload.payment_method,
        "source_account_id": payload.source_account_id or "",
        "simulation_timestamp": sim_ts.isoformat(),
        "correlation_id": corr_id,
    }

    gateway_start = time.monotonic()
    bank_data = _call_bank_service(
        settings.bank_url, bank_request, corr_id, settings.http_timeout_seconds
    )
    gateway_latency_ms = int((time.monotonic() - gateway_start) * 1000)

    # Step 4: Apply Bank Service result
    if bank_data is None:
        # Bank Service unreachable — UNKNOWN outcome.
        # The bank may have processed the transaction but we got no response.
        repo.update_attempt(
            attempt_id,
            status=S_UNKNOWN,
            unknown_at=_utcnow(),
            gateway_latency_ms=gateway_latency_ms,
            bank_state="UNKNOWN",
        )
        logger.warning(
            "payment_unknown_bank_unreachable",
            extra={
                "correlation_id": corr_id,
                "attempt_id": attempt_id,
                "intent_id": str(payload.intent_id),
            },
        )
        # Audit ledger entry — no money moved
        repo.write_ledger_entry(
            event_type=E_PAYMENT_UNKNOWN,
            from_account_id=payload.source_account_id,
            to_account_id=None,
            amount=Decimal("0"),
            simulation_timestamp=sim_ts,
            related_attempt_id=attempt_id,
            metadata_json={
                "payment_method": payload.payment_method,
                "correlation_id": corr_id,
                "reason": "bank_service_unreachable",
            },
        )
        return repo.find_by_attempt_id(attempt_id)

    # Bank Service responded with a dict
    bank_success = bank_data.get("success", False)
    bank_failure_code = bank_data.get("failure_code")
    bank_failure_reason = bank_data.get("failure_reason")
    bank_response_time_ms = bank_data.get("response_time_ms", 0)
    bank_state = bank_data.get("bank_state", "NORMAL")
    source_balance = bank_data.get("source_balance", "0")
    settlement_account_id = bank_data.get("settlement_account_id")
    unknown_outcome = bank_data.get("unknown_outcome", False)

    if unknown_outcome:
        # Bank reported uncertain delivery — treat as UNKNOWN.
        repo.update_attempt(
            attempt_id,
            status=S_UNKNOWN,
            unknown_at=_utcnow(),
            bank_response_time_ms=bank_response_time_ms,
            gateway_latency_ms=gateway_latency_ms,
            bank_state=bank_state,
        )
        logger.warning(
            "payment_unknown_uncertain_delivery",
            extra={
                "correlation_id": corr_id,
                "attempt_id": attempt_id,
                "intent_id": str(payload.intent_id),
            },
        )
        repo.write_ledger_entry(
            event_type=E_PAYMENT_UNKNOWN,
            from_account_id=payload.source_account_id,
            to_account_id=None,
            amount=Decimal("0"),
            simulation_timestamp=sim_ts,
            related_attempt_id=attempt_id,
            metadata_json={
                "payment_method": payload.payment_method,
                "correlation_id": corr_id,
                "reason": bank_failure_reason or "uncertain_delivery",
                "bank_response_time_ms": bank_response_time_ms,
            },
        )
        return repo.find_by_attempt_id(attempt_id)

    if not bank_success:
        # Bank declined (funds, hard decline, network error, etc.)
        repo.update_attempt(
            attempt_id,
            status=S_FAILED,
            failure_code=bank_failure_code,
            failure_reason=bank_failure_reason,
            failed_at=_utcnow(),
            bank_response_time_ms=bank_response_time_ms,
            gateway_latency_ms=gateway_latency_ms,
            bank_state=bank_state,
        )
        logger.info(
            "payment_failed",
            extra={
                "correlation_id": corr_id,
                "attempt_id": attempt_id,
                "intent_id": str(payload.intent_id),
                "failure_code": bank_failure_code,
            },
        )
        # Write audit ledger entry for the failed attempt (no money moved)
        repo.write_ledger_entry(
            event_type=E_PAYMENT_FAILED,
            from_account_id=payload.source_account_id,
            to_account_id=None,
            amount=Decimal("0"),
            simulation_timestamp=sim_ts,
            related_attempt_id=attempt_id,
            metadata_json={
                "payment_method": payload.payment_method,
                "failure_code": bank_failure_code,
                "failure_reason": bank_failure_reason,
                "correlation_id": corr_id,
                "bank_response_time_ms": bank_response_time_ms,
            },
        )
        return repo.find_by_attempt_id(attempt_id)

    # Bank authorized — transition to AUTHORIZED then SETTLED
    repo.update_attempt(
        attempt_id,
        status=S_AUTHORIZED,
        authorized_at=_utcnow(),
        bank_response_time_ms=bank_response_time_ms,
        gateway_latency_ms=gateway_latency_ms,
        bank_state=bank_state,
    )

    # Settle the payment
    repo.update_attempt(
        attempt_id,
        status=S_SETTLED,
        settled_at=_utcnow(),
    )

    # Write settlement ledger entry (customer debit → bank settlement account credit)
    repo.write_ledger_entry(
        event_type=E_PAYMENT_SETTLED,
        from_account_id=payload.source_account_id,
        to_account_id=settlement_account_id,
        amount=Decimal(str(payload.amount)),
        simulation_timestamp=sim_ts,
        related_attempt_id=attempt_id,
        metadata_json={
            "payment_method": payload.payment_method,
            "amount": str(payload.amount),
            "correlation_id": corr_id,
            "bank_response_time_ms": bank_response_time_ms,
            "gateway_latency_ms": gateway_latency_ms,
            "bank_state": bank_state,
            "source_balance": source_balance,
            "settlement_account_id": settlement_account_id,
        },
    )

    logger.info(
        "payment_settled",
        extra={
            "correlation_id": corr_id,
            "attempt_id": attempt_id,
            "intent_id": str(payload.intent_id),
            "amount": str(payload.amount),
        },
    )
    return repo.find_by_attempt_id(attempt_id)


def _attempt_to_response(row: PaymentAttemptRow) -> dict:
    """Build the response dict from a PaymentAttemptRow.

    Matches the format the People Service expects.
    """
    return {
        "attempt_id": row.attempt_id,
        "status": row.status,
        "failure_code": row.failure_code,
        "failure_reason": row.failure_reason,
        "correlation_id": row.correlation_id,
    }


def _attempt_to_detail(row: PaymentAttemptRow, all_attempts: list[PaymentAttemptRow] | None = None) -> dict:
    """Build a full detail response from a PaymentAttemptRow."""
    return {
        "attempt_id": row.attempt_id,
        "intent_id": row.intent_id,
        "attempt_number": row.attempt_number,
        "person_id": str(row.person_id),
        "merchant_id": str(row.merchant_id),
        "amount": str(row.amount) if row.amount else "0.00",
        "payment_method": row.payment_method,
        "source_account_id": str(row.source_account_id) if row.source_account_id else None,
        "destination_account_id": str(row.destination_account_id) if row.destination_account_id else None,
        "status": row.status,
        "failure_code": row.failure_code,
        "failure_reason": row.failure_reason,
        "correlation_id": row.correlation_id,
        "simulation_timestamp": row.simulation_timestamp.isoformat() if row.simulation_timestamp else None,
        "initiated_at": row.initiated_at.isoformat() if row.initiated_at else None,
        "routed_at": row.routed_at.isoformat() if row.routed_at else None,
        "authorized_at": row.authorized_at.isoformat() if row.authorized_at else None,
        "settled_at": row.settled_at.isoformat() if row.settled_at else None,
        "failed_at": row.failed_at.isoformat() if row.failed_at else None,
        "unknown_at": row.unknown_at.isoformat() if row.unknown_at else None,
        "bank_response_time_ms": row.bank_response_time_ms,
        "gateway_latency_ms": row.gateway_latency_ms,
        "bank_state": row.bank_state,
        "related_attempt_id": row.related_attempt_id,
        "retry_for_attempt_id": row.retry_for_attempt_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "all_attempts_for_intent": [
            {
                "attempt_id": r.attempt_id,
                "attempt_number": r.attempt_number,
                "status": r.status,
                "failure_code": r.failure_code,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in (all_attempts or [])
        ],
    }


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.get("/status", response_model=GatewayStatusResponse)
def get_gateway_status(
    request: Request,
    repo: LazerPayRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
):
    """Gateway health check — reports service health, DB, and Bank reachability."""
    db = request.app.state.db
    db_ok = db.health_check()

    bank_reachable = False
    try:
        resp = httpx.get(f"{settings.bank_url}/api/status", timeout=5.0)
        bank_reachable = resp.status_code == 200
    except Exception:
        bank_reachable = False

    pending = len(repo.find_pending())
    return GatewayStatusResponse(
        service="lazerpay",
        status="running",
        version="1.0.0",
        database_reachable=db_ok,
        bank_service_reachable=bank_reachable,
        pending_attempts=pending,
    )


@router.post("/payments/process", response_model=ProcessPaymentResponse)
def process_payment(
    payload: ProcessPaymentRequest,
    request: Request,
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID"),
    repo: LazerPayRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
):
    """Process a payment intent through the gateway.

    Flow:
      1. Check idempotency (DB uniqueness on idempotency_key)
      2. Create PaymentAttempt (INITIATED)
      3. Call Bank Service POST /api/authorize via HTTP
      4. Apply result: SETTLED / FAILED / UNKNOWN
      5. Write ledger entry on SETTLED or FAILED
    """
    attempt_number = 1
    idem_key = _idempotency_key(payload.intent_id, attempt_number)

    result = _process_attempt(
        repo=repo,
        payload=payload,
        settings=settings,
        attempt_number=attempt_number,
        idempotency_key=idem_key,
    )

    return ProcessPaymentResponse(**_attempt_to_response(result))


@router.post("/payments/retry")
def retry_payment(
    attempt_id: str,
    request: Request,
    amount: Optional[float] = None,
    payment_method: Optional[str] = None,
    simulation_timestamp: Optional[str] = None,
    correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-ID"),
    repo: LazerPayRepository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
):
    """Retry a failed/unknown payment.

    Creates a NEW PaymentAttempt with attempt_number = original + 1.
    The original attempt is never mutated.
    """
    original = repo.find_by_attempt_id(attempt_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Original attempt not found")

    new_attempt_number = original.attempt_number + 1
    retry_idem_key = _retry_idempotency_key(attempt_id, new_attempt_number)

    # Build payload from original attempt
    payload = ProcessPaymentRequest(
        intent_id=original.intent_id,
        person_id=str(original.person_id),
        merchant_id=str(original.merchant_id),
        amount=float(amount) if amount else float(original.amount),
        payment_method=payment_method or original.payment_method,
        source_account_id=original.source_account_id,
        simulation_timestamp=simulation_timestamp or (
            original.simulation_timestamp.isoformat() if original.simulation_timestamp else None
        ),
    )

    result = _process_attempt(
        repo=repo,
        payload=payload,
        settings=settings,
        attempt_number=new_attempt_number,
        idempotency_key=retry_idem_key,
        related_attempt_id=original.attempt_id,
    )

    return {
        "original_attempt_id": attempt_id,
        "new_attempt_id": result.attempt_id,
        "status": result.status,
        "failure_code": result.failure_code,
        "failure_reason": result.failure_reason,
        "attempt_number": result.attempt_number,
    }


@router.get("/payments/{attempt_id}")
def get_attempt_status(
    attempt_id: str,
    repo: LazerPayRepository = Depends(get_repo),
):
    """Get full details of a payment attempt including all lifecycle timestamps."""
    row = repo.find_by_attempt_id(attempt_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attempt not found")

    related = repo.find_by_intent(row.intent_id)
    return _attempt_to_detail(row, related)


@router.post("/payments/send-link")
def send_payment_link(
    attempt_id: str,
    person_id: Optional[str] = None,
    payment_method: Optional[str] = None,
    repo: LazerPayRepository = Depends(get_repo),
):
    """Send a payment link to the customer for alternative payment method.

    Creates an auditable link event but does NOT charge the customer.
    """
    attempt = repo.find_by_attempt_id(attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")

    link_id = f"link_{uuid4().hex[:12]}"

    repo.update_attempt(attempt_id, status=S_PENDING_LINK)

    repo.write_ledger_entry(
        event_type="LINK_SENT",
        from_account_id=attempt.source_account_id,
        to_account_id=None,
        amount=Decimal("0"),
        simulation_timestamp=attempt.simulation_timestamp or _utcnow(),
        related_attempt_id=attempt_id,
        metadata_json={
            "link_id": link_id,
            "payment_method": payment_method,
            "person_id": person_id,
        },
    )

    return {
        "status": "link_sent",
        "link_id": link_id,
        "attempt_id": attempt_id,
        "message": "Payment link sent to customer",
    }
