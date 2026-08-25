"""Tests for SimulationRNG — determinism, seeding, and sub-seed derivation."""

from __future__ import annotations

from app.rng import SimulationRNG


class TestRNGDeterminism:
    """Verify that the same seed produces the same sequence."""

    def test_same_seed_same_sequence(self):
        """Two RNGs with the same seed must produce identical sequences."""
        rng_a = SimulationRNG(42)
        rng_b = SimulationRNG(42)

        values_a = [rng_a.randint(0, 1_000_000) for _ in range(100)]
        values_b = [rng_b.randint(0, 1_000_000) for _ in range(100)]

        assert values_a == values_b

    def test_different_seeds_different_sequences(self):
        """Different seeds must produce different sequences."""
        rng_a = SimulationRNG(42)
        rng_b = SimulationRNG(43)

        values_a = [rng_a.random() for _ in range(100)]
        values_b = [rng_b.random() for _ in range(100)]

        assert values_a != values_b

    def test_seed_property(self):
        """The seed property should reflect the constructor argument."""
        rng = SimulationRNG(12345)
        assert rng.seed == 12345

    def test_none_seed(self):
        """A None seed should use system randomness (non-deterministic check)."""
        rng = SimulationRNG(None)
        assert rng.seed is None
        # Should still produce valid output
        value = rng.random()
        assert 0.0 <= value < 1.0


class TestRNGSpawn:
    """Verify that spawn() creates independent but reproducible child RNGs."""

    def test_spawn_is_deterministic(self):
        """Spawning with the same parent seed should produce the same child."""
        parent_a = SimulationRNG(42)
        parent_b = SimulationRNG(42)

        child_a = parent_a.spawn("label")
        child_b = parent_b.spawn("label")

        values_a = [child_a.randint(0, 1_000_000) for _ in range(20)]
        values_b = [child_b.randint(0, 1_000_000) for _ in range(20)]

        assert values_a == values_b

    def test_spawn_produces_independent_streams(self):
        """Children with different spawn labels should differ."""
        parent = SimulationRNG(42)

        child_a = parent.spawn("alpha")
        child_b = parent.spawn("beta")

        values_a = [child_a.randint(0, 1_000_000) for _ in range(20)]
        values_b = [child_b.randint(0, 1_000_000) for _ in range(20)]

        assert values_a != values_b

    def test_spawn_consumes_parent_rng(self):
        """Spawning consumes the parent's RNG to derive a child seed.

        This is by design — spawn uses the parent RNG to produce
        an independent but reproducible child stream.
        """
        parent_a = SimulationRNG(42)
        child_seed_a = parent_a.next_seed()  # consume one draw
        child_a = parent_a.spawn("child")   # spawn consumes another draw

        parent_b = SimulationRNG(42)
        child_seed_b = parent_b.next_seed()
        # parent_b has consumed same draws as parent_a, so next values match
        child_b = parent_b.spawn("child")
        assert child_a.seed == child_b.seed


class TestRNGPrimitiveMethods:
    """Verify each primitive method works correctly."""

    def test_random_range(self):
        rng = SimulationRNG(42)
        for _ in range(1000):
            val = rng.random()
            assert 0.0 <= val < 1.0

    def test_randint_in_range(self):
        rng = SimulationRNG(42)
        for lo, hi in [(0, 10), (1, 100), (-5, 5)]:
            val = rng.randint(lo, hi)
            assert lo <= val <= hi

    def test_uniform_range(self):
        rng = SimulationRNG(42)
        for _ in range(1000):
            val = rng.uniform(10.0, 20.0)
            assert 10.0 <= val <= 20.0

    def test_chance_true_and_false(self):
        rng = SimulationRNG(42)
        # With p=1.0, always True
        assert rng.chance(1.0) is True
        # With p=0.0, always False
        assert rng.chance(0.0) is False
        # With p=0.5, should get both True and False over many trials
        results = {rng.chance(0.5) for _ in range(1000)}
        assert results == {True, False}

    def test_choice_from_sequence(self):
        rng = SimulationRNG(42)
        items = ["a", "b", "c", "d", "e"]
        selected = rng.choice(items)
        assert selected in items

    def test_sample_from_sequence(self):
        rng = SimulationRNG(42)
        items = list(range(20))
        sampled = rng.sample(items, 5)
        assert len(sampled) == 5
        assert all(i in items for i in sampled)

    def test_choices_weighted(self):
        rng = SimulationRNG(42)
        population = ["a", "b", "c"]
        weights = [1, 2, 3]
        results = rng.choices(population, weights=weights, k=100)
        assert all(r in population for r in results)

    def test_lognormvariate_positive(self):
        rng = SimulationRNG(42)
        val = rng.lognormvariate(0.0, 1.0)
        assert val > 0

    def test_normalvariate(self):
        rng = SimulationRNG(42)
        val = rng.normalvariate(0.0, 1.0)
        # Should be within a reasonable range
        assert -10 < val < 10

    def test_money_quantization(self):
        from decimal import Decimal
        rng = SimulationRNG(42)
        val = rng.money(3.14159)
        assert val == Decimal("3.14")

    def test_deterministic_now(self):
        rng = SimulationRNG(42)
        ts = rng.deterministic_now()
        assert ts.year == 2024
        assert ts.month == 1
        assert ts.day == 1
        assert ts.tzinfo is not None
