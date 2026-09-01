"""P2.4 — what a rule found, and what the gate always reports anyway.

Two kinds of output, and keeping them apart is the point.

A **Finding** is a rule that fired. It blocks, unless it is Class B and a live
declared exception satisfies it. There is no third outcome.

A **Measurement** is a number the gate reports on every run, pass or fail. It
cannot block and it is not a weak finding. Framework 4.6 requires the measured
terminal-value share printed always, and the reason it is a separate type is
that the alternative was tried and rejected: a non-blocking lower tier at 70%
was in v1.0 and was deleted, because an observation that cannot block is a
warning by another name, and a warning is a second passing state wearing a
disguise. A measurement makes no claim about acceptability. It states a value.

If a future edit finds itself wanting to give a Measurement a threshold that
*sometimes* matters, that is a Finding and it belongs in `rules.py`.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.qc.exceptions import ExceptionRecord, for_rule
from src.qc.rules import CLASS_A, Rule


@dataclass(frozen=True)
class Measurement:
    """A number reported on every run. Never blocks, never a finding."""

    label: str
    value: Decimal
    unit: str = ""                  # '%', 'pp', 'x', ...
    spec_ref: str = ""
    threshold: Decimal | None = None

    def render(self) -> str:
        line = f"{self.label}: {self.value}{self.unit}"
        if self.threshold is not None:
            line += f" (threshold {self.threshold}{self.unit})"
        return line + (f"  [{self.spec_ref}]" if self.spec_ref else "")


@dataclass(frozen=True)
class Finding:
    """A rule that fired, with the measurement that fired it."""

    rule: Rule
    detail: str                     # 'TV share 86.8%, above the 75% threshold'
    measured: Decimal | None = None
    threshold: Decimal | None = None
    exception: ExceptionRecord | None = None

    def satisfied(self, as_of: date | None = None) -> bool:
        """Whether this finding is answered, and so does not block.

        Class A is never satisfied. Not "not satisfied unless overridden" --
        never, and there is no argument to this method that could change it.
        A Class A rule is one where the figure is wrong or unverifiable, and
        neither of those is a thing an assertion can fix.
        """
        if self.rule.rule_class == CLASS_A:
            return False
        return self.exception is not None and self.exception.live(as_of)

    def render(self, as_of: date | None = None) -> str:
        head = f"{self.rule}\n    {self.detail}"
        if self.exception is None:
            return head
        if self.exception.live(as_of):
            return head + f"\n    satisfied by {self.exception.citation}"
        return (head + f"\n    exception {self.exception.key!r} EXPIRED on "
                       f"{self.exception.expiry} and does not satisfy it")

    def disclosure(self) -> str | None:
        """The line an output carries when it relies on this exception (6.5)."""
        return None if self.exception is None else self.exception.render(self.detail)


@dataclass
class FindingSet:
    """Findings and measurements from one gate run, and the single verdict."""

    findings: list[Finding] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)
    as_of: date | None = None

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if not f.satisfied(self.as_of)]

    @property
    def excepted(self) -> list[Finding]:
        return [f for f in self.findings if f.satisfied(self.as_of)]

    @property
    def passed(self) -> bool:
        """One passing state: nothing blocks. Exceptions are not a second one."""
        return not self.blocking

    @property
    def disclosures(self) -> list[str]:
        """Every exception the output must publish alongside its figures."""
        return [d for f in self.excepted if (d := f.disclosure())]

    def render(self) -> str:
        lines: list[str] = []
        if self.measurements:
            lines.append("MEASUREMENTS  — reported every run, pass or fail")
            lines.append("-" * 72)
            lines.extend("  " + m.render() for m in self.measurements)
        if self.blocking:
            lines.append(f"\nBLOCKING ({len(self.blocking)})")
            lines.append("-" * 72)
            lines.extend("  " + f.render(self.as_of).replace("\n", "\n  ")
                         for f in self.blocking)
        if self.excepted:
            lines.append(f"\nACCEPTED BY DECLARED EXCEPTION ({len(self.excepted)})")
            lines.append("-" * 72)
            lines.extend("  " + f.render(self.as_of).replace("\n", "\n  ")
                         for f in self.excepted)
        return "\n".join(lines)


def apply_exceptions(findings: list[Finding],
                     records: dict[str, ExceptionRecord]) -> list[Finding]:
    """Attach any declared exception to the finding it names.

    Class A findings are not consulted against the store at all -- not as an
    optimisation, but because a record naming a Class A rule cannot exist:
    `exceptions.load_exceptions` refuses to build one. Expired records ARE
    attached, so the report can say a carve-out lapsed rather than reporting
    an unexplained breach.
    """
    from dataclasses import replace

    attached = []
    for finding in findings:
        if finding.rule.rule_class == CLASS_A:
            attached.append(finding)
            continue
        attached.append(replace(finding, exception=for_rule(records, finding.rule.id)))
    return attached
