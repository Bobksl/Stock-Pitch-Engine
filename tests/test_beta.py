"""P2.7 — beta computed both ways (framework 4.4).

Hand-checked throughout. Hamada round-trips exactly in Decimal, which is worth
asserting: unlevering and relevering at the same structure is the identity, and
in float it would not quite be.
"""
from decimal import Decimal

import pytest

from src.valuation.beta import (
    BASIS_PEER_RELEVERED,
    BASIS_REGRESSION,
    BetaError,
    Peer,
    beta_policy,
    blume,
    median,
    relever,
    unlever,
)
from src.valuation.money import D, divide

TAX = Decimal("0.25")

PEERS = (
    Peer("AAA", Decimal("1.50"), Decimal("0.50"), TAX),
    Peer("BBB", Decimal("1.20"), Decimal("0.20"), TAX),
    Peer("CCC", Decimal("0.90"), Decimal("0.00"), TAX),
)


class TestHamada:
    def test_unlever_is_hand_checked(self):
        """1.50 / (1 + 0.75 x 0.50) = 1.50 / 1.375

        Compared through `divide`, not bare `/`: the module computes at the
        50-digit valuation precision and Decimal's default context is 28, so
        the two agree in value and differ in how far they are carried.
        """
        got = unlever(Decimal("1.50"), Decimal("0.50"), TAX)
        assert got == divide(Decimal("1.50"), Decimal("1.375"))
        assert str(got).startswith("1.09090909")

    def test_an_unlevered_company_is_its_own_unlevered_beta(self):
        assert unlever(Decimal("0.90"), Decimal(0), TAX) == Decimal("0.90")

    def test_relevering_at_the_same_structure_round_trips_exactly(self):
        """Exact in Decimal. In float this would be approximate."""
        for beta, de in [("1.50", "0.50"), ("1.20", "0.20"), ("0.83", "1.75")]:
            unlevered = unlever(Decimal(beta), Decimal(de), TAX)
            assert relever(unlevered, Decimal(de), TAX) == Decimal(beta)

    def test_leverage_raises_equity_beta(self):
        unlevered = Decimal("1.00")
        assert relever(unlevered, Decimal("1.0"), TAX) > unlevered


class TestBlume:
    def test_is_hand_checked(self):
        """2/3 x 1.22 + 1/3 = 1.14666..."""
        assert str(blume(Decimal("1.22"))).startswith("1.1466666")

    def test_pulls_toward_one_from_both_sides(self):
        assert Decimal("1.22") > blume(Decimal("1.22")) > Decimal(1)
        assert Decimal("0.60") < blume(Decimal("0.60")) < Decimal(1)

    def test_leaves_one_alone(self):
        assert blume(Decimal(1)) == Decimal(1)


class TestMedian:
    def test_odd_count_takes_the_middle(self):
        assert median([D(3), D(1), D(2)]) == D(2)

    def test_even_count_averages_the_two_middle(self):
        assert median([D(1), D(2), D(3), D(4)]) == Decimal("2.5")

    def test_empty_is_an_error_not_a_zero(self):
        with pytest.raises(BetaError):
            median([])


class TestThePolicy:
    def test_peer_relevered_is_the_default(self):
        policy = beta_policy(PEERS, regression=Decimal("1.60"),
                             target_debt_to_equity=Decimal("0.30"), tax_rate=TAX)
        assert policy.basis == BASIS_PEER_RELEVERED
        assert policy.beta == policy.peer_relevered_adjusted

    def test_both_routes_are_computed_even_though_one_is_adopted(self):
        """4.4: compute both. The unused one is the diagnostic."""
        policy = beta_policy(PEERS, regression=Decimal("1.60"),
                             target_debt_to_equity=Decimal("0.30"), tax_rate=TAX)
        assert policy.peer_relevered_adjusted is not None
        assert policy.regression_adjusted == blume(Decimal("1.60"))

    def test_the_spread_is_reported(self):
        """A regression beta above peer-relevered says the market prices the
        name as riskier than its business model implies (4.4)."""
        policy = beta_policy(PEERS, regression=Decimal("1.60"),
                             target_debt_to_equity=Decimal("0.30"), tax_rate=TAX)
        assert policy.spread > 0
        assert policy.spread == (policy.regression_adjusted
                                 - policy.peer_relevered_adjusted)
        assert "spread" in policy.render()

    def test_a_recent_ipo_has_no_spread_rather_than_a_spread_of_zero(self):
        """Regression beta is unavailable, not merely noisy (4.4). Reporting
        zero would assert an agreement that was never tested."""
        policy = beta_policy(PEERS, regression=None,
                             target_debt_to_equity=Decimal("0.30"), tax_rate=TAX)
        assert policy.spread is None
        assert "spread n/a" in policy.render()
        assert policy.beta is not None

    def test_the_peer_median_is_taken_unlevered_then_relevered(self):
        policy = beta_policy(PEERS, target_debt_to_equity=Decimal("0.30"),
                             tax_rate=TAX)
        expected = median([p.unlevered_beta for p in PEERS])
        assert policy.peer_median_unlevered == expected
        assert policy.peer_relevered == relever(expected, Decimal("0.30"), TAX)

    def test_regression_basis_requires_a_stated_reason(self):
        policy = beta_policy(regression=Decimal("1.10"), basis=BASIS_REGRESSION,
                             reason="large, liquid, no comparable peer set")
        assert policy.basis == BASIS_REGRESSION
        assert "no comparable peer set" in policy.render()

    def test_no_peers_and_the_default_basis_is_a_named_error(self):
        with pytest.raises(BetaError, match="framework 4.4 default"):
            beta_policy(regression=Decimal("1.10"))

    def test_regression_basis_without_a_regression_beta_is_an_error(self):
        with pytest.raises(BetaError, match="no regression beta"):
            beta_policy(PEERS, target_debt_to_equity=Decimal("0.30"),
                        tax_rate=TAX, basis=BASIS_REGRESSION)

    def test_relevering_peers_needs_a_target_structure(self):
        with pytest.raises(BetaError, match="target debt/equity"):
            beta_policy(PEERS)

    def test_an_unknown_basis_is_refused(self):
        with pytest.raises(BetaError, match="unknown beta basis"):
            beta_policy(PEERS, target_debt_to_equity=D(0), tax_rate=TAX,
                        basis="whatever_bloomberg_said")
