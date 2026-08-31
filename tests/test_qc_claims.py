"""P1.1 — numeric claim extraction from a Markdown draft.

Every expected value here is hand-checked. The module is deliberately biased
toward over-extraction, so the tests that matter most are the ones asserting a
figure IS found: a missed numeral is a silent hole in the QC gate.
"""
from decimal import Decimal

from src.qc.claims import (
    KIND_BARE,
    KIND_CURRENCY,
    KIND_MULTIPLE,
    KIND_PERCENT,
    KIND_SHARES,
    SCALE_HEADER,
    SCALE_IMPLICIT,
    SCALE_INLINE,
    SCALE_UNDECLARED,
    NumericClaim,
    extract_claims,
    header_scale,
    mask,
)


def one(md: str) -> NumericClaim:
    claims = extract_claims(md)
    assert len(claims) == 1, [c.text for c in claims]
    return claims[0]


# --------------------------------------------------------------------------
# the shapes the spec names explicitly
# --------------------------------------------------------------------------

def test_scaled_currency():
    c = one("Revenue was $245.1 billion in the year.")
    assert c.text == "$245.1 billion"
    assert c.digits == Decimal("245.1")
    assert c.scale == Decimal("1e9")
    assert c.value == Decimal("245100000000")
    assert c.kind == KIND_CURRENCY and c.unit == "USD"
    assert c.scale_source == SCALE_INLINE


def test_plain_decimal_target_price():
    c = one("The published target is 1,732.66 per share.")
    assert c.digits == Decimal("1732.66")
    assert c.value == Decimal("1732.66")
    assert c.kind == KIND_BARE
    assert c.scale_source == SCALE_IMPLICIT, "prose numerals mean what they say"


def test_percentage_normalises_to_ratio_scale():
    c = one("Operating margin reached 23.5% for the segment.")
    assert c.digits == Decimal("23.5")
    assert c.value == Decimal("0.235")
    assert c.ulp == Decimal("0.001")
    assert c.kind == KIND_PERCENT


def test_multiple():
    c = one("It trades at 4.2x forward EBITDA.")
    assert c.value == Decimal("4.2")
    assert c.kind == KIND_MULTIPLE and c.unit == "pure"


def test_share_count():
    c = one("Fully diluted shares were 7,432 million shares at year end.")
    assert c.value == Decimal("7432000000")
    assert c.kind == KIND_SHARES and c.unit == "shares"


# --------------------------------------------------------------------------
# precision as written -- the input to the tolerance rule
# --------------------------------------------------------------------------

def test_trailing_zero_is_significant():
    loose = one("Revenue was $245.1 billion.")
    tight = one("Revenue was $245.10 billion.")
    assert loose.value == tight.value == Decimal("245100000000")
    assert loose.ulp == Decimal("1e8")
    assert tight.ulp == Decimal("1e7"), "245.10 is a tighter claim than 245.1"


def test_ulp_of_an_integer_scaled_figure():
    assert one("Revenue was $50 billion.").ulp == Decimal("1e9")


def test_ulp_of_a_cent_precise_figure():
    assert one("Par value is $0.00000625 per share.").ulp == Decimal("1e-8")


# --------------------------------------------------------------------------
# sign conventions
# --------------------------------------------------------------------------

def test_parenthesised_figure_is_negative():
    """Filings write losses in parentheses; a verifier that reads them as
    positive would pass a sign-flipped claim."""
    c = one("Segment result was ($1,234) million for the period.")
    assert c.value == Decimal("-1234000000")


def test_explicit_minus_and_unicode_minus():
    assert one("The position fell -30% over six months.").value == Decimal("-0.30")
    assert one("The position fell −30% over six months.").value == Decimal("-0.30")


def test_basis_points_scale():
    c = one("Margin improved 50 bps year on year.")
    assert c.value == Decimal("0.0050")


# --------------------------------------------------------------------------
# masking: numerals that are not claims
# --------------------------------------------------------------------------

def test_years_and_periods_are_not_claims():
    md = ("In FY2026 and FY 25, during Q3 and Q1 FY2026, the period ended "
          "2026-06-30 and the company filed its 10-K.")
    assert extract_claims(md) == []


def test_document_and_spec_references_are_not_claims():
    md = ("Per Item 1A and Item 7, ASC 280 requires it; see §4.6 and §2.5i, "
          "checks C10 and C12, change R5, accession 0001193125-26-323660.")
    assert extract_claims(md) == []


def test_code_fences_and_inline_code_are_masked():
    md = "Formula is `TV = 1.5 * 900` here.\n\n```\nrevenue = 245100000000\n```\n"
    assert extract_claims(md) == []


def test_link_targets_are_masked():
    assert extract_claims("See [the filing](https://sec.gov/1045810/0001.htm).") == []


def test_citation_index_section_is_masked():
    md = ("Revenue was $50 billion [^F1].\n\n"
          "## Citation index\n\n"
          "F1: 0001193125-26-323660 | us-gaap:Revenues | 2025-07-01..2026-06-30\n")
    claims = extract_claims(md)
    assert [c.text for c in claims] == ["$50 billion"]


def test_masking_preserves_offsets():
    md = "See Item 7. Revenue was $50 billion."
    masked = mask(md)
    assert len(masked) == len(md)
    c = one(md)
    assert md[c.span[0]:c.span[1]] == "$50 billion"


def test_span_localises_the_failure():
    md = "Intelligent Cloud revenue was $137,791 million in the year."
    c = one(md)
    assert md[c.span[0]:c.span[1]] == "$137,791 million"
    assert c.line == 1


# --------------------------------------------------------------------------
# table headers carry the scale
# --------------------------------------------------------------------------

def test_header_scale_parsing():
    assert header_scale("Revenue ($m)") == (Decimal("1e6"), "USD", KIND_CURRENCY)
    assert header_scale("Revenue (USD bn)") == (Decimal("1e9"), "USD", KIND_CURRENCY)
    assert header_scale("Op margin (%)")[0] == Decimal("0.01")
    assert header_scale("Segment") == (None, None, None)


def test_table_cell_inherits_scale_from_its_column():
    md = ("| Segment | Revenue ($m) | Margin (%) |\n"
          "|---|---|---|\n"
          "| Intelligent Cloud | 137,791 | 41.4 |\n")
    claims = extract_claims(md)
    assert len(claims) == 2
    rev, margin = claims
    assert rev.value == Decimal("137791000000")
    assert rev.scale_source == SCALE_HEADER and rev.kind == KIND_CURRENCY
    assert margin.value == Decimal("0.414")
    assert margin.kind == KIND_PERCENT


def test_unlabelled_financial_column_is_undeclared_not_guessed():
    """The billion/million corruption class: a bare column of magnitudes with
    no unit in the header must fail, never be inferred into agreement."""
    md = ("| Segment | Revenue |\n"
          "|---|---|\n"
          "| Intelligent Cloud | 137,791 |\n")
    c = one(md)
    assert c.scale_source == SCALE_UNDECLARED
    assert not c.scale_declared


def test_inline_scale_beats_the_header():
    md = ("| Segment | Revenue ($m) |\n"
          "|---|---|\n"
          "| Total | $331.8 billion |\n")
    c = one(md)
    assert c.value == Decimal("331800000000")
    assert c.scale_source == SCALE_INLINE


# --------------------------------------------------------------------------
# anchor binding
# --------------------------------------------------------------------------

def test_anchor_binds_to_the_preceding_figure():
    c = one("Revenue was $331.8 billion [^F1].")
    assert c.anchor == "F1"


def test_range_shares_one_anchor():
    claims = extract_claims("The implied range is $41.43–44.10 [^F9].")
    assert len(claims) == 2
    assert all(c.anchor == "F9" for c in claims)


def test_two_figures_two_anchors_bind_separately():
    claims = extract_claims("Revenue grew from $211.9 billion [^F1] to $245.1 billion [^F2].")
    assert [c.anchor for c in claims] == ["F1", "F2"]


def test_unanchored_figure_reports_no_anchor():
    assert one("Revenue was $245.1 billion.").anchor is None


def test_anchor_does_not_leak_across_table_cells():
    md = ("| Segment | Revenue ($m) | Op profit ($m) |\n"
          "|---|---|---|\n"
          "| Intelligent Cloud | 137,791 | 56,972 [^F4] |\n")
    claims = extract_claims(md)
    assert [c.anchor for c in claims] == [None, "F4"]


# --------------------------------------------------------------------------
# over-extraction bias
# --------------------------------------------------------------------------

def test_every_figure_in_a_dense_sentence_is_found():
    md = ("Revenue of $331.8 billion [^F1] on a 41.4% margin [^F2] implies "
          "24.6x [^F3] earnings against 7,432 million shares [^F4].")
    claims = extract_claims(md)
    assert [c.kind for c in claims] == [KIND_CURRENCY, KIND_PERCENT,
                                        KIND_MULTIPLE, KIND_SHARES]
    assert [c.anchor for c in claims] == ["F1", "F2", "F3", "F4"]


def test_multiline_draft_reports_correct_line_numbers():
    md = "# Heading\n\nRevenue was $50 billion.\n\nMargin was 41.4%.\n"
    lines = [c.line for c in extract_claims(md)]
    assert lines == [3, 5]
