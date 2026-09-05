from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

_MONEY = Decimal("0.01")
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header
from pydantic import BaseModel

from .domain import STATUS_COMPLETED, STATUS_FAILED, STATUS_PENDING, STATUS_RUNNING, LAZERPAY_FEE_RATE
from .recovery.smart_agent import (
    SmartRecoveryEngine,
    ActionValueCalculator,
    FeatureStore,
    PolicyValidator,
    RootCauseDiagnoser,
    Explainer,
    CounterfactualSimulator,
    ScenarioLibrary,
)

router = APIRouter(prefix="/api")


class RunSimulationRequest(BaseModel):
    people_count: int = 100
    days: int = 0
    hours: int = 0
    seed: int | None = None
    enable_recovery: bool = True


class ProcessPaymentRequest(BaseModel):
    person_id: str
    merchant_id: str
    product_id: str
    amount: float
    payment_method: str
    related_subscription_id: str | None = None
    source_account_id: str | None = None
    simulation_timestamp: str | None = None


class ProcessPaymentResponse(BaseModel):
    attempt_id: str
    status: str
    failure_code: str | None
    failure_reason: str | None


@router.post("/simulation/run")
def run_simulation(payload: RunSimulationRequest, request: Request) -> dict:
    if not payload.enable_recovery:
        # Rebuild the orchestrator without recovery wired in. The new
        # orchestrator's _recovery_repo is None, which the hourly loop
        # already guards against (no _process_recovery is called).
        db = request.app.state.db
        settings = request.app.state.settings
        config = request.app.state.sim_config
        from .container import build_orchestrator
        request.app.state.orchestrator = build_orchestrator(
            db,
            seed=payload.seed,
            config=config,
            settings=settings,
            enable_recovery=False,
        )
    orchestrator = request.app.state.orchestrator
    run_id = orchestrator.initialize(payload.people_count, seed=payload.seed)
    total_hours = payload.hours + (payload.days * 24)
    if total_hours > 0:
        orchestrator.run_hours(total_hours)
    summary = orchestrator.summary()
    summary["run_id"] = str(run_id) if run_id else None
    summary["seed"] = payload.seed
    summary["recovery_enabled"] = bool(orchestrator._recovery_repo)
    return {"status": "completed", "summary": summary}


@router.get("/simulation/runs")
def list_simulation_runs(
    request: Request, limit: int = 50
) -> dict:
    """Return recent simulation runs."""
    repo = getattr(request.app.state.orchestrator, "_sim_run_repo", None)
    if repo is None:
        return {"runs": []}
    runs = repo.find_recent(limit) if hasattr(repo, "find_recent") else []
    # Fallback: just return latest
    latest = repo.find_latest()
    runs_list = []
    if latest is not None:
        runs_list.append(_run_to_dict(latest))
    return {"runs": runs_list}


@router.get("/simulation/runs/{run_id}")
def get_simulation_run(run_id: UUID, request: Request) -> dict:
    """Return details for a specific simulation run."""
    repo = getattr(request.app.state.orchestrator, "_sim_run_repo", None)
    if repo is None:
        raise HTTPException(status_code=500, detail="Run repository not available")
    run = repo.find(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_to_dict(run)


def _run_to_dict(run) -> dict:
    return {
        "run_id": str(run.run_id),
        "seed": run.seed,
        "config_snapshot": run.config_snapshot,
        "people_count": run.people_count,
        "hours_run": run.hours_run,
        "status": run.status,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/simulation/status")
def simulation_status(request: Request) -> dict:
    return request.app.state.orchestrator.summary()


@router.post("/simulation/nuke")
def nuke_database(request: Request) -> dict:
    """Drop ALL tables and recreate them empty — complete reset.

    This nukes: people, accounts, banks, merchants, products, subscriptions,
    payment intents, ledger entries, simulation runs, and recovery actions.

    It ALSO drops every preserved parallel-experiment schema and deletes the
    on-disk report files, so the SARA Attempts tab doesn't keep showing
    retries from a previous parallel run after the page reloads.

    After nuking, a fresh orchestrator is built so the service is immediately
    ready for a new simulation run.
    """
    db = request.app.state.db
    settings = request.app.state.settings
    config = request.app.state.sim_config

    db.drop_schema()
    db.create_schema()

    # Drop preserved parallel-experiment schemas + report files so the SARA
    # Attempts tab is fully cleared, not just the public schema's tables.
    parallel_cleanup: dict = {}
    try:
        from .recovery.smart_agent.parallel_runner import ParallelExperimentRunner
        runner = ParallelExperimentRunner(db, settings=settings)
        parallel_cleanup = runner.nuke_all()
    except Exception as exc:
        # Don't fail the reset just because parallel cleanup blew up — the
        # main reset already happened. Log so the operator sees it.
        parallel_cleanup = {"error": str(exc)}

    # Rebuild the orchestrator with a fresh RNG (seed from config)
    from .container import build_orchestrator as _rebuild_orchestrator
    new_orch = _rebuild_orchestrator(
        db,
        seed=config.population.default_seed,
        config=config,
        settings=settings,
    )
    request.app.state.orchestrator = new_orch

    summary = new_orch.summary()
    return {
        "status": "nuked",
        "message": "All tables dropped and recreated. Fresh orchestrator built.",
        "summary": summary,
        "parallel_cleanup": parallel_cleanup,
    }


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
                "salary_deposit_hour": getattr(person, "salary_deposit_hour", 9),
                "spending_profile_category": person.spending_profile_category,
                "income_bracket": getattr(person, "income_bracket", None),
                "age_group": getattr(person, "age_group", None),
                "employment_type": getattr(person, "employment_type", None),
                "payment_preferences": person.payment_preferences_json,
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
        "salary_deposit_hour": getattr(person, "salary_deposit_hour", 9),
        "spending_profile_category": person.spending_profile_category,
        "spending_profile": person.spending_profile_json,
        "income_bracket": getattr(person, "income_bracket", None),
        "age_group": getattr(person, "age_group", None),
        "employment_type": getattr(person, "employment_type", None),
        "payment_preferences": person.payment_preferences_json,
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
def process_payment(
    payload: ProcessPaymentRequest,
    request: Request,
    correlation_id: str = Header(None),
):
    """Process a payment by calling LazerPay service.

    The People Service does NOT call the bank directly.
    It must go through LazerPay API, which then calls RupeeBank.
    """
    from dataclasses import replace
    from .config import Settings
    settings = request.app.state.settings
    lazerpay_url = settings.lazerpay_url
    http_timeout = settings.http_timeout_seconds

    orchestrator = request.app.state.orchestrator

    # Resolve the source account — use provided value or look up from person
    if payload.source_account_id:
        source_account_id = payload.source_account_id
    else:
        try:
            person = orchestrator._person_repo.find_by_id(UUID(payload.person_id))
            source_account_id = str(person.primary_account_id) if person else uuid4().hex
        except (ValueError, AttributeError):
            source_account_id = payload.source_account_id or uuid4().hex

    # Resolve simulation timestamp
    if payload.simulation_timestamp:
        try:
            sim_ts = datetime.fromisoformat(payload.simulation_timestamp)
        except ValueError:
            sim_ts = orchestrator._clock.current_datetime
    else:
        sim_ts = orchestrator._clock.current_datetime

    # Generate or accept correlation ID
    if not correlation_id:
        correlation_id = str(uuid4())
    corr_id = correlation_id[:64]  # truncate to fit column

    # Create payment intent and save it
    from .domain import PaymentIntent, INTENT_PENDING, now

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
        status=INTENT_PENDING,
        related_subscription_id=payload.related_subscription_id,
        created_at=now(),
        expires_at=now() + timedelta(hours=1),
    )
    orchestrator._intent_repo.add([intent])

    # Call LazerPay API to process the payment
    import httpx

    try:
        response = httpx.post(
            f"{lazerpay_url}/api/payments/process",
            json={
                "intent_id": str(intent.intent_id),
                "person_id": str(payload.person_id),
                "merchant_id": str(payload.merchant_id),
                "amount": float(payload.amount),
                "payment_method": payload.payment_method,
                "source_account_id": source_account_id,
                "simulation_timestamp": sim_ts.isoformat(),
                "correlation_id": corr_id,
            },
            headers={"X-Correlation-ID": corr_id},
            timeout=http_timeout,
        )
        lazerpay_response = response.json()
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504, detail="LazerPay service timed out"
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503, detail="LazerPay service unavailable"
        )

    # Update intent status based on LazerPay response
    attempt_id = lazerpay_response.get("attempt_id", "")
    status = lazerpay_response.get("status", "FAILED")
    failure_code = lazerpay_response.get("failure_code")
    failure_reason = lazerpay_response.get("failure_reason")

    updated_intent = replace(intent, status=status)
    orchestrator._intent_repo.save(updated_intent)

    # Handle subscription if applicable
    if payload.related_subscription_id and status == "SETTLED" or status == "AUTHORIZED":
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


@router.get("/payments/failures")
def get_payment_failures(request: Request) -> dict:
    """Return failure analytics: rate + breakdown by reason + recent failures.

    Counts are derived from ``PAYMENT_FAILED`` / ``PAYMENT_SETTLED`` ledger
    entries so the failure rate reflects *all* settlement outcomes across every
    path (inline simulation, process-all fallback, and the LazerPay gateway).

    NOTE: this route MUST be declared before ``/payments/{attempt_id}`` so
    that ``"failures"`` isn't captured as an attempt id.
    """
    from .domain import FAILURE_REASONS, FAILURE_CATEGORIES, PAYMENT_SETTLED, PAYMENT_FAILED
    from .failure_model import LEGACY_CODE_MAP

    orchestrator = request.app.state.orchestrator
    failed = orchestrator._ledger_repo.find_failed(limit=500)
    total_failed = orchestrator._ledger_repo.count_by_event_type(PAYMENT_FAILED)
    total_settled = orchestrator._ledger_repo.count_by_event_type(PAYMENT_SETTLED)

    def _normalize_code(raw: str | None) -> str:
        """Map legacy dummy codes onto the new taxonomy (old DB rows)."""
        code = raw or "UNKNOWN"
        return LEGACY_CODE_MAP.get(code, code)

    # Aggregate failures by reason (Python-side for DB portability incl. SQLite).
    by_reason: dict[str, dict] = {}
    for entry in failed:
        meta = entry.metadata_json or {}
        code = _normalize_code(meta.get("failure_code"))
        reason = meta.get("failure_reason") or FAILURE_REASONS.get(code, "Unknown")
        category = FAILURE_CATEGORIES.get(code, "UNKNOWN")
        bucket = by_reason.setdefault(
            code, {"code": code, "reason": reason, "category": category, "count": 0}
        )
        bucket["count"] += 1

    breakdown = sorted(by_reason.values(), key=lambda b: (-b["count"], b["code"]))
    for bucket in breakdown:
        bucket["pct_of_failures"] = (
            round(bucket["count"] / total_failed * 100, 1) if total_failed else 0.0
        )

    recent = [
        {
            "failure_code": _normalize_code((e.metadata_json or {}).get("failure_code")),
            "failure_reason": (e.metadata_json or {}).get("failure_reason")
            or FAILURE_REASONS.get(
                _normalize_code((e.metadata_json or {}).get("failure_code"))
                or "", "Unknown error"
            ),
            "amount": str(e.amount),
            "person_id": (e.metadata_json or {}).get("person_id"),
            "merchant_id": (e.metadata_json or {}).get("merchant_id"),
            "payment_method": (e.metadata_json or {}).get("payment_method"),
            "event_type": e.event_type,
            "simulation_timestamp": (
                e.simulation_timestamp.isoformat() if e.simulation_timestamp else None
            ),
            "related_attempt_id": e.related_attempt_id,
        }
        for e in failed
    ]

    denominator = total_settled + total_failed
    return {
        "total_failed": total_failed,
        "total_settled": total_settled,
        "failure_rate": (
            round(total_failed / denominator * 100, 2) if denominator else 0.0
        ),
        "by_reason": breakdown,
        "recent_failures": recent,
    }


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
    """Return revenue summary for all merchants (lifetime + monthly) and the
    LazerPay gateway's cut.

    LazerPay earns a flat 2% fee (across every payment method) on each settled
    transaction, taken from the merchant side.  Merchant ``lifetime_revenue``
    is the gross settled volume; ``lazerpay_fee`` (per merchant) and the top-level
    ``lazerpay_revenue`` are that merchant's / aggregate 2% cut that LazerPay keeps.
    """
    orchestrator = request.app.state.orchestrator
    merchants = orchestrator.merchants()
    revenue_map = orchestrator.revenue_by_merchant()
    fee_rate = Decimal(LAZERPAY_FEE_RATE)

    merchant_list = []
    for m in merchants:
        total = revenue_map.get(m.merchant_id, Decimal(0))
        monthly = orchestrator.monthly_revenue_for_merchant(m.merchant_id)
        transactions = orchestrator.settled_transactions_for_merchant(m.merchant_id)
        lazer_fee = (total * fee_rate).quantize(_MONEY, rounding=ROUND_HALF_UP)
        merchant_list.append({
            "merchant_id": str(m.merchant_id),
            "name": m.name,
            "merchant_type": m.merchant_type,
            "lifetime_revenue": str(total),
            "lazerpay_fee": str(lazer_fee),
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
    lazerpay_total = (grand_total * fee_rate).quantize(_MONEY, rounding=ROUND_HALF_UP)
    return {
        "total_lifetime_revenue": str(grand_total),
        "lazerpay_fee_rate": LAZERPAY_FEE_RATE,
        "lazerpay_revenue": str(lazerpay_total),
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

    from .config import Settings
    from .domain import (
        FAILURE_REASONS,
        LedgerEntry, PAYMENT_SETTLED, PAYMENT_FAILED,
        INTENT_SETTLED, INTENT_FAILED, now,
    )
    from .failure_model import classify_failure, failure_probability

    settings: Settings = request.app.state.settings
    lazerpay_url = settings.lazerpay_url
    http_timeout = settings.http_timeout_seconds

    orchestrator = request.app.state.orchestrator
    pending = orchestrator.pending_payment_intents()

    if not pending:
        return {"processed": 0, "settled": 0, "failed": 0, "message": "No pending payments"}

    sim_ts = orchestrator._clock.current_datetime
    settled = 0
    failed = 0
    ledger_entries = []

    for intent in pending:
        person = orchestrator._person_repo.find_by_id(intent.person_id)
        source_account_id = str(person.primary_account_id) if person else _uuid4().hex

        correlation_id = str(_uuid4())[:64]

        status = None
        attempt_id = None
        failure_code = None

        try:
            response = httpx.post(
                f"{lazerpay_url}/api/payments/process",
                json={
                    "intent_id": str(intent.intent_id),
                    "person_id": str(intent.person_id),
                    "merchant_id": str(intent.merchant_id),
                    "amount": float(intent.amount),
                    "payment_method": intent.payment_method,
                    "source_account_id": source_account_id,
                    "simulation_timestamp": sim_ts.isoformat(),
                    "correlation_id": correlation_id,
                },
                headers={"X-Correlation-ID": correlation_id},
                timeout=http_timeout,
            )
            data = response.json()
            status = data.get("status", "FAILED")
            attempt_id = data.get("attempt_id", "")
            failure_code = data.get("failure_code")
        except (httpx.TimeoutException, httpx.ConnectError):
            status = None  # Fall back to inline settlement

        if status is None:
            bank = orchestrator._bank_repo.find_by_name("RupeeBank")
            bank_state = bank.current_state if bank else "NORMAL"
            if person:
                current_balance = orchestrator._ledger_repo.balance_of(person.primary_account_id)
                if current_balance < intent.amount:
                    status = INTENT_FAILED
                    failure_code = "INSUFFICIENT_FUNDS"
                else:
                    p_fail = failure_probability(
                        intent.payment_method,
                        bank_state=bank_state,
                        amount=float(intent.amount),
                        balance=float(current_balance),
                        hour=sim_ts.hour,
                    )
                    if orchestrator._rng.random() >= p_fail:
                        status = INTENT_SETTLED
                    else:
                        status = INTENT_FAILED
                        failure_code, _cat = classify_failure(
                            orchestrator._rng,
                            method=intent.payment_method,
                            bank_state=bank_state,
                        )
            else:
                status = INTENT_SETTLED

        updated = replace(intent, status=status)
        orchestrator.settle_intent(updated)

        if status == INTENT_SETTLED:
            settled += 1
            p = orchestrator._person_repo.find_by_id(intent.person_id)
            debit_account = str(p.primary_account_id) if p else None
            ledger_entries.append(LedgerEntry(
                entry_id=_uuid4(),
                event_type=PAYMENT_SETTLED,
                from_account_id=debit_account,
                to_account_id=None,
                amount=intent.amount,
                simulation_timestamp=sim_ts,
                related_attempt_id=attempt_id,
                related_subscription_id=intent.related_subscription_id,
                metadata_json={
                    "payment_method": intent.payment_method,
                    "amount": str(intent.amount),
                    "correlation_id": correlation_id,
                },
            ))
        else:
            failed += 1
            p = orchestrator._person_repo.find_by_id(intent.person_id)
            debit_account = str(p.primary_account_id) if p else None
            ledger_entries.append(LedgerEntry(
                entry_id=_uuid4(),
                event_type=PAYMENT_FAILED,
                # No money moves on a failed payment — don't debit the account.
                from_account_id=None,
                to_account_id=None,
                amount=intent.amount,
                simulation_timestamp=sim_ts,
                related_attempt_id=attempt_id,
                related_subscription_id=intent.related_subscription_id,
                metadata_json={
                    "payment_method": intent.payment_method,
                    "failure_code": failure_code,
                    "failure_reason": FAILURE_REASONS.get(
                        failure_code or "", "Unknown gateway error"
                    ),
                    "correlation_id": correlation_id,
                },
            ))

    if ledger_entries:
        orchestrator._ledger_repo.append(ledger_entries)

    return {
        "processed": len(pending),
        "settled": settled,
        "failed": failed,
    }


# --- Recovery System ---

@router.get("/recovery/actions")
def list_recovery_actions(
    request: Request,
    limit: int = 500,
    outcome: str | None = None,
    action_type: str | None = None,
    engine_type: str | None = None,
) -> dict:
    """Return recovery actions, optionally filtered by outcome, action type, or engine type.

    Each action is a fully auditable record with all fields needed to
    reconstruct the recovery history for a failed payment.

    Query params:
      engine_type  – filter to actions from a specific engine
                    ('BASELINE' or 'AI_AGENT').
    """
    recovery_repo = getattr(request.app.state.orchestrator, "_recovery_repo", None)
    if recovery_repo is None:
        return {"actions": [], "count": 0, "recovery_enabled": False}

    actions = recovery_repo.find_all(
        limit=limit, outcome=outcome, action_type=action_type, engine_type=engine_type
    )
    return {
        "actions": [_action_to_dict(a) for a in actions],
        "count": len(actions),
        "recovery_enabled": True,
    }


@router.get("/recovery/actions/intent/{intent_id}")
def get_recovery_history(intent_id: UUID, request: Request) -> dict:
    """Return the full recovery history for a single failed payment intent."""
    recovery_repo = getattr(request.app.state.orchestrator, "_recovery_repo", None)
    if recovery_repo is None:
        return {"actions": [], "count": 0, "recovery_enabled": False}

    actions = recovery_repo.find_by_intent_id(intent_id)
    return {
        "intent_id": str(intent_id),
        "actions": [_action_to_dict(a) for a in actions],
        "count": len(actions),
        "recovery_enabled": True,
    }


@router.get("/recovery/metrics")
def get_recovery_metrics(
    request: Request,
    run_id: UUID | None = None,
    engine_type: str | None = None,
) -> dict:
    """Return aggregated recovery metrics (counts, GMV, rates, breakdowns).

    Query params:
      run_id  – filter to a single simulation run.
      engine_type – filter to actions from a specific engine
                    ('BASELINE' or 'AI_AGENT').
    """
    recovery_repo = getattr(request.app.state.orchestrator, "_recovery_repo", None)
    if recovery_repo is None:
        return {
            "recovery_enabled": False,
            "total_recovery_actions": 0,
            "retry_actions": 0,
            "successful_recoveries": 0,
            "failed_recoveries": 0,
            "recovery_rate": 0.0,
            "total_recovered_gmv": "0",
        }

    from .recovery.metrics import RecoveryMetricsCollector

    collector = RecoveryMetricsCollector(recovery_repo._db)
    metrics = collector.collect(run_id=run_id, engine_type=engine_type)
    result = metrics.to_dict()
    result["recovery_enabled"] = True
    return result


@router.get("/recovery/runs")
def list_recovery_runs(request: Request, limit: int = 50) -> dict:
    """Return recent recovery run metadata (strategy, seed, outcomes)."""
    repo = getattr(request.app.state.orchestrator, "_sim_run_repo", None)
    if repo is None:
        return {"runs": []}

    runs = repo.find_recent(limit) if hasattr(repo, "find_recent") else []
    runs_list = []
    for run in runs:
        snapshot = run.config_snapshot or {}
        is_recovery = snapshot.get("engine_type") is not None
        if is_recovery:
            runs_list.append({
                "run_id": str(run.run_id),
                "seed": run.seed,
                "engine_type": snapshot.get("engine_type", "BASELINE"),
                "status": run.status,
                "max_retries": snapshot.get("max_retries", 3),
                "retry_interval_hours": snapshot.get("retry_interval_hours", 12),
                "total_recovery_actions": snapshot.get("total_recovery_actions", 0),
                "successful_recoveries": snapshot.get("successful_recoveries", 0),
                "failed_recoveries": snapshot.get("failed_recoveries", 0),
                "stopped_recoveries": snapshot.get("stopped_recoveries", 0),
                "recovered_gmv": str(snapshot.get("recovered_gmv", "0")),
                "hours_run": run.hours_run,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            })

    # Also include the current recovery run from the orchestrator
    orch = request.app.state.orchestrator
    current_run_id = getattr(orch, "_recovery_run_id", None)
    if current_run_id and not any(r["run_id"] == str(current_run_id) for r in runs_list):
        from .recovery.run import RecoveryRunTracker
        tracker = RecoveryRunTracker(recovery_repo._db) if recovery_repo else None
        if tracker:
            meta = tracker.find(current_run_id)
            if meta:
                runs_list.insert(0, {
                    "run_id": str(meta.run_id),
                    "seed": meta.seed,
                    "engine_type": meta.engine_type.value,
                    "status": meta.status,
                    "max_retries": meta.max_retries,
                    "retry_interval_hours": meta.retry_interval_hours,
                    "total_recovery_actions": meta.total_recovery_actions,
                    "successful_recoveries": meta.successful_recoveries,
                    "failed_recoveries": meta.failed_recoveries,
                    "stopped_recoveries": meta.stopped_recoveries,
                    "recovered_gmv": str(meta.recovered_gmv),
                    "hours_run": 0,
                    "started_at": meta.start_time.isoformat() if meta.start_time else None,
                    "completed_at": meta.end_time.isoformat() if meta.end_time else None,
                })

    return {"runs": runs_list}


def _action_to_dict(action) -> dict:
    """Serialize a RecoveryAction dataclass for API responses."""
    metadata = action.metadata_json or {}
    return {
        "action_id": str(action.action_id),
        "run_id": str(action.run_id) if action.run_id else None,
        "payment_intent_id": str(action.payment_intent_id) if action.payment_intent_id else None,
        "related_attempt_id": action.related_attempt_id,
        "action_type": action.action_type.value if action.action_type else None,
        "retry_number": action.retry_number,
        "reason": action.reason,
        "schedule_reason": action.schedule_reason,
        "scheduled_for": action.scheduled_for.isoformat() if action.scheduled_for else None,
        "executed_at": action.executed_at.isoformat() if action.executed_at else None,
        "outcome": action.outcome.value if action.outcome else None,
        "failure_code": action.failure_code,
        "failure_reason": action.failure_reason,
        "amount": str(action.amount) if action.amount else None,
        "payment_method": action.payment_method,
        "retry_attempt_id": action.retry_attempt_id,
        "customer_declined": action.customer_declined,
        "cost": str(action.cost) if action.cost else None,
        "expected_recovery": str(action.expected_recovery) if action.expected_recovery else None,
        # ENPV is stashed in metadata_json by the scheduler at decision time
        # (avoids a schema migration). Surface it as a top-level field so the
        # SARA tab can render it without depending on the optional XGBoost
        # model in the container image.
        "expected_net_value": metadata.get("expected_net_value"),
        "metadata_json": metadata,
        "created_at": action.created_at.isoformat() if action.created_at else None,
    }


# --------------------------------------------------------------------------- #
# Smart Recovery Agent (SARA) Endpoints
# --------------------------------------------------------------------------- #

class SmartRunRequest(BaseModel):
    """Request to trigger a smart-agent recovery run on failed intents."""
    intent_ids: list[str] | None = None  # specific intents; if None, all recent failures
    seed: int | None = None


class CounterfactualRequest(BaseModel):
    """Request to simulate counterfactual scenarios for a case."""
    scenarios: list[str] | None = None  # scenario names; if None, all applicable


@router.post("/recovery/smart/run")
def run_smart_recovery(payload: SmartRunRequest, request: Request) -> dict:
    """Trigger a Smart Agent recovery run on failed payment intents.

    Uses the injected SmartRecoveryEngine (if configured) to make recovery
    decisions.  Returns a summary of decisions made.
    """
    orch = request.app.state.orchestrator
    recovery_repo = getattr(orch, "_recovery_repo", None)
    if recovery_repo is None:
        return {"status": "error", "message": "Recovery not enabled"}

    # Check if a smart engine is wired
    engine = getattr(orch, "_recovery_engine", None)
    if not isinstance(engine, SmartRecoveryEngine) if engine else True:
        return {
            "status": "error",
            "message": "SmartRecoveryEngine not configured. "
            "Use the experiment runner or configure build_orchestrator with a smart engine.",
        }

    from .recovery.context_builder import RecoveryContextBuilder
    context_builder = getattr(orch, "_recovery_context_builder", None)
    if context_builder is None:
        return {"status": "error", "message": "Context builder not available"}

    # Get failed intents to process
    from uuid import UUID as _UUID
    if payload.intent_ids:
        intent_ids = [_UUID(i) for i in payload.intent_ids]
    else:
        # Get all FAILED intents that haven't been scheduled for recovery yet
        intent_repo = getattr(orch, "_intent_repo", None)
        if intent_repo is None:
            return {"status": "error", "message": "Intent repository not available"}
        all_intents = intent_repo.find_all(status="FAILED")
        intent_ids = [i.intent_id for i in all_intents[:50]]  # limit batch

    decisions = []
    for intent_id in intent_ids:
        intent = orch._intent_repo.find_by_id(intent_id)
        if intent is None:
            continue

        # Build recovery context
        context = context_builder.build_for_intent(
            intent,
            current_simulation_time=orch._clock.now(),
        )

        # Get decision + explanation from the smart engine
        if hasattr(engine, "decide_with_explanation"):
            decision, explanation = engine.decide_with_explanation(context)
        else:
            decision = engine.decide(context)
            explanation = None

        entry = {
            "intent_id": str(intent_id),
            "action": decision.action.value,
            "scheduled_for": decision.scheduled_for.isoformat() if decision.scheduled_for else None,
            "reason": decision.reason,
            "retry_number": decision.retry_number,
        }
        if explanation:
            entry["explanation"] = {
                "why_this_action": explanation.why_this_action,
                "policy_summary": explanation.policy_summary,
                "action_details": explanation.action_details,
            }
        decisions.append(entry)

    return {
        "status": "completed",
        "decisions": decisions,
        "count": len(decisions),
    }


@router.get("/recovery/smart/cases")
def get_smart_cases(
    request: Request,
    limit: int = 100,
    status: str | None = None,
) -> dict:
    """Return the ranked action queue — cases awaiting recovery action.

    Cases are ordered by expected net value (highest first), with
    explanations for why each action was recommended.
    """
    recovery_repo = getattr(request.app.state.orchestrator, "_recovery_repo", None)
    if recovery_repo is None:
        return {"cases": [], "count": 0, "recovery_enabled": False}

    actions = recovery_repo.find_all(limit=limit, outcome="PENDING")

    cases = []
    for action in actions:
        # Try to get explanation from audit trail
        from .recovery.smart_agent.audit import AuditEventWriter
        auditor = AuditEventWriter(recovery_repo._db)
        audit_events = auditor.find_for_case(action.action_id)

        explanation = None
        for evt in audit_events:
            if evt.event_type == "decision" and evt.decision_json:
                explanation = evt.decision_json
                break

        cases.append({
            "action_id": str(action.action_id),
            "intent_id": str(action.payment_intent_id) if action.payment_intent_id else None,
            "action_type": action.action_type.value,
            "reason": action.reason,
            "scheduled_for": action.scheduled_for.isoformat() if action.scheduled_for else None,
            "priority": "high" if action.failure_code in ("INSUFFICIENT_FUNDS", "EXPIRED_PAYMENT_METHOD") else "normal",
            "expected_recovery": str(action.expected_recovery) if action.expected_recovery else None,
            "explanation": explanation,
        })

    # Sort by priority (high first) and scheduled_for time
    cases.sort(key=lambda c: (
        0 if c["priority"] == "high" else 1,
        c["scheduled_for"] or "",
    ))

    return {"cases": cases, "count": len(cases)}


@router.get("/recovery/smart/cases/{case_id}")
def get_smart_case(case_id: str, request: Request) -> dict:
    """Return full details for a single recovery case.

    Includes: context snapshot, diagnosis, candidate actions with ENPV,
    policy checks, audit trail, and explanation.
    """
    from uuid import UUID as _UUID
    from .recovery.smart_agent.audit import AuditEventWriter

    recovery_repo = getattr(request.app.state.orchestrator, "_recovery_repo", None)
    if recovery_repo is None:
        return {"error": "Recovery not enabled"}

    try:
        case_uuid = _UUID(case_id)
    except ValueError:
        return {"error": f"Invalid case_id: {case_id}"}

    action = recovery_repo.find(case_uuid)
    if action is None:
        return {"error": f"Case not found: {case_id}"}

    # Get full audit trail
    auditor = AuditEventWriter(recovery_repo._db)
    audit_events = auditor.find_for_case(action.action_id)

    # Get prior actions for this intent
    prior_actions = []
    if action.payment_intent_id:
        prior_actions = recovery_repo.find_by_intent_id(action.payment_intent_id)

    # Find the decision event
    decision_event = None
    diagnosis_event = None
    for evt in audit_events:
        if evt.event_type == "decision":
            decision_event = evt
        elif evt.event_type == "llm_diagnosis":
            diagnosis_event = evt

    return {
        "case_id": str(action.action_id),
        "intent_id": str(action.payment_intent_id) if action.payment_intent_id else None,
        "action_type": action.action_type.value,
        "status": action.outcome.value if action.outcome else "PENDING",
        "failure_code": action.failure_code,
        "failure_reason": action.failure_reason,
        "amount": str(action.amount) if action.amount else None,
        "payment_method": action.payment_method,
        "retry_number": action.retry_number,
        "scheduled_for": action.scheduled_for.isoformat() if action.scheduled_for else None,
        "executed_at": action.executed_at.isoformat() if action.executed_at else None,
        "expected_recovery": str(action.expected_recovery) if action.expected_recovery else None,
        "reason": action.reason,
        "decision": decision_event.decision_json if decision_event else None,
        "policy_checks": decision_event.policy_checks if decision_event else None,
        "diagnosis": diagnosis_event.decision_json if diagnosis_event else None,
        "prior_actions": [_action_to_dict(a) for a in prior_actions],
        "audit_trail": [
            {
                "event_id": str(evt.event_id),
                "timestamp": evt.timestamp.isoformat(),
                "event_type": evt.event_type,
                "actor": evt.actor,
                "outcome": evt.outcome,
                "input_hash": evt.input_snapshot_hash,
            }
            for evt in audit_events
        ],
    }


@router.post("/recovery/smart/cases/{case_id}/simulate")
def simulate_counterfactuals(
    case_id: str,
    payload: CounterfactualRequest,
    request: Request,
) -> dict:
    """Run counterfactual simulation for a case.

    Evaluates "what-if" scenarios (e.g., "wait 30 min then retry") and
    returns ranked outcomes by expected net value.
    """
    from uuid import UUID as _UUID
    from .recovery.smart_agent.agent import SmartRecoveryEngine

    orch = request.app.state.orchestrator
    recovery_repo = getattr(orch, "_recovery_repo", None)
    if recovery_repo is None:
        return {"error": "Recovery not enabled"}

    engine = getattr(orch, "_recovery_engine", None)
    if not isinstance(engine, SmartRecoveryEngine):
        return {"error": "SmartRecoveryEngine not configured"}

    try:
        case_uuid = _UUID(case_id)
    except ValueError:
        return {"error": f"Invalid case_id: {case_id}"}

    action = recovery_repo.find(case_uuid)
    if action is None:
        return {"error": f"Case not found: {case_id}"}

    # Build context for this case
    context_builder = getattr(orch, "_recovery_context_builder", None)
    if context_builder is None:
        return {"error": "Context builder not available"}

    intent = orch._intent_repo.find_by_id(action.payment_intent_id) if action.payment_intent_id else None
    if intent is None:
        return {"error": "Cannot resolve payment intent for this case"}

    context = context_builder.build_for_intent(intent, orch._clock.now())

    # Run counterfactual evaluation
    scenario_names = payload.scenarios
    scenarios = ScenarioLibrary.get_all()
    if scenario_names:
        scenarios = [s for s in scenarios if s.name in scenario_names]

    # Build a counterfactual simulator
    cf = CounterfactualSimulator(engine._calculator)

    # Build features + diagnosis
    features = engine._feature_store.extract(context)
    diagnosis = engine._diagnoser.diagnose(context, features)

    # Evaluate scenarios
    from .recovery.smart_agent.counterfactual import CounterfactualScenario
    cf_scenarios = [
        CounterfactualScenario(
            name=s.name,
            description=s.description,
            action_type=s.expected_outcome.replace("retry", "RETRY").replace("stop", "STOP").replace("link", "SEND_PAYMENT_LINK"),
            delay_hours=0.0,
            bank_state=s.bank_state,
        )
        for s in scenarios
    ]

    outcomes = cf.evaluate(context, features, diagnosis, cf_scenarios)

    return {
        "case_id": case_id,
        "scenarios": [
            {
                "name": o.scenario.name,
                "description": o.scenario.description,
                "action_type": o.scenario.action_type,
                "delay_hours": o.scenario.delay_hours,
                "expected_net_value": str(o.expected_value.expected_net_value),
                "recovery_probability": o.recovery_probability,
                "risk_notes": o.risk_notes,
            }
            for o in outcomes
        ],
        "best_scenario": outcomes[0].scenario.name if outcomes else None,
    }


@router.post("/recovery/smart/cases/{case_id}/approve")
def approve_action(
    case_id: str,
    request: Request,
) -> dict:
    """Manually approve a recommended smart-agent action.

    In the current simulation, actions are auto-executed.  This endpoint
    is provided for future human-in-the-loop review mode.
    """
    from uuid import UUID as _UUID

    recovery_repo = getattr(request.app.state.orchestrator, "_recovery_repo", None)
    if recovery_repo is None:
        return {"error": "Recovery not enabled"}

    try:
        case_uuid = _UUID(case_id)
    except ValueError:
        return {"error": f"Invalid case_id: {case_id}"}

    action = recovery_repo.find(case_uuid)
    if action is None:
        return {"error": f"Case not found: {case_id}"}

    if action.outcome is not None and action.outcome.value != "PENDING":
        return {
            "status": "already_processed",
            "outcome": action.outcome.value,
        }

    # In simulation mode, the executor already handles execution.
    # This endpoint marks the action as approved for audit purposes.
    return {
        "status": "approved",
        "case_id": case_id,
        "action_type": action.action_type.value,
        "scheduled_for": action.scheduled_for.isoformat() if action.scheduled_for else None,
        "message": "Action approved. Execution will proceed via the normal scheduler.",
    }


@router.post("/recovery/experiments/compare")
def run_experiment_comparison(
    payload: RunSimulationRequest,
    request: Request,
) -> dict:
    """Run a paired experiment: baseline vs Smart Agent on cloned DB state.

    This endpoint orchestrates:
      1. A seed simulation run (creating failed payments).
      2. Two recovery passes — one with BaselineRecoveryEngine, one with
        SmartRecoveryEngine — on cloned database state.
      3. Metric computation and lift calculation.

    Returns the comparison report with lift metrics.
    """
    from .recovery.smart_agent.agent import SmartRecoveryEngine
    from .recovery import BaselineRecoveryEngine

    orch = request.app.state.orchestrator
    db = orch._bank_repo._db

    # Use the experiment runner module
    from .recovery.smart_agent.experiment_runner import ExperimentRunner
    runner = ExperimentRunner(db, settings=orch._settings)
    report = runner.run(
        people_count=payload.people_count,
        hours=payload.hours + (payload.days * 24),
        seed=payload.seed,
    )

    return report.to_dict() if hasattr(report, "to_dict") else {"report": str(report)}


# --------------------------------------------------------------------------- #
# Parallel experiment endpoints — both engines run simultaneously on
# separate PostgreSQL schemas with identical seed data.
# --------------------------------------------------------------------------- #


@router.post("/recovery/experiments/parallel/run")
def run_parallel_experiment(
    payload: RunSimulationRequest,
    request: Request,
) -> dict:
    """Run a parallel experiment: baseline + Smart Agent in separate schemas.

    Both engines receive identical seed data (same seed → same RNG streams)
    and run in parallel threads for the same time window.  The schemas are
    dropped automatically after metrics are collected.

    Returns the comparison report with lift metrics.
    """
    orch = request.app.state.orchestrator
    db = orch._bank_repo._db

    from .recovery.smart_agent.parallel_runner import ParallelExperimentRunner

    # Keep schemas only when explicitly requested for case-level debugging.
    # Normal UI runs should clean up their isolated copies after the scorecard
    # is collected; the JSON report remains available in experiment history.
    keep_schemas = request.query_params.get("keep_schemas", "true").lower() == "true"

    runner = ParallelExperimentRunner(db, settings=orch._settings)
    report = runner.run(
        people_count=payload.people_count,
        hours=payload.hours + (payload.days * 24),
        seed=payload.seed or 42,
        keep_schemas=keep_schemas,
    )

    # Also advance the public/read model used by the dashboard tabs.  The
    # paired schemas remain the source of truth for the comparison; this
    # mirror gives People, Ledger, Bank, Merchant Revenue, and Failures the
    # same seeded simulation window to display after the button is pressed.
    public_run_id = orch.initialize(payload.people_count, seed=payload.seed or 42)
    hours = payload.hours + (payload.days * 24)
    if hours > 0:
        orch.run_hours(hours)

    result = report.to_dict() if hasattr(report, "to_dict") else {"report": str(report)}
    result["experiment_id"] = runner._last_experiment_id if hasattr(runner, "_last_experiment_id") else None
    result["schemas_preserved"] = keep_schemas
    result["seed"] = payload.seed or 42
    result["people_count"] = payload.people_count
    result["hours"] = hours
    result["public_run_id"] = str(public_run_id) if public_run_id else None
    return result

    return report.to_dict()


@router.get("/recovery/experiments/parallel/list")
def list_parallel_experiments(
    limit: int = 20,
    request: Request = None,
) -> dict:
    """List previously saved parallel experiment reports."""
    from .recovery.smart_agent.parallel_runner import ParallelExperimentRunner
    from .config import Settings

    settings = getattr(request.app.state, "settings", Settings.from_env())
    runner = ParallelExperimentRunner.__new__(ParallelExperimentRunner)
    runner._settings = settings
    reports = runner.list_experiments(limit=limit)

    return {"experiments": reports, "count": len(reports)}


@router.get("/recovery/experiments/parallel/{experiment_id}/cases")
def get_parallel_experiment_cases(
    experiment_id: str,
    engine: str = "smart",
    limit: int = 100,
    status: str | None = None,
    request: Request = None,
) -> dict:
    """Retrieve recovery cases from a parallel experiment run.

    Parameters
    ----------
    experiment_id :
        The experiment identifier (first 8 chars of the UUID).
    engine :
        Which engine's schema to query ('baseline' or 'smart').
    limit :
        Maximum number of cases to return.
    status :
        Filter by outcome (SUCCESS, FAILED, UNKNOWN, PENDING).
    """
    from .recovery.smart_agent.parallel_runner import ParallelExperimentRunner
    from .config import Settings

    settings = getattr(request.app.state, "settings", Settings.from_env())
    runner = ParallelExperimentRunner.__new__(ParallelExperimentRunner)
    runner._settings = settings

    cases = runner.get_experiment_cases(
        experiment_id=experiment_id,
        engine=engine,
        limit=limit,
        status=status,
    )

    return {"cases": cases, "count": len(cases), "engine": engine}


@router.get("/recovery/experiments/parallel/{experiment_id}/metrics")
def get_parallel_experiment_metrics(
    experiment_id: str,
    engine: str = "smart",
    request: Request = None,
) -> dict:
    """Return lifetime metrics from a preserved parallel experiment schema."""
    if engine not in ("baseline", "smart"):
        raise HTTPException(status_code=400, detail="engine must be baseline or smart")
    from .recovery.smart_agent.parallel_runner import ParallelExperimentRunner
    from .config import Settings

    settings = getattr(request.app.state, "settings", Settings.from_env())
    runner = ParallelExperimentRunner.__new__(ParallelExperimentRunner)
    runner._settings = settings
    return {
        **runner.get_experiment_metrics(experiment_id, engine=engine),
        "experiment_id": experiment_id,
        "engine": engine,
    }


@router.get("/recovery/experiments/parallel/{experiment_id}/retries")
def get_parallel_experiment_retries(
    experiment_id: str,
    engine: str = "smart",
    limit: int = 5000,
    status: str | None = None,
    request: Request = None,
) -> dict:
    """Return only RETRY actions from a preserved parallel experiment schema."""
    if engine not in ("baseline", "smart"):
        raise HTTPException(status_code=400, detail="engine must be baseline or smart")
    from .recovery.smart_agent.parallel_runner import ParallelExperimentRunner
    from .config import Settings

    settings = getattr(request.app.state, "settings", Settings.from_env())
    runner = ParallelExperimentRunner.__new__(ParallelExperimentRunner)
    runner._settings = settings
    retries = runner.get_experiment_retries(
        experiment_id, engine=engine, limit=min(max(limit, 1), 5000), status=status
    )

    # Best-effort: enrich each row with predicted_p_recovery + predicted_enpv.
    # If the model isn't trained (or xgboost isn't installed), skip silently.
    enriched = _enrich_with_predictions(retries)

    return {"actions": enriched, "count": len(enriched), "experiment_id": experiment_id, "engine": engine}


def _enrich_with_predictions(rows: list[dict]) -> list[dict]:
    """Attach predicted_p_recovery + predicted_enpv to each action row.

    No-op (returns rows untouched) when the model isn't trained, so this is
    safe to call on every request without a feature-flag check at the caller.

    Uses the batched `infer.predict_batch` so a 5000-row retries response
    is a single Booster.predict call rather than 5000 round-trips.
    """
    try:
        import sys
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[3]
        xg_dir = repo_root / "XG_DATA"
        if str(xg_dir) not in sys.path:
            sys.path.insert(0, str(xg_dir))
        import infer
    except Exception:
        return rows

    if not infer.is_ready():
        return rows

    feat_dicts = [
        {
            "amount": row.get("amount"),
            "retry_number": row.get("retry_number"),
            "action_type": row.get("action_type"),
            "payment_method": row.get("payment_method"),
            "failure_code": row.get("failure_code"),
            "customer_declined": row.get("customer_declined"),
        }
        for row in rows
    ]
    try:
        preds = infer.predict_batch(feat_dicts)
    except Exception:
        return rows

    out = []
    for row, pred in zip(rows, preds):
        row = dict(row)
        row["predicted_p_recovery"] = pred.get("p_recovery")
        row["predicted_enpv"] = pred.get("enpv")
        row["has_model"] = pred.get("has_model", False)
        out.append(row)
    return out


@router.get("/recovery/experiments/parallel/{experiment_id}/cases/{case_id}")
def get_parallel_experiment_case_detail(
    experiment_id: str,
    case_id: str,
    engine: str = "smart",
    request: Request = None,
) -> dict:
    """Retrieve full details for a single case from a parallel experiment.

    For the smart agent engine, includes diagnosis, policy checks, audit trail,
    and prior actions for the same payment intent.
    """
    from .recovery.smart_agent.parallel_runner import ParallelExperimentRunner
    from .config import Settings

    settings = getattr(request.app.state, "settings", Settings.from_env())
    runner = ParallelExperimentRunner.__new__(ParallelExperimentRunner)
    runner._settings = settings

    return runner.get_experiment_case_detail(
        experiment_id=experiment_id,
        case_id=case_id,
        engine=engine,
    )


@router.get("/recovery/experiments/parallel/{experiment_id}/audit")
def get_parallel_experiment_audit(
    experiment_id: str,
    engine: str = "smart",
    limit: int = 200,
    request: Request = None,
) -> dict:
    """Return the immutable audit stream for baseline or SARA."""
    if engine not in ("baseline", "smart"):
        raise HTTPException(status_code=400, detail="engine must be baseline or smart")
    from .recovery.smart_agent.parallel_runner import ParallelExperimentRunner
    from .config import Settings
    settings = getattr(request.app.state, "settings", Settings.from_env())
    runner = ParallelExperimentRunner.__new__(ParallelExperimentRunner)
    runner._settings = settings
    events = runner.get_experiment_audit(experiment_id, engine=engine, limit=min(limit, 1000))
    return {"experiment_id": experiment_id, "engine": engine, "events": events, "count": len(events)}


@router.get("/recovery/audit/{case_id}")
def get_audit_trail(case_id: str, request: Request) -> dict:
    """Return the full audit trail for a recovery case.

    Every decision, policy check, execution, and outcome is recorded.
    """
    from uuid import UUID as _UUID
    from .recovery.smart_agent.audit import AuditEventWriter

    recovery_repo = getattr(request.app.state.orchestrator, "_recovery_repo", None)
    if recovery_repo is None:
        return {"error": "Recovery not enabled"}

    try:
        case_uuid = _UUID(case_id)
    except ValueError:
        return {"error": f"Invalid case_id: {case_id}"}

    auditor = AuditEventWriter(recovery_repo._db)
    events = auditor.find_for_case(case_uuid)

    return {
        "case_id": case_id,
        "events": [
            {
                "event_id": str(evt.event_id),
                "run_id": str(evt.run_id) if evt.run_id else None,
                "timestamp": evt.timestamp.isoformat(),
                "agent_version": evt.agent_version,
                "policy_version": evt.policy_version,
                "actor": evt.actor,
                "event_type": evt.event_type,
                "input_snapshot_hash": evt.input_snapshot_hash,
                "evidence_refs": evt.evidence_refs,
                "decision_json": evt.decision_json,
                "policy_checks": evt.policy_checks,
                "idempotency_key": evt.idempotency_key,
                "execution_result": evt.execution_result,
                "outcome": evt.outcome,
            }
            for evt in events
        ],
        "count": len(events),
    }


@router.get("/recovery/insights/rail-health")
def get_rail_health_insights(
    request: Request,
    method: str | None = None,
) -> dict:
    """Return rail health dashboard data.

    Shows current bank state, failure rates, and do-not-retry windows
    for each payment method.
    """
    orch = request.app.state.orchestrator
    settings = getattr(orch, "_settings", None)
    from .recovery.smart_agent.rail_health import RailHealthMonitor
    from .database import Database

    db = orch._bank_repo._db
    monitor = RailHealthMonitor(db, settings)

    methods = [method] if method else ["UPI", "CARD", "NETBANKING"]
    rails = []

    for m in methods:
        health = monitor.get_rail_health(m)
        rails.append({
            "method": health.method,
            "bank_state": health.bank_state,
            "rail_health_score": health.rail_health_score,
            "is_degraded": health.is_degraded,
            "failure_rate_window": health.failure_rate_window,
            "sample_size_window": health.sample_size_window,
            "do_not_retry_until": (
                health.do_not_retry_until.isoformat()
                if health.do_not_retry_until
                else None
            ),
            "last_updated": health.last_updated.isoformat(),
        })

    degraded = monitor.get_degraded_rails()

    return {
        "rails": rails,
        "degraded_rails": degraded,
        "overall_health": (
            "healthy" if not degraded
            else f"degraded: {', '.join(degraded)}"
        ),
    }


# --------------------------------------------------------------------------- #
# ML model inference endpoint (XGBoost trained in XG_DATA/train.py)            #
# --------------------------------------------------------------------------- #


class MLPredictRequest(BaseModel):
    features: dict


@router.post("/ml/predict")
def ml_predict(payload: MLPredictRequest) -> dict:
    """Predict P(recovery) and ENPV for a single recovery action.

    `features` mirrors the columns of sara_recovery_actions.csv; the only
    required key is `amount`. All other keys default to 0 / False.

    If the model hasn't been trained yet, returns has_model=False with
    null predictions rather than raising — the UI renders '—' in that case.
    """
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    xg_dir = repo_root / "XG_DATA"
    if str(xg_dir) not in sys.path:
        sys.path.insert(0, str(xg_dir))

    try:
        import infer
    except Exception as e:  # xgboost/pandas not installed yet, etc.
        return {
            "has_model": False,
            "p_recovery": None,
            "enpv": None,
            "error": f"infer module unavailable: {e}",
        }

    if not infer.is_ready():
        return {
            "has_model": False,
            "p_recovery": None,
            "enpv": None,
            "error": infer.load_error() or "model not trained",
        }

    out = infer.predict(payload.features or {})
    return {
        "has_model": out.get("has_model", False),
        "p_recovery": out.get("p_recovery"),
        "enpv": out.get("enpv"),
    }
