"""P1.2/P1.3 — run every numeric check over a draft and report the verdict.

The entry point for R5. One call in, one QCReport out, and the report is either
clean or it blocks publication: framework 5's "fail loudly" and the standing
decision that an unresolvable figure is a hard failure with no allowlist, no
severity ladder, and no warning anybody can wave through.

What "blocks" means concretely: `QCReport.passed` is False and the CLI exits
non-zero. Nothing downstream is expected to interpret a partial pass.
"""
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from src.qc.anchors import Anchor, CitationIndexError, parse_index
from src.qc.cells import CellRegistry
from src.qc.claims import NumericClaim, extract_claims
from src.qc.external import ExternalRecord, load_records
from src.qc.findings import FindingSet
from src.qc.recency import SeriesFinding, check_recency
from src.qc.resolve import Resolution, resolve_claim

_CELLS_RE_HEADING = "Model cells"


@dataclass
class QCReport:
    """Everything the numeric gate found, and whether the draft may publish."""

    claims: list[NumericClaim] = field(default_factory=list)
    resolutions: list[Resolution] = field(default_factory=list)
    recency: list[SeriesFinding] = field(default_factory=list)
    index: dict[str, Anchor] = field(default_factory=dict)
    externals_used: list[ExternalRecord] = field(default_factory=list)
    #: Rule findings and always-reported measurements (P2.4, framework 6.5).
    #: Empty for a Phase 1 draft check; populated once a valuation is attached.
    rules: FindingSet = field(default_factory=FindingSet)
    fatal: str | None = None                # index/store unparseable

    @property
    def failures(self) -> list[Resolution]:
        return [r for r in self.resolutions if not r.ok]

    @property
    def stale(self) -> list[SeriesFinding]:
        return [f for f in self.recency if not f.ok]

    @property
    def passed(self) -> bool:
        """One passing state (6.5).

        A satisfied Class B finding does not create a second one: it is
        already excluded from `rules.blocking` by its declared exception.
        """
        return (not self.fatal and not self.failures and not self.stale
                and self.rules.passed)

    def render(self) -> str:
        lines: list[str] = []
        if self.fatal:
            return f"QC FAILED\n\n  {self.fatal}\n"

        lines.append(f"{len(self.claims)} numeric claim(s) checked, "
                     f"{len(self.resolutions) - len(self.failures)} resolved")

        if self.failures:
            lines.append(f"\nUNRESOLVED FIGURES ({len(self.failures)})")
            lines.append("-" * 72)
            for res in self.failures:
                lines.append("  " + res.render().replace("\n", "\n  "))

        if self.stale:
            lines.append(f"\nSTALE SERIES ({len(self.stale)})  — framework 6.3 / C12")
            lines.append("-" * 72)
            for finding in self.stale:
                lines.append(f"  {finding.key.describe()}\n    {finding.detail}")
                for claim, period in finding.stale:
                    lines.append(f"    line {claim.line}: {claim.text!r} ({period})")

        rendered_rules = self.rules.render()
        if rendered_rules:
            lines.append("\n" + rendered_rules)

        if self.rules.disclosures:
            lines.append("\nPUBLISHED WITH THIS OUTPUT  — framework 6.5")
            lines.append("-" * 72)
            lines.extend("  " + d for d in self.rules.disclosures)

        if self.externals_used:
            lines.append("\nEXTERNAL SOURCES RELIED ON")
            lines.append("-" * 72)
            for record in self.externals_used:
                lines.append(f"  {record.citation}")

        lines.append("\nQC PASSED" if self.passed else "\nQC FAILED — publication blocked")
        return "\n".join(lines)


def _cell_registry(md: str, as_of: date | None,
                   externals: dict[str, ExternalRecord]) -> CellRegistry:
    """Model cells declared in a '## Model cells' section of the draft."""
    import re
    section = re.search(
        rf"^#{{1,6}}[ \t]*{_CELLS_RE_HEADING}[ \t]*$(?P<body>.*?)(?=^#{{1,6}}[ \t]|\Z)",
        md, re.MULTILINE | re.DOTALL | re.I)
    if not section:
        return CellRegistry(as_of=as_of, externals=externals)
    blocks = re.findall(r"```[ \t]*(?:yaml|yml)?[ \t]*\n(.*?)^```",
                        section.group("body"), re.MULTILINE | re.DOTALL)
    return CellRegistry.from_yaml("\n".join(blocks) or section.group("body"),
                                  as_of=as_of, externals=externals)


def verify_draft(md: str, *, as_of: date | None = None,
                 externals: dict[str, ExternalRecord] | str | Path | None = None,
                 cells: CellRegistry | None = None) -> QCReport:
    """Run P1.2 resolution and P1.3 recency over a Markdown draft."""
    report = QCReport()

    try:
        report.index = parse_index(md)
    except CitationIndexError as exc:
        report.fatal = str(exc)
        return report

    if not isinstance(externals, dict):
        try:
            externals = load_records(externals)
        except Exception as exc:                       # noqa: BLE001 - reported, not raised
            report.fatal = str(exc)
            return report

    if cells is None:
        try:
            cells = _cell_registry(md, as_of, externals)
        except Exception as exc:                       # noqa: BLE001
            report.fatal = f"model cell declarations: {exc}"
            return report

    report.claims = extract_claims(md)
    report.resolutions = [
        resolve_claim(c, report.index, cells=cells, externals=externals, as_of=as_of)
        for c in report.claims]
    report.recency = check_recency(report.resolutions, report.index, as_of=as_of)

    used = {a.body.get("record") for a in report.index.values() if a.kind == "ext"}
    report.externals_used = [r for k, r in sorted(externals.items()) if k in used]
    return report


def verify_file(path: str | Path, **kwargs) -> QCReport:
    return verify_draft(Path(path).read_text(encoding="utf-8"), **kwargs)
