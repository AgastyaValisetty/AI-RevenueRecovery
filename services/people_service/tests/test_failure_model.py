"""Tests for the real-world failure model (P(failure) + taxonomy + composition)."""

from __future__ import annotations

from random import Random

import pytest

from app.failure_model import (
    BASE_FAILURE_RATE,
    BANK_DECLINE,
    COMPOSITION,
    CUSTOMER_STATE,
    FAILURE_CATEGORIES,
    FAILURE_REASONS,
    INFRASTRUCTURE,
    LEGACY_CODE_MAP,
    MERCHANT_CONFIG,
    STATE_MULTIPLIERS,
    classify_failure,
    classifiable_codes,
    failure_probability,
)


class TestBaseRates:
    def test_upi_within_expected_range(self):
        # UPI failure rate should sit in the user's 5–7% band.
        assert 0.05 <= BASE_FAILURE_RATE["UPI"] <= 0.07

    def test_card_within_expected_range(self):
        # CARD 5–8%.
        assert 0.05 <= BASE_FAILURE_RATE["CARD"] <= 0.08

    def test_netbanking_equals_average(self):
        # avg of SBI 6.34 / HDFC 4.64 / Axis 5.05 / ICICI 4.34 / BOI 11.04.
        expected = (6.34 + 4.64 + 5.05 + 4.34 + 11.04) / 5 / 100.0
        assert BASE_FAILURE_RATE["NETBANKING"] == pytest.approx(expected, abs=1e-4)


class TestComposition:
    def test_composition_values_are_valid_codes(self):
        for code, _weight in COMPOSITION:
            assert code in FAILURE_REASONS
            assert code in FAILURE_CATEGORIES

    def test_reasons_and_categories_complete(self):
        assert len(FAILURE_REASONS) >= 12
        cats = set(FAILURE_CATEGORIES.values())
        assert {CUSTOMER_STATE, BANK_DECLINE, INFRASTRUCTURE, MERCHANT_CONFIG} <= cats

    def test_legacy_map_targets_new_codes(self):
        for new_code in LEGACY_CODE_MAP.values():
            assert new_code in FAILURE_REASONS


class TestFailureProbability:
    def test_neutral_normal_is_base(self):
        assert failure_probability("UPI") == pytest.approx(BASE_FAILURE_RATE["UPI"])

    def test_state_multipliers_monotonic(self):
        normal = failure_probability("UPI", bank_state="NORMAL")
        peak = failure_probability("UPI", bank_state="PEAK")
        degraded = failure_probability("UPI", bank_state="DEGRADED")
        outage = failure_probability("UPI", bank_state="OUTAGE")
        assert normal <= peak <= degraded <= outage

    def test_large_amount_bumps(self):
        assert failure_probability("UPI", bank_state="NORMAL", amount=25_000) > failure_probability(
            "UPI", bank_state="NORMAL", amount=500
        )

    def test_thin_balance_bumps(self):
        thin = failure_probability("UPI", bank_state="NORMAL", balance=200, amount=1000)
        comfortable = failure_probability("UPI", bank_state="NORMAL", balance=50_000, amount=1000)
        assert thin > comfortable

    def test_peak_hour_bumps(self):
        assert failure_probability("UPI", bank_state="NORMAL", hour=20) > failure_probability(
            "UPI", bank_state="NORMAL", hour=3
        )

    def test_clamped_below_max(self):
        p = failure_probability("UPI", bank_state="OUTAGE", amount=100_000, hour=20)
        assert p <= 0.9

    def test_netbanking_rate_uses_average(self):
        assert failure_probability("NETBANKING") == pytest.approx((6.34 + 4.64 + 5.05 + 4.34 + 11.04) / 5 / 100.0, abs=1e-4)


class TestClassifyFailure:
    def test_returns_valid_code_and_category(self):
        rng = Random(1)
        code, cat = classify_failure(rng, method="UPI", bank_state="NORMAL")
        assert code in FAILURE_REASONS
        assert cat == FAILURE_CATEGORIES[code]

    def test_normal_state_never_returns_insufficient_or_bank_degraded_here(self):
        # INSUFFICIENT_FUNDS is owned by the caller (real insolvency); in a
        # healthy bank BANK_DEGRADED must not be drawn from the composition.
        seen = set()
        for seed in range(200):
            code, _ = classify_failure(Random(seed), method="CARD", bank_state="NORMAL")
            seen.add(code)
        assert "INSUFFICIENT_FUNDS" not in seen
        assert "BANK_DEGRADED" not in seen

    def test_degraded_state_boils_toward_bank_degraded(self):
        seen = []
        for seed in range(200):
            code, _ = classify_failure(Random(seed), method="UPI", bank_state="DEGRADED")
            seen.append(code)
        assert seen.count("BANK_DEGRADED") > len(seen) * 0.3  # dominates

    def test_method_gating_card_keeps_expired_and_auth(self):
        eligible = [c for c, _w in classifiable_codes("CARD")]
        assert "EXPIRED_PAYMENT_METHOD" in eligible
        assert "AUTHENTICATION_FAILURE" in eligible

    def test_unsupported_method_only_for_unsupported(self):
        # UNSUPPORTED_METHOD lives in the composition; method gating for
        # non-CARD/UPI keeps it available for NETBANKING.
        eligible = [c for c, _w in classifiable_codes("NETBANKING")]
        assert "UNSUPPORTED_METHOD" in eligible
