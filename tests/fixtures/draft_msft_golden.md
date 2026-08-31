# Microsoft — Company Overview

**Conclusion.** Microsoft turns a dollar of revenue into 46.8% [^M1] of operating
profit, and the marginal dollar increasingly comes from Intelligent Cloud, which
grew 29.7% [^M2] against 17.8% [^M3] for the company as a whole. The segment now
carries 41.5% [^M4] of group revenue at a 41.3% [^M5] operating margin — below
the 59.9% [^M6] Productivity margin, so the mix shift the growth story depends on
is dilutive to group margin, not accretive to it. That tension is the thing to
underwrite.

Revenue reached $331.8 billion [^F1] in the year ended 30 June 2026, against
$281.7 billion [^F2] the year before. Operating income of $155.2 billion [^F3]
compares with $128.5 billion [^F4], a 20.8% [^M7] increase — faster than revenue,
so operating leverage is visible in the reported numbers rather than merely
asserted.

Research and development ran at $35.6 billion [^F5], or 10.7% [^M8] of revenue.
Stock-based compensation of $12.4 billion [^F6] is a real cost against
7,453 million shares [^F7] diluted, and diluted earnings were $17.95 [^F8] per
share. Against a share price of $512.40 [^E1], that is 28.5x [^M9] trailing
earnings.

## Segment mix

| Segment | Revenue ($m) | Operating profit ($m) |
|---|---|---|
| Productivity and Business Processes | 139,996 [^F9] | 83,879 [^F10] |
| Intelligent Cloud | 137,791 [^F11] | 56,972 [^F12] |
| More Personal Computing | 54,052 [^F13] | 14,386 [^F14] |

More Personal Computing runs a 26.6% [^M10] margin, less than half the
Productivity segment's, and its revenue fell from $54.6 billion [^F15] a year
earlier — the only segment going backwards.

## Model cells

```yaml
group_op_margin_fy26:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: operating_income, period_end: 2026-06-30}
    - {cik: 789019, concept: revenue, period_end: 2026-06-30}

ic_revenue_growth_fy26:
  op: growth
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: revenue, period_end: 2026-06-30,
       segments: {us-gaap:StatementBusinessSegmentsAxis: msft:IntelligentCloudMember}}
    - {cik: 789019, concept: revenue, period_end: 2025-06-30,
       segments: {us-gaap:StatementBusinessSegmentsAxis: msft:IntelligentCloudMember}}

group_revenue_growth_fy26:
  op: growth
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: revenue, period_end: 2026-06-30}
    - {cik: 789019, concept: revenue, period_end: 2025-06-30}

ic_share_of_revenue_fy26:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: revenue, period_end: 2026-06-30,
       segments: {us-gaap:StatementBusinessSegmentsAxis: msft:IntelligentCloudMember}}
    - {cik: 789019, concept: revenue, period_end: 2026-06-30}

ic_margin_fy26:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: operating_income, period_end: 2026-06-30,
       segments: {us-gaap:StatementBusinessSegmentsAxis: msft:IntelligentCloudMember}}
    - {cik: 789019, concept: revenue, period_end: 2026-06-30,
       segments: {us-gaap:StatementBusinessSegmentsAxis: msft:IntelligentCloudMember}}

pbp_margin_fy26:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: operating_income, period_end: 2026-06-30,
       segments: {us-gaap:StatementBusinessSegmentsAxis: msft:ProductivityAndBusinessProcessesMember}}
    - {cik: 789019, concept: revenue, period_end: 2026-06-30,
       segments: {us-gaap:StatementBusinessSegmentsAxis: msft:ProductivityAndBusinessProcessesMember}}

mpc_margin_fy26:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: operating_income, period_end: 2026-06-30,
       segments: {us-gaap:StatementBusinessSegmentsAxis: msft:MorePersonalComputingMember}}
    - {cik: 789019, concept: revenue, period_end: 2026-06-30,
       segments: {us-gaap:StatementBusinessSegmentsAxis: msft:MorePersonalComputingMember}}

group_op_income_growth_fy26:
  op: growth
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: operating_income, period_end: 2026-06-30}
    - {cik: 789019, concept: operating_income, period_end: 2025-06-30}

rnd_intensity_fy26:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {cik: 789019, concept: research_and_development, period_end: 2026-06-30}
    - {cik: 789019, concept: revenue, period_end: 2026-06-30}

trailing_pe:
  op: ratio
  quantize: "0.000001"
  inputs:
    - {external: msft_price_20260828}
    - {cik: 789019, concept: diluted_eps, period_end: 2026-06-30}
```

## Citation index

```yaml
F1:  {kind: fact, cik: 789019, concept: revenue, period_end: 2026-06-30}
F2:  {kind: fact, cik: 789019, concept: revenue, period_end: 2025-06-30}
F3:  {kind: fact, cik: 789019, concept: operating_income, period_end: 2026-06-30}
F4:  {kind: fact, cik: 789019, concept: operating_income, period_end: 2025-06-30}
F5:  {kind: fact, cik: 789019, concept: research_and_development, period_end: 2026-06-30}
F6:  {kind: fact, cik: 789019, concept: share_based_compensation, period_end: 2026-06-30}
F7:  {kind: fact, cik: 789019, concept: diluted_shares, period_end: 2026-06-30}
F8:  {kind: fact, cik: 789019, concept: diluted_eps, period_end: 2026-06-30}
F9:  {kind: fact, cik: 789019, concept: revenue, period_end: 2026-06-30,
      segments: {us-gaap:StatementBusinessSegmentsAxis: msft:ProductivityAndBusinessProcessesMember}}
F10: {kind: fact, cik: 789019, concept: operating_income, period_end: 2026-06-30,
      segments: {us-gaap:StatementBusinessSegmentsAxis: msft:ProductivityAndBusinessProcessesMember}}
F11: {kind: fact, cik: 789019, concept: revenue, period_end: 2026-06-30,
      segments: {us-gaap:StatementBusinessSegmentsAxis: msft:IntelligentCloudMember}}
F12: {kind: fact, cik: 789019, concept: operating_income, period_end: 2026-06-30,
      segments: {us-gaap:StatementBusinessSegmentsAxis: msft:IntelligentCloudMember}}
F13: {kind: fact, cik: 789019, concept: revenue, period_end: 2026-06-30,
      segments: {us-gaap:StatementBusinessSegmentsAxis: msft:MorePersonalComputingMember}}
F14: {kind: fact, cik: 789019, concept: operating_income, period_end: 2026-06-30,
      segments: {us-gaap:StatementBusinessSegmentsAxis: msft:MorePersonalComputingMember}}
F15: {kind: fact, cik: 789019, concept: revenue, period_end: 2025-06-30,
      segments: {us-gaap:StatementBusinessSegmentsAxis: msft:MorePersonalComputingMember}}
M1:  {kind: model, cell: group_op_margin_fy26}
M2:  {kind: model, cell: ic_revenue_growth_fy26}
M3:  {kind: model, cell: group_revenue_growth_fy26}
M4:  {kind: model, cell: ic_share_of_revenue_fy26}
M5:  {kind: model, cell: ic_margin_fy26}
M6:  {kind: model, cell: pbp_margin_fy26}
M7:  {kind: model, cell: group_op_income_growth_fy26}
M8:  {kind: model, cell: rnd_intensity_fy26}
M9:  {kind: model, cell: trailing_pe}
M10: {kind: model, cell: mpc_margin_fy26}
E1:  {kind: ext, record: msft_price_20260828}
```
