from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api")


class RunSimulationRequest(BaseModel):
    people_count: int = 100
    days: int = 0


class ProcessPaymentRequest(BaseModel):
    person_id: str
    merchant_id: str
    product_id: str
    amount: float
    payment_method: str
    related_subscription_id: str | None = None


class ProcessPaymentResponse(BaseModel):
    attempt_id: str
    status: str
    failure_code: str | None
    failure_reason: str | None


@router.post("/simulation/run")
def run_simulation(payload: RunSimulationRequest, request: Request) -> dict:
    orchestrator = request.app.state.orchestrator
    orchestrator.initialize(payload.people_count)
    if payload.days > 0:
        orchestrator.run_days(payload.days)
    return {"status": "completed", "summary": orchestrator.summary()}


@router.get("/simulation/status")
def simulation_status(request: Request) -> dict:
    return request.app.state.orchestrator.summary()


@router.get("/people")
def list_people(request: Request) -> dict:
    orchestrator = request.app.state.orchestrator
    people = orchestrator.people()
    account_ids = [p.primary_account_id for p in people]
    balances = orchestrator.balance_of_all(account_ids)
    return {
        "count": len(people),
        "people": [
            {
                "person_id": str(person.person_id),
                "name": person.name,
                "age": person.age,
                "salary": str(person.salary),
                "salary_deposit_day": person.salary_deposit_day,
                "spending_profile_category": person.spending_profile_category,
                "current_balance": str(balances.get(person.primary_account_id, Decimal(0))),
            }
            for person in people
        ],
    }


@router.get("/people/{person_id}")
def get_person(person_id: UUID, request: Request) -> dict:
    orchestrator = request.app.state.orchestrator
    person = orchestrator.person_by_id(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return {
        "person_id": str(person.person_id),
        "name": person.name,
        "age": person.age,
        "salary": str(person.salary),
        "salary_deposit_day": person.salary_deposit_day,
        "spending_profile_category": person.spending_profile_category,
        "current_balance": str(orchestrator.balance_of(person.primary_account_id)),
    }


@router.get("/merchants")
def list_merchants(request: Request) -> dict:
    merchants = request.app.state.orchestrator.merchants()
    return {
        "count": len(merchants),
        "merchants": [
            {
                "merchant_id": str(merchant.merchant_id),
                "name": merchant.name,
                "merchant_type": merchant.merchant_type,
            }
            for merchant in merchants
        ],
    }


@router.get("/ledger")
def list_ledger(request: Request, limit: int = 500) -> dict:
    entries = request.app.state.orchestrator.ledger_entries(limit=limit)
    return {
        "count": len(entries),
        "entries": [
            {
                "entry_id": str(e.entry_id),
                "event_type": e.event_type,
                "from_account_id": str(e.from_account_id) if e.from_account_id else None,
                "to_account_id": str(e.to_account_id) if e.to_account_id else None,
                "amount": str(e.amount),
                "simulation_timestamp": e.simulation_timestamp.isoformat(),
                "metadata_json": e.metadata_json,
            }
            for e in entries
        ],
    }


@router.get("/subscriptions")
def list_subscriptions(request: Request, limit: int = 500) -> dict:
    subs = request.app.state.orchestrator.subscriptions(limit=limit)
    return {
        "count": len(subs),
        "subscriptions": [
            {
                "subscription_id": str(s.subscription_id),
                "person_id": str(s.person_id),
                "merchant_id": str(s.merchant_id),
                "product_id": str(s.product_id),
                "amount": str(s.amount),
                "billing_cycle": s.billing_cycle,
                "status": s.status,
                "next_billing_date": str(s.next_billing_date),
                "consecutive_failures": s.consecutive_failures,
            }
            for s in subs
        ],
    }


# --- Payment Integration with LazerPay ---

@router.post("/payments/process", response_model=ProcessPaymentResponse)
def process_payment(payload: ProcessPaymentRequest, request: Request) -> ProcessPaymentResponse:
    """Process a payment by calling LazerPay service.

    The People Service does NOT call the bank directly.
    It must go through LazerPay API, which then calls RupeeBank.
    """
    from dataclasses import replace
    orchestrator = request.app.state.orchestrator

    # Create payment intent and save it
    from .domain import PaymentIntent, PENDING, now

    # product_id may be a non-UUID string (e.g. "any") from the frontend;
    # pick an existing product for that merchant so the FK constraint holds.
    try:
        product_uuid = UUID(payload.product_id)
    except (ValueError, AttributeError):
        product_uuid = orchestrator._product_repo.first_product_for_merchant(
            payload.merchant_id
        )

    intent = PaymentIntent(
        intent_id=uuid4(),
        person_id=payload.person_id,
        merchant_id=payload.merchant_id,
        product_id=product_uuid,
        amount=payload.amount,
        payment_method=payload.payment_method,
        status=PENDING,
        related_subscription_id=payload.related_subscription_id,
        created_at=now(),
        expires_at=now() + timedelta(hours=1),
    )

    # Save intent to repository
    orchestrator._intent_repo.add([intent])

    # Look up the person to get their primary bank account for the source
    from uuid import UUID as _UUID
    person = orchestrator._person_repo.find_by_id(_UUID(payload.person_id))
    source_account_id = str(person.primary_account_id) if person else uuid4().hex

    # Call LazerPay API to process the payment
    lazerpay_base = "http://lazerpay_service:8001"  # In production, from config
    import httpx

    try:
        response = httpx.post(
            f"{lazerpay_base}/api/payments/process",
            json={
                "intent_id": str(intent.intent_id),
                "person_id": str(payload.person_id),
                "merchant_id": str(payload.merchant_id),
                "amount": float(payload.amount),
                "payment_method": payload.payment_method,
                "source_account_id": source_account_id,
            },
            timeout=30.0,
        )
        lazerpay_response = response.json()
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"LazerPay service unavailable: {str(e)}"
        )

    # Update intent status based on LazerPay response
    attempt_id = lazerpay_response.get("attempt_id", "")
    status = lazerpay_response.get("status", "FAILED")
    failure_code = lazerpay_response.get("failure_code")
    failure_reason = lazerpay_response.get("failure_reason")

    # Update the intent status (frozen dataclass → use replace)
    updated_intent = replace(intent, status=status)
    orchestrator._intent_repo.save(updated_intent)

    # Handle subscription if applicable
    if payload.related_subscription_id and status == "SETTLED":
        subscription = orchestrator._subscription_repo.find(
            payload.related_subscription_id
        )
        if subscription:
            updated_sub = replace(
                subscription,
                consecutive_failures=0,
                last_successful_payment_date=orchestrator._clock.current_date(),
            )
            orchestrator._subscription_repo.save(updated_sub)

    return ProcessPaymentResponse(
        attempt_id=attempt_id,
        status=status,
        failure_code=failure_code,
        failure_reason=failure_reason,
    )


@router.get("/payments/{attempt_id}")
def get_payment_attempt(attempt_id: str, request: Request) -> dict:
    """Get status of a payment attempt."""
    # Look up in the intent repository or ledger
    orchestrator = request.app.state.orchestrator
    # Try to find related ledger entry
    ledger_entries = orchestrator.ledger_entries(limit=1000)
    for entry in ledger_entries["entries"]:
        if entry.get("related_attempt_id") == attempt_id:
            return {
                "attempt_id": attempt_id,
                "status": entry.get("event_type"),
                "amount": entry.get("amount"),
                "event_type": entry.get("event_type"),
            }

    return {
        "attempt_id": attempt_id,
        "status": "not_found",
        "message": "Attempt not found in ledger",
    }


# --- Merchant Management ---

class AddMerchantRequest(BaseModel):
    name: str
    merchant_type: str
    products: list[dict]  # [{"name": "...", "price": "99.00", "product_type": "SUBSCRIPTION"}]


@router.post("/merchants")
def add_merchant(payload: AddMerchantRequest, request: Request) -> dict:
    """Add a new merchant and its products.

    The merchant is persisted to the database immediately and
    also appended to the merchant_catalog.json config file so
    it survives restarts.
    """
    from .generators import MerchantGenerator
    from .domain import Merchant, Product, MONTHLY, now
    from uuid import uuid4

    orchestrator = request.app.state.orchestrator
    bank = orchestrator._bank_repo.find_by_name("RupeeBank")
    if bank is None:
        bank = orchestrator._bank_repo.add(orchestrator._rupeebank())

    timestamp = now()
    merchant = Merchant(
        merchant_id=uuid4(),
        name=payload.name,
        merchant_type=payload.merchant_type,
        settlement_bank_id=bank.bank_id,
        created_at=timestamp,
    )
    orchestrator._merchant_repo.add([merchant])

    products = []
    for prod in payload.products:
        products.append(
            Product(
                product_id=uuid4(),
                merchant_id=merchant.merchant_id,
                name=prod["name"],
                price=Decimal(prod["price"]),
                product_type=prod["product_type"],
                billing_cycle=MONTHLY if prod["product_type"] == "SUBSCRIPTION" else None,
                created_at=timestamp,
            )
        )
    if products:
        orchestrator._product_repo.add(products)

    # Persist to config file for modularity / persistence
    MerchantGenerator.add_merchant_to_catalog(
        payload.name, payload.merchant_type, payload.products
    )

    return {
        "status": "added",
        "merchant_id": str(merchant.merchant_id),
        "name": merchant.name,
        "product_count": len(products),
    }


# --- Revenue Analysis ---

@router.get("/revenue")
def get_revenue(request: Request) -> dict:
    """Return revenue summary for all merchants (lifetime + monthly)."""
    orchestrator = request.app.state.orchestrator
    merchants = orchestrator.merchants()
    revenue_map = orchestrator.revenue_by_merchant()

    merchant_list = []
    for m in merchants:
        total = revenue_map.get(m.merchant_id, Decimal(0))
        monthly = orchestrator.monthly_revenue_for_merchant(m.merchant_id)
        transactions = orchestrator.settled_transactions_for_merchant(m.merchant_id)
        merchant_list.append({
            "merchant_id": str(m.merchant_id),
            "name": m.name,
            "merchant_type": m.merchant_type,
            "lifetime_revenue": str(total),
            "transaction_count": len(transactions),
            "monthly_revenue": monthly,
            "recent_transactions": [
                {
                    "intent_id": str(t.intent_id),
                    "person_id": str(t.person_id),
                    "amount": str(t.amount),
                    "payment_method": t.payment_method,
                    "status": t.status,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "settled_at": t.related_subscription_id and "SETTLED" or None,
                }
                for t in transactions[:50]  # cap at 50 for frontend
            ],
        })

    grand_total = sum(
        (revenue_map.get(m.merchant_id, Decimal(0)) for m in merchants),
        Decimal(0),
    )
    return {
        "total_lifetime_revenue": str(grand_total),
        "merchant_count": len(merchants),
        "merchants": merchant_list,
    }


@router.get("/revenue/{merchant_id}")
def get_merchant_revenue(merchant_id: UUID, request: Request) -> dict:
    """Return detailed revenue for a single merchant."""
    orchestrator = request.app.state.orchestrator
    merchant = next(
        (m for m in orchestrator.merchants() if m.merchant_id == merchant_id), None
    )
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")

    transactions = orchestrator.settled_transactions_for_merchant(merchant_id)
    monthly = orchestrator.monthly_revenue_for_merchant(merchant_id)
    lifetime = sum(
        (t.amount for t in transactions),
        Decimal(0),
    )

    return {
        "merchant_id": str(merchant.merchant_id),
        "name": merchant.name,
        "merchant_type": merchant.merchant_type,
        "lifetime_revenue": str(lifetime),
        "transaction_count": len(transactions),
        "monthly_revenue": monthly,
        "transactions": [
            {
                "intent_id": str(t.intent_id),
                "person_id": str(t.person_id),
                "product_id": str(t.product_id),
                "amount": str(t.amount),
                "payment_method": t.payment_method,
                "status": t.status,
                "related_subscription_id": str(t.related_subscription_id) if t.related_subscription_id else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transactions
        ],
    }


# --- Process All Pending Payments ---

@router.post("/payments/process-all")
def process_all_payments(request: Request) -> dict:
    """Process all pending payment intents through LazerPay.

    When LazerPay is unavailable, falls back to inline settlement
    (probabilistic bank decision + balance check) and creates
    ledger entries so subscription payments appear in the ledger
    and affect account balances.
    """
    from dataclasses import replace
    from uuid import uuid4 as _uuid4
    import httpx

    from .domain import LedgerEntry, PAYMENT_SETTLED, PAYMENT_FAILED, SETTLED, FAILED, now

    orchestrator = request.app.state.orchestrator
    pending = orchestrator.pending_payment_intents()

    if not pending:
        return {"processed": 0, "settled": 0, "failed": 0, "message": "No pending payments"}

    lazerpay_base = "http://lazerpay_service:8001"
    settled = 0
    failed = 0
    ledger_entries = []

    for intent in pending:
        person = orchestrator._person_repo.find_by_id(intent.person_id)
        source_account_id = str(person.primary_account_id) if person else _uuid4().hex

        status = None
        try:
            response = httpx.post(
                f"{lazerpay_base}/api/payments/process",
                json={
                    "intent_id": str(intent.intent_id),
                    "person_id": str(intent.person_id),
                    "merchant_id": str(intent.merchant_id),
                    "amount": float(intent.amount),
                    "payment_method": intent.payment_method,
                    "source_account_id": source_account_id,
                },
                timeout=10.0,
            )
            data = response.json()
            status = data.get("status", "FAILED")
        except Exception:
            status = None  # Fall back to inline settlement

        if status is None:
            # Inline settlement fallback (LazerPay unavailable)
            bank = orchestrator._bank_repo.find_by_name("RupeeBank")
            person = orchestrator._person_repo.find_by_id(intent.person_id)
            rng = orchestrator._spending_engine._rng

            if person:
                current_balance = orchestrator._ledger_repo.balance_of(person.primary_account_id)
                if current_balance < intent.amount:
                    status = FAILED
                else:
                    success_rate = float(bank.authorization_success_rate) if bank else 99.1
                    if rng.random() * 100 < success_rate:
                        status = SETTLED
                    else:
                        status = FAILED
            else:
                status = SETTLED  # No person record, just settle for revenue

        # Use replace() for the frozen dataclass
        updated = replace(intent, status=status)
        orchestrator.settle_intent(updated)

        if status == SETTLED:
            settled += 1
            # Look up person's account for the DEBIT
            p = orchestrator._person_repo.find_by_id(intent.person_id)
            debit_account = p.primary_account_id if p else None
            ledger_entries.append(LedgerEntry(
                entry_id=_uuid4(),
                event_type=PAYMENT_SETTLED,
                from_account_id=debit_account,
                to_account_id=None,
                amount=intent.amount,
                simulation_timestamp=intent.created_at or now(),
                related_attempt_id=None,
                related_subscription_id=intent.related_subscription_id,
                metadata_json={
                    "payment_method": intent.payment_method,
                    "amount": str(intent.amount),
                },
            ))
        else:
            failed += 1
            ledger_entries.append(LedgerEntry(
                entry_id=_uuid4(),
                event_type=PAYMENT_FAILED,
                from_account_id=None,
                to_account_id=None,
                amount=intent.amount,
                simulation_timestamp=intent.created_at or now(),
                related_attempt_id=None,
                related_subscription_id=intent.related_subscription_id,
                metadata_json={
                    "payment_method": intent.payment_method,
                    "failure_reason": "bank_declined",
                },
            ))

    if ledger_entries:
        orchestrator._ledger_repo.append(ledger_entries)

    return {
        "processed": len(pending),
        "settled": settled,
        "failed": failed,
    }