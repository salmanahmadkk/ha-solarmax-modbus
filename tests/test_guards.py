"""Unit tests for the counter guards (no Home Assistant needed)."""

from __future__ import annotations

from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "solarmax_modbus"))
from guards import CONFIRM_READINGS, DailyGuard, LifetimeGuard  # noqa: E402

RATE = 30.0  # kWh per hour (3 x 10 kW)
NOON = datetime(2026, 10, 30, 12, 0)


def feed(guard, values, start=0.0, step=10.0):
    out, t = [], start
    for v in values:
        out.append(guard.update(v, t))
        t += step
    return out, t


def started(value=12617.0) -> LifetimeGuard:
    g = LifetimeGuard("total_import", RATE)
    g.seed(value, 0.0)
    return g


# ------------------------------------------------------------- lifetime
def test_the_30_october_glitch_is_ignored():
    g = started()
    out, _ = feed(g, [12617.0, 0.0, 12617.0, 12617.01])
    assert out == [12617.0, 12617.0, 12617.0, 12617.01]
    assert g.rejected == 1 and g.rebased == 0


def test_garbage_jump_up_is_ignored_and_does_not_freeze_the_counter():
    g = started()
    out, _ = feed(g, [12617.0, 42949672.95, 12617.05, 12617.1])
    assert out == [12617.0, 12617.0, 12617.05, 12617.1]


def test_small_drop_is_held_never_published():
    g = started(12630.0)
    out, _ = feed(g, [12629.65, 12629.7, 12630.2])
    assert out == [12630.0, 12630.0, 12630.2]


def test_persistent_reset_rebases_without_dip_or_double_count():
    g = started(12617.0)
    values = [12617.0] + [0.0] * CONFIRM_READINGS + [0.5, 1.0]
    out, _ = feed(g, values)
    assert all(b >= a for a, b in zip(out, out[1:], strict=False)), "published never goes down"
    assert out[-2] == 12617.5 and out[-1] == 12618.0, "new counter continues from the old total"
    assert g.rebased == 1


def test_temporary_zeros_then_back_counts_energy_in_between():
    g = started(12617.0)
    feed(g, [12617.0] + [0.0] * (CONFIRM_READINGS + 2))  # rebased onto the zero track
    assert g.rebased == 1
    # real counter returns, 0.8 kWh higher than before the fault
    value = g.update(12617.8, 200.0)
    assert value == 12617.8
    assert g.prev is None


def test_long_home_assistant_downtime_accepts_real_increase():
    g = started(12617.0)
    g.update(12617.0, 0.0)
    # HA off for 2 days, 90 kWh imported meanwhile: plausible for 48 h
    assert g.update(12707.0, 2 * 24 * 3600.0) == 12707.0
    assert g.rejected == 0


def test_fresh_counter_needs_consistent_readings_and_ignores_zero():
    g = LifetimeGuard("total_export", RATE)
    assert g.update(0.0, 0) is None
    assert g.update(18715.0, 10) is None
    assert g.update(18715.0, 20) is None
    assert g.update(18715.01, 30) == 18715.01


def test_persistence_round_trip():
    g = started()
    feed(g, [12617.0, 0.0])
    h = LifetimeGuard("total_import", RATE)
    assert h.load(g.to_dict())
    assert h.update(12617.2, 100.0) == 12617.2
    assert h.rejected == 1


def test_inconsistent_anomalies_never_confirm():
    g = started()
    noisy = [0.0, 5e6, 0.0, 5e6, 0.0, 5e6, 0.0, 5e6, 0.0]
    out, _ = feed(g, [12617.0] + noisy)
    assert set(out) == {12617.0} and g.rebased == 0


# ---------------------------------------------------------------- daily
def daily(value=25.0) -> DailyGuard:
    g = DailyGuard("daily_import", RATE)
    g.update(value, 0.0, NOON)
    return g


def test_midnight_reset_is_accepted_immediately():
    g = daily(44.2)
    assert g.update(0.0, 10.0, datetime(2026, 10, 31, 0, 0, 30)) == 0.0
    assert g.update(0.0, 20.0, datetime(2026, 10, 31, 23, 58)) == 0.0


def test_midday_zero_glitch_is_ignored():
    g = daily(25.0)
    assert g.update(0.0, 10.0, NOON) == 25.0
    assert g.update(25.01, 20.0, NOON) == 25.01


def test_persistent_midday_drop_is_accepted_after_confirmation():
    g = daily(25.0)
    t, out = 10.0, []
    for _ in range(CONFIRM_READINGS + 1):
        out.append(g.update(3.0, t, NOON))
        t += 12
    assert out[0] == 25.0 and out[-1] == 3.0


def test_daily_garbage_jump_is_ignored():
    g = daily(25.0)
    assert g.update(9999.0, 10.0, NOON) == 25.0
    assert g.update(25.02, 20.0, NOON) == 25.02
