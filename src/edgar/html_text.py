"""Module 13 — filing HTML -> plain text with stable character offsets.

The Item segmenter and the chunker both address the filing by character offset,
so this function must be deterministic: the same bytes always produce the same
string, and therefore the same offsets. Normalisation happens once, here, rather
than being re-applied downstream where it would shift every anchor.

Two things are dropped rather than rendered:
  ix:header / ix:hidden  — the XBRL resource block: contexts, units and hidden
                           facts. It is machine data, already parsed by ixbrl.py,
                           and rendering it would put thousands of tokens of
                           noise in front of Item 1.
  script / style         — never prose.

CLI:  python -m src.edgar.html_text 0000950170-24-087843 --head 40
"""
import re

from lxml import etree

# Elements whose end implies a line break in the rendered text.
BLOCK_TAGS = frozenset({
    "p", "div", "br", "tr", "table", "li", "ul", "ol", "td", "th",
    "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "hr",
})
DROP_TAGS = frozenset({"script", "style", "header", "hidden", "resources"})

_SPACES = re.compile(r"[ \t   ]+")
_BLANKS = re.compile(r"\n{3,}")
_TRAILING = re.compile(r"[ \t]+\n")


def _localname(el) -> str:
    tag = el.tag
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def to_text(raw: bytes) -> str:
    """Render filing HTML to normalised plain text."""
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    root = etree.fromstring(raw, parser=parser)
    if root is None:
        raise ValueError("document could not be parsed")

    out: list[str] = []
    skipping = None                      # the element whose subtree we are dropping

    # Iterative walk: these documents nest far deeper than the recursion limit.
    for event, el in etree.iterwalk(root, events=("start", "end")):
        name = _localname(el)
        if event == "start":
            if skipping is not None:
                continue
            if name in DROP_TAGS:
                skipping = el
                continue
            if name == "br":
                out.append("\n")
            if el.text:
                out.append(el.text)
        else:
            if skipping is not None:
                if skipping is not el:
                    continue
                skipping = None          # subtree finished; its tail still counts
            elif name in BLOCK_TAGS:
                out.append("\n")
            if el.tail:
                out.append(el.tail)

    text = "".join(out)
    text = text.replace("­", "")                       # soft hyphens
    text = _SPACES.sub(" ", text)
    text = _TRAILING.sub("\n", text)
    return _BLANKS.sub("\n\n", text).strip()


def cached_filing_text(accession: str) -> str:
    from src.db import get_conn

    with get_conn() as conn:
        row = conn.execute(
            "SELECT cached_path FROM filings WHERE accession = %s", (accession,)).fetchone()
    if not row:
        raise ValueError(f"accession {accession} has not been fetched")
    return to_text(open(row[0], "rb").read())


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("accession")
    ap.add_argument("--head", type=int, default=30, help="lines to show")
    a = ap.parse_args()

    text = cached_filing_text(a.accession)
    print(f"{len(text):,} characters, {text.count(chr(10)) + 1:,} lines\n")
    for line in text.split("\n")[:a.head]:
        print(f"  {line[:110]}")
