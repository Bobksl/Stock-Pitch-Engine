# AI Equity Research Framework — v1.2

**Owner:** Bob Liang  ·  **Status:** Approved for build  ·  **Date:** 2026-09-01
**Scope:** US-listed equities (SEC EDGAR), position horizon (months–quarters), IT sector first
**Output:** Polished shareable pitch + auditable Excel valuation model
**Mode:** Interactive co-pilot, section by section

## Changelog

**v1.2 — 2026-09-01**

- **§4.5** — stub-period discounting convention stated explicitly, and **§4.13** — the matching Class A rule added. Phase 2 found the gap while enumerating the rule registry: the defect is required to be flagged and Class A by the Phase 2 exit criterion, but no §4.13 rule covered it. The audit's §2.10 mapping table asserts every one of its findings is caught by an existing rule and omits this one, so the claim was false rather than the rule merely unwritten.
- **§4.13** — beta sourced from a terminal listed as its own Class A rule. §4.13 previously named only "WACC copied from a terminal"; §4.4 states the beta policy in its own right, and the two are separately detectable and separately reported.

**v1.1 — 2026-08-31**

- **P2, §1.3** — segment facts sourced from the inline-XBRL instance; `companyfacts` demoted to reconciliation oracle (D1)
- **P3, §6.4** — provenance model expanded: three provenance classes, anchor-based resolution, `Decimal` recomputation (D5–D9)
- **§2.4** — fiscal-period alignment convention stated explicitly (D3)
- **§4.6** — terminal-value threshold is a single hard 75%; the 70% figure removed
- **§4.13** — restructured into Class A / Class B rules
- **§6.5** — new: QC rule classes and exception records
- **§8, C10** — restated against the provenance model

**Maintenance rule.** Any decision whose `Spec ref` names a section requires an amendment to that section in the same phase-boundary pass that moves the decision to Decided. The spec is a third artifact alongside the repo and the project page, and it is the one that drifts silently.

---

## 0. Governing Principles

These override any section-level rule in conflict.

**P1 — Two loops.** Research/synthesis (LLM-assisted) is separate from calculation and execution (deterministic code). An LLM never computes a number that appears in an output.

**P2 — Numbers from XBRL, narrative from RAG.** Vector retrieval is never the source of a figure. All financial data comes from the **inline-XBRL instance** of the filing itself, parsed into the facts table; `companyfacts` is a reconciliation oracle, not a source (§1.3). RAG answers "how does management describe X," never "what was X."

**P3 — Every figure carries declared provenance.** Each number in any output resolves to one of exactly three provenance classes — fact, derived, or external (§6.4). Resolution is anchor-based; derived figures are recomputed in `Decimal` at verification time. An unresolvable figure is a hard failure, not a warning. There is no allowlist and no severity ladder.

**P4 — Insight over facts.** Every sentence must answer "so what for the thesis?" A sentence that states a fact without consequence is cut.

**P5 — Conclusion first.** Research order (1→5) is not presentation order. Every section leads with its conclusion.

**P6 — The framework may conclude "pass."** Passes are logged with reasoning and reviewed. A pipeline that never declines is not screening.

**P7 — No marketing language.** Filings are promotional by construction. Banned-phrase list enforced at QC. *Carve-out:* newly disclosed revenue streams or segments are escalated for evaluation even when described in promotional language (see §6.2).

---

## 1. Section 1 — Company Overview

### 1.1 Objective
Convey the **economic engine** in layman's terms — how a dollar of revenue becomes a dollar of profit — and establish the 3–4 structural facts later sections stand on. Not a description of the business.

### 1.2 Inputs
| Source | Use |
|---|---|
| 10-K Item 1 (Business) | Business model, customers, competition framing |
| 10-K Item 7 (MD&A) | Management's driver explanation |
| Segment footnote (ASC 280) | Segment revenue **and operating profit** |
| Revenue disaggregation (ASC 606) | Revenue by type, geography, timing |
| Latest 10-Q | Current mix, seasonality |
| S-1 | Recent listings |
| Earnings calls (Bloomberg) | Management framing, analyst concerns |

### 1.3 Deterministic Extraction

**Source of record.** Facts are parsed from the **inline-XBRL instance** of the filing itself, which preserves the dimensional qualifiers (axis/member) that segment and disaggregated figures depend on. The `companyfacts` API is **not** the source — it drops dimensions, so segment breakdowns are not obtainable from it at all — and is retained as an **independent reconciliation oracle**: undimensioned consolidated totals are cross-checked against it, and disagreement is a hard failure.

Constraints established in Phase 0:

- A period's segment breakdown must come from a **single filing**. Filers rename segment members and re-file; mixing vintages silently fabricates a breakdown.
- `sign="-"` is part of the value, not a display hint.
- Duplicate facts at differing precision are legal and must be reconciled, not rejected.
- `companyfacts` rounds sub-cent fractions; reconciliation tolerance must be explicit.
- A tagged fact can be an English word (SEC `numwordsen` transformation).
- Filers restate, so any question of the form "what did the market know at time T" requires an `as_of` filing date, not merely a fiscal period.

**Extracted fields:**

- Revenue by segment / geography / product, 3–5 years
- **Segment operating profit and margin by segment** — required, not optional
- Gross / operating / EBITDA margin history
- Quarterly revenue (seasonality detection)
- Deferred revenue, RPO / cRPO, contract balances
- Customer concentration (Item 1 + concentration footnote)
- Disclosed KPIs per sector taxonomy (§7)
- Fully diluted share count, SBC, dilution path

### 1.4 Judgment Layer

**a. Plain-English description.** What it sells, to whom, who writes the check. No company adjectives.

**b. Driver controllability.** Decompose growth into volume / price / mix, then classify each driver as **company-controlled** (product, pricing, distribution) or **externally driven** (GDP, commodities, rates, regulation). External drivers require a source and become explicit macro assumptions with their own sensitivity. This ratio caps how much credit management deserves and determines how much of the thesis is a macro bet.
→ *Structured field, carried to Sections 3 and 4.*

**c. Revenue quality.** Recurring / contracted vs. usage vs. transactional, **quantified**. Evidence over labels: deferred revenue, RPO, retention disclosure, contract duration.

**d. Contract structure.** Who bears cost, volume, and duration risk. Cost-plus caps margin and floors risk; fixed-price does the opposite. Applies generally (defense contract mix, committed vs. usage SaaS).
→ *Structured field.*

**e. Cyclicality and seasonality.** Quarterly pattern from data; behaviour through the last downturn.

**f. Pricing power.** Switching costs plus **evidence**: realised price increases, gross margin stability through cost inflation, retention. No number, no claim.

**g. Margin structure and operating leverage.** Fixed vs. variable COGS; incremental margin on the last dollar of revenue; structural (software) vs. headcount-bound (services). **Test against history:** incremental margins over the last 8–12 quarters either demonstrate operating leverage or they don't.

**h. Type classification.** Dominant segment by revenue **and by profit**. Disagreement between the two is itself flagged and discussed.
→ *Join key: determines which industry Section 2 analyses and which comp set Section 4 uses. GICS is the default, overridden by profit-weighted reality.*

### 1.5 Output
~250 words, conclusion first. Required exhibits: revenue **and profit** mix by segment; margin / incremental-margin history; KPI snapshot. Every figure cited.

### 1.6 QC — Fail Conditions
- Banned marketing phrases present
- Pricing-power or operating-leverage claim without a supporting number
- Segment revenue shown without segment profit
- Any sentence failing the "so what" test
- **Recency:** any figure not from the latest filed period, or any prior-year figure without its current-year comparative

---

## 2. Section 2 — Industry Overview

### 2.1 Objective
Industry structure sets the ceiling on returns; company skill decides where beneath it you land. Must conclude two things: **is this a good place to make money, and is this company's position improving or eroding?** Every position-horizon thesis reduces to "structure is better than believed" or "this company is taking share."

### 2.2 Inputs
Target 10-K Items 1 / 1A / 7; **the comp set's own 10-Ks and calls** (competitors describe the same industry differently — the disagreements are the signal); trade and regulatory data; Bloomberg for third-party sizing and share; price history for drawdown analysis.

### 2.3 Comp Set — Two Tiers

| Tier | Definition | Used by |
|---|---|---|
| **Direct competitors** | Same customer, same buying decision, comparable scale | Structural analysis (§2.5) |
| **Valuation reference** | Similar economics, growth, margin profile | Section 4 comps |

Overlapping but distinct. A 10x size gap with a different customer base means *not* a direct competitor. Auto-proposed from the type field and revenue-model tags; **manually approved**, with written justification per member.

### 2.4 Deterministic Extraction — Industry Panel
For every comp-set member, 3–5 years: revenue growth, gross / EBIT margin, ROIC, R&D and capex intensity, revenue share of panel.
Plus **peer drawdown analysis**: define stress windows; compute peak-to-trough drawdown, recovery time, downside capture, correlation, beta.

**Period alignment.** Periods are stored exactly as reported. A calendar mapping is derived separately, following the SEC `frames` convention. The tolerance window of that convention is documented in code, because it determines whether an off-cycle peer is **excluded** from a panel or **mis-assigned** to a calendar period — and the latter silently corrupts every cross-sectional comparison built on the panel. Exclusion is the default; mis-assignment is never acceptable.

*This is the mechanism enforcing §4.8's "same calendar period, same estimate source, across all peers."*

### 2.5 Judgment Layer

**a. Define the market before sizing it**, driven by the type field. Size **bottom-up** (units × price, or customers × ACV), reconcile against any top-down figure. A TAM lifted from an investor deck is the clearest tell of student-grade work.

**b. TAM → SAM → capturable share, with the capture rate defended.**
→ *This is the same number as the DCF's terminal revenue assumption. Link enforced in §8.*

**c. Structure.** Concentration (share dispersion from the panel), entry barriers, buyer and supplier power, substitution, and — most usefully — **what firms compete on**. Price-based and feature-based rivalry produce entirely different margin trajectories.

**d. Profit pool location and migration.** Where in the value chain does profit sit, and is it moving?

**e. Industry-level pricing dynamics.** Customer price sensitivity, switching behaviour, commoditisation.
→ *Distinct from §1.4f: Section 1 asks whether this company has demonstrated pricing power; Section 2 asks whether the structure permits it at all. A company with apparent pricing power in a commoditising industry is a fading asset — only both sections together catch it.*

**f. Growth decomposition** into secular / cyclical / share shift. Buying a cyclical trough and buying a secular winner require different entries and exits.

**g. Cyclicality and macro sensitivity** at industry level.

**h. Competitive position with direction of travel.** Quantitative proxy: **company growth minus peer-median growth**, per year. Sustained positive = share gain; pair with relative margin to see whether it's bought with price.

**i. Peer drawdown interpretation.** *The first place market data enters, and the only input that reveals what the market actually believes about relative quality rather than what it says.* The peer that holds up is telling you something about revenue durability, balance sheet, or customer mix. **If that ranking contradicts the fundamental analysis, one of the two is wrong — and the discrepancy is often where variant perception hides.** Feeds position sizing and entry timing.

**j. Industry lead indicators.** The 2–3 observable series that move before the company's numbers. Feed the monitoring layer and Section 5.

**k. Consensus industry assumptions, and where you differ.**

### 2.6 Output
~400–500 words, conclusion first. Exhibits: industry panel; relative-growth / share chart; peer drawdown table. Explicit stance on structure and direction.

### 2.7 QC — Fail Conditions
- TAM or CAGR without source and derivation method
- Competitor list with no structural conclusion
- Comp set inherited from GICS without type-field justification
- No conclusion on profit capture
- Missing tier tags or justifications

### 2.8 Industry Primer Caching
Industry work is cached as a **versioned primer**, reusable across names in the same sector, refreshed quarterly. Pitches reference a primer version. Saves duplicated effort and enforces internal consistency across your coverage.

---

## 3. Section 3 — Investment Thesis

### 3.1 Objective
Name the story, then decompose it into quantified drivers. Sections 1–2 establish what is **true**; Section 3 establishes what is **not yet priced**. A thesis describing a good company without identifying a mispricing is not a thesis — quality is not an edge if everyone agrees on it.

### 3.2 Step 0 — Evidence Inventory
Dump every structured field from Sections 1–2, then reason down the list to a conclusion. Makes the story **derived**, not asserted. *This step exists specifically to stop the model picking a narrative first and back-filling support — its default failure mode.*

### 3.3 Step 1 — Name the Story (one primary archetype)

| Archetype | Return comes from | Required bridge |
|---|---|---|
| **Growth** | Volume, price, mix, new products, share | Revenue bridge |
| **Margin / self-help** | Operating leverage, cost, mix, M&A integration | Margin bridge |
| **Re-rating** | Multiple expansion | Multiple bridge |
| **Cycle / timing** | Macro regime positioning | Macro linkage |
| **Dislocation / optionality** | Mispriced segment, SOTP, overreaction | Value gap |

The choice is load-bearing in both directions: pitching a commoditised, capped-upside name as a growth story is the wrong archetype, while the same facts make a sound defensive pitch.
→ *Determines Section 4 method weighting.*

### 3.4 Step 2 — The Driver Bridge (the heart of the section)
Archetype-specific, quantified, and **components must sum to the headline forecast**.

- **Growth story → revenue bridge.** Each component gets a rate, a driver, and a source.
  *Reference construction:* GDP / consumption → 3–4%; capacity-shortage-enabled pricing → 3–4%; total 6–8%. Every leg separately defensible and separately falsifiable.
- **Margin story → margin bridge by lever, with a benchmark proving attainability.**
  **Rule — existence proof required:** a margin target needs a peer achieving it, a subsegment already at it, or the company's own history. (25% vs. a nearest competitor at 14% is what makes "+1–2%/yr" credible rather than hopeful.)
- **Re-rating story → multiple bridge** with a *named structural mechanism* (revenue-quality mix shift, deleveraging, comp-set reclassification, coverage or index inclusion, capital allocation). Assertion that the market will feel better is not a mechanism.
- **Cycle story →** the macro variable, current regime read, and what breaks the position on a regime shift.

**Two required tags per driver:**
1. **Internal vs. external** (inherited from §1.4b)
2. **Model line** — which forecast input it feeds. *A driver touching no model line is colour, not thesis.*

### 3.5 Step 3 — Variant Perception
Consensus assumes X (BEst, by forward year); the bridge produces Y; the gap sits in **this specific leg**. Because it is a bridge rather than a vibe, the disagreement is located, testable, and monitorable.

### 3.6 Step 4 — Why Now
**Mispricing mechanism**, named: time-horizon arbitrage, misunderstood or under-disclosed segment, one-off optics, forced or index selling, complexity or spin-off, post-earnings drift, narrative lag. *If you cannot name the mechanism, the market probably is not wrong — you are.*
**Catalyst path with dates**, inside 2–4 quarters. For cycle stories the catalyst is a macro print, not a company event — which is why archetype is named first.

### 3.7 Step 5 — Falsifiers, Expiry, Other Side
Per bridge leg: what observation kills it. Plus review date, one-line pre-mortem ("if this is down 30% in six months, the likeliest cause is ___"), and a steelmanned bear argument.
→ *Hands to Section 5 and the monitoring layer.*

### 3.8 Output
Conclusion first: direction, target, horizon, conviction, intended size. Then archetype, bridge, variant perception, catalysts, falsifiers.

### 3.9 QC — Fail Conditions
- Bridge components do not sum to the forecast (arithmetic)
- Any driver without a source or a model line
- Margin target without an existence proof
- More than one primary archetype
- Catalyst without a date window
- Pillar restating consensus
- More than 3 pillars ("if you need five reasons, you don't have one")
- Laundry list of company positives masquerading as thesis

---

## 4. Section 4 — Valuation

### 4.1 Objective
Prove the target price and be transparent about the 3–4 assumptions that determine it. The output is a defensible range plus a clear statement of what is being bet on.

### 4.2 Method Weighting Follows Archetype
DCF-led for growth and margin stories; comps-led for re-rating; normalised / mid-cycle earnings for cycle stories. **Always triangulate all three and explain why they disagree** — the reconciliation is usually more informative than any single output.
*Never assign 100% weight to a single method.*

### 4.3 WACC — Built From Inputs, Never Copied

**Cost of equity**
- Risk-free: on-the-run sovereign matched to cash-flow duration
- ERP: chosen and justified, not inherited
- **Beta: compute both, default to peer-median unlevered relevered** (see §4.4)

**Cost of debt**
- Issue-level spreads or CDS — **not** book interest expense, which reflects legacy issuance rather than marginal cost

**Structure**
- Market-value weights; **equity weight = market capitalisation** (do not net debt out of market cap)
- Target rather than spot structure where the balance sheet is in transition
- Capitalised leases as debt
- Marginal (not effective) tax rate with a stated path

### 4.4 Beta — Resolved Policy
**Compute both; default to peer-median unlevered beta, relevered to target structure.**

*Rationale.* Single-name regression betas are statistically noisy — wide standard errors, materially sensitive to window, frequency, and index — and contaminated by idiosyncratic history that says nothing about forward business risk, which is what a discount rate must capture. Peer-median betas average that noise away and isolate business risk.

*Qualifications.*
- Apply a Blume adjustment (⅔β + ⅓) toward 1.0; betas mean-revert
- Prefer regression beta only when the name is large, liquid, long-listed, and genuinely lacks a comp set — or when the thesis is specifically that its risk profile differs from peers
- Recent IPOs: regression beta is unavailable, not merely noisy. Peer-relevered is the only defensible choice
- If the thesis involves mix shift, blend segment betas and relever at target structure

*The spread is diagnostic and must be shown.* A regression beta well above peer-relevered means the market prices the name as riskier than its business model implies — either a mispricing to exploit or something the fundamental work missed. Belongs in the thesis discussion, not buried in the WACC tab.

### 4.5 Forecast Drivers — Hard Linkage
**The DCF's forecast drivers ARE the Section 3 bridge.** Not new assumptions. If modelled revenue growth does not equal the bridge components summed, one is wrong. Automated check (§8).

**Stub periods.** A valuation struck part-way through a period discounts a **pro-rated slice** of that period's cash flow at the matching partial-period factor. Either count the fraction of the period that remains, or discount a full period at a full-period factor — never a full period of cash flow at a partial-period factor, which collects a year of cash for a month of waiting. Class A: this is an arithmetic error, not a modelling preference.

### 4.6 Terminal Value Discipline
- Perpetuity growth ≤ long-run **nominal** GDP. *Do not apply a real growth rate to nominal cash flows.*
- Always cross-check the implied exit multiple against comps and the company's own history
- **Fail when TV > 75% of enterprise value.** Single threshold, hard block, **Class B** (exceptionable — see §6.5). The QC report prints the measured TV share on **every** run, pass or fail, as a reported measurement rather than a warning tier.
- **Fail when WACC − g < 4pp** — below this the model is a terminal-value assumption wearing a DCF as a disguise. Class B.
- Report target-price sensitivity to ±50bp on g alongside every DCF output

*A non-blocking lower tier was considered and rejected: an observation that cannot block is a warning by another name, and that breaches P3. Printing the measured value on every run delivers the same visibility without a second passing state.*

### 4.7 Reverse DCF — Required
Back out what today's price implies for growth and margins, then argue why that is wrong. Often more persuasive than the forward DCF for re-rating and "market misunderstands this" theses, and cheap once the model exists.

### 4.8 Comparable Company Analysis

**Pairing rule — enforced as a hard error, not a warning:**

| Numerator | Pairs with | Rationale |
|---|---|---|
| Enterprise Value | Sales, EBITDA, EBIT | Pre-interest metrics, available to all capital providers |
| Equity Value | Earnings, FCFE, Book | Post-interest metrics, available to equity only |

**Metric selection decision tree:**

| Condition | Metric | Note |
|---|---|---|
| Profitable, D&A material | **EV/EBITDA** | Default. Neutral to capital structure, tax, non-recurring items |
| Profitable, D&A immaterial | **EV/EBIT** | Decent operating cash-flow proxy |
| Unprofitable, high growth, long runway | **EV/Sales** | Explicitly a placeholder; graduates to EV/EBITDA once margins arrive |
| Heavy reinvestment, earnings distorted | **P/FCF** | Earnings manipulable; cash is not |
| Financials | **P/E, P/B** | Interest is operating, not financing |

**The multiple is a function of the business model.** Software commands higher multiples than hardware because of structurally superior margin trajectory, lower capital intensity, and longer growth runway — not sentiment. Consequences:
1. **Sanity gate:** if the model implies a multiple far outside the sub-industry distribution, flag it and require written justification ("does this hardware company deserve that premium to hardware peers?").
2. **Re-rating theses require a business-model change** — a genuinely new revenue stream or structural shift, not improved sentiment. Enforces §3.4.

**Normalisation.** Growth-adjusted multiples (multiple ÷ growth) as a **cross-check only**. They are PEG's problems transplanted: linear in growth, blind to margin structure, scale, and retention. Two companies growing 25% with different terminal margins do not deserve the same EV/Sales.
**Primary method: regress the multiple on growth and a profitability measure (Rule of 40 for software) across a wide comp set; read the residual.**

**Anchor disclosure — mandatory.** Show the implied multiple under **every** peer anchor, and state the full resulting range in the output.
*Worked example (Reddit at IPO): growth-adjusted, PINS 5.0/19 = 0.263x, SNAP 3.6/16 = 0.225x, RDDT 5.11/25 = 0.204x. Anchoring to PINS → 6.58x → $41.43–44.10, i.e. 22–30% upside. Anchoring to SNAP → 5.62x → $36.76, i.e. **+8% upside**. Same method, same inputs; the headline conclusion is roughly three times larger purely because of which peer was chosen as the anchor — and the source write-up never flags the choice.*

**Consistency requirements.** Same calendar period, same estimate source, same metric definitions across all peers. Minimum comp set size enforced — n=2 is a teaching example, not a valuation.

### 4.9 Price Target Mechanics

```
Implied EV     = Target multiple × Forward metric
Implied Equity = Implied EV + Cash − Debt   (pro-forma, post any offering)
Implied Price  = Implied Equity ÷ Fully diluted shares
Upside         = Implied Price ÷ Current Price − 1
```

**Return decomposition — required output:**

```
Δ Price = Δ Multiple (re-rating)
        + Δ Forward Metric (estimate revision)
        + Time Roll-Forward
```

Maps one-to-one onto Section 3 archetypes: a growth story earns through the second term, a re-rating story through the first. Makes the target decomposable — "of 30% upside, 18 points is estimate revision, 12 is multiple" — which is far more auditable and tells you which catalyst you are waiting on.

**Roll-forward rule:** the multiple always applies to the **forward metric relevant at the valuation date**, with an explicit convention. Applying a multiple to trailing actuals when the market has already moved to next year's estimates is a systematic error.

**Share count and balance sheet:** fully diluted including RSUs and options, with the dilution path shown. Pro-forma cash and shares post-offering for recent IPOs. SBC treated as a real cost. *This is the quiet way retail targets end up 15% too high.*

### 4.10 Scenarios and Sensitivity
- Bull / base / bear tied to **thesis pillars succeeding or failing**, never arbitrary ±10% tweaks
- Probability weights in coarse buckets (default 60 / 25 / 15) — no false decimals
- Probability-weighted expected value, enabling cross-idea ranking in the portfolio layer
- Two-way sensitivity tables on the highest-leverage assumptions, **top 3 named explicitly**

### 4.11 Tactical Timing
Entry level; risk/reward against the bear case; position relative to the §2.5i peer drawdown analysis; **position size derived from quantified downside, not conviction**.

### 4.12 Excel Architecture
Python owns calculation. The workbook is a **two-way interface**, not a report.

Tabs: `Inputs` (all hardcodes, colour-coded, the only place you type) · `WACC` · `Model` · `Comps` · `DCF` · `Scenarios` · `Sensitivity` · `Summary`

Live formulas written via openpyxl so every number is traceable in Excel; Python maintains a parallel calculation so nothing depends on Excel being installed. Overrides typed into `Inputs` are read back into Python.

**Divergence risk is the real hazard of dual-track calculation.** Mitigation: a reconciliation test recalculates the workbook headlessly (LibreOffice) and asserts outputs match Python within tolerance. That test is what makes the design safe.

### 4.13 QC — Fail Conditions

Each rule carries a class (§6.5). **Class A is never exceptionable**; Class B may be satisfied by a declared exception record.

**Class A — correctness**

- Any LLM-computed arithmetic
- WACC copied from a terminal rather than derived *(a sourcing violation, not a shape heuristic)*
- Beta taken from a terminal rather than computed and relevered (§4.4)
- **Terminal value computed from an already-discounted cash flow** (see Audit §2)
- Real growth rate applied to nominal cash flows
- **Stub-period discounting that counts a full period of cash flow** (§4.5)
- Unit or scale mismatch; scale undeclared
- Unresolvable figure
- Numerator/denominator pairing violation
- Comp definitions inconsistent across peers
- Scenarios not traceable to thesis pillars
- Share count not fully diluted
- Target price reverse-engineered from a desired upside
- Anchor range not disclosed
- Excel/Python reconciliation divergence
- Figure not from the latest filed period

**Class B — model shape** *(exceptionable)*

- TV > 75% of enterprise value
- WACC − g spread < 4pp
- Single-method valuation
- Comp set below minimum size

---

## 5. Section 5 — Key Risks & Mitigants

### 5.1 Objective
Identify what actually kills the thesis, size it, show why it is contained — or concede it is not. The real job is making risk **tradeable**: every risk becomes a number in the bear case, an observable in the monitoring layer, and a constraint on position size.

### 5.2 Governing Principle
**Risks attack pillars, not companies.** Every risk maps to a specific leg of the Section 3 bridge. Item 1A boilerplate — cyber, key person, generic macro — is excluded unless it threatens a named pillar. Mechanically enforceable via the required pillar reference.

### 5.3 Required Fields

| Field | Requirement |
|---|---|
| Pillar attacked | Reference to a Section 3 bridge leg |
| Mechanism | Transmission path to a specific model line |
| Quantification | Per-share impact, not adjectives |
| Probability | Coarse bucket, consistent with §4.10 weights |
| Early-warning signal | Specific observable **with a threshold** |
| Mitigant | Structural, demonstrated, or hedgeable — with evidence |
| Residual | What remains after the mitigant |

### 5.4 Mitigant Discipline
A mitigant qualifies only if it is:
- **Structural** — contract duration, backlog coverage, switching costs, balance sheet capacity
- **Demonstrated** — the company came through a prior episode of exactly this (§2.5i drawdown analysis is the evidence base)
- **Hedgeable** — sizing, optionality, a pair

"Management is aware" and "they have a strong team" are **not mitigants** and are flagged automatically. *This is where pitches go soft.*

### 5.5 Ranking
By **probability × impact**, worst first. The common failure is leading with the risk you have the best answer for.

### 5.6 Coverage Checklist
Execution · competitive · industry structure · customer and supplier concentration · regulatory and legal · macro-cycle · financial (leverage, refi, FX) · capital allocation and M&A · governance and ownership · accounting quality · technological disruption.
Risks touching the thesis are written up; the rest get a one-line "screened, not material" so coverage is **auditable rather than assumed**.

### 5.7 Automated Inputs

**a. Accounting-quality screen** (deterministic, from the facts table): DSO and inventory-day trends, accruals ratio, cash conversion, receivables growth vs. revenue growth, capitalised cost changes, non-GAAP or segment redefinitions, auditor changes, restatements, insider selling.

**b. Item 1A year-over-year diff:** risks newly added, risks quietly dropped, language intensified. *New risk-factor language is one of the few genuinely under-exploited signals in filings.* The existing `alerts.py` module is the right tool pointed at a new target.

### 5.8 Upside Risks — Required
What could make this work materially better than base case? A one-directional risk section systematically produces conservative targets.
*Reference case: the Reddit miss was not a downside risk — it was catastrophically underestimating a new revenue stream (AI licensing) that was dismissed because the filing described it in marketing language. See P7 carve-out.*

### 5.9 Output
~300–400 words, conclusion first with the top 2–3 risks named. Full risk table. **Position-sizing conclusion:** max size from quantified downside, stop or invalidation level, correlation with existing book positions.

### 5.10 QC — Fail Conditions
- Item 1A boilerplate present
- Unquantified risk
- Assertion-mitigant
- Risk with no early-warning signal or threshold
- **Top-ranked risk absent from the Section 4 bear case**
- Section 3 steelman not represented as a quantified risk
- No upside risks

---

## 6. Cross-Cutting Rules

### 6.1 Banned Language
Marketing adjectives lifted from filings: "AI-powered," "leading," "world-class," "best-in-class," "end-to-end," "empowers," "revolutionary," "seamless," "innovative," "cutting-edge," "transformative," "synergistic," "robust ecosystem." Enforced by regex at QC.

### 6.2 The Marketing Carve-Out
Stripping promotional adjectives must not discard **substance**. Any newly disclosed revenue stream, segment, or business line is escalated for explicit evaluation *even when described promotionally*. Implemented via the RAG YoY diff: new Item 1 language describing a **new way of making money** is escalated, never filtered.

### 6.3 Recency Rule
Every figure from the latest filed period. Any prior-year figure must appear alongside its current-year comparative. Automated staleness check against the facts table.

### 6.4 Provenance Model

Every figure in every output resolves to a declared provenance record. There are exactly three classes, and there is no fourth.

| Class | Source | Resolution |
|---|---|---|
| **Fact** | Inline-XBRL instance | Cited anchor checked against the facts table |
| **Derived** | Computed from cited facts | Recomputed at verification time |
| **External** | Declared external record | Kind must come from a closed vocabulary |

**Carriage.** A draft carries provenance as Markdown footnote markers in the prose, mapped by a fenced YAML block under a `## Citation index` heading. Markers are **content-addressed, not sequential** — editing prose must not silently renumber markers and invalidate the index.

**Resolution is anchor-based, not search-based.** The draft carries the citation and the verifier checks the cited row. Searching the facts table for a matching value is rejected: many facts share a value, so search produces false positives that resolve successfully while citing the wrong fact. (Settled by measurement in Phase 1.)

**Derived figures are recomputed, never stored.** Recomputation runs in `Decimal` from the cited facts, through a **closed operation vocabulary** — no expression language, no `eval`. Float arithmetic is not acceptable for financial figures.

**External provenance is deliberately narrow.** It exists only for quantities XBRL cannot answer. The closed vocabulary is:

- consensus estimates
- transcript statements
- market prices and returns
- credit spreads and CDS levels
- third-party market sizing
- peer trading multiples

**Anything expressible in XBRL is inadmissible as external.** Without that constraint this class becomes a general bypass for the facts table.

**Scale is read, never inferred.** A figure's scale comes from its table column header. A financial figure in an unlabelled column is `scale undeclared` and fails (Class A).

### 6.5 QC Rule Classes and Exception Records

**Every QC rule is Class A or Class B.**

- **Class A — correctness.** The figure is wrong or unverifiable. **Never exceptionable.**
- **Class B — model shape.** The model is unusual, not wrong. **Exceptionable.**

**There remains exactly one passing state.** An exception is not a severity level and not a dismissed warning — it is a positive, structured, attributed assertion that a named condition was accepted for a declared reason.

Class B rules are heuristics about model shape, and a legitimately long-duration asset — infrastructure concession, pre-revenue biotech, anything carrying a 15-year explicit forecast — can breach them honestly. A hard block with no path would mean the system cannot value those names at all, so the analyst routes around the system. That is strictly worse than a reviewable exception.

**Exception record fields**

| Field | Rule |
|---|---|
| Condition | Which Class B rule, and the measured value |
| Reason | Closed vocabulary: `long_duration_asset`, `pre_revenue`, `regulated_concession` |
| Detail | Free text, supplementary only — never load-bearing |
| Author | Named |
| Date | Set at creation |
| Expiry | **Required.** Exceptions must not calcify into permanent carve-outs |

Closed classification is what makes exceptions countable and reviewable. Free text alone would be unauditable.

**Exceptions are published, not merely consumed by the gate.** Any output relying on one carries it visibly:

> Exception: `long_duration_asset` — TV share 84%, above the 75% threshold.

This makes the condition **more** visible to a reader than prose discussion would, not less.

---

## 7. Sector KPI Taxonomy — Information Technology

Fixed per sub-group. Each entry: name, definition, source (XBRL tag or filing text), disclosed vs. derived.

### 7.1 Software / SaaS
ARR · NRR · GRR · net new ARR · RPO and cRPO growth · CAC payback · magic number · Rule of 40 · gross margin split by revenue type (subscription vs. services) · FCF margin · SBC as % revenue

### 7.2 Semiconductors
Utilisation · ASP **and** unit volume separately · book-to-bill · inventory days and channel inventory · capex intensity · R&D intensity · node and product mix · design wins

### 7.3 Hardware / Equipment
Unit volume · ASP · attach rate · backlog and coverage ratio · warranty and return rates · BOM cost trend · gross margin bridge

### 7.4 IT Services
Headcount · utilisation · bill rate · revenue per employee · book-to-bill · contract duration · offshore mix

### 7.5 Roadmap
Healthcare and Financials to follow. **Financials require framework rework**, not just a new KPI list — revenue quality, margin structure, and DCF mechanics all behave differently (P/E and P/B primary; interest is operating).

---

## 8. Cross-Section Consistency Checks

Deterministic. Any failure blocks publication. All are Class A unless noted (§6.5).

| # | Check | Links |
|---|---|---|
| C1 | Type field determines comp set and industry analysed | §1.4h → §2.3 |
| C2 | Capturable share = DCF terminal revenue assumption | §2.5b → §4.6 |
| C3 | DCF forecast drivers = Section 3 bridge components, exactly | §3.4 → §4.5 |
| C4 | Bridge components sum to headline forecast | §3.4 internal |
| C5 | Every driver maps to a model line | §3.4 → §4 |
| C6 | Scenario assumptions trace to specific thesis pillars | §3.3 → §4.10 |
| C7 | Top-ranked risks are the bear-case assumptions | §5.5 → §4.10 |
| C8 | Section 3 steelman appears as a quantified risk | §3.7 → §5 |
| C9 | Falsifiers have thresholds and feed monitoring | §3.7 → §5.3 |
| C10 | Every figure resolves to a declared provenance class | §6.4, global |
| C11 | Excel recalculation matches Python within tolerance | §4.12 |
| C12 | All figures from latest filed period | §6.3 |

---

## 9. Output Assembly

Presentation order (≠ research order):

1. **Header** — ticker, price, target, upside, market cap, liquidity, key multiples
2. **Recommendation & the debate** — call, horizon, conviction, size; 2–3 load-bearing reasons; what the market believes and why it is wrong
3. **Company overview** (§1)
4. **Industry overview** (§2)
5. **Investment thesis** (§3) — archetype, bridge, variant perception, catalysts
6. **Valuation** (§4) — method weighting, WACC derivation, DCF, reverse DCF, comps, scenarios, return decomposition, target range
7. **Risks & mitigants** (§5) — table, position sizing
8. **Appendix** — model, exhibits, citation index, QC report

**Accompanying deliverable:** the Excel workbook (§4.12).
