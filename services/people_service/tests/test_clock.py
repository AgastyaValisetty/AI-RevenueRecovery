"""Tests for SimulationClock — hourly granularity, phase dispatch."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from app.orchestrator import SimulationClock, SIMULATION_START


class TestSimulationClock:
    """Verify the hourly clock operates correctly."""

    def test_current_datetime_initial(self):
        clock = SimulationClock()
        assert clock.current_datetime == SIMULATION_START

    def test_current_hour_initial(self):
        clock = SimulationClock()
        assert clock.current_hour == 0

    def test_advance_increments_by_one_hour(self):
        clock = SimulationClock()
        for i in range(1, 10):
            new_dt = clock.advance()
            assert clock.current_hour == i
            assert new_dt == clock.current_datetime

    def test_current_hour_of_day_cycle(self):
        """Hour-of-day should wrap at 24."""
        clock = SimulationClock()
        # Advance 24 hours → day 1, hour 0
        for _ in range(24):
            clock.advance()
        assert clock.current_hour == 24
        assert clock.current_hour_of_day == 0

    def test_current_day_index(self):
        clock = SimulationClock()
        assert clock.current_day_index == 0
        for _ in range(23):
            clock.advance()
        assert clock.current_day_index == 0  # still day 0
        clock.advance()
        assert clock.current_day_index == 1  # now day 1

    def test_is_weekend(self):
        """Jan 1 2024 is a Monday → weekday."""
        clock = SimulationClock()
        assert clock.is_weekend is False
        # Advance to Saturday (day 5)
        for _ in range(5 * 24):
            clock.advance()
        # Now at Sat Jan 6
        assert clock.is_weekend is True

    def test_sync_to_timestamp(self):
        clock = SimulationClock()
        future = SIMULATION_START + timedelta(hours=48)
        clock.sync_to_timestamp(future)
        assert clock.current_hour == 48

    def test_sync_to_past_does_nothing(self):
        clock = SimulationClock()
        clock.advance()  # hour 1
        past = SIMULATION_START - timedelta(hours=1)
        clock.sync_to_timestamp(past)
        assert clock.current_hour == 1

    def test_custom_start_datetime(self):
        start = datetime(2025, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
        clock = SimulationClock(start_datetime=start)
        assert clock.current_datetime == start
