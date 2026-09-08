"""P3.6 — framework 2.4 / 2.5i: peer drawdown analysis.

    2.5i: "The first place market data enters, and the only input that reveals
     what the market actually believes about relative quality rather than what
     it says. The peer that holds up is telling you something about revenue
     durability, balance sheet, or customer mix. If that ranking contradicts
     the fundamental analysis, one of the two is wrong -- and the discrepancy
     is often where variant perception hides."

That last sentence is why this module reports rather than concludes. It
produces a ranking; whether the ranking agrees with the industry panel is the
analyst's question, and the interesting case is the one where it does not.

Stress windows are derived, not typed in
----------------------------------------
2.4 says "define stress windows" and leaves the definition open. A hardcoded
list of dates would be an assertion nobody can check and would rot the moment
the corpus moves. Here a stress window IS a benchmark decline of at least
`STRESS_THRESHOLD` from a running peak: peak date, trough date, and the date
the benchmark regained the peak, or None if it has not. Reproducible from the
price series alone, and it moves when the data does.

This beta is not the WACC beta
------------------------------
`stress_beta` is measured over one stress window, which is exactly what makes
it interesting for 2.5i and exactly what makes it wrong for a discount rate.
Framework 4.4's beta is a five-year regression against a broad index, or a
peer-median unlevered beta relevered to target structure, and it lives in
`valuation/beta.py`. Feeding a stress-window beta into WACC would substitute
"how this name behaved in one crisis" for "the forward business risk of this
company", which is the mistake 4.4 spends a section arguing against. The two
are named differently for that reason and neither imports the other.

Decimal throughout, including the square root
---------------------------------------------
`Decimal.sqrt()` runs in the process context `money.py` sets, so correlation is
computed at the same precision as everything else and no float appears. A float
here would be invisible: correlations round to two decimals in any report and
the error would never show.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

#: A benchmark decline of this depth from a running peak opens a stress window.
#: Ten percent is the conventional definition of a correction, and it is a
#: project decision rather than a derived quantity -- stated once so that
#: changing it is one reviewable edit.
STRESS_THRESHOLD = Decimal("0.10")

Series = list[tuple[date, Decimal]]


class DrawdownError(ValueError):
    """A statistic is undefined for this data, and a number would be a lie."""


@dataclass(frozen=True)
class StressWindow:
    """A benchmark decline, and how long it took to come back."""

    peak: date
    trough: date
    recovered: date | None
    benchmark_drawdown: Decimal

    @property
    def label(self) -> str:
        end = self.recovered or "unrecovered"
        return f"{self.peak}..{self.trough} (recovered {end})"

    def contains(self, day: date) -> bool:
        return self.peak <= day <= (self.recovered or date.max)


@dataclass(frozen=True)
class PeerDrawdown:
    """One peer's behaviour through one stress window."""

    ticker: str
    window: StressWindow
    drawdown: Decimal
    trough: date
    recovery_days: int | None
    downside_capture: Decimal | None
    correlation: Decimal | None
    beta: Decimal | None

    @property
    def recovered(self) -> bool:
        return self.recovery_days is not None

    def render(self) -> str:
        rec = f"{self.recovery_days}d" if self.recovered else "not recovered"
        cap = "n/a" if self.downside_capture is None else f"{self.downside_capture:.2f}x"
        cor = "n/a" if self.correlation is None else f"{self.correlation:.2f}"
        beta = "n/a" if self.beta is None else f"{self.beta:.2f}"
        return (f"{self.ticker:<6} {self.drawdown:>8.1%} {rec:>15} "
                f"{cap:>8} {cor:>7} {beta:>7}")


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def returns(series: Series) -> list[tuple[date, Decimal]]:
    """Simple daily returns, dated by the closing day of each move.

    Simple and not log: downside capture is a ratio of returns and drawdown is
    a peak-to-trough fall, and both are conventionally simple. Mixing log
    returns in would silently change what the capture ratio means.
    """
    out: list[tuple[date, Decimal]] = []
    for (_, prev), (day, price) in zip(series, series[1:]):
        if prev == 0:
            raise DrawdownError(f"zero price before {day}; a return is undefined")
        out.append((day, price / prev - 1))
    return out


def max_drawdown(series: Series) -> tuple[Decimal, date, date]:
    """(drawdown, peak date, trough date), measured from the RUNNING peak.

    Not from the first price. A series that rises before it falls has its
    drawdown measured from the high it actually reached, which is the number
    an investor experienced.
    """
    if not series:
        raise DrawdownError("empty series")
    worst, peak_day, trough_day = Decimal(0), series[0][0], series[0][0]
    running_peak, running_peak_day = series[0][1], series[0][0]
    for day, price in series:
        if price > running_peak:
            running_peak, running_peak_day = price, day
        fall = price / running_peak - 1
        if fall < worst:
            worst, peak_day, trough_day = fall, running_peak_day, day
    return worst, peak_day, trough_day


def recovery_date(series: Series, peak: date, trough: date) -> date | None:
    """First close at or above the peak price after the trough, or None.

    None means "still under water at the end of the data" and is the most
    informative outcome 2.5i has. Reporting it as a zero-day recovery would
    invert the reading entirely.
    """
    peak_price = next((p for d, p in series if d == peak), None)
    if peak_price is None:
        raise DrawdownError(f"no close on the peak date {peak}")
    return next((d for d, p in series if d > trough and p >= peak_price), None)


def downside_capture(peer_return: Decimal, benchmark_return: Decimal) -> Decimal:
    """Peer return divided by benchmark return over a falling market.

    Refuses when the benchmark did not fall. A capture ratio against a flat or
    rising market is not a small number or a large one, it is meaningless, and
    returning one would put it in a table to be compared.
    """
    if benchmark_return >= 0:
        raise DrawdownError(
            f"benchmark did not fall ({benchmark_return}); downside capture is "
            f"undefined against a flat or rising market")
    return peer_return / benchmark_return


def _paired(peer: Series, benchmark: Series) -> tuple[list[Decimal], list[Decimal]]:
    """Returns for the days BOTH series have, aligned by date.

    By date and never by position: two series that differ by one holiday would
    otherwise be compared a day apart for the rest of the window, which shows
    up as a plausible-looking beta rather than as an error.
    """
    peer_by_day = dict(returns(peer))
    bench_by_day = dict(returns(benchmark))
    days = sorted(set(peer_by_day) & set(bench_by_day))
    if len(days) < 2:
        raise DrawdownError(
            f"the two series overlap on {len(days)} day(s); a beta needs at "
            f"least two paired returns")
    return [peer_by_day[d] for d in days], [bench_by_day[d] for d in days]


def _moments(xs: list[Decimal], ys: list[Decimal]
             ) -> tuple[Decimal, Decimal, Decimal]:
    """(covariance, variance of xs, variance of ys), population form."""
    n = Decimal(len(xs))
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    vx = sum((x - mx) ** 2 for x in xs) / n
    vy = sum((y - my) ** 2 for y in ys) / n
    return cov, vx, vy


def stress_beta(peer: Series, benchmark: Series) -> Decimal:
    """Beta over one window. NOT the 4.4 WACC beta -- see the module docstring."""
    peer_r, bench_r = _paired(peer, benchmark)
    cov, _, var_bench = _moments(peer_r, bench_r)
    if var_bench == 0:
        raise DrawdownError("the benchmark has no variance over this window")
    return cov / var_bench


def correlation(peer: Series, benchmark: Series) -> Decimal:
    peer_r, bench_r = _paired(peer, benchmark)
    cov, var_peer, var_bench = _moments(peer_r, bench_r)
    if var_peer == 0 or var_bench == 0:
        raise DrawdownError("a series has no variance over this window")
    return cov / (var_peer.sqrt() * var_bench.sqrt())


# ---------------------------------------------------------------------------
# Windows and the per-peer table
# ---------------------------------------------------------------------------

def stress_windows(benchmark: Series, *,
                   min_drawdown: Decimal = STRESS_THRESHOLD) -> list[StressWindow]:
    """Every benchmark decline of at least `min_drawdown`, peak to recovery.

    Episodes are non-overlapping: a window closes when the benchmark regains
    its peak, and the next one can only open after that. A still-running
    decline is returned with `recovered=None` rather than dropped -- the most
    recent stress is usually the unfinished one, and excluding it would quietly
    exclude the present.
    """
    windows: list[StressWindow] = []
    i, n = 0, len(benchmark)
    while i < n:
        rest = benchmark[i:]
        fall, peak, trough = max_drawdown(rest)
        if -fall < min_drawdown:
            break
        recovered = recovery_date(rest, peak, trough)
        windows.append(StressWindow(peak=peak, trough=trough,
                                    recovered=recovered,
                                    benchmark_drawdown=fall))
        if recovered is None:
            break
        i += next(k for k, (d, _) in enumerate(rest) if d == recovered) + 1
    return windows


def _slice(series: Series, window: StressWindow) -> Series:
    end = window.recovered or series[-1][0]
    return [(d, p) for d, p in series if window.peak <= d <= end]


def _price_on(series: Series, day: date) -> Decimal | None:
    return next((p for d, p in series if d == day), None)


def peer_drawdown(ticker: str, peer: Series, benchmark: Series,
                  window: StressWindow) -> PeerDrawdown:
    """One peer through one window. Every statistic that cannot be computed
    comes back None with the peer still in the table -- an absent number and a
    dropped peer read very differently in a ranking."""
    peer_slice = _slice(peer, window)
    bench_slice = _slice(benchmark, window)
    if len(peer_slice) < 2:
        raise DrawdownError(
            f"{ticker} has {len(peer_slice)} close(s) in {window.label}")

    # Recovery is measured against the peer's OWN peak, not the benchmark's.
    # The window supplies the period; it does not supply the price. IBM's own
    # 2022 peak was 132.26 on 2022-12-13 while its close on the benchmark's
    # peak date was 113.85, and measuring against the latter set a bar IBM was
    # already above -- reporting an 8-day recovery from a 17.6% drawdown.
    fall, peer_peak, trough = max_drawdown(peer_slice)
    recovered = recovery_date(peer, peer_peak, trough)
    days = (recovered - trough).days if recovered else None

    peak_price = _price_on(peer_slice, window.peak)
    trough_price = _price_on(peer_slice, window.trough)
    capture = None
    if peak_price and trough_price:
        try:
            capture = downside_capture(trough_price / peak_price - 1,
                                       window.benchmark_drawdown)
        except DrawdownError:
            capture = None

    try:
        corr = correlation(peer_slice, bench_slice)
        beta = stress_beta(peer_slice, bench_slice)
    except DrawdownError:
        corr = beta = None

    return PeerDrawdown(ticker=ticker, window=window, drawdown=fall,
                        trough=trough, recovery_days=days,
                        downside_capture=capture, correlation=corr, beta=beta)


def render_table(rows: list[PeerDrawdown], window: StressWindow) -> str:
    """2.6's peer drawdown table, ranked by who held up best."""
    head = (f"{'peer':<6} {'drawdown':>8} {'recovery':>15} "
            f"{'capture':>8} {'corr':>7} {'beta':>7}")
    lines = [f"Stress window {window.label} "
             f"(benchmark {window.benchmark_drawdown:.1%})", head,
             "-" * len(head)]
    lines += [r.render() for r in sorted(rows, key=lambda r: -r.drawdown)]
    return "\n".join(lines)
