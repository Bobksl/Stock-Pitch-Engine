"""Framework 4.12 — the workbook as a two-way interface, not a report.

Two directions, deliberately separate modules. `workbook`/`readback` write and
re-read *our own* export. `reader`/`audit` read a *foreign* workbook: somebody
else's model, whose formulas are the evidence being audited.
"""
