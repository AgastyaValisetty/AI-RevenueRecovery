from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from .database import Database
from .domain import (
    Bank,
    BankAccount,
    LedgerEntry,
    Merchant,
    PaymentIntent,
    Person,
    Product,
    Subscription,
)
from .schema import (
    BankAccountRow,
    BankRow,
    LedgerEntryRow,
    MerchantRow,
    PaymentIntentRow,
    PersonRow,
    ProductRow,
    SubscriptionRow,
)


def _bank_to_row(bank: Bank) -> BankRow:
    return BankRow(
        bank_id=bank.bank_id,
        name=bank.name,
        authorization_success_rate=bank.authorization_success_rate,
        timeout_rate=bank.timeout_rate,
        issuer_decline_rate=bank.issuer_decline_rate,
        network_error_rate=bank.network_error_rate,
        current_state=bank.current_state,
        state_multipliers_json=bank.state_multipliers_json,
        created_at=bank.created_at,
    )


def _bank_from_row(row: BankRow) -> Bank:
    return Bank(
        bank_id=row.bank_id,
        name=row.name,
        authorization_success_rate=row.authorization_success_rate,
        timeout_rate=row.timeout_rate,
        issuer_decline_rate=row.issuer_decline_rate,
        network_error_rate=row.network_error_rate,
        current_state=row.current_state,
        state_multipliers_json=row.state_multipliers_json,
        created_at=row.created_at,
    )


def _person_to_row(person: Person) -> PersonRow:
    return PersonRow(
        person_id=person.person_id,
        name=person.name,
        age=person.age,
        salary=person.salary,
        salary_deposit_day=person.salary_deposit_day,
        spending_profile_category=person.spending_profile_category,
        spending_profile_json=person.spending_profile_json,
        payment_preferences_json=person.payment_preferences_json,
        primary_bank_id=person.primary_bank_id,
        primary_account_id=person.primary_account_id,
        created_at=person.created_at,
    )


def _person_from_row(row: PersonRow) -> Person:
    return Person(
        person_id=row.person_id,
        name=row.name,
        age=row.age,
        salary=row.salary,
        salary_deposit_day=row.salary_deposit_day,
        spending_profile_category=row.spending_profile_category,
        spending_profile_json=row.spending_profile_json,
        payment_preferences_json=row.payment_preferences_json,
        primary_bank_id=row.primary_bank_id,
        primary_account_id=row.primary_account_id,
        created_at=row.created_at,
    )


def _account_to_row(account: BankAccount) -> BankAccountRow:
    return BankAccountRow(
        account_id=account.account_id,
        person_id=account.person_id,
        bank_id=account.bank_id,
        created_at=account.created_at,
    )


def _merchant_to_row(merchant: Merchant) -> MerchantRow:
    return MerchantRow(
        merchant_id=merchant.merchant_id,
        name=merchant.name,
        merchant_type=merchant.merchant_type,
        settlement_bank_id=merchant.settlement_bank_id,
        created_at=merchant.created_at,
    )


def _merchant_from_row(row: MerchantRow) -> Merchant:
    return Merchant(
        merchant_id=row.merchant_id,
        name=row.name,
        merchant_type=row.merchant_type,
        settlement_bank_id=row.settlement_bank_id,
        created_at=row.created_at,
    )


def _product_to_row(product: Product) -> ProductRow:
    return ProductRow(
        product_id=product.product_id,
        merchant_id=product.merchant_id,
        name=product.name,
        price=product.price,
        product_type=product.product_type,
        billing_cycle=product.billing_cycle,
        created_at=product.created_at,
    )


def _product_from_row(row: ProductRow) -> Product:
    return Product(
        product_id=row.product_id,
        merchant_id=row.merchant_id,
        name=row.name,
        price=row.price,
        product_type=row.product_type,
        billing_cycle=row.billing_cycle,
        created_at=row.created_at,
    )


def _subscription_to_row(subscription: Subscription) -> SubscriptionRow:
    return SubscriptionRow(
        subscription_id=subscription.subscription_id,
        person_id=subscription.person_id,
        merchant_id=subscription.merchant_id,
        product_id=subscription.product_id,
        amount=subscription.amount,
        billing_cycle=subscription.billing_cycle,
        status=subscription.status,
        next_billing_date=subscription.next_billing_date,
        last_successful_payment_date=subscription.last_successful_payment_date,
        consecutive_failures=subscription.consecutive_failures,
        created_at=subscription.created_at,
        cancelled_at=subscription.cancelled_at,
    )


def _subscription_from_row(row: SubscriptionRow) -> Subscription:
    return Subscription(
        subscription_id=row.subscription_id,
        person_id=row.person_id,
        merchant_id=row.merchant_id,
        product_id=row.product_id,
        amount=row.amount,
        billing_cycle=row.billing_cycle,
        status=row.status,
        next_billing_date=row.next_billing_date,
        last_successful_payment_date=row.last_successful_payment_date,
        consecutive_failures=row.consecutive_failures,
        created_at=row.created_at,
        cancelled_at=row.cancelled_at,
    )


def _intent_to_row(intent: PaymentIntent) -> PaymentIntentRow:
    return PaymentIntentRow(
        intent_id=intent.intent_id,
        person_id=intent.person_id,
        merchant_id=intent.merchant_id,
        product_id=intent.product_id,
        amount=intent.amount,
        payment_method=intent.payment_method,
        status=intent.status,
        related_subscription_id=intent.related_subscription_id,
        created_at=intent.created_at,
        expires_at=intent.expires_at,
    )


def _ledger_to_row(entry: LedgerEntry) -> LedgerEntryRow:
    return LedgerEntryRow(
        entry_id=entry.entry_id,
        event_type=entry.event_type,
        from_account_id=entry.from_account_id,
        to_account_id=entry.to_account_id,
        amount=entry.amount,
        related_attempt_id=entry.related_attempt_id,
        related_subscription_id=entry.related_subscription_id,
        simulation_timestamp=entry.simulation_timestamp,
        created_at=entry.created_at,
        metadata_json=entry.metadata_json,
    )


class BankRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, bank: Bank) -> Bank:
        with self._db.session() as session:
            session.add(_bank_to_row(bank))
        return bank

    def find_by_name(self, name: str) -> Bank | None:
        with self._db.session() as session:
            row = session.scalar(select(BankRow).where(BankRow.name == name))
            return _bank_from_row(row) if row else None


class PersonRepository:
    def __init__(self, db: Database):
        self._db = db

    def add_people_with_accounts(
        self, people: list[Person], accounts: list[BankAccount]
    ) -> None:
        with self._db.session() as session:
            session.add_all([_account_to_row(a) for a in accounts])
            session.add_all([_person_to_row(p) for p in people])

    def count(self) -> int:
        with self._db.session() as session:
            return session.scalar(select(func.count()).select_from(PersonRow))

    def find_all(self) -> list[Person]:
        with self._db.session() as session:
            rows = session.scalars(select(PersonRow)).all()
            return [_person_from_row(r) for r in rows]

    def find_by_id(self, person_id: UUID) -> Person | None:
        with self._db.session() as session:
            row = session.get(PersonRow, person_id)
            return _person_from_row(row) if row else None


class MerchantRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, merchants: list[Merchant]) -> None:
        with self._db.session() as session:
            session.add_all([_merchant_to_row(m) for m in merchants])

    def count(self) -> int:
        with self._db.session() as session:
            return session.scalar(select(func.count()).select_from(MerchantRow))

    def find_all(self) -> list[Merchant]:
        with self._db.session() as session:
            rows = session.scalars(select(MerchantRow)).all()
            return [_merchant_from_row(r) for r in rows]


class ProductRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, products: list[Product]) -> None:
        with self._db.session() as session:
            session.add_all([_product_to_row(p) for p in products])

    def subscription_products(self) -> list[Product]:
        with self._db.session() as session:
            rows = session.scalars(
                select(ProductRow).where(ProductRow.product_type == "SUBSCRIPTION")
            ).all()
            return [_product_from_row(r) for r in rows]


class SubscriptionRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, subscriptions: list[Subscription]) -> None:
        with self._db.session() as session:
            session.add_all([_subscription_to_row(s) for s in subscriptions])

    def count(self) -> int:
        with self._db.session() as session:
            return session.scalar(
                select(func.count()).select_from(SubscriptionRow)
            )

    def find_due_on(self, on_date: date) -> list[Subscription]:
        with self._db.session() as session:
            rows = session.scalars(
                select(SubscriptionRow).where(
                    SubscriptionRow.next_billing_date == on_date,
                    SubscriptionRow.status == "ACTIVE",
                )
            ).all()
            return [_subscription_from_row(r) for r in rows]


class PaymentIntentRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, intents: list[PaymentIntent]) -> None:
        with self._db.session() as session:
            session.add_all([_intent_to_row(i) for i in intents])

    def count(self) -> int:
        with self._db.session() as session:
            return session.scalar(
                select(func.count()).select_from(PaymentIntentRow)
            )


class LedgerRepository:
    def __init__(self, db: Database):
        self._db = db

    def append(self, entries: list[LedgerEntry]) -> None:
        with self._db.session() as session:
            session.add_all([_ledger_to_row(e) for e in entries])

    def count(self) -> int:
        with self._db.session() as session:
            return session.scalar(
                select(func.count()).select_from(LedgerEntryRow)
            )

    def balance_of(self, account_id: UUID) -> Decimal:
        with self._db.session() as session:
            credits = session.scalar(
                select(func.coalesce(func.sum(LedgerEntryRow.amount), 0)).where(
                    LedgerEntryRow.to_account_id == account_id
                )
            )
            debits = session.scalar(
                select(func.coalesce(func.sum(LedgerEntryRow.amount), 0)).where(
                    LedgerEntryRow.from_account_id == account_id
                )
            )
            return Decimal(credits) - Decimal(debits)



