"""P3.5 — framework 2.4 period alignment: the fork-2 decision, in code.

    "Periods are stored exactly as reported. A calendar mapping is derived
     separately, following the SEC frames convention. The tolerance window of
     that convention is documented in code, because it determines whether an
     off-cycle peer is EXCLUDED from a panel or MIS-ASSIGNED to a calendar
     period -- and the latter silently corrupts every cross-sectional
     comparison built on the panel. Exclusion is the default; mis-assignment is
     never acceptable."

Every expected value below is computed by hand from real fiscal year ends in
the corpus. Nine filers, seven distinct fiscal calendars, so the exclusion path
runs on live data rather than on a contrived case.
"""
from datetime import date

import pytest

from src.pitch.panel import (
    ANNUAL_DAYS,
    ANNUAL_TOLERANCE_DAYS,
    PeriodAlignmentError,
    align,
    calendar_overlap_days,
    calendar_year,
    is_annual,
)


# ---------------------------------------------------------------------------
# The SEC duration rule -- documented, cited, and about a different question
# ---------------------------------------------------------------------------

class TestIsAnnual:
    """SEC frames: an annual period is 365 days +/- 30. This decides whether a
    period is ANNUAL AT ALL, not which calendar year it belongs to -- the two
    are separate questions and SEC only publishes a number for the first."""

    def test_the_sec_tolerance_is_stated_not_invented(self):
        assert (ANNUAL_DAYS, ANNUAL_TOLERANCE_DAYS) == (365, 30)

    def test_a_normal_fiscal_year_is_annual(self):
        assert is_annual(date(2024, 11, 4), date(2025, 11, 2))     # AVGO, 363d
        assert is_annual(date(2025, 1, 1), date(2025, 12, 31))     # 364d

    def test_a_53_week_year_is_annual(self):
        """Retail-calendar filers run a 371-day year every five or six years."""
        assert is_annual(date(2024, 1, 1), date(2025, 1, 6))       # 371d

    def test_a_quarter_is_not_annual(self):
        assert not is_annual(date(2025, 1, 1), date(2025, 3, 31))

    def test_a_two_year_period_is_not_annual(self):
        assert not is_annual(date(2024, 1, 1), date(2025, 12, 31))


# ---------------------------------------------------------------------------
# Assignment: how much of the fiscal year is actually in the calendar year
# ---------------------------------------------------------------------------

class TestOverlap:
    """SEC says only that frames use "the dates that best align". It publishes
    no assignment tolerance, so the measure is stated here and owned here:
    days of the fiscal period that fall inside the calendar year."""

    def test_a_calendar_year_filer_overlaps_completely(self):
        """IBM, 2025-01-01 to 2025-12-31."""
        assert calendar_overlap_days(date(2025, 1, 1), date(2025, 12, 31), 2025) == 365

    def test_broadcoms_november_year_overlaps_by_306_days(self):
        """AVGO FY2025 runs 2024-11-04 to 2025-11-02. Inside CY2025 that is
        1 January to 2 November = 31+28+31+30+31+30+31+31+30+31+2 = 306."""
        assert calendar_overlap_days(date(2024, 11, 4), date(2025, 11, 2), 2025) == 306

    def test_microsofts_june_year_barely_reaches_half(self):
        """MSFT FY2026 runs 2025-07-01 to 2026-06-30. Inside CY2025 that is
        1 July to 31 December = 31+31+30+31+30+31 = 184."""
        assert calendar_overlap_days(date(2025, 7, 1), date(2026, 6, 30), 2025) == 184

    def test_no_overlap_is_zero_not_negative(self):
        assert calendar_overlap_days(date(2025, 1, 1), date(2025, 12, 31), 2030) == 0


class TestCalendarYear:
    """The corpus, by hand. Overlap with CY2025 out of 365 days."""

    CASES = [
        # (label, start, end, overlap, aligned at 300d)
        ("IBM  12-31", date(2025, 1, 1), date(2025, 12, 31), 365, True),
        ("AMD  12-27", date(2024, 12, 29), date(2025, 12, 27), 361, True),
        ("NVDA 01-25", date(2025, 1, 27), date(2026, 1, 25), 339, True),
        ("MRVL 01-31", date(2025, 2, 2), date(2026, 1, 31), 333, True),
        ("AVGO 11-02", date(2024, 11, 4), date(2025, 11, 2), 306, True),
        ("QCOM 09-28", date(2024, 9, 30), date(2025, 9, 28), 271, False),
        ("ORCL 05-31", date(2025, 6, 1), date(2026, 5, 31), 214, False),
        ("MSFT 06-30", date(2025, 7, 1), date(2026, 6, 30), 184, False),
    ]

    @pytest.mark.parametrize("label,start,end,overlap,_", CASES)
    def test_overlap_matches_the_hand_count(self, label, start, end, overlap, _):
        assert calendar_overlap_days(start, end, 2025) == overlap, label

    @pytest.mark.parametrize("label,start,end,_,aligned", CASES)
    def test_assignment_at_the_declared_threshold(self, label, start, end, _, aligned):
        got = calendar_year(start, end, min_overlap_days=300)
        assert (got == 2025) is aligned, f"{label} -> {got}"

    def test_an_unalignable_period_returns_none_rather_than_the_nearest(self):
        """The whole point of fork 2. Returning the nearest calendar year is
        the mis-assignment 2.4 calls never acceptable."""
        assert calendar_year(date(2025, 7, 1), date(2026, 6, 30),
                             min_overlap_days=300) is None

    def test_a_non_annual_period_refuses(self):
        with pytest.raises(PeriodAlignmentError, match="not an annual period"):
            calendar_year(date(2025, 1, 1), date(2025, 3, 31))


# ---------------------------------------------------------------------------
# align(): the panel column, and the peers it drops BY NAME
# ---------------------------------------------------------------------------

class TestAlign:
    PERIODS = {
        "IBM": (date(2025, 1, 1), date(2025, 12, 31)),
        "AVGO": (date(2024, 11, 4), date(2025, 11, 2)),
        "MSFT": (date(2025, 7, 1), date(2026, 6, 30)),
    }

    def test_aligned_peers_come_back_with_their_overlap(self):
        aligned, _ = align(self.PERIODS, 2025, min_overlap_days=300)
        assert set(aligned) == {"IBM", "AVGO"}
        assert aligned["AVGO"].overlap_days == 306

    def test_excluded_peers_are_named_with_their_reason(self):
        _, excluded = align(self.PERIODS, 2025, min_overlap_days=300)
        assert list(excluded) == ["MSFT"]
        assert "184" in excluded["MSFT"] and "300" in excluded["MSFT"]

    def test_nothing_is_silently_dropped(self):
        aligned, excluded = align(self.PERIODS, 2025, min_overlap_days=300)
        assert set(aligned) | set(excluded) == set(self.PERIODS)

    def test_a_stricter_threshold_drops_more_and_says_so(self):
        aligned, excluded = align(self.PERIODS, 2025, min_overlap_days=350)
        assert set(aligned) == {"IBM"}
        assert set(excluded) == {"AVGO", "MSFT"}
