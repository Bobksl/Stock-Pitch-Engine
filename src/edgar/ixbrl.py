"""Module 7 — inline-XBRL instance parser (R1, the load-bearing module).

The post-2019 10-K primary document IS the XBRL instance: every reported figure
is wrapped in <ix:nonFraction> pointing at an <xbrli:context> that carries the
period and — crucially — the dimensions. Those dimensions are what SEC's
companyfacts API drops, and they are the only source of segment revenue and
segment operating profit (framework 1.3, 1.4h, 2.4).

Parsing rules that are easy to get wrong, and are each pinned by a test:

- scale is a power of ten applied to the displayed text: '64,773' scale='6'
  is 64,773,000,000, not 64,773.
- sign="-" is PART OF THE VALUE, not a display instruction. The displayed text
  is the absolute value. (Display-only negation is a different mechanism: the
  negatedLabel role in the label linkbase, which this parser never applies.)
- an instant context has no start date; a duration has both. Storing an instant
  as a zero-length duration silently breaks period matching later.
- ix:exclude subtrees are inside a fact element but not part of its value.
- Decimal throughout. A float here becomes a wrong target price six modules on.

Namespace prefixes vary between filers (xbrli: vs default), so traversal matches
on local names only.

CLI:  python -m src.edgar.ixbrl 0000950170-24-087843 --tag Revenues
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from lxml import etree

XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"


class IxbrlError(RuntimeError):
    """The instance could not be parsed, or contradicts itself."""


@dataclass(frozen=True)
class XbrlFact:
    taxonomy: str                 # 'us-gaap' | 'dei' | 'srt' | company prefix
    tag: str                      # 'RevenueFromContractWithCustomerExcludingAssessedTax'
    value: Decimal
    unit: str                     # 'USD' | 'shares' | 'USD/shares' | 'pure'
    period_type: str              # 'duration' | 'instant'
    period_start: date | None
    period_end: date
    segments: dict[str, str]      # {axis_qname: member_qname}; {} = consolidated
    context_id: str
    decimals: int | None

    @property
    def qname(self) -> str:
        return f"{self.taxonomy}:{self.tag}"


def _localname(el) -> str:
    tag = el.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _split_qname(qname: str) -> tuple[str, str]:
    prefix, _, local = qname.partition(":")
    return (prefix, local) if local else ("", prefix)


def _parse_contexts(root) -> dict[str, dict]:
    contexts: dict[str, dict] = {}
    for el in root.iter():
        if _localname(el) != "context":
            continue
        ctx_id = el.get("id")
        period_type, start, end = None, None, None
        segments: dict[str, str] = {}
        for sub in el.iter():
            name = _localname(sub)
            if name == "instant":
                period_type, end = "instant", date.fromisoformat(sub.text.strip())
            elif name == "startDate":
                start = date.fromisoformat(sub.text.strip())
            elif name == "endDate":
                period_type, end = "duration", date.fromisoformat(sub.text.strip())
            elif name == "explicitMember":
                segments[sub.get("dimension")] = (sub.text or "").strip()
            elif name == "typedMember":
                # Rare outside financials; recorded so it can never be mistaken
                # for a consolidated fact.
                inner = "".join(x.strip() for x in sub.itertext())
                segments[sub.get("dimension")] = f"(typed){inner}"
        if ctx_id and end and period_type:
            contexts[ctx_id] = {"period_type": period_type, "start": start,
                                "end": end, "segments": segments}
    return contexts


def _parse_units(root) -> dict[str, str]:
    """unit id -> 'USD' | 'shares' | 'USD/shares' | 'pure'."""
    units: dict[str, str] = {}
    for el in root.iter():
        if _localname(el) != "unit":
            continue
        numerators, denominators, plain = [], [], []
        for sub in el.iter():
            if _localname(sub) != "measure":
                continue
            measure = _split_qname((sub.text or "").strip())[1]
            parent = _localname(sub.getparent())
            if parent == "unitNumerator":
                numerators.append(measure)
            elif parent == "unitDenominator":
                denominators.append(measure)
            else:
                plain.append(measure)
        if denominators:
            units[el.get("id")] = f"{'*'.join(numerators)}/{'*'.join(denominators)}"
        elif plain:
            units[el.get("id")] = "*".join(plain)
    return units


def _fact_text(el) -> str:
    """Text of a fact element, minus any ix:exclude subtrees."""
    parts = [el.text or ""]
    for child in el:
        if _localname(child) != "exclude":
            parts.append("".join(child.itertext()))
        parts.append(child.tail or "")
    return "".join(parts)


_WORDS = {
    "no": 0, "none": 0, "nil": 0, "zero": 0, "one": 1, "two": 2, "three": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 10**6, "billion": 10**9}


def _words_to_number(text: str) -> Decimal:
    """SEC's ixt-sec:numwordsen rule — 'No' -> 0, 'twenty-one' -> 21.

    Filings use this for small counts and for 'No'/'None' on impairment lines.
    An unrecognised word raises rather than defaulting to zero: a silent zero on
    a goodwill impairment line is exactly the kind of plausible wrong number
    this pipeline exists to prevent.
    """
    total, current = 0, 0
    for word in text.lower().replace("-", " ").replace(",", " ").split():
        if word == "and":
            continue
        if word in _WORDS:
            current += _WORDS[word]
        elif word in _SCALES:
            scale = _SCALES[word]
            current = max(current, 1) * scale
            if scale >= 1000:
                total, current = total + current, 0
        else:
            raise IxbrlError(f"ixt-sec:numwordsen: unrecognised word {word!r} in {text!r}")
    return Decimal(total + current)


def parse_number(text: str, fmt: str | None = None) -> Decimal:
    """Displayed text -> Decimal, honouring the ix transformation rule."""
    rule = (fmt or "").rsplit(":", 1)[-1]
    if rule.startswith("fixed-"):
        return {"fixed-zero": Decimal(0), "fixed-one": Decimal(1),
                "fixed-none": Decimal(0)}.get(rule, Decimal(0))
    if rule == "numwordsen":
        return _words_to_number(text.strip())

    s = "".join(text.split())
    for junk in (" ", "$", "€", "£", "%"):
        s = s.replace(junk, "")
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "comma-decimal" in rule:              # 1.646,50 -> 1646.50
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    if not s or s == "-":
        return Decimal(0)
    value = Decimal(s)
    return -value if negative else value


def parse_instance(raw: bytes) -> tuple[list[XbrlFact], dict[str, str]]:
    """Parse an inline-XBRL document. Returns (numeric facts, dei metadata)."""
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    root = etree.fromstring(raw, parser=parser)
    if root is None:
        raise IxbrlError("document could not be parsed as XML")

    contexts = _parse_contexts(root)
    units = _parse_units(root)
    if not contexts:
        raise IxbrlError("no xbrli:context elements — not an inline-XBRL instance")

    facts: list[XbrlFact] = []
    dei: dict[str, str] = {}

    for el in root.iter():
        local = _localname(el)
        if local not in ("nonFraction", "nonNumeric"):
            continue
        name = el.get("name")
        if not name:
            continue
        taxonomy, tag = _split_qname(name)

        if local == "nonNumeric":
            if taxonomy == "dei":
                dei.setdefault(tag, _fact_text(el).strip())
            continue

        if el.get(XSI_NIL) == "true":
            continue
        ctx = contexts.get(el.get("contextRef", ""))
        if ctx is None:
            raise IxbrlError(f"fact {name} references unknown context {el.get('contextRef')!r}")

        value = parse_number(_fact_text(el), el.get("format"))
        scale = int(el.get("scale") or 0)
        if scale:
            value *= Decimal(10) ** scale
        if el.get("sign") == "-":
            value = -value

        decimals = el.get("decimals")
        facts.append(XbrlFact(
            taxonomy=taxonomy, tag=tag, value=value,
            unit=units.get(el.get("unitRef", ""), ""),
            period_type=ctx["period_type"], period_start=ctx["start"],
            period_end=ctx["end"], segments=dict(ctx["segments"]),
            context_id=el.get("contextRef"),
            decimals=None if decimals in (None, "INF") else int(decimals),
        ))

    return facts, dei


def _round_to(value: Decimal, decimals: int | None) -> Decimal:
    """Round to the precision a `decimals` attribute claims. None = exact."""
    if decimals is None:
        return value
    step = Decimal(10) ** (-decimals)
    return (value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step


def _coarser(d1: int | None, d2: int | None) -> int | None:
    """The less precise of two `decimals` values (None = infinitely precise)."""
    if d1 is None:
        return d2
    if d2 is None:
        return d1
    return min(d1, d2)


def dedupe(facts: list[XbrlFact]) -> list[XbrlFact]:
    """Collapse duplicate facts, keeping the most precise value.

    The same figure is legitimately tagged more than once at different
    precision — MSFT's FY2024 goodwill appears as 50,969 million in the balance
    sheet and as $51.0 billion in the notes. XBRL calls these consistent
    duplicates when they agree once both are rounded to the coarser precision.

    Disagreement beyond that is NOT a data quirk: it means the parser mis-scaled
    or mis-signed something, so it raises.
    """
    best: dict[tuple, XbrlFact] = {}
    for f in facts:
        key = (f.qname, f.unit, f.context_id)
        prior = best.get(key)
        if prior is None:
            best[key] = f
            continue
        d = _coarser(prior.decimals, f.decimals)
        if _round_to(prior.value, d) != _round_to(f.value, d):
            raise IxbrlError(
                f"{f.qname} in context {f.context_id} is an inconsistent duplicate: "
                f"{prior.value} (decimals={prior.decimals}) vs "
                f"{f.value} (decimals={f.decimals})")
        # keep the more precise of the two
        if prior.decimals is not None and (f.decimals is None or f.decimals > prior.decimals):
            best[key] = f
    return list(best.values())


def consolidated(facts: list[XbrlFact]) -> list[XbrlFact]:
    """Facts with no dimensions — the subset companyfacts also publishes."""
    return [f for f in facts if not f.segments]


def parse_cached_filing(accession: str) -> tuple[list[XbrlFact], dict[str, str]]:
    """Parse a filing already fetched by src.edgar.fetch."""
    from src.db import get_conn

    with get_conn() as conn:
        row = conn.execute(
            "SELECT cached_path FROM filings WHERE accession = %s", (accession,)).fetchone()
    if not row:
        raise IxbrlError(f"accession {accession} has not been fetched")
    facts, dei = parse_instance(open(row[0], "rb").read())
    return dedupe(facts), dei


if __name__ == "__main__":
    import argparse
    from collections import Counter

    ap = argparse.ArgumentParser()
    ap.add_argument("accession")
    ap.add_argument("--tag", help="show every fact for this tag")
    a = ap.parse_args()

    facts, dei = parse_cached_filing(a.accession)
    dims = Counter(len(f.segments) for f in facts)
    print(f"{len(facts):,} numeric facts   consolidated={dims[0]:,}  dimensional={len(facts)-dims[0]:,}")
    print(f"dei: FY{dei.get('DocumentFiscalYearFocus')} {dei.get('DocumentFiscalPeriodFocus')} "
          f"{dei.get('DocumentType')} period_end={dei.get('DocumentPeriodEndDate')}")

    if a.tag:
        for f in sorted((f for f in facts if f.tag == a.tag),
                        key=lambda f: (f.period_end, len(f.segments))):
            seg = " · ".join(f"{k.split(':')[-1]}={v.split(':')[-1]}" for k, v in f.segments.items())
            start = str(f.period_start) if f.period_start else "(instant)"
            print(f"  {start:>10} -> {f.period_end}  {f.value:>20,}  {f.unit:<10} {seg}")
