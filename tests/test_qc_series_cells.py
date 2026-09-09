"""P3.8 — spec v1.5: series-valued inputs and the closed series-operation set.

2.4's peer drawdown analysis is the first thing in the framework that is not
arithmetic over two scalars. All three existing routes fail it: prices are not
in XBRL so the figures cannot be facts; `sum / difference / product / ratio /
growth` cannot express a drawdown; and storing a computed statistic in an
external record would record it rather than recompute it -- a wrong drawdown
recorded faithfully would verify clean, which is the hole 6.4 exists to close.

So the vocabulary widens, and the guarantee that matters survives: each op is a
named function reviewable in a diff, there is no expression language and no
eval, and every statistic is recomputed at verification time. The measurement
window lives in the input declaration, so a figure states the period it was
measured over instead of implying it.

The prices below are the same hand-checkable shapes as test_pitch_drawdown:
a 20% fall against a 10% fall is a capture of 2.0, and a peer moving exactly
twice the benchmark has a beta of 2 and a correlation of 1.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.qc.cells import OPS, SERIES_OPS, CellError, CellRegistry

TICKER, BENCH = "__DDTEST__", "__DDBENCH__"
#: A second pair where the peer moves EXACTLY twice the benchmark on every
#: day, so beta is 2 and correlation is 1 by construction rather than by
#: arithmetic that happens to land near them.
DOUBLE, DBENCH = "__DDDOUBLE__", "__DDDBENCH__"
START, END = date(2001, 1, 1), date(2001, 1, 31)


def _table_ready() -> bool:
    try:
        from src.db import get_conn
        with get_conn() as c:
            return c.execute("SELECT to_regclass('public.prices') IS NOT NULL"
                             ).fetchone()[0]
    except Exception:
        return False


live = pytest.mark.skipif(not _table_ready(), reason="prices table not created")


def _seed(rows, ticker):
    from datetime import timedelta

    from src.ingest.prices import Bar, store_bars
    store_bars(ticker, [Bar(day=START + timedelta(days=i), close=Decimal(str(p)))
                        for i, p in enumerate(rows)])


class TestTheVocabularies:
    def test_series_ops_are_separate_from_scalar_ops(self):
        """Two closed vocabularies, not one widened past recognition. A caller
        reading OPS still sees only arithmetic."""
        assert set(SERIES_OPS).isdisjoint(OPS)

    def test_the_series_vocabulary_covers_exactly_what_2_4_asks_for(self):
        assert set(SERIES_OPS) == {
            "max_drawdown", "recovery_days", "downside_capture",
            "correlation", "stress_beta"}

    def test_every_series_op_is_a_named_function_not_an_expression(self):
        assert all(callable(fn) for _, fn in SERIES_OPS.values())


@live
class TestAgainstSeededPrices:
    """Series ops read the prices table through a declared series input."""

    @classmethod
    def setup_class(cls):
        # 100 -> 110 -> 88 -> 99 -> 110: peak 110, trough 88, -20%, recovers.
        _seed([100, 110, 88, 99, 110], TICKER)
        # Benchmark falls 10% on the same peak-to-trough leg, which is what
        # the downside-capture test slices. Its later moves are NOT half the
        # peer's, so beta is measured on the DOUBLE pair instead.
        _seed([100, 105, 94.5, 99.225, 104.18625], BENCH)
        _seed([100, 120, 96, 115.2, 92.16], DOUBLE)
        _seed([100, 110, 99, 108.9, 98.01], DBENCH)

    @classmethod
    def teardown_class(cls):
        from src.db import get_conn
        with get_conn() as c:
            c.execute("DELETE FROM prices WHERE ticker = ANY(%s)",
                      ([TICKER, BENCH, DOUBLE, DBENCH],))

    def _registry(self, decls):
        return CellRegistry(declarations=decls)

    def test_a_drawdown_is_recomputed_from_the_table(self):
        reg = self._registry({"dd": {
            "op": "max_drawdown", "unit": "pure",
            "inputs": [{"series": TICKER, "from": START, "to": END}]}})
        assert reg.compute("dd").value == Decimal("-0.2")

    def test_recovery_days_counts_from_trough_back_to_peak(self):
        """Trough on 2001-01-03, back to 110 on 2001-01-05: two days."""
        reg = self._registry({"rec": {
            "op": "recovery_days", "unit": "days",
            "inputs": [{"series": TICKER, "from": START, "to": END}]}})
        assert reg.compute("rec").value == Decimal(2)

    def test_an_unrecovered_drawdown_refuses_rather_than_returning_zero(self):
        """There is no number, so there is no figure. A cell that cannot be
        computed blocks the draft, which is the correct outcome -- the prose
        has to say 'not recovered' without citing a numeral."""
        _seed([100, 110, 88, 90, 92], TICKER + "2")
        reg = self._registry({"rec": {
            "op": "recovery_days", "unit": "days",
            "inputs": [{"series": TICKER + "2", "from": START, "to": END}]}})
        with pytest.raises(CellError, match="not recovered"):
            reg.compute("rec")
        from src.db import get_conn
        with get_conn() as c:
            c.execute("DELETE FROM prices WHERE ticker = %s", (TICKER + "2",))

    def test_downside_capture_takes_two_series_and_the_window_slices_them(self):
        """Peak-to-trough only: 2001-01-02..2001-01-03. Peer -20%, bench -10%."""
        reg = self._registry({"cap": {
            "op": "downside_capture", "unit": "x",
            "inputs": [{"series": TICKER, "from": date(2001, 1, 2),
                        "to": date(2001, 1, 3)},
                       {"series": BENCH, "from": date(2001, 1, 2),
                        "to": date(2001, 1, 3)}]}})
        assert reg.compute("cap").value == Decimal(2)

    def test_beta_is_two_and_correlation_is_one(self):
        """Every daily return exactly twice the benchmark's."""
        window = {"from": START, "to": END}
        reg = self._registry({
            "b": {"op": "stress_beta", "unit": "x",
                  "inputs": [{"series": DOUBLE, **window},
                             {"series": DBENCH, **window}]},
            "c": {"op": "correlation", "unit": "pure",
                  "inputs": [{"series": DOUBLE, **window},
                             {"series": DBENCH, **window}]}})
        assert reg.compute("b").value.quantize(Decimal("0.000001")) == \
            Decimal("2.000000")
        assert abs(reg.compute("c").value - 1) < Decimal("1e-20")

    def test_the_citation_names_the_series_and_its_window(self):
        """6.4: the window is IN the declaration, so a figure states the period
        it was measured over rather than implying it."""
        reg = self._registry({"dd": {
            "op": "max_drawdown", "unit": "pure",
            "inputs": [{"series": TICKER, "from": START, "to": END}]}})
        citation = reg.compute("dd").citation
        assert TICKER in citation
        assert "2001-01-01..2001-01-31" in citation

    def test_an_empty_window_refuses_rather_than_returning_nothing(self):
        reg = self._registry({"dd": {
            "op": "max_drawdown", "unit": "pure",
            "inputs": [{"series": TICKER, "from": date(1990, 1, 1),
                        "to": date(1990, 12, 31)}]}})
        with pytest.raises(CellError, match="no prices"):
            reg.compute("dd")

    def test_a_scalar_op_refuses_a_series_input(self):
        """The two vocabularies do not mix: ratio() over a price series would
        be a type confusion that happens to produce a number."""
        reg = self._registry({"x": {
            "op": "ratio",
            "inputs": [{"series": TICKER, "from": START, "to": END},
                       {"series": BENCH, "from": START, "to": END}]}})
        with pytest.raises(CellError, match="series"):
            reg.compute("x")

    def test_a_series_op_refuses_a_scalar_input(self):
        reg = self._registry({"x": {
            "op": "max_drawdown",
            "inputs": [{"literal": 5, "note": "not a series"}]}})
        with pytest.raises(CellError, match="series"):
            reg.compute("x")
