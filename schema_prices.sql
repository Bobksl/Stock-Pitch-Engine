-- Price history — framework 2.4 peer drawdown analysis.
--
--   psql -U postgres -d filings -f schema_prices.sql
--
-- The SCHEMA is public and reviewable; the DATA never enters the repository.
-- Market data carries redistribution terms whoever the vendor is, and this
-- repo is public, so prices live only in the local database and are loaded
-- from the vendor on demand by scripts/load_prices.py. There is no export file
-- to leak: unlike the Bloomberg CSV route this replaced, nothing is ever
-- written to disk for scripts/pre-commit to have to block.
--
-- Framework 2.5i calls this "the first place market data enters, and the only
-- input that reveals what the market actually believes". It is deliberately
-- the narrowest table that can answer that: a close, a date, a ticker, and a
-- declaration of where it came from and how it was adjusted.

CREATE TABLE IF NOT EXISTS prices (
    ticker      TEXT    NOT NULL,          -- 'AVGO', matching companies.ticker
    date        DATE    NOT NULL,
    close       NUMERIC NOT NULL,          -- NUMERIC, never double precision
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    volume      BIGINT,

    -- Provenance, on every row rather than assumed per table.
    source      TEXT    NOT NULL,          -- 'moomoo'
    adjustment  TEXT    NOT NULL,          -- 'forward' | 'none'
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (ticker, date, source, adjustment)
);

-- Drawdown work reads one ticker across a window, in date order.
CREATE INDEX IF NOT EXISTS prices_ticker_date ON prices (ticker, date);

-- NUMERIC and not double precision, for the reason money.py exists: a close is
-- a financial figure, every statistic 2.4 asks for is computed from it, and a
-- float column would put a binary rounding boundary underneath a Decimal
-- engine. Postgres NUMERIC round-trips a Decimal exactly.
--
-- The adjustment is part of the KEY, not a column to be overwritten. A raw and
-- a forward-adjusted series for one ticker are different series that happen to
-- share a name, and a drawdown computed across a split boundary on raw prices
-- is wrong by the split ratio. Storing both under one key would let the second
-- load silently redefine the first.
