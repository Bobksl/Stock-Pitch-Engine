"""P3.4c — price history for the framework 2.4 peer drawdown analysis.

Fork 1, as decided: a local `prices` table, loaded from moomoo through the
already-installed OpenD gateway. This replaced a Bloomberg CSV export, and the
replacement is strictly better on the constraint that mattered — there is no
export file to keep out of git, because nothing is ever written to disk. The
schema is public and reviewable; the data lives only in the local database.

Two floats that never happen
----------------------------
The gateway answers in JSON, and `json.loads(..., parse_float=Decimal)` builds
the Decimal straight from the source text. No float is constructed at any point,
so this needs no third sanctioned crossing in `money.py` — `from_spreadsheet`
and `to_spreadsheet` remain the only two, and a float here would still be a bug.

The column is NUMERIC for the same reason. Every statistic 2.4 asks for is
computed from these closes, and a float column would put a binary rounding
boundary underneath a Decimal engine.

Why a subprocess
----------------
The moomoo SDK lives in a different interpreter from this pipeline's, and that
is a feature: a market-data vendor's client has no business in the venv that
parses filings. The boundary is a JSON document over stdout, which is also what
makes the loader testable without a gateway.

Adjustment is part of the key
-----------------------------
A raw and a forward-adjusted series for one ticker are different series that
share a name. A drawdown computed across a split boundary on raw prices is
wrong by the split ratio — Broadcom's 10:1 in July 2024 would read as a 90%
crash — so the two cannot share a primary key and let a later load silently
redefine an earlier one.
"""
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.db import get_conn

SOURCE_MOOMOO = "moomoo"
ADJ_FORWARD, ADJ_NONE = "forward", "none"

#: The interpreter that has moomoo-api installed, and the skill that wraps it.
MOOMOO_PYTHON = os.getenv("MOOMOO_PYTHON", r"C:\Python314\python.exe")
MOOMOO_SKILL_DIR = os.getenv(
    "MOOMOO_SKILL_DIR", str(Path.home() / ".claude" / "skills" / "moomooapi"))

#: moomoo codes are market-prefixed; the facts table is not.
MARKET_PREFIX = {"US": "US."}


class PriceError(RuntimeError):
    """Prices could not be fetched or stored."""


@dataclass(frozen=True)
class Bar:
    """One daily bar, every field a Decimal or an int."""

    day: date
    close: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: int | None = None


def moomoo_code(ticker: str, market: str = "US") -> str:
    return f"{MARKET_PREFIX.get(market, 'US.')}{ticker.upper()}"


def parse_kline(payload: str) -> tuple[str, list[Bar]]:
    """(code, bars) from the gateway's JSON, in Decimal throughout.

    `parse_float=Decimal` is the whole point: the numbers are built from the
    source text and a float is never constructed.
    """
    line = next((ln for ln in payload.splitlines()
                 if ln.lstrip().startswith("{")), None)
    if line is None:
        raise PriceError(f"no JSON object in the gateway response: "
                         f"{payload.strip()[:200]}")
    try:
        doc = json.loads(line, parse_float=Decimal, parse_int=Decimal)
    except json.JSONDecodeError as exc:
        raise PriceError(f"gateway response is not valid JSON: {exc}") from None

    bars = []
    for row in doc.get("data") or []:
        day = date.fromisoformat(str(row["time"])[:10])
        bars.append(Bar(
            day=day, close=row["close"], open=row.get("open"),
            high=row.get("high"), low=row.get("low"),
            volume=int(row["volume"]) if row.get("volume") is not None else None))
    if not bars:
        raise PriceError(f"gateway returned no bars for {doc.get('code')!r}")
    return doc.get("code", ""), bars


def fetch_kline(ticker: str, start: date, end: date, *,
                market: str = "US", adjustment: str = ADJ_FORWARD) -> list[Bar]:
    """Daily bars from the moomoo gateway. Requires OpenD to be running."""
    script = Path(MOOMOO_SKILL_DIR) / "scripts" / "quote" / "get_kline.py"
    if not script.exists():
        raise PriceError(
            f"moomoo gateway script not found at {script}. Set MOOMOO_SKILL_DIR, "
            f"or install the skill")
    cmd = [MOOMOO_PYTHON, str(script), moomoo_code(ticker, market),
           "--ktype", "1d", "--start", start.isoformat(), "--end", end.isoformat(),
           "--rehab", adjustment, "--json"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                             encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PriceError(f"could not run the moomoo gateway: {exc}") from None
    if out.returncode != 0:
        raise PriceError(
            f"moomoo gateway exited {out.returncode} for {ticker}. Is OpenD "
            f"running on 127.0.0.1:11111?\n{(out.stderr or '').strip()[:300]}")
    return parse_kline(out.stdout)[1]


def store_bars(ticker: str, bars: list[Bar], *, source: str = SOURCE_MOOMOO,
               adjustment: str = ADJ_FORWARD) -> int:
    """Upsert bars. Re-loading a window is idempotent, not duplicative."""
    rows = [(ticker.upper(), b.day, b.close, b.open, b.high, b.low, b.volume,
             source, adjustment) for b in bars]
    with get_conn() as conn:
        conn.cursor().executemany("""
            INSERT INTO prices (ticker, date, close, open, high, low, volume,
                                source, adjustment)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, date, source, adjustment) DO UPDATE SET
                close = EXCLUDED.close, open = EXCLUDED.open,
                high = EXCLUDED.high, low = EXCLUDED.low,
                volume = EXCLUDED.volume, loaded_at = now()
        """, rows)
    return len(rows)


def load_prices(ticker: str, start: date, end: date, *, market: str = "US",
                adjustment: str = ADJ_FORWARD) -> int:
    return store_bars(ticker, fetch_kline(ticker, start, end, market=market,
                                          adjustment=adjustment),
                      adjustment=adjustment)


def get_closes(ticker: str, start: date, end: date, *,
               source: str = SOURCE_MOOMOO,
               adjustment: str = ADJ_FORWARD) -> list[tuple[date, Decimal]]:
    """The stored series, oldest first. Decimal out, as it went in."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT date, close FROM prices
            WHERE ticker = %s AND source = %s AND adjustment = %s
              AND date BETWEEN %s AND %s
            ORDER BY date
        """, (ticker.upper(), source, adjustment, start, end)).fetchall()
