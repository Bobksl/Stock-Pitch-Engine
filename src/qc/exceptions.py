"""P2.4 — declared exceptions to Class B rules (framework 6.5).

Structurally this is `external.py` again, and deliberately so. That module
faced the same problem in Phase 1 -- a legitimate case that cannot satisfy the
normal rule -- and solved it with a declared record and a closed vocabulary
rather than a severity level. This is the same shape applied to model form,
and reusing it is a decision, not a coincidence: a second mechanism would be a
second way to say "yes but", and the framework permits exactly one.

**An exception is not a dismissed warning.** It is a positive, structured,
attributed assertion that a named condition was accepted for a declared
reason, by a named person, until a stated date. There is still exactly one
passing state.

The load-time refusal is the load-bearing part
----------------------------------------------
A record naming a Class A rule fails to *parse*. It is not accepted and then
ignored at check time -- it never becomes an object. So "Class A is never
exceptionable" is not a rule the gate has to remember to apply; it is a
sentence that cannot be written down. `external.py` earns its guarantee the
same way, by rejecting a figure XBRL could have answered at declaration time
rather than at resolution time.

**Expiry is required.** An exception with no end date is a permanent carve-out
with extra steps, and the whole objection to a severity ladder was that it
lets an unusual model become a normal one by attrition. An expired record is
kept and reported -- "an exception existed and lapsed on 2026-03-01" is a far
more useful failure than "unexplained breach" -- but it does not satisfy
anything.

Redistribution note, and the contrast with external records
-----------------------------------------------------------
`data/external/` is git-ignored because it holds licensed terminal data.
`data/exceptions/` is the opposite: it is committed, and it must be. Closed
classification is what makes exceptions countable and reviewable, and a
carve-out nobody can see in a diff is the thing this design exists to prevent.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from src.config import PROJECT_ROOT
from src.qc.rules import CLASS_A, Rule, UnknownRule, rule as lookup_rule

REASON_LONG_DURATION_ASSET = "long_duration_asset"
REASON_PRE_REVENUE = "pre_revenue"
REASON_REGULATED_CONCESSION = "regulated_concession"

#: Closed vocabulary (6.5). Free text alone would be unauditable: closed
#: classification is what makes exceptions countable, so that "how many
#: long-duration carve-outs are live?" is a question with an answer. Adding a
#: reason is a reviewable change to this file.
EXCEPTION_REASONS = (REASON_LONG_DURATION_ASSET, REASON_PRE_REVENUE,
                     REASON_REGULATED_CONCESSION)

DEFAULT_STORE = PROJECT_ROOT / "data" / "exceptions"

_REQUIRED = ("condition", "reason", "detail", "author", "date", "expiry")


class ExceptionError(ValueError):
    """An exception record is malformed, or names a rule it may not except."""


@dataclass(frozen=True)
class ExceptionRecord:
    """A Class B breach, accepted on the record (6.5)."""

    key: str
    rule: Rule                      # resolved at parse time, never a bare string
    measured: Decimal | None
    reason: str
    detail: str                     # supplementary only, never load-bearing
    author: str
    declared: date
    expiry: date

    def live(self, as_of: date | None = None) -> bool:
        """Still in force on the valuation date."""
        return (as_of or date.today()) <= self.expiry

    @property
    def citation(self) -> str:
        return (f"exc:{self.key} | {self.rule.id} | {self.reason} | "
                f"{self.author} | expires {self.expiry}")

    def render(self, detail: str | None = None) -> str:
        """The published form (6.5).

        Exceptions are published, not merely consumed by the gate. A pitch
        relying on one carries it visibly, which makes the condition *more*
        legible to a reader than prose discussion would.
        """
        return f"Exception: `{self.reason}` — {detail or self.detail}."


def _parse(key: str, entry: Any) -> ExceptionRecord:
    if not isinstance(entry, dict):
        raise ExceptionError(f"exception {key!r}: entry must be a mapping")

    missing = [f for f in _REQUIRED if entry.get(f) is None]
    if missing:
        # Expiry lands here, and its absence is the common case worth naming.
        raise ExceptionError(
            f"exception {key!r}: missing required field(s) "
            f"{', '.join(missing)}. Every field is required, expiry included: "
            f"an exception without an end date is a permanent carve-out.")

    try:
        target = lookup_rule(str(entry["condition"]))
    except UnknownRule as exc:
        raise ExceptionError(f"exception {key!r}: {exc}") from None

    if target.rule_class == CLASS_A:
        raise ExceptionError(
            f"exception {key!r} names {target.id!r}, which is Class A "
            f"({target.spec_ref}: {target.title}). Class A is correctness -- "
            f"the figure is wrong or unverifiable -- and is never "
            f"exceptionable. Fix the model, not the gate.")

    if entry["reason"] not in EXCEPTION_REASONS:
        raise ExceptionError(
            f"exception {key!r}: reason {entry['reason']!r} is not in the "
            f"closed vocabulary {EXCEPTION_REASONS}. Free text alone would be "
            f"unauditable; the detail field carries the specifics.")

    declared, expiry = _as_date(key, entry["date"]), _as_date(key, entry["expiry"])
    if expiry <= declared:
        raise ExceptionError(
            f"exception {key!r}: expiry {expiry} is not after its date {declared}")

    measured = entry.get("measured")
    return ExceptionRecord(
        key=key, rule=target,
        measured=None if measured is None else Decimal(str(measured)),
        reason=str(entry["reason"]), detail=str(entry["detail"]),
        author=str(entry["author"]), declared=declared, expiry=expiry)


def _as_date(key: str, value: Any) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ExceptionError(
            f"exception {key!r}: {value!r} is not an ISO date") from None


def load_exceptions(source: str | Path | None = None) -> dict[str, ExceptionRecord]:
    """Every declared exception, keyed by record key.

    `source` may be a YAML string, a file, or a directory of `*.yaml` files.
    A missing store is not an error: it yields {}, and the resulting failure is
    reported per rule ("no exception declared for X") rather than as one opaque
    error about a missing directory. Same contract as `external.load_records`.
    """
    if source is None:
        source = DEFAULT_STORE

    texts: list[str] = []
    if isinstance(source, str) and "\n" in source:
        texts.append(source)
    else:
        path = Path(source)
        if path.is_dir():
            texts.extend(p.read_text(encoding="utf-8")
                         for p in sorted(path.glob("*.yaml")))
        elif path.is_file():
            texts.append(path.read_text(encoding="utf-8"))

    records: dict[str, ExceptionRecord] = {}
    for text in texts:
        try:
            loaded = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise ExceptionError(f"exception store is not valid YAML: {exc}") from None
        if not isinstance(loaded, dict):
            raise ExceptionError("exception store must be a mapping of key -> record")
        entries = loaded.get("records") if "records" in loaded else loaded
        for key, entry in (entries or {}).items():
            records[str(key)] = _parse(str(key), entry)
    return records


def for_rule(records: dict[str, ExceptionRecord], rule_id: str
             ) -> ExceptionRecord | None:
    """The declared exception for a rule, preferring the latest expiry."""
    matches = [r for r in records.values() if r.rule.id == rule_id]
    return max(matches, key=lambda r: r.expiry) if matches else None
