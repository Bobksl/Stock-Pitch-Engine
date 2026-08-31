"""P1.2 — the written-precision tolerance rule.

The two cases in the phase brief are the first two tests and are the contract:
"$245.1 billion" resolves against 245,122,000,000 and "$245.9 billion" does not.
Every expected value below is hand-computed.
"""
from decimal import Decimal

import pytest

from src.qc.claims import extract_claims
from src.qc.tolerance import resolves, scale_hypothesis, tolerance_of

MSFT_REVENUE = Decimal("245122000000")


def claim(md: str):
    claims = extract_claims(md)
    assert len(claims) == 1, [c.text for c in claims]
    return claims[0]


# --------------------------------------------------------------------------
# the contract
# --------------------------------------------------------------------------

def test_correctly_rounded_figure_resolves():
    c = claim("Revenue was $245.1 billion.")
    tol = tolerance_of(c)
    assert tol.half_ulp == Decimal("5e7")
    assert tol.low == Decimal("245050000000")
    assert tol.high == Decimal("245150000000")
    assert tol.accepts(MSFT_REVENUE)


def test_wrongly_rounded_figure_does_not_resolve():
    c = claim("Revenue was $245.9 billion.")
    tol = tolerance_of(c)
    assert tol.low == Decimal("245850000000")
    assert not tol.accepts(MSFT_REVENUE)


def test_error_reports_distance_outside_the_interval():
    # 245,850,000,000 - 245,122,000,000 = 728,000,000 short of the interval
    assert tolerance_of(claim("Revenue was $245.9 billion.")).error(MSFT_REVENUE) \
        == Decimal("728000000")
    assert tolerance_of(claim("Revenue was $245.1 billion.")).error(MSFT_REVENUE) == 0


# --------------------------------------------------------------------------
# precision as written drives the width
# --------------------------------------------------------------------------

def test_more_precise_claim_is_a_stronger_claim():
    loose = claim("Revenue was $245.1 billion.")
    tight = claim("Revenue was $245.12 billion.")
    assert loose.value == Decimal("245100000000")
    assert tolerance_of(loose).accepts(MSFT_REVENUE)
    # 245.12bn +/- 5e6 -> [245,115,000,000 .. 245,125,000,000]
    assert tolerance_of(tight).accepts(MSFT_REVENUE)
    assert tolerance_of(tight).half_ulp < tolerance_of(loose).half_ulp


def test_over_precise_claim_fails_where_the_loose_one_passed():
    """245.10bn asserts two decimals of accuracy it does not have."""
    assert not resolves(claim("Revenue was $245.10 billion."), MSFT_REVENUE)
    assert resolves(claim("Revenue was $245.1 billion."), MSFT_REVENUE)


def test_exact_figure_resolves_exactly():
    c = claim("Revenue was $245,122,000,000.")
    assert tolerance_of(c).half_ulp == Decimal("0.5")
    assert resolves(c, MSFT_REVENUE)
    assert not resolves(c, MSFT_REVENUE + 1)


def test_whole_billion_claim_is_a_wide_but_honest_claim():
    c = claim("Revenue was $245 billion.")
    assert tolerance_of(c).half_ulp == Decimal("5e8")
    assert resolves(c, MSFT_REVENUE)
    assert not resolves(c, Decimal("245600000000"))


# --------------------------------------------------------------------------
# boundaries
# --------------------------------------------------------------------------

def test_interval_is_closed_at_both_ends():
    """A value on the boundary is a rounding tie; half-up and half-even
    disagree there and a draft must not fail over the convention."""
    c = claim("Revenue was $245.1 billion.")
    tol = tolerance_of(c)
    assert tol.accepts(tol.low) and tol.accepts(tol.high)
    assert not tol.accepts(tol.low - 1)
    assert not tol.accepts(tol.high + 1)


def test_negative_claims_use_a_positive_interval():
    c = claim("Segment result was ($1,234) million.")
    tol = tolerance_of(c)
    assert c.value == Decimal("-1234000000")
    assert tol.half_ulp == Decimal("5e5")
    assert tol.low < tol.high
    assert resolves(c, Decimal("-1234200000"))
    assert not resolves(c, Decimal("1234000000")), "a sign flip must not resolve"


# --------------------------------------------------------------------------
# non-currency kinds
# --------------------------------------------------------------------------

def test_percent_tolerance_is_in_ratio_units():
    c = claim("Operating margin was 41.4%.")
    assert tolerance_of(c).half_ulp == Decimal("0.0005")
    assert resolves(c, Decimal("0.4138"))
    assert not resolves(c, Decimal("0.4200"))


def test_margin_from_the_facts_api_resolves_against_a_written_percent():
    """PanelCell.margin quantises to 4dp; a one-decimal percent claim must
    accept it. MSFT Intelligent Cloud FY2025: 44,589 / 106,265 = 0.41955...
    -> 0.4196 -> '42.0%'."""
    computed = (Decimal("44589") / Decimal("106265")).quantize(Decimal("0.0001"))
    assert computed == Decimal("0.4196")
    assert resolves(claim("The margin was 42.0%."), computed)
    assert not resolves(claim("The margin was 41.9%."), computed)


def test_a_rounding_tie_resolves_against_both_neighbours():
    """MSFT Intelligent Cloud FY2026: 56,972 / 137,791 -> 0.4135, exactly on
    the boundary between '41.3%' and '41.4%'. Closed intervals accept both,
    which is the intended consequence: the draft is not wrong either way, and
    failing it would be a finding about a tie-breaking convention, not about
    the number."""
    computed = (Decimal("56972") / Decimal("137791")).quantize(Decimal("0.0001"))
    assert computed == Decimal("0.4135")
    assert resolves(claim("The margin was 41.3%."), computed)
    assert resolves(claim("The margin was 41.4%."), computed)
    assert not resolves(claim("The margin was 41.5%."), computed)


def test_multiple_tolerance():
    c = claim("It trades at 4.2x EBITDA.")
    assert tolerance_of(c).half_ulp == Decimal("0.05")
    assert resolves(c, Decimal("4.23"))
    assert not resolves(c, Decimal("4.31"))


def test_basis_points():
    c = claim("The spread widened 50 bps.")
    assert c.value == Decimal("0.0050")
    assert tolerance_of(c).half_ulp == Decimal("0.00005")


# --------------------------------------------------------------------------
# the scale hint -- diagnostic only
# --------------------------------------------------------------------------

def test_scale_hypothesis_names_the_fix_without_applying_it():
    md = ("| Segment | Revenue |\n"
          "|---|---|\n"
          "| Intelligent Cloud | 137,791 |\n")
    c = claim(md)
    assert not resolves(c, Decimal("137791000000")), \
        "an undeclared scale must fail, never be silently rescued"
    assert scale_hypothesis(c, Decimal("137791000000")) == Decimal("1e6")


def test_scale_hypothesis_is_none_when_no_scale_would_help():
    c = claim("Revenue was $245.9 billion.")
    assert scale_hypothesis(c, MSFT_REVENUE) is None


@pytest.mark.parametrize("written,actual,expected", [
    ("$245.1 billion", "245122000000", True),
    ("$245.9 billion", "245122000000", False),
    ("$245.2 billion", "245122000000", False),
    ("$245.0 billion", "245122000000", False),
    ("$331.8 billion", "331839000000", True),
    ("$331.9 billion", "331839000000", False),
])
def test_rounding_table(written, actual, expected):
    assert resolves(claim(f"Revenue was {written}."), Decimal(actual)) is expected
