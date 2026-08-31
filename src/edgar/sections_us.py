"""Module 14 — Item-anchored segmentation for US filings (R3).

The heuristic segmenter in src/sections.py guesses at headings because HK annual
reports have no fixed structure. A 10-K does: Regulation S-K fixes the Item
numbers, their order, and their titles. So this segmenter does not guess — it
anchors, and it fails loudly when the anchors are not where the form says.

Three problems any real 10-K poses, and how each is handled:

1. Every Item appears at least twice — once in the table of contents, once as
   the section itself. The TOC is found as the densest cluster of Item matches
   in the document and excluded, rather than assumed to be "the first ones".

2. Prose cross-references ("see Item 8") look like headings. A match counts only
   when the text after the number matches the Item's own title from the form.

3. Filers vary the wording ("Exhibit and Financial Statement Schedules" vs
   "Exhibits, Financial Statement Schedules"), so titles are matched on a
   prefix keyword rather than in full.

Output carries BOTH keys: `section_key` ('item_1a') for Item-precise retrieval,
and the legacy `section_type` ('Risk Factors') so rag_chat, alerts and app keep
working unchanged across the HK and US corpora.

CLI:  python -m src.edgar.sections_us 0000950170-24-087843
"""
import re
from dataclasses import dataclass

# Item -> (accepted title prefixes, legacy section_type)
ITEMS: dict[str, tuple[tuple[str, ...], str]] = {
    "1":   (("business",), "Business"),
    "1A":  (("risk factor",), "Risk Factors"),
    "1B":  (("unresolved staff",), "Other"),
    "1C":  (("cybersecurity",), "Cybersecurity"),
    "2":   (("propert",), "Properties"),
    "3":   (("legal proceeding",), "Legal Proceedings"),
    "4":   (("mine safety",), "Other"),
    "5":   (("market for",), "Market for Common Equity"),
    "6":   (("[reserved]", "reserved", "selected financial"), "Other"),
    "7":   (("management's discussion", "management’s discussion"), "MD&A"),
    "7A":  (("quantitative and qualitative",), "Market Risk"),
    "8":   (("financial statements",), "Financial Statements"),
    "9":   (("changes in and disagreements",), "Other"),
    "9A":  (("controls and procedures",), "Controls and Procedures"),
    "9B":  (("other information",), "Other"),
    "9C":  (("disclosure regarding foreign",), "Other"),
    "10":  (("directors,", "directors and", "directors, executive"), "Corporate Governance"),
    "11":  (("executive compensation",), "Corporate Governance"),
    "12":  (("security ownership",), "Corporate Governance"),
    "13":  (("certain relationships",), "Corporate Governance"),
    "14":  (("principal account",), "Corporate Governance"),
    "15":  (("exhibit",), "Exhibits"),
    "16":  (("form 10-k summary",), "Other"),
}

ORDER = list(ITEMS)
RANK = {item: i for i, item in enumerate(ORDER)}

# Items a real 10-K must contain. Their absence means the anchors are wrong,
# which is a build error rather than a document quirk.
REQUIRED = ("1", "1A", "7", "7A", "8")

ITEM_RE = re.compile(r"(?im)^[ \t]*item[ \t ]*(\d{1,2}[ABC]?)[ \t]*[.:\-–—]?[ \t]*(.{0,80})")

TOC_MAX_GAP = 300           # consecutive TOC entries sit a line or two apart
TOC_MIN_ITEMS = 8
TOC_MAX_START_FRAC = 0.25   # a table of contents is near the front
TOC_MAX_SPAN_FRAC = 0.20    # and short: it lists sections, it is not one
MIN_SECTION_CHARS = 200     # shorter "sections" are cross-references, not sections


class SegmentationError(RuntimeError):
    """The filing did not segment into the Items the form requires."""


@dataclass(frozen=True)
class Section:
    section_key: str        # 'item_1a'
    item: str               # '1A'
    section_type: str       # legacy vocabulary, shared with the HK segmenter
    title: str
    start_char: int
    end_char: int

    @property
    def length(self) -> int:
        return self.end_char - self.start_char


def _candidates(text: str) -> list[tuple[int, str, str]]:
    """(offset, item, title) for every line that reads like an Item heading."""
    out = []
    for m in ITEM_RE.finditer(text):
        item = m.group(1).upper()
        if item not in ITEMS:
            continue
        title = m.group(2).strip()
        prefixes, _ = ITEMS[item]
        if title.lower().startswith(prefixes):
            out.append((m.start(), item, title))
    return out


def _toc_span(candidates: list[tuple[int, str, str]], doc_len: int) -> tuple[int, int] | None:
    """Locate the table of contents, if its entries were matched as headings.

    Four things are true of a real table of contents and of nothing else in a
    10-K: its entries sit a line or two apart, it lists Item 1, it lists most of
    the form, and it is short and near the front.

    Each test earns its place. Without the Item 1 test, MSFT's Part III block —
    9B, 9C and 10 through 15 within a few hundred characters of each other —
    reads as a table of contents and its Items are lost. Without the span tests,
    a filing whose Items are all short (Part III incorporated by reference) has
    its entire body swallowed as one long "table of contents".
    """
    best = None
    for i in range(len(candidates)):
        j = i
        while (j + 1 < len(candidates)
               and candidates[j + 1][0] - candidates[j][0] < TOC_MAX_GAP
               # a table of contents ascends; the body restarting at Item 1 is a
               # rank drop, and that is where the contents block ends
               and RANK[candidates[j + 1][1]] > RANK[candidates[j][1]]):
            j += 1
        window = candidates[i:j + 1]
        items = {c[1] for c in window}
        start, end = window[0][0], window[-1][0]
        if ("1" in items
                and len(items) >= TOC_MIN_ITEMS
                and start <= doc_len * TOC_MAX_START_FRAC
                and (end - start) <= doc_len * TOC_MAX_SPAN_FRAC):
            if best is None or len(items) > best[2]:
                best = (start, end, len(items))
    return (best[0], best[1]) if best else None


def segment_text(text: str) -> list[Section]:
    """Anchor a 10-K on its Item headings. Raises if the anchors are unusable."""
    candidates = _candidates(text)
    if not candidates:
        raise SegmentationError("no Item headings found — is this a 10-K?")

    toc = _toc_span(candidates, len(text))
    body = [c for c in candidates if not (toc and toc[0] <= c[0] <= toc[1])]
    if not body:
        raise SegmentationError("every Item heading fell inside the table of contents")

    # First occurrence of each Item, in form order; later repeats (exhibit
    # indexes, signature pages) cannot move an anchor backwards.
    anchors: list[tuple[int, str, str]] = []
    for offset, item, title in body:
        if anchors and RANK[item] <= RANK[anchors[-1][1]]:
            continue
        anchors.append((offset, item, title))

    sections = []
    for i, (offset, item, title) in enumerate(anchors):
        end = anchors[i + 1][0] if i + 1 < len(anchors) else len(text)
        _, section_type = ITEMS[item]
        sections.append(Section(section_key=f"item_{item.lower()}", item=item,
                                section_type=section_type, title=title,
                                start_char=offset, end_char=end))

    _assert_usable(sections)
    return sections


def _assert_usable(sections: list[Section]) -> None:
    found = {s.item for s in sections}
    missing = [i for i in REQUIRED if i not in found]
    if missing:
        raise SegmentationError(
            f"required Items missing after segmentation: {missing}. "
            f"Found: {sorted(found, key=lambda i: RANK[i])}")

    offsets = [s.start_char for s in sections]
    if offsets != sorted(offsets):
        raise SegmentationError("Item anchors are not in document order")

    thin = [s.section_key for s in sections
            if s.item in REQUIRED and s.length < MIN_SECTION_CHARS]
    if thin:
        raise SegmentationError(f"required Items resolved to near-empty spans: {thin}")


def segment_filing(accession: str) -> tuple[str, list[Section]]:
    from src.edgar.html_text import cached_filing_text

    text = cached_filing_text(accession)
    return text, segment_text(text)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("accession")
    a = ap.parse_args()

    text, sections = segment_filing(a.accession)
    print(f"{len(text):,} characters -> {len(sections)} Item sections\n")
    for s in sections:
        print(f"  {s.section_key:<9} {s.start_char:>7}-{s.end_char:<7} "
              f"{s.length:>7,} chars  {s.section_type:<26} {s.title[:44]}")
