"""P3.5 — framework 2.4: the industry panel.

    "For every comp-set member, 3-5 years: revenue growth, gross / EBIT margin,
     ROIC, R&D and capex intensity, revenue share of panel."

Everything here is derived from cited facts through model cells, so a panel
figure carries the same provenance a Section 1 figure does. Nothing is stored:
`cells.py` recomputes at verification time, and the panel is a set of
declarations plus the alignment that says who may appear in a column.

The alignment is not decoration. A panel that quietly included Microsoft's June
year alongside IBM's December one would look complete and compare different
twelve-month windows, which is the corruption 2.4 exists to prevent -- so the
excluded peers travel WITH the panel and a test asserts they are named.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.pitch.industry import (
    PANEL_METRICS,
    IndustryPanel,
    PanelError,
)

AVGO, AMD, IBM, MRVL, NVDA = 1730168, 2488, 51143, 1835632, 1045810
MSFT, ORCL, QCOM, AAPL = 789019, 1341439, 804328, 320193

Q = Decimal("0.0001")


def _loaded() -> bool:
    try:
        from src.facts.api import get_fact
        return get_fact(AVGO, "revenue", date(2025, 11, 2)) is not None
    except Exception:
        return False


live = pytest.mark.skipif(not _loaded(), reason="corpus not loaded")


class TestTheMetricSet:
    def test_2_4_names_these_metrics(self):
        assert set(PANEL_METRICS) >= {
            "revenue_growth", "gross_margin", "ebit_margin",
            "rd_intensity", "capex_intensity"}

    def test_every_metric_is_a_model_cell_not_a_stored_number(self):
        """6.4: derived figures are recomputed, never stored."""
        from src.qc.cells import OPS
        for spec in PANEL_METRICS.values():
            assert spec["op"] in OPS


@live
class TestAgainstTheCorpus:
    """Nine filers, seven fiscal calendars. CY2025."""

    def setup_method(self):
        self.panel = IndustryPanel.build(
            {"AVGO": AVGO, "AMD": AMD, "IBM": IBM, "MRVL": MRVL, "NVDA": NVDA,
             "MSFT": MSFT, "ORCL": ORCL, "QCOM": QCOM, "AAPL": AAPL},
            calendar_year=2025)

    def test_only_aligned_members_hold_a_column(self):
        assert set(self.panel.members) == {"AVGO", "AMD", "IBM", "MRVL", "NVDA"}

    def test_every_excluded_peer_is_named_with_its_reason(self):
        assert set(self.panel.excluded) == {"MSFT", "ORCL", "QCOM", "AAPL"}
        assert all("overlaps CY2025" in why
                   for why in self.panel.excluded.values())

    def test_the_partition_is_exact(self):
        """A peer in neither would be a silent drop."""
        assert len(self.panel.members) + len(self.panel.excluded) == 9

    def test_broadcom_metrics_match_the_hand_checked_values(self):
        """AVGO FY2025: gross 43,294/63,887 = 67.77%; R&D 10,977/63,887 =
        17.18%; capex 623/63,887 = 0.98%; revenue 63,887/51,574 - 1 = 23.87%."""
        m = self.panel.metrics("AVGO")
        assert m["gross_margin"].quantize(Q) == Decimal("0.6777")
        assert m["rd_intensity"].quantize(Q) == Decimal("0.1718")
        assert m["capex_intensity"].quantize(Q) == Decimal("0.0098")
        assert m["revenue_growth"].quantize(Q) == Decimal("0.2387")

    def test_revenue_share_of_panel_sums_to_one(self):
        """2.4 asks for 'revenue share of panel', so the denominator is the
        panel and it must be the aligned members only."""
        shares = [self.panel.revenue_share(m) for m in self.panel.members]
        assert sum(shares).quantize(Q) == Decimal("1.0000")

    def test_a_panel_figure_carries_its_provenance(self):
        """Same contract as a Section 1 figure: a cited formula over cited facts."""
        citation = self.panel.citation("AVGO", "gross_margin")
        assert "ratio(" in citation and citation.count("<-") == 2

    def test_the_rendered_panel_carries_its_exclusions(self):
        rendered = self.panel.render()
        assert "EXCLUDED" in rendered
        for peer in ("MSFT", "ORCL", "QCOM", "AAPL"):
            assert peer in rendered


@live
def test_a_panel_with_too_few_aligned_members_refuses():
    """4.8: n=2 is a teaching example, not a valuation. A panel that cannot
    reach the minimum says so rather than reporting a thin one as if it were
    a comp set."""
    with pytest.raises(PanelError, match="aligned"):
        IndustryPanel.build({"AVGO": AVGO, "MSFT": MSFT}, calendar_year=2025)


@live
def test_an_empty_calendar_year_refuses():
    with pytest.raises(PanelError, match="aligned"):
        IndustryPanel.build({"AVGO": AVGO, "AMD": AMD, "IBM": IBM,
                             "MRVL": MRVL, "NVDA": NVDA}, calendar_year=1990)
