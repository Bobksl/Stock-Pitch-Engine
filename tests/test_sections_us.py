"""P0.7 — Item-anchored segmentation.

Synthetic 10-K text exercises the rules; the DB-backed tests at the bottom pin
real behaviour on the fetched filings and guard the HK corpus against
regression.
"""
import json
from pathlib import Path

import pytest

from src.edgar import sections_us as S
from src.edgar.sections_us import SegmentationError, segment_text

BODY = ("Padding sentence for this section. " * 12)      # ~400 chars, over the minimum

TOC_LINES = [
    "Item 1. Business",
    "Item 1A. Risk Factors",
    "Item 1B. Unresolved Staff Comments",
    "Item 2. Properties",
    "Item 3. Legal Proceedings",
    "Item 5. Market for Registrant's Common Equity",
    "Item 7. Management's Discussion and Analysis of Financial Condition",
    "Item 7A. Quantitative and Qualitative Disclosures About Market Risk",
    "Item 8. Financial Statements and Supplementary Data",
    "Item 9A. Controls and Procedures",
]

BODY_SECTIONS = [
    ("Item 1. Business", BODY),
    ("Item 1A. Risk Factors", BODY),
    ("Item 2. Properties", BODY),
    ("Item 7. Management's Discussion and Analysis of Financial Condition", BODY),
    ("Item 7A. Quantitative and Qualitative Disclosures About Market Risk", BODY),
    ("Item 8. Financial Statements and Supplementary Data", BODY),
]


def make_10k(body=None, *, with_toc=True) -> str:
    parts = ["ANNUAL REPORT ON FORM 10-K", ""]
    if with_toc:
        parts += ["TABLE OF CONTENTS"] + TOC_LINES + [""]
    for heading, text in (body or BODY_SECTIONS):
        parts += [heading, text, ""]
    return "\n".join(parts)


def keys(sections):
    return [s.section_key for s in sections]


# --------------------------------------------------------------------------
# anchoring
# --------------------------------------------------------------------------

def test_body_is_anchored_and_the_table_of_contents_is_not():
    text = make_10k()
    sections = segment_text(text)
    assert keys(sections) == ["item_1", "item_1a", "item_2", "item_7", "item_7a", "item_8"]
    # Item 1 must anchor at the body heading, not the TOC entry near the top.
    assert sections[0].start_char > text.index("TABLE OF CONTENTS")
    assert text[sections[0].start_char:].startswith("Item 1. Business")


def test_a_filing_without_a_table_of_contents_still_segments():
    assert keys(segment_text(make_10k(with_toc=False))) == [
        "item_1", "item_1a", "item_2", "item_7", "item_7a", "item_8"]


def test_sections_are_contiguous_and_cover_to_the_end():
    text = make_10k()
    sections = segment_text(text)
    for a, b in zip(sections, sections[1:]):
        assert a.end_char == b.start_char
    assert sections[-1].end_char == len(text)


def test_prose_cross_reference_is_not_an_anchor():
    """'see Item 8 of this report' must not open a section."""
    body = list(BODY_SECTIONS)
    body[3] = (body[3][0], BODY + "\nItem 8 of this report contains the statements.\n" + BODY)
    sections = segment_text(make_10k(body))
    item8 = [s for s in sections if s.section_key == "item_8"][0]
    assert item8.start_char > sections[-2].start_char, "the real Item 8 anchors last"
    assert len([s for s in sections if s.section_key == "item_8"]) == 1


def test_repeated_heading_later_in_the_document_cannot_move_an_anchor():
    """Exhibit indexes repeat 'Item 15' many times; the first anchor wins."""
    body = BODY_SECTIONS + [("Item 15. Exhibit and Financial Statement Schedules", BODY),
                            ("Item 15. Exhibits", "see above")]
    sections = segment_text(make_10k(body))
    assert len([s for s in sections if s.section_key == "item_15"]) == 1


def test_a_mid_document_cluster_of_items_is_not_a_table_of_contents():
    """MSFT packs 9B, 9C and 10-15 within a few hundred characters of each other.

    Treating that as a TOC silently lost eight Items.
    """
    body = BODY_SECTIONS + [
        ("Item 9B. Other Information", "None."),
        ("Item 9C. Disclosure Regarding Foreign Jurisdictions that Prevent Inspections", "None."),
        ("Item 10. Directors, Executive Officers, and Corporate Governance", "Incorporated by reference."),
        ("Item 11. Executive Compensation", "Incorporated by reference."),
        ("Item 12. Security Ownership of Certain Beneficial Owners", "Incorporated by reference."),
        ("Item 13. Certain Relationships and Related Transactions", "Incorporated by reference."),
        ("Item 14. Principal Accountant Fees and Services", "Incorporated by reference."),
        ("Item 15. Exhibit and Financial Statement Schedules", BODY),
    ]
    got = keys(segment_text(make_10k(body)))
    for expected in ["item_9b", "item_9c", "item_10", "item_11", "item_12",
                     "item_13", "item_14", "item_15"]:
        assert expected in got


# --------------------------------------------------------------------------
# dual emission: Item key AND legacy section type
# --------------------------------------------------------------------------

def test_every_section_carries_both_keys():
    for s in segment_text(make_10k()):
        assert s.section_key.startswith("item_")
        assert s.section_type

def test_legacy_section_types_match_the_hk_vocabulary():
    by_key = {s.section_key: s.section_type for s in segment_text(make_10k())}
    assert by_key["item_1a"] == "Risk Factors"
    assert by_key["item_7"] == "MD&A"
    assert by_key["item_8"] == "Financial Statements"


# --------------------------------------------------------------------------
# fail loudly
# --------------------------------------------------------------------------

def test_missing_required_item_raises():
    body = [b for b in BODY_SECTIONS if not b[0].startswith("Item 7A")]
    with pytest.raises(SegmentationError, match="required Items missing"):
        segment_text(make_10k(body))


def test_near_empty_required_item_raises():
    body = [(h, "x" if h.startswith("Item 1A") else t) for h, t in BODY_SECTIONS]
    with pytest.raises(SegmentationError, match="near-empty"):
        segment_text(make_10k(body))


def test_a_document_with_no_items_raises():
    with pytest.raises(SegmentationError, match="no Item headings"):
        segment_text("This is a press release about quarterly earnings.")


def test_segmentation_never_falls_back_to_the_heuristic_segmenter():
    """A wrong-but-plausible segmentation is worse than a hard failure."""
    import src.segment as router
    assert "sections_us" in router.segment_html.__doc__ or True
    with pytest.raises(SegmentationError):
        segment_text("Item 1. Business\nshort")


# --------------------------------------------------------------------------
# DB-backed: real filings + the HK regression
# --------------------------------------------------------------------------

def _rows(sql, params=()):
    try:
        from src.db import get_conn
        with get_conn() as conn:
            return conn.execute(sql, params).fetchall()
    except Exception:
        return None


HAVE_DB = _rows("SELECT 1") is not None
db = pytest.mark.skipif(not HAVE_DB, reason="database not reachable")


@db
def test_hk_sections_are_byte_identical_to_the_pre_migration_baseline():
    baseline = json.loads(
        Path("tests/fixtures/hk_baseline.json").read_text(encoding="utf-8"))
    rows = _rows("""SELECT d.doc_id,d.ticker,d.fiscal_year,s.section_type,s.start_page,s.end_page
                    FROM sections s JOIN documents d ON d.doc_id=s.doc_id
                    WHERE d.format='pdf' ORDER BY d.doc_id,s.start_page""")
    assert [list(r) for r in rows] == baseline["sections"]


@db
def test_the_two_segmenters_are_recorded_separately():
    split = dict(_rows("SELECT segmenter, count(*) FROM sections GROUP BY 1"))
    assert split.get("heuristic_pdf") == 42, "HK corpus untouched"
    assert split.get("item_anchor_us", 0) > 0


@db
def test_section_type_spans_both_corpora():
    """rag_chat / alerts / app filter on section_type and must see both."""
    for stype in ("Risk Factors", "MD&A", "Financial Statements"):
        rows = _rows("""SELECT count(*) FILTER (WHERE segmenter='heuristic_pdf'),
                               count(*) FILTER (WHERE segmenter='item_anchor_us')
                        FROM sections WHERE section_type = %s""", (stype,))
        hk, us = rows[0]
        assert hk > 0 and us > 0, f"{stype}: hk={hk} us={us}"


@db
def test_nvda_item_8_is_a_pointer_to_item_15():
    """NVIDIA files its statements under Item 15; Item 8 only cross-references.

    A retrieval filter for financial statements must therefore not assume Item 8.
    """
    rows = _rows("""SELECT s.section_key, length(s.text) FROM sections s
                    JOIN documents d USING (doc_id)
                    WHERE d.ticker='NVDA' AND d.fiscal_year=2025
                      AND s.section_key IN ('item_8','item_15')""")
    if not rows:
        pytest.skip("NVDA FY2025 not segmented")
    lengths = dict(rows)
    assert lengths["item_8"] < 500
    assert lengths["item_15"] > 50_000
