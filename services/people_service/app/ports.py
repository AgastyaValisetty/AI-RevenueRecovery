from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

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


class BankRepository(Protocol):
    def add(self, bank: Bank) -> Bank: ...

    def find_by_name(self, name: str) -> Bank | None: ...


class PersonRepository(Protocol):
    def add_people_with_accounts(
        self, people: list[Person], accounts: list[BankAccount]
    ) -> None: ...

    def count(self) -> int: ...

    def find_all(self) -> list[Person]: ...

    def find_by_id(self, person_id: UUID) -> Person | None: ...


class MerchantRepository(Protocol):
    def add(self, merchants: list[Merchant]) -> None: ...

    def count(self) -> int: ...

    def find_all(self) -> list[Merchant]: ...


class ProductRepository(Protocol):
    def add(self, products: list[Product]) -> None: ...

    def subscription_products(self) -> list[Product]: ...


class SubscriptionRepository(Protocol):
    def add(self, subscriptions: list[Subscription]) -> None: ...

    def count(self) -> int: ...

    def find_due_on(self, on_date: date) -> list[Subscription]: ...


class PaymentIntentRepository(Protocol):
    def add(self, intents: list[PaymentIntent]) -> None: ...

    def count(self) -> int: ...


class LedgerRepository(Protocol):
    def append(self, entries: list[LedgerEntry]) -> None: ...

    def count(self) -> int: ...

    def balance_of(self, account_id: UUID) -> Decimal: ...
