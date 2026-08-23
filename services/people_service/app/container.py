import random

from .config import Settings
from .database import Database
from .engines import SalaryEngine, SpendingEngine, SubscriptionEngine
from .generators import (
    MerchantGenerator,
    PersonGenerator,
    SubscriptionGenerator,
)
from .orchestrator import Orchestrator, SimulationClock
from .repositories import (
    BankRepository,
    LedgerRepository,
    MerchantRepository,
    PaymentIntentRepository,
    PersonRepository,
    ProductRepository,
    SubscriptionRepository,
)


def build_database(settings: Settings) -> Database:
    return Database(settings)


def build_orchestrator(db: Database, seed: int | None = None) -> Orchestrator:
    rng = random.Random(seed)
    return Orchestrator(
        bank_repo=BankRepository(db),
        person_repo=PersonRepository(db),
        merchant_repo=MerchantRepository(db),
        product_repo=ProductRepository(db),
        subscription_repo=SubscriptionRepository(db),
        intent_repo=PaymentIntentRepository(db),
        ledger_repo=LedgerRepository(db),
        person_generator=PersonGenerator(rng),
        merchant_generator=MerchantGenerator(),
        subscription_generator=SubscriptionGenerator(rng),
        salary_engine=SalaryEngine(),
        spending_engine=SpendingEngine(rng),
        subscription_engine=SubscriptionEngine(rng),
        clock=SimulationClock(),
    )
