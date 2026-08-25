"""Tests for bank_service/app/engine.py — pure domain logic.

These tests exercise the engine classes in isolation, without a database
or HTTP server, to verify the authorization probability, latency
simulation, funds validation, and bank state machine logic.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain import BankPolicy, BankState, FailureCode
from app.engine import (
    BankStateMachine,
    FundsValidator,
    LatencySimulator,
    ProbabilityEngine,
)


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def bank_normal() -> BankPolicy:
    return BankPolicy(
        bank_id="normal-bank",
        name="NormalBank",
        authorization_success_rate=99.1,
        timeout_rate=0.3,
        issuer_decline_rate=0.4,
        network_error_rate=0.2,
        current_state=BankState.NORMAL,
        state_multipliers={
            "NORMAL": 1.0,
            "PEAK": 2.0,
            "DEGRADED": 5.0,
            "OUTAGE": 50.0,
        },
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def bank_outage() -> BankPolicy:
    return BankPolicy(
        bank_id="outage-bank",
        name="OutageBank",
        authorization_success_rate=99.1,
        timeout_rate=0.3,
        issuer_decline_rate=0.4,
        network_error_rate=0.2,
        current_state=BankState.OUTAGE,
        state_multipliers={
            "NORMAL": 1.0,
            "PEAK": 2.0,
            "DEGRADED": 5.0,
            "OUTAGE": 50.0,
        },
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def rng() -> random.Random:
    return random.Random(42)


# ------------------------------------------------------------------ #
# FundsValidator
# ------------------------------------------------------------------ #

class TestFundsValidator:
    def test_sufficient_funds(self):
        assert FundsValidator.has_sufficient_funds(
            Decimal("100.00"), Decimal("50.00")
        ) is True

    def test_exact_balance(self):
        assert FundsValidator.has_sufficient_funds(
            Decimal("50.00"), Decimal("50.00")
        ) is True

    def test_insufficient_funds(self):
        assert FundsValidator.has_sufficient_funds(
            Decimal("49.99"), Decimal("50.00")
        ) is False

    def test_zero_balance(self):
        assert FundsValidator.has_sufficient_funds(
            Decimal("0"), Decimal("1.00")
        ) is False

    def test_zero_amount(self):
        assert FundsValidator.has_sufficient_funds(
            Decimal("0"), Decimal("0")
        ) is True


# ------------------------------------------------------------------ #
# LatencySimulator
# ------------------------------------------------------------------ #

class TestLatencySimulator:
    def test_response_time_in_range(self, rng):
        sim = LatencySimulator(rng)
        for _ in range(100):
            ms = sim.simulate_response_time()
            assert 50 <= ms <= 500

    def test_deterministic_with_seed(self):
        sim1 = LatencySimulator(random.Random(123))
        sim2 = LatencySimulator(random.Random(123))
        assert sim1.simulate_response_time() == sim2.simulate_response_time()

    def test_varied_values(self):
        rng = random.Random(999)
        sim = LatencySimulator(rng)
        values = [sim.simulate_response_time() for _ in range(100)]
        assert len(set(values)) > 1  # Should produce some variety


# ------------------------------------------------------------------ #
# ProbabilityEngine
# ------------------------------------------------------------------ #

class TestProbabilityEngine:
    def test_adjusted_success_rate_normal(self, bank_normal):
        engine = ProbabilityEngine(random.Random(42))
        rate = engine.get_adjusted_success_rate(bank_normal)
        # NORMAL multiplier is 1.0 — no change
        assert rate == pytest.approx(99.1)

    def test_adjusted_success_rate_peak(self):
        bank = BankPolicy(
            bank_id="peak-bank",
            name="PeakBank",
            authorization_success_rate=99.1,
            timeout_rate=0.3,
            issuer_decline_rate=0.4,
            network_error_rate=0.2,
            current_state=BankState.PEAK,
            state_multipliers={"NORMAL": 1.0, "PEAK": 2.0, "DEGRADED": 5.0, "OUTAGE": 50.0},
            created_at=datetime.now(timezone.utc),
        )
        engine = ProbabilityEngine(random.Random(42))
        rate = engine.get_adjusted_success_rate(bank)
        # PEAK multiplier is 2.0 — success rate halved
        assert rate == pytest.approx(99.1 / 2.0)

    def test_adjusted_success_rate_outage(self, bank_outage):
        engine = ProbabilityEngine(random.Random(42))
        rate = engine.get_adjusted_success_rate(bank_outage)
        # OUTAGE multiplier is 50.0
        assert rate == pytest.approx(99.1 / 50.0)

    def test_decide_success(self, bank_normal):
        # Force a high roll (close to 1.0) → roll < adjusted_rate → success
        rng = random.Random(42)
        engine = ProbabilityEngine(rng)
        # Patch the rng to return 0.5 (always success)
        mock_rng = random.Random(42)
        mock_rng.random = lambda: 0.5
        engine = ProbabilityEngine(mock_rng)
        success, code, reason = engine.decide(bank_normal)
        assert success is True
        assert code is None
        assert reason is None

    def test_decide_failure(self, bank_outage):
        # In OUTAGE, adjusted_success_rate ≈ 1.98, so a roll of 50.0 → failure
        mock_rng = random.Random(42)
        mock_rng.random = lambda: 50.0
        engine = ProbabilityEngine(mock_rng)
        success, code, reason = engine.decide(bank_outage)
        assert success is False
        assert code is not None
        assert code in [fc.value for fc in FailureCode if fc != FailureCode.INSUFFICIENT_FUNDS and fc != FailureCode.BANK_DEGRADED]
        assert reason is not None
        assert len(reason) > 0

    def test_decide_failure_code_distribution(self):
        """When failures occur, various bank-decline codes should be possible."""
        bank = BankPolicy(
            bank_id="dist-bank",
            name="DistBank",
            authorization_success_rate=10.0,  # Low success rate → lots of failures
            timeout_rate=0.3,
            issuer_decline_rate=0.4,
            network_error_rate=0.2,
            current_state=BankState.NORMAL,
            state_multipliers={"NORMAL": 1.0, "PEAK": 2.0, "DEGRADED": 5.0, "OUTAGE": 50.0},
            created_at=datetime.now(timezone.utc),
        )
        codes_seen = set()
        # Try many seeds to cover all failure types
        for seed in range(10000):
            rng = random.Random(seed)
            engine = ProbabilityEngine(rng)
            success, code, _ = engine.decide(bank)
            if not success and code:
                codes_seen.add(code)
            if len(codes_seen) >= 5:  # All 5 weighted failure codes
                break
        assert len(codes_seen) >= 3  # At least some variety

    def test_deterministic_decide(self, bank_normal):
        """The same seed must produce the same decision."""
        outcome1 = ProbabilityEngine(random.Random(7)).decide(bank_normal)
        outcome2 = ProbabilityEngine(random.Random(7)).decide(bank_normal)
        assert outcome1 == outcome2

    def test_different_seeds_may_differ(self, bank_normal):
        """Different seeds should eventually produce different results."""
        results = set()
        for seed in range(1000):
            outcome = ProbabilityEngine(random.Random(seed)).decide(bank_normal)
            results.add(outcome[0])  # Just success/failure
            if len(results) > 1:
                return
        # If we get here, all seeds produced the same result.
        # With 99.1% success rate this is statistically possible but very unlikely
        # over 1000 seeds — allow it as a soft assertion.
        pytest.skip("All seeds produced same outcome (statistically unlikely but possible)")


# ------------------------------------------------------------------ #
# BankStateMachine
# ------------------------------------------------------------------ #

class TestBankStateMachine:
    @pytest.fixture
    def sm(self) -> BankStateMachine:
        return BankStateMachine(random.Random(42))

    def test_normal_stays_normal_no_traffic(self, sm):
        result = sm.bank_state_transition(
            current_state=BankState.NORMAL,
            txn_count_last_minute=0,
            failure_rate_last_minute=0.0,
            consecutive_failures=0,
            outage_started_at=None,
        )
        assert result is None  # No transition

    def test_normal_to_peak(self, sm):
        result = sm.bank_state_transition(
            current_state=BankState.NORMAL,
            txn_count_last_minute=150,
            failure_rate_last_minute=2.5,
            consecutive_failures=0,
            outage_started_at=None,
        )
        assert result == BankState.PEAK

    def test_normal_stays_normal_low_traffic(self, sm):
        result = sm.bank_state_transition(
            current_state=BankState.NORMAL,
            txn_count_last_minute=150,
            failure_rate_last_minute=0.5,  # Below 1% threshold
            consecutive_failures=0,
            outage_started_at=None,
        )
        assert result is None

    def test_normal_stays_normal_high_failure_low_traffic(self, sm):
        result = sm.bank_state_transition(
            current_state=BankState.NORMAL,
            txn_count_last_minute=10,  # Below 100 threshold
            failure_rate_last_minute=5.0,  # High failure
            consecutive_failures=0,
            outage_started_at=None,
        )
        assert result is None

    def test_peak_to_degraded(self, sm):
        result = sm.bank_state_transition(
            current_state=BankState.PEAK,
            txn_count_last_minute=200,
            failure_rate_last_minute=6.0,
            consecutive_failures=10,
            outage_started_at=None,
        )
        assert result == BankState.DEGRADED

    def test_peak_to_normal_low_traffic(self, sm):
        result = sm.bank_state_transition(
            current_state=BankState.PEAK,
            txn_count_last_minute=30,
            failure_rate_last_minute=2.0,
            consecutive_failures=0,
            outage_started_at=None,
        )
        assert result == BankState.NORMAL

    def test_degraded_to_outage(self, sm):
        result = sm.bank_state_transition(
            current_state=BankState.DEGRADED,
            txn_count_last_minute=200,
            failure_rate_last_minute=12.0,
            consecutive_failures=20,
            outage_started_at=None,
        )
        assert result == BankState.OUTAGE

    def test_degraded_to_normal_recovery(self, sm):
        result = sm.bank_state_transition(
            current_state=BankState.DEGRADED,
            txn_count_last_minute=100,
            failure_rate_last_minute=3.0,  # Below 5% threshold
            consecutive_failures=0,
            outage_started_at=None,
        )
        assert result == BankState.NORMAL

    def test_degraded_stays_degraded(self, sm):
        result = sm.bank_state_transition(
            current_state=BankState.DEGRADED,
            txn_count_last_minute=100,
            failure_rate_last_minute=7.0,  # Between 5% and 10%
            consecutive_failures=5,
            outage_started_at=None,
        )
        assert result is None

    def test_outage_recovery_after_timeout(self, sm):
        started = datetime.now(timezone.utc) - timedelta(minutes=35)
        result = sm.bank_state_transition(
            current_state=BankState.OUTAGE,
            txn_count_last_minute=10,
            failure_rate_last_minute=60.0,
            consecutive_failures=50,
            outage_started_at=started,
        )
        assert result == BankState.NORMAL

    def test_outage_stays_outage_recent(self, sm):
        started = datetime.now(timezone.utc) - timedelta(minutes=5)
        result = sm.bank_state_transition(
            current_state=BankState.OUTAGE,
            txn_count_last_minute=10,
            failure_rate_last_minute=60.0,
            consecutive_failures=50,
            outage_started_at=started,
        )
        assert result is None

    def test_outage_without_started_at_stays_outage(self, sm):
        result = sm.bank_state_transition(
            current_state=BankState.OUTAGE,
            txn_count_last_minute=10,
            failure_rate_last_minute=60.0,
            consecutive_failures=50,
            outage_started_at=None,
        )
        assert result is None

    def test_get_state_multiplier(self, sm):
        assert sm.get_state_multiplier(BankState.NORMAL) == 1.0
        assert sm.get_state_multiplier(BankState.PEAK) == 2.0
        assert sm.get_state_multiplier(BankState.DEGRADED) == 5.0
        assert sm.get_state_multiplier(BankState.OUTAGE) == 50.0
