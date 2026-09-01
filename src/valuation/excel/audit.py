"""P2.6 — audit a foreign valuation workbook against framework 4.

The entry point behind the Phase 2 exit criterion and the repository's demo:
read somebody else's model, reproduce its published answer from its own
inputs, then say what is wrong with it and what the answer becomes once it is
put right.

Three runs, differing only in `Conventions`:

    as built        the workbook's own conventions. Reproduces its published
                    target, which is what earns the right to criticise the rest
    tv corrected    defect 1 repaired and NOTHING else -- the audit's
                    "corrected" row, and the run whose terminal-value share
                    and WACC-minus-g spread the Class B rules are measured on
    spec            every convention framework 4 requires

The middle run is the interesting one and it is deliberately not the tidiest.
Repairing one defect while leaving the others in place looks arbitrary until
you see what it shows: the model's terminal value share jumps from an
unremarkable 81.8% to 86.8%, above the threshold, because the arithmetic error
was *masking* a terminal-value-dominated model. Two errors partially
offsetting, landing in a believable range. Jump straight to the fully repaired
run and that finding disappears into a different number, and the single most
important thing this fixture demonstrates is lost.

Reproduction comes first for a reason beyond tidiness. A tool that reports
defects without first reproducing the published number is indistinguishable
from a tool with a parsing bug, and the modeller has no reason to believe it.
Reproducing TWD 1,732.66 to the cent and *then* saying the terminal value is
double-discounted is an argument; the second half alone is an assertion.
"""
from dataclasses import dataclass, replace

from src.qc.exceptions import ExceptionRecord, load_exceptions
from src.qc.findings import FindingSet, apply_exceptions
from src.qc.valuation_rules import (
    convention_findings,
    terminal_value_share_measurement,
    wacc_growth_spread_measurement,
)
from src.valuation.dcf import DcfResult, discounted_cash_flow
from src.valuation.inputs import Conventions
from src.valuation.money import quantize_price
from src.valuation.excel.reader import CellMap, TSMC_CELL_MAP, WorkbookModel, read_model


@dataclass
class WorkbookAudit:
    """A foreign model, reproduced and judged."""

    model: WorkbookModel
    as_built: DcfResult
    tv_corrected: DcfResult
    spec: DcfResult
    rules: FindingSet

    @property
    def passed(self) -> bool:
        return self.rules.passed

    @property
    def reproduced(self) -> bool:
        """Whether the engine matched the workbook's own published figure."""
        if self.model.published_price is None:
            return False
        return (quantize_price(self.as_built.share_price)
                == quantize_price(self.model.published_price))

    def render(self) -> str:
        currency = self.model.inputs.currency

        def price(result: DcfResult) -> str:
            return f"{currency} {quantize_price(result.share_price):,}"

        lines = []
        if self.model.published_price is not None:
            verdict = "reproduced" if self.reproduced else "DID NOT REPRODUCE"
            lines.append(
                f"Published target  {currency} "
                f"{quantize_price(self.model.published_price):,}  — {verdict} "
                f"from the workbook's own inputs")
        lines.append(f"Terminal value corrected  {price(self.tv_corrected)}"
                     f"  — defect 1 repaired, nothing else changed")
        lines.append(f"All conventions corrected {price(self.spec)}"
                     f"  — every convention framework 4 requires")
        lines.append("")
        lines.append(self.as_built.capital.render())
        lines.append("")
        lines.append(self.rules.render())
        lines.append("\nAUDIT PASSED" if self.passed
                     else "\nAUDIT FAILED — publication blocked")
        return "\n".join(lines)


def audit_workbook(path, cell_map: CellMap = TSMC_CELL_MAP,
                   published_price_cell: str | None = None,
                   exceptions: dict[str, ExceptionRecord] | str | None = None,
                   as_of=None) -> WorkbookAudit:
    """Read a workbook, reproduce it, and evaluate framework 4 against it."""
    model = read_model(path, cell_map, published_price_cell=published_price_cell)

    as_built = discounted_cash_flow(model.inputs, model.conventions)
    tv_corrected = discounted_cash_flow(
        model.inputs,
        replace(model.conventions,
                terminal_value_base=Conventions.SPEC.terminal_value_base))
    spec = discounted_cash_flow(model.inputs, Conventions.SPEC)

    if not isinstance(exceptions, dict):
        exceptions = load_exceptions(exceptions)

    findings = apply_exceptions(
        convention_findings(model, as_built, tv_corrected), exceptions)

    return WorkbookAudit(
        model=model, as_built=as_built, tv_corrected=tv_corrected, spec=spec,
        rules=FindingSet(
            findings=findings,
            measurements=[
                terminal_value_share_measurement(
                    as_built, "Terminal value share (as built)"),
                terminal_value_share_measurement(
                    tv_corrected, "Terminal value share (TV corrected)"),
                wacc_growth_spread_measurement(tv_corrected),
            ],
            as_of=as_of))
