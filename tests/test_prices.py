"""P3.4c — the price table and its loader (framework 2.4, fork 1 as decided).

The parsing tests are the load-bearing ones. Everything 2.4 asks for -- peak to
trough, recovery time, downside capture, correlation, beta -- is computed from
these closes, so a float anywhere here would put a binary rounding boundary
underneath a Decimal engine.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.ingest.prices import (
    ADJ_FORWARD,
    ADJ_NONE,
    Bar,
    PriceError,
    get_closes,
    moomoo_code,
    parse_kline,
    store_bars,
)

PAYLOAD = (
    '2026-09-08 10:30:49,113 | [open_context_base.py:411] New connect ready\n'
    '{"code": "US.AVGO", "ktype": "1d", "source": "history", "data": ['
    '{"time": "2025-11-03 00:00:00", "open": 366.10, "high": 372.25,'
    ' "low": 365.00, "close": 370.34, "volume": 11756540},'
    '{"time": "2025-11-04 00:00:00", "open": 370.50, "high": 375.00,'
    ' "low": 368.10, "close": 374.12, "volume": 9900000}]}\n'
)


class TestParsing:
    def test_no_float_is_ever_constructed(self):
        """json.loads(parse_float=Decimal) builds from the source text."""
        _, bars = parse_kline(PAYLOAD)
        assert all(isinstance(b.close, Decimal) for b in bars)
        assert bars[0].close == Decimal("370.34")

    def test_the_decimal_is_exact_not_a_float_repr(self):
        """Decimal(370.34) from a float would be 370.339999999999974...;
        from the text it is 370.34 and compares equal to the literal."""
        _, bars = parse_kline(PAYLOAD)
        assert str(bars[0].close) == "370.34"
        assert bars[0].close != Decimal(370.34)

    def test_the_gateway_banner_is_skipped(self):
        """OpenD prints a connection line to stdout before the JSON."""
        code, bars = parse_kline(PAYLOAD)
        assert code == "US.AVGO" and len(bars) == 2

    def test_dates_are_dates_not_timestamps(self):
        _, bars = parse_kline(PAYLOAD)
        assert bars[0].day == date(2025, 11, 3)

    def test_volume_is_an_int(self):
        _, bars = parse_kline(PAYLOAD)
        assert bars[0].volume == 11756540

    def test_a_response_with_no_json_is_named_not_guessed(self):
        with pytest.raises(PriceError, match="no JSON object"):
            parse_kline("ERROR: OpenD is not running\n")

    def test_an_empty_series_refuses(self):
        with pytest.raises(PriceError, match="no bars"):
            parse_kline('{"code": "US.NOPE", "data": []}')


def test_the_market_prefix_is_added():
    assert moomoo_code("AVGO") == "US.AVGO"


# ---------------------------------------------------------------------------
# DB-backed
# ---------------------------------------------------------------------------

def _table_ready() -> bool:
    try:
        from src.db import get_conn
        with get_conn() as c:
            return c.execute("SELECT to_regclass('public.prices') IS NOT NULL"
                             ).fetchone()[0]
    except Exception:
        return False


live = pytest.mark.skipif(not _table_ready(), reason="prices table not created")

BARS = [Bar(day=date(2001, 1, 2), close=Decimal("10.25")),
        Bar(day=date(2001, 1, 3), close=Decimal("11.50"))]


@live
class TestStorage:
    TICKER = "__TEST__"

    def teardown_method(self):
        from src.db import get_conn
        with get_conn() as c:
            c.execute("DELETE FROM prices WHERE ticker = %s", (self.TICKER,))

    def test_a_close_round_trips_as_an_exact_decimal(self):
        store_bars(self.TICKER, BARS)
        got = get_closes(self.TICKER, date(2001, 1, 1), date(2001, 1, 31))
        assert [c for _, c in got] == [Decimal("10.25"), Decimal("11.50")]

    def test_reloading_a_window_is_idempotent(self):
        store_bars(self.TICKER, BARS)
        store_bars(self.TICKER, BARS)
        assert len(get_closes(self.TICKER, date(2001, 1, 1), date(2001, 1, 31))) == 2

    def test_raw_and_adjusted_are_different_series(self):
        """A drawdown across a split boundary on raw prices is wrong by the
        split ratio, so the adjustment is part of the key and a raw load
        cannot overwrite an adjusted one."""
        store_bars(self.TICKER, BARS, adjustment=ADJ_FORWARD)
        store_bars(self.TICKER, [Bar(day=date(2001, 1, 2), close=Decimal("102.50"))],
                   adjustment=ADJ_NONE)
        fwd = get_closes(self.TICKER, date(2001, 1, 1), date(2001, 1, 31))
        raw = get_closes(self.TICKER, date(2001, 1, 1), date(2001, 1, 31),
                         adjustment=ADJ_NONE)
        assert [c for _, c in fwd] == [Decimal("10.25"), Decimal("11.50")]
        assert [c for _, c in raw] == [Decimal("102.50")]
