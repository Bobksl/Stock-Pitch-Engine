"""P0.4 — inline-XBRL parser.

Unit tests run on hand-written markup that mirrors real filer output (prefixes,
attribute order and all). The integration test at the bottom runs against the
cached MSFT FY2024 10-K when it is present, with hand-checked golden values.
"""
from datetime import date
from decimal import Decimal

import pytest

from src.ingest.edgar import ixbrl
from src.ingest.edgar.ixbrl import IxbrlError, XbrlFact, parse_instance, parse_number

HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024"
      xmlns:dei="http://xbrl.sec.gov/dei/2024"
      xmlns:msft="http://www.microsoft.com/20240630">
<body><ix:header><ix:resources>
  <xbrli:context id="D24">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000789019</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-07-01</xbrli:startDate><xbrli:endDate>2024-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="I24">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000789019</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-06-30</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:context id="D24_SEG">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000789019</xbrli:identifier>
      <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">msft:IntelligentCloudMember</xbrldi:explicitMember></xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-07-01</xbrli:startDate><xbrli:endDate>2024-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="D24_TWO">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000789019</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">msft:IntelligentCloudMember</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">country:US</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-07-01</xbrli:startDate><xbrli:endDate>2024-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="D24_TYPED">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000789019</xbrli:identifier>
      <xbrli:segment><xbrldi:typedMember dimension="msft:PlanAxis"><msft:PlanName>Plan A</msft:PlanName></xbrldi:typedMember></xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-07-01</xbrli:startDate><xbrli:endDate>2024-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="SH"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
  <xbrli:unit id="EPS">
    <xbrli:divide>
      <xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
      <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
    </xbrli:divide>
  </xbrli:unit>
</ix:resources></ix:header>
"""
TAIL = "</body></html>"


def instance(*facts: str) -> bytes:
    return (HEAD + "\n".join(facts) + TAIL).encode("utf-8")


def only(raw: bytes) -> XbrlFact:
    facts, _ = parse_instance(raw)
    assert len(facts) == 1, f"expected one fact, got {len(facts)}"
    return facts[0]


NF = ('<ix:nonFraction contextRef="{ctx}" name="{name}" unitRef="{unit}" '
      'scale="{scale}" decimals="{dec}"{extra}>{text}</ix:nonFraction>')


def nf(text, *, ctx="D24", name="us-gaap:Revenues", unit="USD", scale="6",
       dec="-6", extra=""):
    return NF.format(ctx=ctx, name=name, unit=unit, scale=scale, dec=dec,
                     extra=extra, text=text)


# --------------------------------------------------------------------------
# value construction
# --------------------------------------------------------------------------

def test_scale_is_a_power_of_ten_on_the_displayed_text():
    assert only(instance(nf("64,773"))).value == Decimal("64773000000")


def test_sign_attribute_is_part_of_the_value_not_presentation():
    # MSFT FY2024 NonoperatingIncomeExpense: displayed '1,646', sign='-'
    f = only(instance(nf("1,646", name="us-gaap:NonoperatingIncomeExpense", extra=' sign="-"')))
    assert f.value == Decimal("-1646000000")


def test_unscaled_fact_keeps_its_value():
    assert only(instance(nf("12345", scale="0"))).value == Decimal("12345")


def test_parentheses_mean_negative():
    assert parse_number("(1,646)") == Decimal("-1646")


def test_fixed_zero_rule():
    assert parse_number("—", "ixt:fixed-zero") == Decimal(0)


def test_comma_decimal_rule():
    assert parse_number("1.646,50", "ixt:num-comma-decimal") == Decimal("1646.50")


def test_number_words_rule():
    assert parse_number("No", "ixt-sec:numwordsen") == Decimal(0)
    assert parse_number("twenty-one", "ixt-sec:numwordsen") == Decimal(21)


def test_unrecognised_number_word_raises_rather_than_defaulting_to_zero():
    with pytest.raises(IxbrlError, match="unrecognised word"):
        parse_number("umpteen", "ixt-sec:numwordsen")


def test_exclude_subtree_is_not_part_of_the_value():
    raw = instance('<ix:nonFraction contextRef="D24" name="us-gaap:Revenues" unitRef="USD" '
                   'scale="6" decimals="-6">64,773<ix:exclude> (unaudited)</ix:exclude></ix:nonFraction>')
    assert only(raw).value == Decimal("64773000000")


def test_nil_facts_are_skipped():
    raw = instance('<ix:nonFraction contextRef="D24" name="us-gaap:Revenues" unitRef="USD" '
                   'xsi:nil="true" decimals="-6"></ix:nonFraction>')
    facts, _ = parse_instance(raw)
    assert facts == []


# --------------------------------------------------------------------------
# contexts, periods, dimensions, units
# --------------------------------------------------------------------------

def test_duration_context_carries_both_dates():
    f = only(instance(nf("1")))
    assert f.period_type == "duration"
    assert (f.period_start, f.period_end) == (date(2023, 7, 1), date(2024, 6, 30))


def test_instant_context_has_no_start_date():
    f = only(instance(nf("1", ctx="I24", name="us-gaap:Goodwill")))
    assert f.period_type == "instant"
    assert f.period_start is None
    assert f.period_end == date(2024, 6, 30)


def test_consolidated_fact_has_no_segments():
    assert only(instance(nf("1"))).segments == {}


def test_explicit_member_becomes_a_segment():
    f = only(instance(nf("105,362", ctx="D24_SEG")))
    assert f.segments == {"us-gaap:StatementBusinessSegmentsAxis": "msft:IntelligentCloudMember"}


def test_multiple_axes_on_one_fact():
    f = only(instance(nf("1", ctx="D24_TWO")))
    assert f.segments == {
        "us-gaap:StatementBusinessSegmentsAxis": "msft:IntelligentCloudMember",
        "srt:StatementGeographicalAxis": "country:US",
    }


def test_typed_member_is_recorded_so_it_cannot_pass_as_consolidated():
    f = only(instance(nf("1", ctx="D24_TYPED")))
    assert f.segments == {"msft:PlanAxis": "(typed)Plan A"}
    assert ixbrl.consolidated([f]) == []


def test_units():
    assert only(instance(nf("1"))).unit == "USD"
    assert only(instance(nf("1", unit="SH", name="dei:EntityCommonStockSharesOutstanding"))).unit == "shares"
    assert only(instance(nf("3.30", unit="EPS", scale="0",
                            name="us-gaap:EarningsPerShareDiluted"))).unit == "USD/shares"


def test_taxonomy_and_tag_are_split():
    f = only(instance(nf("1")))
    assert (f.taxonomy, f.tag) == ("us-gaap", "Revenues")
    assert f.qname == "us-gaap:Revenues"


def test_unknown_context_reference_raises():
    with pytest.raises(IxbrlError, match="unknown context"):
        parse_instance(instance(nf("1", ctx="NOPE")))


def test_document_without_contexts_is_not_an_instance():
    with pytest.raises(IxbrlError, match="not an inline-XBRL instance"):
        parse_instance(b"<html><body><p>plain 10-K</p></body></html>")


def test_dei_metadata_is_collected_separately_from_numeric_facts():
    raw = instance(nf("1"),
                   '<ix:nonNumeric contextRef="D24" name="dei:DocumentFiscalYearFocus">2024</ix:nonNumeric>',
                   '<ix:nonNumeric contextRef="D24" name="dei:DocumentType">10-K</ix:nonNumeric>')
    facts, dei = parse_instance(raw)
    assert len(facts) == 1, "nonNumeric elements are not numeric facts"
    assert dei == {"DocumentFiscalYearFocus": "2024", "DocumentType": "10-K"}


# --------------------------------------------------------------------------
# duplicate handling
# --------------------------------------------------------------------------

def test_consistent_duplicates_collapse_to_the_most_precise():
    # MSFT FY2024 goodwill: 50,969 million in the statements, $51.0 billion in the notes
    raw = instance(nf("50,969", ctx="I24", name="us-gaap:Goodwill", scale="6", dec="-6"),
                   nf("51.0", ctx="I24", name="us-gaap:Goodwill", scale="9", dec="-8"))
    facts = ixbrl.dedupe(parse_instance(raw)[0])
    assert len(facts) == 1
    assert facts[0].value == Decimal("50969000000")


def test_inconsistent_duplicates_raise():
    raw = instance(nf("50,969", ctx="I24", name="us-gaap:Goodwill", scale="6", dec="-6"),
                   nf("60,000", ctx="I24", name="us-gaap:Goodwill", scale="6", dec="-6"))
    with pytest.raises(IxbrlError, match="inconsistent duplicate"):
        ixbrl.dedupe(parse_instance(raw)[0])


def test_same_tag_in_different_contexts_is_not_a_duplicate():
    raw = instance(nf("245,122"), nf("105,362", ctx="D24_SEG"))
    assert len(ixbrl.dedupe(parse_instance(raw)[0])) == 2


# --------------------------------------------------------------------------
# integration: the real MSFT FY2024 10-K, hand-checked against the filing
# --------------------------------------------------------------------------

MSFT_FY24 = "0000950170-24-087843"


def _cached_msft():
    try:
        from src.db import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT cached_path FROM filings WHERE accession = %s", (MSFT_FY24,)).fetchone()
    except Exception:
        return None
    if not row:
        return None
    from pathlib import Path
    return row[0] if Path(row[0]).exists() else None


real = pytest.mark.skipif(_cached_msft() is None,
                          reason="MSFT FY2024 10-K not fetched into the local cache")


@real
def test_real_filing_segment_revenue_sums_to_consolidated():
    facts, dei = parse_instance(open(_cached_msft(), "rb").read())
    facts = ixbrl.dedupe(facts)
    assert dei["DocumentFiscalYearFocus"] == "2024"
    assert dei["DocumentType"] == "10-K"

    axis = "us-gaap:StatementBusinessSegmentsAxis"
    fy24 = [f for f in facts
            if f.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
            and f.period_start == date(2023, 7, 1) and f.period_end == date(2024, 6, 30)]

    by_segment = {f.segments[axis].split(":")[-1]: f.value
                  for f in fy24 if list(f.segments) == [axis]}
    consolidated = [f.value for f in fy24 if not f.segments]

    assert by_segment == {
        "ProductivityAndBusinessProcessesMember": Decimal("77728000000"),
        "IntelligentCloudMember": Decimal("105362000000"),
        "MorePersonalComputingMember": Decimal("62032000000"),
    }
    assert consolidated == [Decimal("245122000000")]
    assert sum(by_segment.values()) == consolidated[0]


@real
def test_real_filing_segment_operating_profit_is_available():
    """The figure companyfacts cannot give at all (framework 1.3)."""
    facts = ixbrl.dedupe(parse_instance(open(_cached_msft(), "rb").read())[0])
    axis = "us-gaap:StatementBusinessSegmentsAxis"
    by_segment = {
        f.segments[axis].split(":")[-1]: f.value for f in facts
        if f.tag == "OperatingIncomeLoss" and list(f.segments) == [axis]
        and f.period_start == date(2023, 7, 1) and f.period_end == date(2024, 6, 30)
    }
    assert by_segment == {
        "ProductivityAndBusinessProcessesMember": Decimal("40540000000"),
        "IntelligentCloudMember": Decimal("49584000000"),
        "MorePersonalComputingMember": Decimal("19309000000"),
    }
