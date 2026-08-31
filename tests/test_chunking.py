"""P0.8 — HTML chunking with character anchors, and format-aware citations."""
import pytest

from src.chunk_embed import _blocks, build_chunks_from_text
from src.config import CHUNK_TOKENS
from src.rag_chat import _locator

PARA = "This is a sentence in a filing paragraph. " * 8       # ~330 chars


def doc(n: int) -> str:
    return "\n\n".join(f"Paragraph {i}. {PARA}" for i in range(n))


# --------------------------------------------------------------------------
# offsets are the citation anchor, so they must be exact
# --------------------------------------------------------------------------

def test_offsets_round_trip_exactly():
    text = doc(40)
    for c in build_chunks_from_text(text):
        assert text[c["start_char"]:c["end_char"]].strip() == c["content"]


def test_chunks_cover_the_whole_document():
    text = doc(40)
    chunks = build_chunks_from_text(text)
    assert chunks[0]["start_char"] == 0
    assert chunks[-1]["end_char"] == len(text)


def test_chunks_respect_the_token_budget():
    for c in build_chunks_from_text(doc(40)):
        assert c["token_count"] <= CHUNK_TOKENS


def test_consecutive_chunks_overlap():
    """Overlap keeps a fact that straddles a boundary retrievable from either side."""
    chunks = build_chunks_from_text(doc(60))
    assert len(chunks) > 1
    for a, b in zip(chunks, chunks[1:]):
        assert b["start_char"] < a["end_char"], "no overlap between consecutive chunks"


def test_paragraph_boundaries_are_respected():
    """A chunk starts at a paragraph, not mid-sentence."""
    text = doc(30)
    for c in build_chunks_from_text(text):
        assert c["content"].startswith("Paragraph ")


def test_empty_document_yields_no_chunks():
    assert build_chunks_from_text("") == []
    assert build_chunks_from_text("\n\n   \n\n") == []


# --------------------------------------------------------------------------
# block splitting
# --------------------------------------------------------------------------

def test_block_spans_are_exact():
    text = doc(5)
    for a, b in _blocks(text):
        assert text[a:b].startswith("Paragraph")
        assert not text[a:b].endswith("\n")


def test_an_oversized_paragraph_is_split_on_line_breaks():
    """Financial tables arrive as one enormous 'paragraph'."""
    table = "\n".join(f"Row {i} | 1,234,567 | 2,345,678 | 3,456,789" for i in range(4000))
    spans = _blocks(table)
    assert len(spans) > 1, "an oversized block must be split, not emitted whole"
    for c in build_chunks_from_text(table):
        assert c["token_count"] <= CHUNK_TOKENS
        assert table[c["start_char"]:c["end_char"]].strip() == c["content"]


def test_blank_lines_do_not_shift_offsets():
    text = "First paragraph here.\n\nSecond paragraph here.\n\nThird one."
    assert [text[a:b] for a, b in _blocks(text)] == [
        "First paragraph here.", "Second paragraph here.", "Third one."]


# --------------------------------------------------------------------------
# citations name the location in the terms each format uses
# --------------------------------------------------------------------------

def test_pdf_chunk_is_cited_by_page():
    assert _locator({"format": "pdf", "page": 5, "end_page": 5}) == "p.5"
    assert _locator({"format": "pdf", "page": 5, "end_page": 6}) == "p.5-6"


def test_us_filing_chunk_is_cited_by_item():
    assert _locator({"format": "html", "section_key": "item_7a", "start_char": 1}) == "Item 7A"
    assert _locator({"format": "html", "section_key": "item_1", "start_char": 1}) == "Item 1"


def test_us_chunk_outside_any_item_falls_back_to_the_offset():
    """Cover page and table of contents sit before Item 1."""
    assert _locator({"format": "html", "section_key": None, "start_char": 412}) == "@412"
