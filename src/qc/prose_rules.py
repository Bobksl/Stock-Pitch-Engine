"""P3.3 — the framework 1.6 rules, evaluated against a draft.

Phase 3 is the first phase that generates prose, and these are the first rules
about what a draft *says* rather than about what a figure *is*. Each function
answers one rule and returns a `Finding` or `None`; whether it blocks is
`FindingSet`'s business and whether it could ever be excepted was settled by
its class in `rules.py`. Same shape as `valuation_rules.py`.

All three are Class A. The deciding test is the one spec v1.3 added to 6.5: no
reason in the closed exception vocabulary -- `long_duration_asset`,
`pre_revenue`, `regulated_concession` -- could excuse a marketing adjective, an
unsupported pricing-power claim, or a segment mix shown revenue-only. A Class B
here would be an exception path that can never be used honestly.

What each rule reads
--------------------
`banned_language` reads the masked draft, so a member qname or a cell name is
never mistaken for marketing copy -- `claims.mask` already blanks the citation
index, the model-cell block, fenced code and inline spans, and it blanks them
to spaces so every offset still indexes the original text.

`unsupported_qualitative_claim` reads sentences and the claim list, and asks
whether a sentence making a pricing-power or operating-leverage claim contains
a figure. 1.4f is unambiguous: no number, no claim.

`segment_profit_missing` reads the **citation index**, not the rendered table.
Anchor-based like every other resolution here: the draft declares which fact it
stands on and the gate reads that, rather than inferring intent from Markdown
column headers. It also means a segment figure smuggled into prose rather than
a table is caught on the same footing.
"""
import re
from datetime import date

from src.qc.anchors import KIND_FACT, Anchor
from src.qc.claims import NumericClaim, mask
from src.qc.findings import Finding
from src.qc.rules import rule

#: Framework 6.1, verbatim. Marketing adjectives lifted from filings.
BANNED_PHRASES: tuple[str, ...] = (
    "AI-powered", "leading", "world-class", "best-in-class", "end-to-end",
    "empowers", "revolutionary", "seamless", "innovative", "cutting-edge",
    "transformative", "synergistic", "robust ecosystem",
)

#: A hyphen in a filing's copy is a space in a draft's, and neither is a
#: signal. `AI-powered`, `AI powered` and `AI Powered` are one phrase.
_BANNED_RE = re.compile(
    r"\b(?:" + "|".join(p.replace("-", r"[-\s]").replace(" ", r"[-\s]")
                        for p in BANNED_PHRASES) + r")\b", re.I)

#: Claims 1.4f and 1.4g require a number to make at all. Deliberately a narrow,
#: explicit list of the two claim families 1.6 names, not a general "does this
#: sound like a claim" heuristic -- the same discipline as `claims.py`'s mask
#: list, and for the same reason: a wrong hit is one loud edit, and a rule
#: nobody can predict gets worked around.
CLAIM_PHRASES: tuple[str, ...] = (
    "pricing power", "price increase", "price increases", "raise prices",
    "raised prices", "pass through cost", "passed through cost",
    "switching cost", "switching costs",
    "operating leverage", "incremental margin", "incremental margins",
)

_CLAIM_RE = re.compile(
    r"\b(?:" + "|".join(p.replace(" ", r"\s+") for p in CLAIM_PHRASES) + r")\b",
    re.I)

#: A sentence ends at . ! or ? followed by whitespace, or at a blank line.
#: Abbreviations are not a problem here: the text this runs over has already
#: had accession numbers, ISO dates and section references blanked.
_SENTENCE_RE = re.compile(r"[^.!?\n]*(?:[.!?]+|\n\s*\n|$)")

SEGMENT_AXIS = "us-gaap:StatementBusinessSegmentsAxis"


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def banned_language_finding(md: str) -> Finding | None:
    """6.1 — marketing adjectives lifted from the filing.

    No carve-out for quotation. 6.2's carve-out escalates a promotionally
    described *revenue stream* for evaluation; it does not license reproducing
    the adjective in our own prose, and a quotation exemption would be a bypass
    anybody could reach ("management calls it world-class").
    """
    masked = mask(md)
    hits = [(m.start(), m.group(0)) for m in _BANNED_RE.finditer(masked)]
    if not hits:
        return None

    where = ", ".join(f"line {_line_of(md, pos)}: {text!r}" for pos, text in hits)
    return Finding(
        rule=rule("banned_language"),
        detail=(f"{len(hits)} banned phrase(s) from the 6.1 list are in the "
                f"draft prose - {where}. Filings are promotional by "
                f"construction (P7); the adjective carries no information the "
                f"figures do not."))


def _sentences(md: str) -> list[tuple[int, str]]:
    """(offset, text) for each sentence of the masked draft."""
    masked = mask(md)
    out = []
    for m in _SENTENCE_RE.finditer(masked):
        text = m.group(0)
        if text.strip():
            out.append((m.start(), text))
    return out


def unsupported_claim_finding(md: str,
                              claims: list[NumericClaim]) -> Finding | None:
    """1.4f / 1.6 — a pricing-power or operating-leverage claim with no number.

    The number has to be in the same sentence. A figure two sentences away is
    proximity, not support, and accepting it would make the rule satisfiable by
    writing the claim next to any statistic at all.
    """
    offending = []
    for start, text in _sentences(md):
        hit = _CLAIM_RE.search(text)
        if not hit:
            continue
        end = start + len(text)
        if any(start <= c.span[0] < end for c in claims):
            continue
        offending.append((start, hit.group(0), " ".join(text.split())))

    if not offending:
        return None

    where = "; ".join(
        f"line {_line_of(md, start)} claims {phrase!r} in {sentence!r}"
        for start, phrase, sentence in offending)
    return Finding(
        rule=rule("unsupported_qualitative_claim"),
        detail=(f"{len(offending)} claim(s) carry no supporting figure in the "
                f"sentence that makes them - {where}. Framework 1.4f: no "
                f"number, no claim."))


def _segment_facts(index: dict[str, Anchor]) -> list[tuple[Anchor, date, str]]:
    out = []
    for anchor in index.values():
        if anchor.kind != KIND_FACT:
            continue
        member = anchor.segments.get(SEGMENT_AXIS)
        if member and anchor.period_end:
            out.append((anchor, anchor.period_end, member))
    return out


def segment_profit_finding(index: dict[str, Anchor]) -> Finding | None:
    """1.3 / 1.6 — segment revenue shown without segment operating profit.

    Scoped to the LATEST cited period, which is where 1.5's mix exhibit is
    struck and where the failure this rule guards against actually lives:
    showing the current mix revenue-only is what hides a small segment carrying
    the profit. A prior-year segment revenue quoted for a comparison is 6.3's
    business, and 6.3 already requires its current-year comparative.
    """
    facts = _segment_facts(index)
    if not facts:
        return None

    latest = max(period for _, period, _ in facts)
    by_member: dict[str, set[str]] = {}
    for anchor, period, member in facts:
        if period == latest:
            by_member.setdefault(member, set()).add(anchor.concept or "")

    missing = sorted(m for m, concepts in by_member.items()
                     if "revenue" in concepts and "operating_income" not in concepts)
    if not missing:
        return None

    from src.facts.api import pretty_member
    names = ", ".join(pretty_member(m) for m in missing)
    return Finding(
        rule=rule("segment_profit_missing"),
        detail=(f"segment revenue is cited for {names} at {latest} with no "
                f"segment operating profit. Framework 1.3 makes segment profit "
                f"required, not optional: a revenue-only mix hides whether the "
                f"largest segment is the one earning the money."))


def prose_findings(md: str, claims: list[NumericClaim],
                   index: dict[str, Anchor]) -> list[Finding]:
    """Every 1.6 rule, over one draft."""
    candidates = (banned_language_finding(md),
                  unsupported_claim_finding(md, claims),
                  segment_profit_finding(index))
    return [f for f in candidates if f is not None]
