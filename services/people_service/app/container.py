"""Dependency injection container.

Wires all repositories, generators, engines, and the :class:`~orchestrator.Orchestrator`
together with the :class:`~rng.SimulationRNG` and :class:`~sim_config.SimConfig`.

Usage:
    db = build_database(settings)
    orchestrator = build_orchestrator(db, seed=42)
"""

from __future__ import annotations

import logging

from .config import Settings
from .database import Database
from .engines import (
    EcommerceEngine,
    SalaryEngine,
    SpendingEngine,
    SubscriptionEngine,
)
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
    SimulationRunRepository,
    SubscriptionRepository,
)
from .rng import SimulationRNG
from .sim_config import SimConfig

logger = logging.getLogger(__name__)


def build_database(settings: Settings) -> Database:
    return Database(settings)


def build_orchestrator(
    db: Database,
    seed: int | None = None,
    config: SimConfig | None = None,
) -> Orchestrator:
    """Build a fully-wired :class:`Orchestrator`.

    Parameters
    ----------
    db : Database
        Database connection (schema already created).
    seed : int, optional
        Root seed for :class:`SimulationRNG`.  Falls back to the config's
        ``population.default_seed``.
    config : SimConfig, optional
        Calibrated configuration.  Loads ``sim_calibration.json`` if omitted.
    """
    config = config or SimConfig.defaults()
    seed = seed if seed is not None else config.population.default_seed

    rng = SimulationRNG(seed)

    # Spawn child RNGs for each stochastic component so they get
    # independent but reproducible streams from the same root seed.
    person_rng = rng.spawn("people")
    subscription_rng = rng.spawn("subscriptions")
    spending_rng = rng.spawn("spending")

    person_generator = PersonGenerator(person_rng, config)
    merchant_generator = MerchantGenerator()
    subscription_generator = SubscriptionGenerator(subscription_rng, config)

    salary_engine = SalaryEngine(config)
    spending_engine = SpendingEngine(spending_rng, config)
    subscription_engine = SubscriptionEngine(spending_rng, config)
    ecommerce_engine = EcommerceEngine(spending_rng, config)

    clock = SimulationClock(config.temporal.start_datetime)

    orchestrator = Orchestrator(
        bank_repo=BankRepository(db),
        person_repo=PersonRepository(db),
        merchant_repo=MerchantRepository(db),
        product_repo=ProductRepository(db),
        subscription_repo=SubscriptionRepository(db),
        intent_repo=PaymentIntentRepository(db),
        ledger_repo=LedgerRepository(db),
        sim_run_repo=SimulationRunRepository(db),
        person_generator=person_generator,
        merchant_generator=merchant_generator,
        subscription_generator=subscription_generator,
        salary_engine=salary_engine,
        spending_engine=spending_engine,
        subscription_engine=subscription_engine,
        ecommerce_engine=ecommerce_engine,
        clock=clock,
        rng=rng,
        sim_config=config,
    )

    logger.info(
        "Orchestrator built: seed=%s, config_version=%s", seed, config.version
    )
    return orchestrator
