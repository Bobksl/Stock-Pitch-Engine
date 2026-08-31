"""P1.1 — every numeric claim in a Markdown draft, with its character span.

Framework 6.4: "No free-floating figures." Before a figure can be checked it has
to be found, and found precisely enough that a failure names a position in the
draft rather than a page of prose.

Two design commitments worth stating, because both were argued:

1. **Bias toward over-extraction.** A numeral this module misses is a silent
   hole in the QC gate — the one failure mode the phase exists to prevent. A
   numeral it wrongly extracts is a loud failure the author fixes in one edit.
   Non-financial numerals are therefore excluded by a narrow, explicit, tested
   mask list (years, ISO dates, Item / form / section references), never by a
   general "does this look financial" heuristic.

2. **Precision as written is preserved.** The numeral is parsed with Decimal
   from its source string, so `245.10` carries a tighter tolerance than `245.1`
   (see tolerance.py). Parsing through float would destroy exactly the
   information the tolerance rule is derived from.

Scale resolution, in order: a scale word attached to the numeral, else the unit
declared in the Markdown table column header, else unit scale. A currency or
share figure sitting in a table whose header declares no unit is `undeclared`
and fails — a bare column of "137,791" that means billions is the corruption
class no value comparison can catch on its own.
"""
import re
from dataclasses import dataclass
from decimal import Decimal

# ---------------------------------------------------------------------------
# Scales. Values are exact Decimals; percent-like units are scales too, which
# is what lets "23.5%" and "50 bps" compare against a stored ratio directly.
# ---------------------------------------------------------------------------

SCALE_WORDS: dict[str, Decimal] = {
    "trillion": Decimal("1e12"), "tn": Decimal("1e12"),
    "billion": Decimal("1e9"), "bn": Decimal("1e9"),
    "million": Decimal("1e6"), "mn": Decimal("1e6"),
    "thousand": Decimal("1e3"),
}
# Suffix units that also set the kind.
PERCENT_SCALE = Decimal("0.01")
BPS_SCALE = Decimal("0.0001")

CURRENCIES = {"$": "USD", "US$": "USD", "USD": "USD", "HK$": "HKD", "HKD": "HKD",
              "NT$": "TWD", "TWD": "TWD", "€": "EUR", "£": "GBP", "¥": "JPY"}

# Currency-attached short scales ($5bn, $5m). Only recognised WITH a currency
# symbol: a bare "5 m" is far more likely to be prose than five million.
SHORT_SCALES = {"b": Decimal("1e9"), "m": Decimal("1e6"), "k": Decimal("1e3"),
                "t": Decimal("1e12")}

KIND_CURRENCY, KIND_PERCENT, KIND_MULTIPLE = "currency", "percent", "multiple"
KIND_SHARES, KIND_BARE = "shares", "bare"

SCALE_INLINE, SCALE_HEADER, SCALE_IMPLICIT, SCALE_UNDECLARED = (
    "inline", "header", "implicit_unit", "undeclared")


@dataclass(frozen=True)
class NumericClaim:
    """A figure as the draft writes it, plus where it is and what it means."""

    text: str                       # exact source slice, e.g. "$245.1 billion"
    span: tuple[int, int]           # char offsets into the raw draft
    line: int                       # 1-based, for human-readable failures
    digits: Decimal                 # as written; trailing zeros significant
    scale: Decimal
    scale_source: str
    kind: str
    unit: str | None                # 'USD' | 'shares' | 'pure' | None
    anchor: str | None = None       # citation-index key, e.g. 'F7'
    column: str | None = None       # table header this cell sat under

    @property
    def value(self) -> Decimal:
        """The figure in canonical units: USD, shares, or a bare ratio."""
        return self.digits * self.scale

    @property
    def ulp(self) -> Decimal:
        """One unit in the last place *as written*, scaled.

        `245.1` -> 1e8 at billion scale; `245.10` -> 1e7. This is the whole
        input to the tolerance rule.
        """
        exponent = self.digits.as_tuple().exponent
        return Decimal(1).scaleb(exponent) * self.scale

    @property
    def scale_declared(self) -> bool:
        return self.scale_source != SCALE_UNDECLARED


# ---------------------------------------------------------------------------
# Masking. Regions and tokens that must never yield a claim.
#
# Masking replaces characters with spaces rather than deleting them, so every
# span this module reports still indexes the ORIGINAL draft text.
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[ \t]*$",
                       re.MULTILINE | re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_LINK_TARGET_RE = re.compile(r"\]\([^)]*\)")
_ANCHOR_RE = re.compile(r"\[\^([A-Za-z][A-Za-z0-9_.-]*)\]")

# Non-financial numerals. Each entry is a real token seen in these drafts.
#
# Order matters: the accession number must be masked before the ISO-date
# pattern, which otherwise matches "3125-26-32" inside 0001193125-26-323660 and
# leaves two digit fragments behind that then read as claims. Every pattern that
# can sit inside a longer digit run is also guarded against digit neighbours.
_MASK_TOKENS = [
    re.compile(r"(?<!\d)\d{10}-\d{2}-\d{6}(?!\d)"),      # accession number
    re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)"),       # ISO date
    re.compile(r"\bFY\s?\d{2,4}\b", re.I),               # FY2026, FY 26
    re.compile(r"\bQ[1-4]\s?(?:FY)?\s?\d{0,4}\b", re.I),  # Q3, Q3 FY2026
    re.compile(r"\bItems?\s+\d+[A-Za-z]?\b", re.I),      # Item 1A
    re.compile(r"\bSections?\s+\d+(?:\.\d+)*\b", re.I),  # Section 3, Section 2.5
    re.compile(r"^#{1,6}[ \t]*\d+(?:\.\d+)*\.?", re.M),  # numbered heading
    re.compile(r"^[ \t]*\d{1,3}[.)][ \t]", re.M),        # ordered-list marker
    re.compile(r"(?<!\d)\d{1,2}-[KQ]\b"),                # 10-K, 10-Q
    re.compile(r"§\s?\d+(?:\.\d+)*[a-z]?"),              # §4.6, §2.5i
    re.compile(r"\b[A-Z]\d+(?:\.\d+)*\b"),               # C10, P1.2, R5
    re.compile(r"\bASC\s+\d+\b", re.I),                  # ASC 280
    re.compile(r"\bCIK\s*:?\s*\d+\b", re.I),
]

# Prose dates: "30 June 2026", "June 30, 2026", "Jun. 2026". Deliberately
# CASE-SENSITIVE -- a month is a proper noun in a date, and matching "may"
# case-insensitively would swallow the figure in "may fall 30%".
_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|"
           "Oct|Nov|Dec")
_MASK_TOKENS.append(re.compile(
    rf"\b(?:\d{{1,2}}\s+)?(?:{_MONTHS})\.?(?:\s+\d{{1,2}})?,?(?:\s+\d{{4}})?\b"))

_CITATION_INDEX_RE = re.compile(
    r"^#{1,6}\s*Citation index\s*$.*?(?=^#{1,6}\s|\Z)",
    re.MULTILINE | re.DOTALL | re.I)


def _blank(text: str, start: int, end: int) -> str:
    """Replace a slice with spaces, preserving newlines so line numbers hold."""
    region = "".join("\n" if ch == "\n" else " " for ch in text[start:end])
    return text[:start] + region + text[end:]


def mask(md: str) -> str:
    """The draft with every no-claim region blanked, offsets unchanged."""
    out = md
    for pattern in (_FENCE_RE, _CITATION_INDEX_RE, _INLINE_CODE_RE,
                    _LINK_TARGET_RE, _ANCHOR_RE, *_MASK_TOKENS):
        for m in list(pattern.finditer(out)):
            out = _blank(out, m.start(), m.end())
    return out


# ---------------------------------------------------------------------------
# Markdown tables: the column header is where scale usually lives.
# ---------------------------------------------------------------------------

_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
_HEADER_UNIT_RE = re.compile(
    r"[(\[]?\s*(?:(US\$|HK\$|NT\$|USD|HKD|TWD|\$|€|£)\s*)?"
    r"(trillion|billion|million|thousand|bn|mn|tn|m|b|k)\s*[)\]]?\s*$", re.I)
_HEADER_PERCENT_RE = re.compile(r"[(\[]?\s*(%|percent|bps|pp)\s*[)\]]?\s*$", re.I)


def _cells(line: str) -> list[tuple[int, int]]:
    """(start, end) of each pipe-delimited cell, as offsets within `line`.

    A leading or trailing pipe does not open an empty cell, so the indices line
    up with the header row's cells whether or not the table is fully fenced.
    """
    pipes = [m.start() for m in re.finditer(r"\|", line)]
    if not pipes:
        return []
    spans: list[tuple[int, int]] = []
    if line[:pipes[0]].strip():
        spans.append((0, pipes[0]))
    for prev, nxt in zip(pipes, pipes[1:]):
        spans.append((prev + 1, nxt))
    if line[pipes[-1] + 1:].strip():
        spans.append((pipes[-1] + 1, len(line)))
    return spans


def header_scale(header: str) -> tuple[Decimal | None, str | None, str | None]:
    """(scale, currency, kind) declared by a table header cell, if any.

    'Revenue ($m)' -> (1e6, 'USD', currency)   ·   'Margin (%)' -> (0.01, None, percent)
    """
    text = header.strip().rstrip(":")
    if pct := _HEADER_PERCENT_RE.search(text):
        token = pct.group(1).lower()
        scale = BPS_SCALE if token == "bps" else PERCENT_SCALE
        return scale, None, KIND_PERCENT
    if m := _HEADER_UNIT_RE.search(text):
        symbol, word = m.group(1), m.group(2).lower()
        scale = SCALE_WORDS.get(word) or SHORT_SCALES.get(word)
        if scale is None:
            return None, None, None
        currency = CURRENCIES.get(symbol.upper() if symbol else "", None) if symbol else None
        kind = KIND_CURRENCY if currency else None
        return scale, currency, kind
    return None, None, None


def _table_columns(md: str) -> dict[int, list[str]]:
    """line index (0-based) -> that row's header cells, for rows inside a table."""
    lines = md.split("\n")
    headers: dict[int, list[str]] = {}
    i = 0
    while i < len(lines) - 1:
        if "|" in lines[i] and _SEPARATOR_RE.match(lines[i + 1]) and "|" in lines[i + 1]:
            head = [lines[i][s:e].strip() for s, e in _cells(lines[i])]
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                headers[j] = head
                j += 1
            i = j
        else:
            i += 1
    return headers


# ---------------------------------------------------------------------------
# The numeral grammar.
# ---------------------------------------------------------------------------

# Note on boundaries: `%` is not a word character, so `\b` after it never
# matches — the suffix alternatives use a negative lookahead instead. The scale
# word is allowed both inside and outside a closing parenthesis, because filings
# write "(1,234 million)" and drafts write "($1,234) million".
_SCALE_ALT = r"trillion|billion|million|thousand|bn|mn|tn"

_NUMERAL_RE = re.compile(rf"""
    (?P<open>\()?
    (?P<currency>US\$|HK\$|NT\$|USD\ |TWD\ |HKD\ |\$|€|£|¥)?\s?
    (?P<sign>[-−–+])?
    (?P<digits>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)
    (?:\s?(?P<scale_in>{_SCALE_ALT})(?![A-Za-z])
       |(?P<short>[bmkt])(?![A-Za-z]))?
    (?(open)\s*\))
    (?:\s?(?P<scale_out>{_SCALE_ALT})(?![A-Za-z]))?
    (?:\s?(?P<suffix>%|bps(?![A-Za-z])|pp(?![A-Za-z])|x(?![A-Za-z])|×))?
""", re.VERBOSE | re.IGNORECASE)

_SHARES_RE = re.compile(r"^\W*(?:diluted\s+|basic\s+|common\s+)?shares\b", re.I)


def _scale_word(m: re.Match) -> str:
    return m.group("scale_in") or m.group("scale_out") or ""


def _classify(m: re.Match, after: str) -> tuple[str, str | None]:
    """(kind, unit) from the numeral's own decoration."""
    suffix = (m.group("suffix") or "").lower()
    if suffix in ("%", "bps", "pp"):
        return KIND_PERCENT, "pure"
    if suffix in ("x", "×"):
        return KIND_MULTIPLE, "pure"
    if symbol := m.group("currency"):
        symbol = symbol.strip()
        return KIND_CURRENCY, CURRENCIES.get(symbol) or CURRENCIES.get(symbol.upper())
    if _SHARES_RE.match(after):
        return KIND_SHARES, "shares"
    return KIND_BARE, None


def _is_year(m: re.Match) -> bool:
    """A bare undecorated 1900-2100 integer is a year, not a figure."""
    if m.group("currency") or _scale_word(m) or m.group("short") or m.group("suffix"):
        return False
    d = m.group("digits")
    return len(d) == 4 and d.isdigit() and 1900 <= int(d) <= 2100


def extract_claims(md: str) -> list[NumericClaim]:
    """Every numeric claim in the draft, in document order.

    Anchors bind backwards: `[^F7]` claims every unanchored figure since the
    previous anchor on that line. That makes a range ("$41.43-44.10 [^F7]")
    work, and makes "revenue rose from X to Y [^F3]" fail loudly on Y rather
    than pass silently — which is the correct outcome for a sentence that
    needs two citations and carries one.
    """
    masked = mask(md)
    headers = _table_columns(md)
    lines = md.split("\n")
    starts = [0] + [i + 1 for i, ch in enumerate(md) if ch == "\n"]

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    claims: list[NumericClaim] = []
    for m in _NUMERAL_RE.finditer(masked):
        if _is_year(m):
            continue
        digits = Decimal(m.group("digits").replace(",", ""))
        if m.group("sign") in ("-", "−", "–") or m.group("open"):
            digits = -digits

        # `\s?` after the optional currency can swallow a leading space; keep the
        # span tight so md[start:end] is exactly the figure as written.
        start, end = m.start(), m.end()
        while start < end and md[start].isspace():
            start += 1
        # Line comes from `start`, not `m.start()`: the optional `\s?` after the
        # currency group can swallow the preceding NEWLINE, which would put the
        # claim on the line above -- misreporting its position and, worse,
        # preventing its anchor on the real line from binding.
        line_idx = line_of(start)
        line_text = lines[line_idx]
        col_off = start - starts[line_idx]

        after = masked[m.end():m.end() + 40]
        kind, unit = _classify(m, after)

        # -- scale, in priority order -------------------------------------
        scale, source = None, None
        if word := _scale_word(m):
            scale, source = SCALE_WORDS[word.lower()], SCALE_INLINE
        elif short := (m.group("short") or ""):
            if m.group("currency"):
                scale, source = SHORT_SCALES[short.lower()], SCALE_INLINE
            else:
                # A bare "50 m" is prose, not fifty million. Keep the figure —
                # dropping it would be under-extraction — but end the claim's
                # span before the letter so the reported text stays honest.
                end = m.end("digits")
        elif kind == KIND_PERCENT:
            token = (m.group("suffix") or "").lower()
            scale = BPS_SCALE if token == "bps" else PERCENT_SCALE
            source = SCALE_INLINE

        column = None
        if scale is None and line_idx in headers:
            cells = _cells(line_text)
            idx = next((i for i, (s, e) in enumerate(cells) if s <= col_off < e), None)
            if idx is not None and idx < len(headers[line_idx]):
                column = headers[line_idx][idx]
                h_scale, h_currency, h_kind = header_scale(column)
                if h_scale is not None:
                    scale, source = h_scale, SCALE_HEADER
                    if h_kind and kind == KIND_BARE:
                        kind = h_kind
                        unit = h_currency or "pure"
                    elif h_currency and unit is None:
                        unit = h_currency

        if scale is None:
            # A financial magnitude in an unlabelled table column is the one
            # case we refuse to guess at (see module docstring).
            in_table = line_idx in headers
            if in_table and kind in (KIND_CURRENCY, KIND_SHARES, KIND_BARE):
                scale, source = Decimal(1), SCALE_UNDECLARED
            else:
                scale, source = Decimal(1), SCALE_IMPLICIT

        claims.append(NumericClaim(
            text=md[start:end], span=(start, end), line=line_idx + 1,
            digits=digits, scale=scale, scale_source=source, kind=kind, unit=unit,
            column=column))

    return _bind_anchors(md, claims)


def _bind_anchors(md: str, claims: list[NumericClaim]) -> list[NumericClaim]:
    """Attach each `[^Fn]` marker to the claims it follows on the same line."""
    anchors = [(m.start(), m.group(1)) for m in _ANCHOR_RE.finditer(md)]
    if not anchors:
        return claims

    starts = [0] + [i + 1 for i, ch in enumerate(md) if ch == "\n"]

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    bound: list[NumericClaim] = []
    for claim in claims:
        line = claim.line - 1
        # In a table the anchor must share the cell; elsewhere, the line.
        candidates = [(pos, key) for pos, key in anchors
                      if line_of(pos) == line and pos >= claim.span[1]]
        key = None
        if candidates:
            pos, key = min(candidates)
            between = md[claim.span[1]:pos]
            if "|" in between:            # anchor belongs to a later cell
                key = None
        bound.append(NumericClaim(**{**claim.__dict__, "anchor": key}))
    return bound


if __name__ == "__main__":
    import argparse
    import pathlib

    ap = argparse.ArgumentParser(description="list every numeric claim in a draft")
    ap.add_argument("draft")
    a = ap.parse_args()

    text = pathlib.Path(a.draft).read_text(encoding="utf-8")
    for c in extract_claims(text):
        anchor = c.anchor or "-"
        print(f"  L{c.line:>3} {c.text:<24} {c.value:>22,}  ulp={c.ulp:<14} "
              f"{c.kind:<9} {c.scale_source:<13} [{anchor}]")
