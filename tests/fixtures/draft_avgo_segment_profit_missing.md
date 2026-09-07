<!-- DEGRADED FIXTURE. The segment mix shown revenue-only: profit column, profit shares and both segment-profit anchors removed together, so nothing dangles. Trips segment_profit_missing and nothing else. -->
# Broadcom — Company Overview

**Conclusion.** Broadcom is two businesses of similar profit weight wearing one
semiconductor label. Semiconductor Solutions sells 57.69% [^M1] of the revenue
and Infrastructure Software sells 42.31% [^M3]. The semiconductor half is
the larger of the two.

Revenue reached $63,887 million [^F1] in the year ended 2 November 2025, against
$51,574 million [^F2] the year before, a 23.87% [^M7] increase. Operating income
of $25,484 million [^F3] is 39.89% [^M8] of revenue, and gross profit of
$43,294 million [^F4] is 67.77% [^M9] — a gross margin the semiconductor
half alone does not explain.

Research and development ran at $10,977 million [^F5], or 17.18% [^M10] of
revenue. Share-based compensation of $7,568 million [^F6] is 11.85% [^M11] of
revenue and a real cost against reported profit. Operating cash flow of
$27,537 million [^F7] less capital expenditure of $623 million [^F8] leaves free
cash flow of $26,914 million [^M12], a 42.13% [^M13] margin — capital intensity
of 0.98% [^M14] of revenue is a fabless economic profile, not a fab owner's.

Contracted revenue not yet recognised stands at $33,300 million [^F9] against
$20,500 million [^F10], a 62.44% [^M15] increase, so the software half is
selling duration rather than seats.

## Segment mix

| Segment | Revenue ($m) |
|---|---|
| Semiconductor Solutions | 36,858 [^F11] |
| Infrastructure Software | 27,029 [^F13] |

## Model cells

```yaml
avgo_semis_revenue_share:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02,
       segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:SemiconductorSolutionsMember}}
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02}

avgo_infra_revenue_share:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02,
       segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:InfrastructureSoftwareMember}}
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02}

avgo_segment_profit:
  op: sum
  inputs:
    - {cik: 1730168, concept: operating_income, period_end: 2025-11-02,
       segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:SemiconductorSolutionsMember}}
    - {cik: 1730168, concept: operating_income, period_end: 2025-11-02,
       segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:InfrastructureSoftwareMember}}

avgo_semis_profit_share:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: operating_income, period_end: 2025-11-02,
       segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:SemiconductorSolutionsMember}}
    - {cell: avgo_segment_profit}

avgo_infra_profit_share:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: operating_income, period_end: 2025-11-02,
       segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:InfrastructureSoftwareMember}}
    - {cell: avgo_segment_profit}

avgo_semis_margin:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: operating_income, period_end: 2025-11-02,
       segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:SemiconductorSolutionsMember}}
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02,
       segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:SemiconductorSolutionsMember}}

avgo_infra_margin:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: operating_income, period_end: 2025-11-02,
       segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:InfrastructureSoftwareMember}}
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02,
       segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:InfrastructureSoftwareMember}}

avgo_revenue_growth:
  op: growth
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02}
    - {cik: 1730168, concept: revenue, period_end: 2024-11-03}

avgo_op_margin:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: operating_income, period_end: 2025-11-02}
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02}

avgo_gross_margin:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: gross_profit, period_end: 2025-11-02}
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02}

avgo_rd_intensity:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: research_and_development, period_end: 2025-11-02}
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02}

avgo_sbc_intensity:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: share_based_compensation, period_end: 2025-11-02}
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02}

avgo_free_cash_flow:
  op: difference
  unit: USD
  inputs:
    - {cik: 1730168, concept: operating_cash_flow, period_end: 2025-11-02}
    - {cik: 1730168, concept: capex, period_end: 2025-11-02}

avgo_fcf_margin:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cell: avgo_free_cash_flow}
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02}

avgo_capex_intensity:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: capex, period_end: 2025-11-02}
    - {cik: 1730168, concept: revenue, period_end: 2025-11-02}

avgo_rpo_growth:
  op: growth
  quantize: "0.000001"
  inputs:
    - {cik: 1730168, concept: remaining_performance_obligation, period_end: 2025-11-02}
    - {cik: 1730168, concept: remaining_performance_obligation, period_end: 2024-11-03}
```

## Citation index

```yaml
F1:  {kind: fact, cik: 1730168, concept: revenue, period_end: 2025-11-02}
F2:  {kind: fact, cik: 1730168, concept: revenue, period_end: 2024-11-03}
F3:  {kind: fact, cik: 1730168, concept: operating_income, period_end: 2025-11-02}
F4:  {kind: fact, cik: 1730168, concept: gross_profit, period_end: 2025-11-02}
F5:  {kind: fact, cik: 1730168, concept: research_and_development, period_end: 2025-11-02}
F6:  {kind: fact, cik: 1730168, concept: share_based_compensation, period_end: 2025-11-02}
F7:  {kind: fact, cik: 1730168, concept: operating_cash_flow, period_end: 2025-11-02}
F8:  {kind: fact, cik: 1730168, concept: capex, period_end: 2025-11-02}
F9:  {kind: fact, cik: 1730168, concept: remaining_performance_obligation,
      period_end: 2025-11-02}
F10: {kind: fact, cik: 1730168, concept: remaining_performance_obligation,
      period_end: 2024-11-03}
F11: {kind: fact, cik: 1730168, concept: revenue, period_end: 2025-11-02,
      segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:SemiconductorSolutionsMember}}
F13: {kind: fact, cik: 1730168, concept: revenue, period_end: 2025-11-02,
      segments: {us-gaap:StatementBusinessSegmentsAxis: avgo:InfrastructureSoftwareMember}}
M1:  {kind: model, cell: avgo_semis_revenue_share}
M3:  {kind: model, cell: avgo_infra_revenue_share}
M7:  {kind: model, cell: avgo_revenue_growth}
M8:  {kind: model, cell: avgo_op_margin}
M9:  {kind: model, cell: avgo_gross_margin}
M10: {kind: model, cell: avgo_rd_intensity}
M11: {kind: model, cell: avgo_sbc_intensity}
M12: {kind: model, cell: avgo_free_cash_flow}
M13: {kind: model, cell: avgo_fcf_margin}
M14: {kind: model, cell: avgo_capex_intensity}
M15: {kind: model, cell: avgo_rpo_growth}
```
