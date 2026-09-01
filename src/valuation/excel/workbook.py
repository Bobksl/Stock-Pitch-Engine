"""P2.5 — export the valuation as a workbook of live formulas (framework 4.12).

Python owns calculation. The workbook is a two-way interface, not a report:
you type in `Inputs`, everything else recalculates, and `readback.py` reads
your overrides back into Python.

**No calculation cell holds a pasted value.** Every cell outside `Inputs` is a
formula referencing other cells. This is the property that makes C11 mean
anything at all -- if the exporter wrote Python's numbers into the calculation
tabs, recalculating the workbook would agree with Python trivially and the
reconciliation would be a test of openpyxl's ability to store a float. Writing
formulas instead means Excel genuinely recomputes the model from the inputs,
and agreement is evidence that two independent implementations concur.

`LAYOUT` is the single source of truth for where things live. The writer, the
readback and the reconciliation all address cells through it, so moving a row
is one edit rather than three that must be kept in step -- which is the same
class of bug C11 exists to catch, one level up.

Compliant models only
---------------------
The exporter refuses to write a model whose conventions differ from
`Conventions.SPEC`. It can *read* a defective workbook (that is `reader.py`'s
job and the whole point of the audit), but emitting formulas that implement a
terminal value built from an already-discounted cash flow would be shipping
the defect, and a file that leaves this repository should not contain one.
"""
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from src.valuation.dcf import DcfResult
from src.valuation.excel.formulas import formula, sum_range
from src.valuation.inputs import Conventions
from src.valuation.money import to_spreadsheet

SHEET_INPUTS = "Inputs"
SHEET_WACC = "WACC"
SHEET_MODEL = "Model"
SHEET_DCF = "DCF"
SHEET_SUMMARY = "Summary"

#: Tabs framework 4.12 names that arrive with their components at P2.10.
#: Each must land with its C11 coverage in the same commit.
PENDING_SHEETS = ("Comps", "Scenarios", "Sensitivity")


class ExportError(ValueError):
    """The model cannot be written as a compliant workbook."""


@dataclass(frozen=True)
class Layout:
    """Where every quantity lives. Addressed by the writer, readback and C11."""

    #: Inputs sheet: field name -> row. Values sit in column B.
    scalar_rows: dict[str, int]
    #: Inputs sheet: driver name -> row, one column per forecast period.
    driver_rows: dict[str, int]
    #: First forecast column on every sheet that has periods.
    first_period_column: int = 3            # C
    #: Inputs sheet row carrying the period labels.
    period_row: int = 26

    # WACC sheet rows
    wacc_cost_of_equity: int = 3
    wacc_after_tax_debt: int = 4
    wacc_equity_value: int = 5
    wacc_debt_value: int = 6
    wacc_debt_weight: int = 7
    wacc_equity_weight: int = 8
    wacc_value: int = 9

    # Model sheet rows
    model_period: int = 3
    model_revenue: int = 4
    model_ebitda: int = 5
    model_depreciation: int = 6
    model_ebit: int = 7
    model_tax: int = 8
    model_capex: int = 9
    model_nwc: int = 10
    model_ufcf: int = 11

    # DCF sheet rows
    dcf_period: int = 3
    dcf_exponent: int = 4
    dcf_factor: int = 5
    dcf_flow: int = 6
    dcf_present_value: int = 7
    dcf_pv_forecast: int = 9
    dcf_terminal_value: int = 10
    dcf_pv_terminal: int = 11
    dcf_enterprise_value: int = 12
    dcf_equity_value: int = 13
    dcf_share_price: int = 14

    def column(self, index: int) -> str:
        return get_column_letter(self.first_period_column + index)


LAYOUT = Layout(
    scalar_rows={
        "risk_free_rate": 4,
        "equity_risk_premium": 5,
        "beta": 6,
        "cost_of_debt": 7,
        "tax_rate": 8,
        "market_capitalisation": 11,
        "gross_debt": 12,
        "terminal_growth": 15,
        "total_debt": 18,
        "cash_and_equivalents": 19,
        "shares_outstanding": 20,
        "stub_fraction": 21,
        "base_revenue": 24,
    },
    driver_rows={
        "revenue_growth": 27,
        "ebitda_margin": 28,
        "depreciation": 29,
        "capex": 30,
        "change_in_nwc": 31,
    },
)

_SCALAR_LABELS = {
    "risk_free_rate": "Risk-free rate",
    "equity_risk_premium": "Equity risk premium",
    "beta": "Beta",
    "cost_of_debt": "Cost of debt (marginal)",
    "tax_rate": "Tax rate (marginal)",
    "market_capitalisation": "Market capitalisation",
    "gross_debt": "Gross debt",
    "terminal_growth": "Terminal growth (nominal)",
    "total_debt": "Total debt (signed)",
    "cash_and_equivalents": "Cash and equivalents",
    "shares_outstanding": "Shares outstanding (fully diluted)",
    "stub_fraction": "Stub fraction of first period",
    "base_revenue": "Base period revenue",
}

_DRIVER_LABELS = {
    "revenue_growth": "Revenue growth",
    "ebitda_margin": "EBITDA margin",
    "depreciation": "Depreciation and amortisation",
    "capex": "Capital expenditure (signed)",
    "change_in_nwc": "Change in net working capital (signed)",
}

_INPUT_FILL = PatternFill("solid", fgColor="DCE6F1")   # typed here, and only here
_HEADING = Font(bold=True)
_TITLE = Font(bold=True, size=12)


def _title(sheet, text: str, subtitle: str = "") -> None:
    sheet["A1"] = text
    sheet["A1"].font = _TITLE
    if subtitle:
        sheet["A2"] = subtitle


def _label(sheet, row: int, text: str, bold: bool = False) -> None:
    cell = sheet.cell(row, 1, text)
    if bold:
        cell.font = _HEADING


def _write_inputs(sheet, result: DcfResult, layout: Layout) -> None:
    inputs = result.inputs
    _title(sheet, f"Inputs — {inputs.currency} {inputs.unit}",
           "The only sheet you type in. Every other cell is a live formula.")

    for row, text in ((3, "Cost of capital (4.3)"),
                      (10, "Capital structure — equity weight is market cap (4.3)"),
                      (14, "Terminal value (4.6)"),
                      (17, "Equity bridge (4.9)"),
                      (23, "Explicit forecast — the Section 3 bridge (4.5)")):
        _label(sheet, row, text, bold=True)

    for field, row in layout.scalar_rows.items():
        _label(sheet, row, _SCALAR_LABELS[field])
        cell = sheet.cell(row, 2, to_spreadsheet(getattr(inputs, field)))
        cell.fill = _INPUT_FILL

    _label(sheet, layout.period_row, "Period", bold=True)
    for index, year in enumerate(inputs.forecast):
        cell = sheet.cell(layout.period_row, layout.first_period_column + index,
                          year.period)
        cell.font = _HEADING
        cell.alignment = Alignment(horizontal="right")

    for field, row in layout.driver_rows.items():
        _label(sheet, row, _DRIVER_LABELS[field])
        for index, year in enumerate(inputs.forecast):
            cell = sheet.cell(row, layout.first_period_column + index,
                              to_spreadsheet(getattr(year, field)))
            cell.fill = _INPUT_FILL

    sheet.column_dimensions["A"].width = 42


def _inp(layout: Layout, field: str, absolute: bool = False) -> str:
    row = layout.scalar_rows[field]
    return f"{SHEET_INPUTS}!{'$B$' if absolute else 'B'}{row}"


def _driver(layout: Layout, field: str, index: int) -> str:
    return (f"{SHEET_INPUTS}!{layout.column(index)}"
            f"{layout.driver_rows[field]}")


def _write_wacc(sheet, layout: Layout) -> None:
    _title(sheet, "WACC — built from inputs, never copied (4.3)",
           "Equity weight is market capitalisation; debt is not netted out of it.")
    rows = {
        layout.wacc_cost_of_equity: (
            "Cost of equity (CAPM)",
            "=" + _inp(layout, "risk_free_rate")
            + f"+{_inp(layout, 'beta')}*{_inp(layout, 'equity_risk_premium')}"),
        layout.wacc_after_tax_debt: (
            "Cost of debt, after tax",
            formula("product", _inp(layout, "cost_of_debt"),
                    f"(1-{_inp(layout, 'tax_rate')})")),
        layout.wacc_equity_value: (
            "Equity value (market capitalisation)",
            f"={_inp(layout, 'market_capitalisation')}"),
        layout.wacc_debt_value: ("Debt value", f"={_inp(layout, 'gross_debt')}"),
        layout.wacc_debt_weight: (
            "D / (D + E)",
            formula("ratio", f"B{layout.wacc_debt_value}",
                    f"(B{layout.wacc_equity_value}+B{layout.wacc_debt_value})")),
        layout.wacc_equity_weight: (
            "E / (D + E)", formula("complement", f"B{layout.wacc_debt_weight}")),
        layout.wacc_value: (
            "WACC",
            formula("weighted_pair", f"B{layout.wacc_cost_of_equity}",
                    f"B{layout.wacc_equity_weight}",
                    f"B{layout.wacc_after_tax_debt}",
                    f"B{layout.wacc_debt_weight}")),
    }
    for row, (label, cell_formula) in rows.items():
        _label(sheet, row, label, bold=row == layout.wacc_value)
        sheet.cell(row, 2, cell_formula)
    sheet.column_dimensions["A"].width = 38


def _write_model(sheet, result: DcfResult, layout: Layout) -> None:
    _title(sheet, "Model — the explicit forecast (4.5)",
           "Drivers are the Section 3 bridge, not independent assumptions.")
    labels = {
        layout.model_period: "Period",
        layout.model_revenue: "Revenue",
        layout.model_ebitda: "EBITDA",
        layout.model_depreciation: "Depreciation and amortisation",
        layout.model_ebit: "EBIT",
        layout.model_tax: "Tax on EBIT",
        layout.model_capex: "Capital expenditure",
        layout.model_nwc: "Change in net working capital",
        layout.model_ufcf: "Unlevered free cash flow",
    }
    for row, text in labels.items():
        _label(sheet, row, text,
               bold=row in (layout.model_period, layout.model_ufcf))

    for index in range(len(result.inputs.forecast)):
        col = layout.column(index)
        set_ = lambda row, value: sheet.cell(  # noqa: E731 - local, one line
            row, layout.first_period_column + index, value)

        set_(layout.model_period,
             f"={SHEET_INPUTS}!{col}{layout.period_row}")
        previous = (_inp(layout, "base_revenue") if index == 0
                    else f"{layout.column(index - 1)}{layout.model_revenue}")
        set_(layout.model_revenue,
             formula("grow_by", previous, _driver(layout, "revenue_growth", index)))
        set_(layout.model_ebitda,
             formula("product", f"{col}{layout.model_revenue}",
                     _driver(layout, "ebitda_margin", index)))
        set_(layout.model_depreciation, f"={_driver(layout, 'depreciation', index)}")
        set_(layout.model_ebit,
             formula("difference", f"{col}{layout.model_ebitda}",
                     f"{col}{layout.model_depreciation}"))
        set_(layout.model_tax,
             formula("negated_product", f"{col}{layout.model_ebit}",
                     _inp(layout, "tax_rate", absolute=True)))
        set_(layout.model_capex, f"={_driver(layout, 'capex', index)}")
        set_(layout.model_nwc, f"={_driver(layout, 'change_in_nwc', index)}")
        set_(layout.model_ufcf,
             formula("sum", f"{col}{layout.model_ebitda}", f"{col}{layout.model_tax}",
                     f"{col}{layout.model_capex}", f"{col}{layout.model_nwc}"))

    sheet.column_dimensions["A"].width = 38


def _write_dcf(sheet, result: DcfResult, layout: Layout) -> None:
    _title(sheet, "DCF — discounting and the equity bridge (4.6, 4.9)",
           "Terminal value is built from the final UNDISCOUNTED cash flow.")
    periods = len(result.inputs.forecast)
    last = layout.column(periods - 1)
    wacc = f"{SHEET_WACC}!$B${layout.wacc_value}"

    for row, text in {layout.dcf_period: "Period",
                      layout.dcf_exponent: "Discount exponent (years)",
                      layout.dcf_factor: "Discount factor",
                      layout.dcf_flow: "Cash flow discounted",
                      layout.dcf_present_value: "Present value"}.items():
        _label(sheet, row, text, bold=row == layout.dcf_period)

    for index in range(periods):
        col = layout.column(index)
        set_ = lambda row, value: sheet.cell(  # noqa: E731
            row, layout.first_period_column + index, value)
        set_(layout.dcf_period, f"={SHEET_MODEL}!{col}{layout.model_period}")
        stub = _inp(layout, "stub_fraction", absolute=True)
        set_(layout.dcf_exponent,
             f"={stub}" if index == 0 else f"={stub}+{index}")
        set_(layout.dcf_factor,
             formula("discount_factor", wacc, f"{col}{layout.dcf_exponent}"))
        # The stub period contributes a pro-rated slice of its cash flow (4.5).
        set_(layout.dcf_flow,
             formula("product", f"{SHEET_MODEL}!{col}{layout.model_ufcf}", stub)
             if index == 0 else f"={SHEET_MODEL}!{col}{layout.model_ufcf}")
        set_(layout.dcf_present_value,
             formula("product", f"{col}{layout.dcf_flow}",
                     f"{col}{layout.dcf_factor}"))

    first = layout.column(0)
    totals = {
        layout.dcf_pv_forecast: (
            "PV of explicit forecast",
            sum_range(f"{first}{layout.dcf_present_value}",
                      f"{last}{layout.dcf_present_value}")),
        layout.dcf_terminal_value: (
            "Terminal value",
            formula("perpetuity", f"{SHEET_MODEL}!{last}{layout.model_ufcf}",
                    _inp(layout, "terminal_growth"), wacc)),
        layout.dcf_pv_terminal: (
            "PV of terminal value",
            formula("product", f"B{layout.dcf_terminal_value}",
                    f"{last}{layout.dcf_factor}")),
        layout.dcf_enterprise_value: (
            "Enterprise value",
            formula("sum", f"B{layout.dcf_pv_forecast}",
                    f"B{layout.dcf_pv_terminal}")),
        layout.dcf_equity_value: (
            "Equity value",
            formula("sum", f"B{layout.dcf_enterprise_value}",
                    _inp(layout, "total_debt"),
                    _inp(layout, "cash_and_equivalents"))),
        layout.dcf_share_price: (
            "Implied share price",
            formula("ratio", f"B{layout.dcf_equity_value}",
                    _inp(layout, "shares_outstanding"))),
    }
    for row, (label, cell_formula) in totals.items():
        _label(sheet, row, label, bold=row == layout.dcf_share_price)
        sheet.cell(row, 2, cell_formula)

    sheet.column_dimensions["A"].width = 38


def _write_summary(sheet, result: DcfResult, layout: Layout) -> None:
    inputs = result.inputs
    _title(sheet, f"Summary — {inputs.currency} {inputs.unit}",
           "Every figure below is a reference. Nothing is typed on this sheet.")
    rows = {
        4: ("Implied share price", f"={SHEET_DCF}!B{layout.dcf_share_price}"),
        5: ("Enterprise value", f"={SHEET_DCF}!B{layout.dcf_enterprise_value}"),
        6: ("PV of explicit forecast", f"={SHEET_DCF}!B{layout.dcf_pv_forecast}"),
        7: ("PV of terminal value", f"={SHEET_DCF}!B{layout.dcf_pv_terminal}"),
        8: ("Terminal value share of EV",
            formula("ratio", f"{SHEET_DCF}!B{layout.dcf_pv_terminal}",
                    f"{SHEET_DCF}!B{layout.dcf_enterprise_value}")),
        9: ("WACC", f"={SHEET_WACC}!B{layout.wacc_value}"),
        10: ("WACC less terminal growth",
             formula("difference", f"{SHEET_WACC}!B{layout.wacc_value}",
                     _inp(layout, "terminal_growth"))),
    }
    for row, (label, cell_formula) in rows.items():
        _label(sheet, row, label, bold=row == 4)
        sheet.cell(row, 2, cell_formula)
    sheet.column_dimensions["A"].width = 34


def write_workbook(result: DcfResult, path: str | Path,
                   layout: Layout = LAYOUT) -> Path:
    """Write the valuation as live formulas. Returns the path written."""
    if result.conventions != Conventions.SPEC:
        diverging = ", ".join(result.conventions.divergences(Conventions.SPEC))
        raise ExportError(
            f"refusing to export a model whose conventions diverge from the "
            f"framework: {diverging}. reader.py can READ a defective workbook "
            f"-- that is what the audit is for -- but emitting formulas that "
            f"implement the defect would ship it.")

    book = Workbook()
    inputs_sheet = book.active
    inputs_sheet.title = SHEET_INPUTS
    _write_inputs(inputs_sheet, result, layout)
    _write_wacc(book.create_sheet(SHEET_WACC), layout)
    _write_model(book.create_sheet(SHEET_MODEL), result, layout)
    _write_dcf(book.create_sheet(SHEET_DCF), result, layout)
    _write_summary(book.create_sheet(SHEET_SUMMARY), result, layout)

    path = Path(path)
    book.save(path)
    return path
