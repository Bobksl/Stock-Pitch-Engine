"""Module 10 — instance vs companyfacts reconciliation (fail-loud, R1).

Every consolidated fact parsed out of a filing is compared, to the cent, with
SEC's own companyfacts rendering of the same (accession, tag, unit, period).
Two independent readings of one document agreeing is the evidence that makes
custom iXBRL parsing safe to rely on for the numbers that reach a price target.

A mismatch RAISES. It is not a warning, and it is not tolerated with a note:
under the architecture rule "QC failures block publication", a parser that
disagrees with SEC about a reported figure is a build error.

Facts that companyfacts structurally cannot carry are not failures and are
counted separately:
  - dimensional facts (segment / geography members) — the reason we parse at all
  - company-extension taxonomies (e.g. 'msft:') — not in the standard taxonomies

CLI:  python -m src.edgar.reconcile 0000950170-24-087843
      python -m src.edgar.reconcile --all
"""
from dataclasses import dataclass
from decimal import Decimal

from src.db import get_conn
from src.edgar.companyfacts import index_by_key
from src.edgar.ixbrl import parse_cached_filing

STANDARD_TAXONOMIES = frozenset({"us-gaap", "dei", "srt", "ifrs-full", "invest"})


class ReconcileError(AssertionError):
    """The instance parser disagrees with SEC about a reported figure."""


@dataclass
class Report:
    accession: str
    compared: int = 0
    matched: int = 0            # equal to the cent
    rounded: int = 0            # equal once rounded to companyfacts' own precision
    dimensional: int = 0        # not publishable by companyfacts, by design
    extension: int = 0          # company-specific taxonomy
    unmatched: int = 0          # standard tag, but absent from companyfacts
    mismatches: list = None

    def __post_init__(self):
        self.mismatches = self.mismatches or []

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def __str__(self) -> str:
        return (f"{self.accession}  compared={self.compared:,} matched={self.matched:,} "
                f"rounded={self.rounded} mismatched={len(self.mismatches)}  "
                f"[dimensional={self.dimensional:,} extension={self.extension:,} "
                f"absent={self.unmatched:,}]")


def agrees(parsed: Decimal, expected: Decimal) -> str | None:
    """'exact' | 'rounded' | None.

    companyfacts serialises values as JSON numbers and rounds fractions to about
    six decimal places: MSFT's par value of $0.00000625 per share is published as
    0.000006. The filing is right and the API is lossy, so a parsed value that
    agrees once rounded to the precision companyfacts actually carries is treated
    as agreement — and counted separately so it stays visible.

    Every money fact is an integer, so this tolerance cannot mask a material
    error; it only covers sub-cent per-share fractions.
    """
    if parsed == expected:
        return "exact"
    places = -expected.as_tuple().exponent
    if places > 0 and round(parsed, places) == expected:
        return "rounded"
    return None


def compare(facts, index: dict, accession: str) -> Report:
    """Pure comparison of parsed facts against a companyfacts index."""
    report = Report(accession=accession)
    for f in facts:
        if f.segments:
            report.dimensional += 1
            continue
        if f.taxonomy not in STANDARD_TAXONOMIES:
            report.extension += 1
            continue

        entries = index.get(
            (accession, f.taxonomy, f.tag, f.unit, f.period_start, f.period_end))
        if not entries:
            report.unmatched += 1
            continue

        report.compared += 1
        expected = Decimal(str(entries[0]["val"]))
        verdict = agrees(f.value, expected)
        if verdict == "exact":
            report.matched += 1
        elif verdict == "rounded":
            report.rounded += 1
        else:
            report.mismatches.append({
                "tag": f.qname, "unit": f.unit, "context": f.context_id,
                "period": (f.period_start, f.period_end),
                "parsed": f.value, "companyfacts": expected,
                "delta": f.value - expected,
            })
    return report


def reconcile_filing(accession: str, *, raise_on_mismatch: bool = True) -> Report:
    """Compare one filing's consolidated facts against companyfacts."""
    with get_conn() as conn:
        row = conn.execute("SELECT cik FROM filings WHERE accession = %s", (accession,)).fetchone()
    if not row:
        raise ValueError(f"accession {accession} has not been fetched")
    cik = row[0]

    facts, _ = parse_cached_filing(accession)
    report = compare(facts, index_by_key(cik), accession)

    if raise_on_mismatch and report.mismatches:
        lines = "\n".join(
            f"  {m['tag']} {m['period'][0]}..{m['period'][1]}: "
            f"parsed {m['parsed']:,} vs companyfacts {m['companyfacts']:,} "
            f"(delta {m['delta']:,})" for m in report.mismatches[:10])
        raise ReconcileError(
            f"{accession}: {len(report.mismatches)} fact(s) disagree with SEC companyfacts\n{lines}")

    return report


def reconcile_all(*, raise_on_mismatch: bool = True) -> list[Report]:
    with get_conn() as conn:
        accessions = [r[0] for r in conn.execute(
            "SELECT accession FROM filings ORDER BY cik, period_end DESC")]
    return [reconcile_filing(a, raise_on_mismatch=raise_on_mismatch) for a in accessions]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("accession", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-raise", action="store_true", help="report instead of failing")
    a = ap.parse_args()

    reports = (reconcile_all(raise_on_mismatch=not a.no_raise) if a.all
               else [reconcile_filing(a.accession, raise_on_mismatch=not a.no_raise)])
    for r in reports:
        print(("PASS " if r.ok else "FAIL ") + str(r))
    total = sum(r.compared for r in reports)
    rounded = sum(r.rounded for r in reports)
    bad = sum(len(r.mismatches) for r in reports)
    print(f"\n{total:,} facts compared against SEC companyfacts, {bad} mismatched, "
          f"{rounded} agreeing only after rounding to the API's own precision")
