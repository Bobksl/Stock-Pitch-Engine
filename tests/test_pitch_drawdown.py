"""P3.6 — framework 2.4 / 2.5i: peer drawdown analysis.

    "Plus peer drawdown analysis: define stress windows; compute peak-to-trough
     drawdown, recovery time, downside capture, correlation, beta."

    2.5i: "The first place market data enters, and the only input that reveals
     what the market actually believes about relative quality rather than what
     it says."

The synthetic series below are chosen so every statistic is exact and can be
checked by hand -- a 20% fall against a 10% fall is a downside capture of 2.0,
and a peer whose every daily return is twice the benchmark's has a beta of 2
and a correlation of 1. Real prices are licensed and local; the arithmetic is
tested against numbers a reader can verify without them, the same way
tests/test_comps.py tests the pairing rule against the Reddit worked example.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.pitch.drawdown import (
    STRESS_THRESHOLD,
    DrawdownError,
    correlation,
    downside_capture,
    max_drawdown,
    recovery_date,
    returns,
    stress_beta,
    stress_windows,
)


def series(*prices, start=date(2025, 1, 1)):
    """A daily close series from bare numbers, oldest first."""
    return [(start + timedelta(days=i), Decimal(str(p)))
            for i, p in enumerate(prices)]


# 100 -> 110 -> 88 -> 99 -> 110 -> 121. Peak 110, trough 88: 88/110 - 1 = -20%.
SHAPE = series(100, 110, 88, 99, 110, 121)

# Every daily return exactly twice the benchmark's.
BENCH = series(100, 110, 99, 108.9, 98.01)
DOUBLE = series(100, 120, 96, 115.2, 92.16)


class TestReturns:
    def test_simple_returns_not_log(self):
        """Drawdown and capture are conventionally simple returns; mixing in
        log returns would make the capture ratio mean something else."""
        r = returns(series(100, 110, 99))
        assert [v for _, v in r] == [Decimal("0.1"), Decimal("-0.1")]

    def test_a_single_point_has_no_returns(self):
        assert returns(series(100)) == []

    def test_a_zero_price_refuses_rather_than_dividing(self):
        with pytest.raises(DrawdownError, match="zero"):
            returns(series(100, 0, 50))


class TestMaxDrawdown:
    def test_peak_to_trough_is_measured_from_the_running_peak(self):
        """Not from the first price: a series that rises then falls has its
        drawdown measured from the high, which is the whole point."""
        dd, peak, trough = max_drawdown(SHAPE)
        assert dd == Decimal("-0.2")
        assert peak == date(2025, 1, 2)      # the 110
        assert trough == date(2025, 1, 3)    # the 88

    def test_a_monotonic_rise_has_no_drawdown(self):
        dd, _, _ = max_drawdown(series(100, 110, 120))
        assert dd == 0

    def test_the_deepest_drawdown_wins_not_the_first(self):
        dd, _, trough = max_drawdown(series(100, 90, 100, 60, 100))
        assert dd == Decimal("-0.4") and trough == date(2025, 1, 4)


class TestRecovery:
    def test_recovery_is_the_first_close_back_at_the_peak(self):
        assert recovery_date(SHAPE, date(2025, 1, 2), date(2025, 1, 3)) == \
            date(2025, 1, 5)

    def test_an_unrecovered_drawdown_is_none_not_zero(self):
        """A peer still under water is the most informative case in 2.5i, and
        reporting it as recovered-in-zero-days would invert the reading."""
        never = series(100, 110, 88, 90, 92)
        assert recovery_date(never, date(2025, 1, 2), date(2025, 1, 3)) is None


class TestDownsideCapture:
    def test_twice_the_fall_is_a_capture_of_two(self):
        assert downside_capture(Decimal("-0.20"), Decimal("-0.10")) == Decimal(2)

    def test_half_the_fall_is_a_capture_of_a_half(self):
        assert downside_capture(Decimal("-0.05"), Decimal("-0.10")) == \
            Decimal("0.5")

    def test_a_peer_that_rose_while_the_market_fell_is_negative(self):
        assert downside_capture(Decimal("0.05"), Decimal("-0.10")) == \
            Decimal("-0.5")

    def test_capture_against_a_market_that_did_not_fall_refuses(self):
        """Undefined, not zero, not one. A ratio to a non-fall says nothing
        about downside."""
        with pytest.raises(DrawdownError, match="did not fall"):
            downside_capture(Decimal("-0.20"), Decimal("0.03"))


class TestBetaAndCorrelation:
    """A peer moving exactly twice the benchmark, every day."""

    def test_beta_is_two(self):
        assert stress_beta(DOUBLE, BENCH).quantize(Decimal("0.000001")) == \
            Decimal("2.000000")

    def test_correlation_is_one(self):
        assert abs(correlation(DOUBLE, BENCH) - 1) < Decimal("1e-20")

    def test_an_inverse_peer_correlates_minus_one(self):
        inverse = series(100, 90, 99, 89.1, 98.01)
        assert abs(correlation(inverse, BENCH) + 1) < Decimal("1e-20")

    def test_a_flat_benchmark_refuses_rather_than_dividing_by_zero(self):
        flat = series(100, 100, 100, 100, 100)
        with pytest.raises(DrawdownError, match="no variance"):
            stress_beta(DOUBLE, flat)

    def test_mismatched_dates_refuse(self):
        """Aligning two series by position rather than by date is how a peer
        gets compared against the wrong day."""
        with pytest.raises(DrawdownError, match="overlap"):
            stress_beta(DOUBLE, series(100, 110, 99, 108.9, 98.01,
                                       start=date(2020, 1, 1)))


class TestStressWindows:
    def test_a_window_is_derived_from_the_benchmark_not_asserted(self):
        """2.4 says 'define stress windows'. Deriving them from a benchmark
        decline makes them reproducible from the data instead of a date list
        someone typed."""
        bench = series(100, 110, 88, 99, 110, 121)
        windows = stress_windows(bench, min_drawdown=Decimal("0.10"))
        assert len(windows) == 1
        w = windows[0]
        assert (w.peak, w.trough, w.recovered) == (
            date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 5))
        assert w.benchmark_drawdown == Decimal("-0.2")

    def test_a_shallow_dip_is_not_a_stress_window(self):
        bench = series(100, 110, 105, 112)
        assert stress_windows(bench, min_drawdown=Decimal("0.10")) == []

    def test_the_default_threshold_is_the_conventional_correction(self):
        assert STRESS_THRESHOLD == Decimal("0.10")

    def test_an_unrecovered_window_still_counts(self):
        """The most recent stress is usually the one still running, and
        dropping it would quietly exclude the present."""
        bench = series(100, 110, 88, 90)
        w = stress_windows(bench, min_drawdown=Decimal("0.10"))[0]
        assert w.recovered is None


# ---------------------------------------------------------------------------
# Recovery is measured against the PEER's own peak (regression)
# ---------------------------------------------------------------------------

def test_recovery_uses_the_peers_own_peak_not_the_windows():
    """Found on real data: IBM's own 2022 peak was 132.26 on 2022-12-13, while
    its close on the benchmark's peak date was 113.85. Measuring recovery
    against the benchmark's peak date set a bar IBM was already above, and
    reported an 8-day recovery from a 17.6% drawdown.

    A peer's drawdown is its OWN peak to its OWN trough, so its recovery is the
    return to its OWN peak. The window supplies the period, not the price.
    """
    from src.pitch.drawdown import StressWindow, peer_drawdown

    window = StressWindow(peak=date(2025, 1, 1), trough=date(2025, 1, 3),
                          recovered=date(2025, 1, 4),
                          benchmark_drawdown=Decimal("-0.15"))
    # Peer rises after the window opens, then falls and does NOT regain its own
    # peak. Its close on the window's peak date (100) is a far lower bar.
    peer = series(100, 120, 96, 110)
    bench = series(100, 95, 85, 100)

    got = peer_drawdown("PEER", peer, bench, window)
    assert got.drawdown == Decimal("-0.2")          # 96 / 120 - 1
    assert got.recovery_days is None, (
        "110 clears the window-peak close of 100 but not the peer's own 120")
