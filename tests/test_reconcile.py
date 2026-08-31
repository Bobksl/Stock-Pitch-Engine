"""P0.5 — reconciliation of instance-parsed facts against SEC companyfacts.

compare() is pure, so these run with no DB, no cache and no network.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.edgar.ixbrl import XbrlFact
from src.edgar.reconcile import ReconcileError, Report, agrees, compare, reconcile_filing

ACC = "0000950170-24-087843"
START, END = date(2023, 7, 1), date(2024, 6, 30)


def fact(value, *, taxonomy="us-gaap", tag="Revenues", unit="USD", segments=None):
    return XbrlFact(taxonomy=taxonomy, tag=tag, value=Decimal(value), unit=unit,
                    period_type="duration", period_start=START, period_end=END,
                    segments=segments or {}, context_id="C1", decimals=-6)


def index(*entries):
    """Build a companyfacts index like companyfacts.index_by_key does."""
    out = {}
    for taxonomy, tag, unit, val in entries:
        out[(ACC, taxonomy, tag, unit, START, END)] = [{"val": val}]
    return out


# --------------------------------------------------------------------------
# the agreement rule
# --------------------------------------------------------------------------

def test_exact_agreement():
    assert agrees(Decimal("245122000000"), Decimal("245122000000")) == "exact"


def test_disagreement_is_reported():
    assert agrees(Decimal("245122000000"), Decimal("245100000000")) is None


def test_companyfacts_rounding_of_sub_cent_fractions_is_tolerated():
    # MSFT par value: the filing says 0.00000625, the API publishes 0.000006
    assert agrees(Decimal("0.00000625"), Decimal("0.000006")) == "rounded"


def test_rounding_tolerance_cannot_excuse_a_material_error():
    # A whole-dollar difference never rounds away: companyfacts money is integral.
    assert agrees(Decimal("245122000000"), Decimal("245122000001")) is None
    assert agrees(Decimal("1.25"), Decimal("2.00")) is None


# --------------------------------------------------------------------------
# comparison bookkeeping
# --------------------------------------------------------------------------

def test_matching_fact_counts_as_matched():
    r = compare([fact("245122000000")], index(("us-gaap", "Revenues", "USD", 245122000000)), ACC)
    assert (r.compared, r.matched, r.mismatches) == (1, 1, [])
    assert r.ok


def test_mismatch_is_recorded_with_both_values_and_the_delta():
    r = compare([fact("245122000000")], index(("us-gaap", "Revenues", "USD", 245100000000)), ACC)
    assert not r.ok
    m = r.mismatches[0]
    assert m["parsed"] == Decimal("245122000000")
    assert m["companyfacts"] == Decimal("245100000000")
    assert m["delta"] == Decimal("22000000")


def test_dimensional_facts_are_excluded_not_failed():
    """companyfacts cannot publish these at all — that is why we parse instances."""
    seg = {"us-gaap:StatementBusinessSegmentsAxis": "msft:IntelligentCloudMember"}
    r = compare([fact("105362000000", segments=seg)], index(), ACC)
    assert (r.dimensional, r.compared, r.mismatches) == (1, 0, [])
    assert r.ok


def test_company_extension_tags_are_excluded_not_failed():
    r = compare([fact("1", taxonomy="msft", tag="SomeCustomMetric")], index(), ACC)
    assert (r.extension, r.compared) == (1, 0)


def test_standard_tag_missing_from_companyfacts_is_counted_as_absent():
    # e.g. MSFT's zero-length-duration GoodwillImpairmentLoss facts
    r = compare([fact("0", tag="GoodwillImpairmentLoss")], index(), ACC)
    assert (r.unmatched, r.compared) == (1, 0)
    assert r.ok, "absence is not disagreement"


def test_rounded_agreements_are_counted_separately_from_exact_ones():
    facts = [fact("0.00000625", taxonomy="dei", tag="EntityListingParValuePerShare",
                  unit="USD/shares"),
             fact("245122000000")]
    idx = index(("dei", "EntityListingParValuePerShare", "USD/shares", 0.000006),
                ("us-gaap", "Revenues", "USD", 245122000000))
    r = compare(facts, idx, ACC)
    assert (r.matched, r.rounded, r.mismatches) == (1, 1, [])


def test_report_string_surfaces_every_bucket():
    s = str(Report(accession=ACC, compared=5, matched=4, rounded=1, dimensional=9,
                   extension=2, unmatched=3))
    for token in ["compared=5", "matched=4", "rounded=1", "dimensional=9",
                  "extension=2", "absent=3"]:
        assert token in s


# --------------------------------------------------------------------------
# fail-loud contract
# --------------------------------------------------------------------------

def test_reconcile_filing_raises_on_mismatch(monkeypatch):
    """A parser that disagrees with SEC must stop the build, not warn."""
    import src.edgar.reconcile as R

    monkeypatch.setattr(R, "get_conn", lambda: _conn_returning((789019,)))
    monkeypatch.setattr(R, "parse_cached_filing", lambda acc: ([fact("245122000000")], {}))
    monkeypatch.setattr(R, "index_by_key",
                        lambda cik: index(("us-gaap", "Revenues", "USD", 245100000000)))

    with pytest.raises(ReconcileError, match="disagree with SEC companyfacts"):
        reconcile_filing(ACC)

    report = reconcile_filing(ACC, raise_on_mismatch=False)
    assert len(report.mismatches) == 1, "--no-raise still reports the mismatch"


class _conn_returning:
    """Minimal stand-in for the psycopg connection context manager."""

    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        return self

    def fetchone(self):
        return self._row
