import random
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from .domain import (
    ACTIVE,
    BankAccount,
    Merchant,
    MONTHLY,
    Person,
    Product,
    Subscription,
    now,
)

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Ishaan", "Kabir",
    "Rohan", "Kunal", "Rahul", "Amit", "Sunil", "Ravi", "Rajesh", "Deepak",
    "Priya", "Ananya", "Diya", "Aisha", "Kavya", "Sneha", "Pooja", "Meera",
    "Nisha", "Kirti", "Sanya", "Ritika", "Neha", "Anjali",
]

LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Kumar", "Singh", "Patel", "Reddy", "Nair",
    "Iyer", "Menon", "Das", "Chatterjee", "Mukherjee", "Joshi", "Desai",
    "Kulkarni", "Rao", "Bose", "Sen", "Kapoor", "Malhotra", "Agarwal",
]

PROFILES = [
    "student",
    "young_professional",
    "family",
    "high_income",
    "retired",
]

SPENDING_CATEGORIES = [
    "groceries",
    "utilities",
    "dining",
    "transport",
    "entertainment",
]

PAYMENT_METHODS = ("UPI", "CARD", "NETBANKING")

MIN_SALARY = 30_000
MAX_SALARY = 500_000
MIN_AGE = 18
MAX_AGE = 80
MIN_DEPOSIT_DAY = 1
MAX_DEPOSIT_DAY = 28


class PersonGenerator:
    def __init__(self, rng: random.Random):
        self._rng = rng

    def generate(
        self, count: int, bank_id: UUID
    ) -> tuple[list[Person], list[BankAccount]]:
        people = []
        accounts = []
        timestamp = now()
        for _ in range(count):
            person_id = uuid4()
            account_id = uuid4()
            accounts.append(
                BankAccount(
                    account_id=account_id,
                    person_id=person_id,
                    bank_id=bank_id,
                    created_at=timestamp,
                )
            )
            people.append(
                Person(
                    person_id=person_id,
                    name=f"{self._rng.choice(FIRST_NAMES)} {self._rng.choice(LAST_NAMES)}",
                    age=self._rng.randint(MIN_AGE, MAX_AGE),
                    salary=Decimal(self._rng.randint(MIN_SALARY, MAX_SALARY)),
                    salary_deposit_day=self._rng.randint(
                        MIN_DEPOSIT_DAY, MAX_DEPOSIT_DAY
                    ),
                    spending_profile_category=self._rng.choice(PROFILES),
                    spending_profile_json=self._spending_profile(),
                    payment_preferences_json=self._payment_preferences(),
                    primary_bank_id=bank_id,
                    primary_account_id=account_id,
                    created_at=timestamp,
                )
            )
        return people, accounts

    def _spending_profile(self) -> dict:
        return {
            "base_percentage": round(self._rng.uniform(1.0, 3.0), 2),
            "category_weights": {
                category: round(self._rng.uniform(0.1, 0.3), 2)
                for category in SPENDING_CATEGORIES
            },
        }

    def _payment_preferences(self) -> dict:
        weights = [self._rng.random() for _ in PAYMENT_METHODS]
        total = sum(weights)
        return {
            method: round(weight / total, 2)
            for method, weight in zip(PAYMENT_METHODS, weights)
        }


class MerchantGenerator:
    _CATALOG = [
        ("Spotifly", "SUBSCRIPTION_ONLY", [
            ("Spotifly Monthly", Decimal("119.00"), "SUBSCRIPTION"),
        ]),
        ("Petflix", "SUBSCRIPTION_ONLY", [
            ("Petflix Monthly", Decimal("199.00"), "SUBSCRIPTION"),
        ]),
        ("Amazin", "MIXED", [
            ("Amazin Prime", Decimal("599.00"), "SUBSCRIPTION"),
            ("Sony Headphones", Decimal("24999.00"), "ONE_TIME"),
            ("Kindle 2024", Decimal("10999.00"), "ONE_TIME"),
        ]),
        ("Flip Cartel", "MIXED", [
            ("Flip Cartel Plus", Decimal("499.00"), "SUBSCRIPTION"),
            ("Smartphone", Decimal("45000.00"), "ONE_TIME"),
            ("Running Shoes", Decimal("3299.00"), "ONE_TIME"),
        ]),
    ]

    def generate(self, bank_id: UUID) -> tuple[list[Merchant], list[Product]]:
        merchants = []
        products = []
        timestamp = now()
        for name, merchant_type, catalog in self._CATALOG:
            merchant_id = uuid4()
            merchants.append(
                Merchant(
                    merchant_id=merchant_id,
                    name=name,
                    merchant_type=merchant_type,
                    settlement_bank_id=bank_id,
                    created_at=timestamp,
                )
            )
            for product_name, price, product_type in catalog:
                products.append(
                    Product(
                        product_id=uuid4(),
                        merchant_id=merchant_id,
                        name=product_name,
                        price=price,
                        product_type=product_type,
                        billing_cycle=MONTHLY if product_type == "SUBSCRIPTION" else None,
                        created_at=timestamp,
                    )
                )
        return merchants, products


class SubscriptionGenerator:
    def __init__(self, rng: random.Random):
        self._rng = rng

    def generate(
        self,
        people: list[Person],
        products: list[Product],
        start_date: date,
    ) -> list[Subscription]:
        subscriptions = []
        timestamp = now()
        for person in people:
            picks = self._rng.sample(
                products, k=self._rng.randint(2, min(3, len(products)))
            )
            for product in picks:
                subscriptions.append(
                    Subscription(
                        subscription_id=uuid4(),
                        person_id=person.person_id,
                        merchant_id=product.merchant_id,
                        product_id=product.product_id,
                        amount=product.price,
                        billing_cycle=MONTHLY,
                        status=ACTIVE,
                        next_billing_date=start_date
                        + timedelta(days=self._rng.randint(0, 89)),
                        created_at=timestamp,
                    )
                )
        return subscriptions

