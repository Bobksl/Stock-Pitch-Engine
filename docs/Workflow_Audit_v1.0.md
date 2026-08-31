# Workflow Audit — AI Equity Research Pipeline v1.0

**Date:** 2026-08-29 · **Scope:** the framework in `Equity_Research_Framework_v1.0.md` as an implementable system

---

## 1. Architecture Assessment

### 1.1 The design is sound because it separates three things most retail pipelines conflate

| Layer | Owner | Determinism |
|---|---|---|
| **Extraction** — filings, XBRL facts, prices, estimates | Code | Fully deterministic |
| **Synthesis** — narrative, judgment, thesis | LLM, scaffolded | Non-deterministic, reviewed |
| **Calculation** — DCF, comps, scenarios, QC | Code | Fully deterministic |

The load-bearing rule is **P2 (numbers from XBRL, narrative from RAG)**. Without it, a figure retrieved from a PDF table by vector similarity can enter the model, propagate into the target price, and survive to the final document with a citation that looks legitimate. With it, the failure mode is eliminated by construction rather than by review.

### 1.2 What the design does that a standard LLM research pipeline does not

- **Cross-section consistency checks (C1–C12).** Most pipelines generate five independent sections that sound coherent but contradict each other numerically. C3 (DCF drivers = thesis bridge) and C7 (top risks = bear case) are what force a single internally consistent view.
- **Return decomposition.** Splitting upside into re-rating vs. estimate revision converts a target price from an assertion into an auditable claim, and tells you which catalyst you are actually waiting on.
- **Anchor disclosure.** Showing the target under every peer anchor prevents the most common silent failure in comps work.
- **Permission to pass (P6).** A pipeline that always produces a pitch is a pitch generator, not a research process.

---

## 2. Validation of the QC Layer Against the Sample Model

The TSMC workbook in the project folder was used as a test case. It is a competent, well-organised student model — which is precisely why the findings matter: **these errors survive ordinary review.**

### 2.1 Reproduction
Recomputing the model from its own inputs reproduces the published target of **TWD 1,732.66 exactly**, confirming the findings below are structural rather than transcription artefacts.

### 2.2 Finding 1 — Terminal value double-discounting (material, ~36% error)

The terminal value is computed as `N16 × (1+g) / (WACC−g)`, where **N16 is the already-discounted 2030 UFCF**, and the result is then discounted again by `N15`.

Correct form: `TV = UFCF₂₀₃₀ × (1+g) / (WACC−g)`, then `PV(TV) = TV × N15`.

| | PV(TV), TWD bn | EV, TWD bn | Target |
|---|---|---|---|
| As built | 35,416 | 43,308 | **1,732.66** |
| Corrected | 51,666 | 59,558 | **2,359.34** |

### 2.3 Finding 2 — The corrected model is structurally unusable

Correcting the arithmetic does **not** produce a trustworthy answer:

- Terminal value = **86.8%** of enterprise value (threshold: 75%)
- WACC − g spread = **3.13pp** (threshold: 4pp)
- Sensitivity: g at 3.95% → TWD 2,076.86; g at 4.95% → TWD 2,749.11. A ±50bp assumption swings the target by **28.5%** of the corrected value

**The arithmetic error was accidentally masking a terminal-value-dominated model.** Two errors partially offsetting is the worst possible state, because the output looks plausible. This single case justifies the entire deterministic QC layer — no amount of careful reading catches a compounding error whose output falls in a believable range.

### 2.4 Finding 3 — Terminal growth uses a real rate on nominal cash flows
g = 4.45% is sourced as Taiwan **real** GDP growth and applied to nominal forecast cash flows. Unit mismatch in either direction; and 4.45% in perpetuity for a capital-intensive cyclical is aggressive regardless.

### 2.5 Finding 4 — Beta sourced from Bloomberg
β = 1.22 taken directly from the terminal — exactly the practice the framework prohibits (§4.3, §4.4). *In fairness, the cost of debt is well handled* — average YTM across 15 outstanding bonds is a genuinely market-based marginal-cost estimate, better than most student work.

### 2.6 Finding 5 — Equity weight computed as market cap minus debt
`Equity = 36.31 − 1.01`. Market capitalisation **is** the equity value; netting debt out of it is not a defined quantity. Numerically small here (D/(D+E) 2.78% vs. 2.71%, WACC 7.5827% vs. 7.5858%) but conceptually wrong and materially so on a levered name.

### 2.7 Finding 6 — Stub-period discounting counts a full year of cash flow
2025 UFCF is discounted at `(1+WACC)^(1/6)` on the stated basis that ~2 months remain in the year, but the **full year's** cash flow is included. Either count 2/12 of 2025 UFCF, or discount a full year at a full-year factor.

### 2.8 Finding 7 — Method concentration
"Assign 100% weight on DCF approach." Violates §4.2. For a name whose valuation is 87% terminal value, a comps cross-check is not optional — it is the only thing standing between the model and an unfalsifiable number.

### 2.9 Finding 8 — Structural gaps
No scenario analysis · no sensitivity table · no reverse DCF · gross profit line computed but never used in the UFCF build (dead line, divergence risk) · EBITDA margin forecast oscillates (67.3 / 68.7 / 67.6 / 68.9 / 67.4 / 68.8) with no stated rationale — reads as noise rather than a modelled view.

### 2.10 Mapping to QC rules
Every finding above is caught by a rule already in the framework:

| Finding | Rule |
|---|---|
| TV double-discount | §4.13 "TV computed from an already-discounted cash flow" |
| TV share, WACC−g spread | §4.6 thresholds |
| Real g on nominal flows | §4.6, §4.13 |
| Bloomberg beta | §4.3, §4.4 |
| Equity weight | §4.3 "equity weight = market capitalisation" |
| 100% DCF | §4.2, §4.13 single-method |
| No scenarios / sensitivity / reverse DCF | §4.7, §4.10 |

**The QC layer is validated.** It catches every material defect in a real, competent model.

---

## 3. Data Lineage

```
SEC EDGAR
├── companyfacts API ──────► facts table (Postgres) ──► ALL NUMBERS
│                                      │
│                                      ├──► Section 1 extraction
│                                      ├──► Section 2 industry panel
│                                      ├──► DCF / comps inputs
│                                      └──► accounting-quality screen
│
└── filing HTML ──► Item-anchored segmentation ──► chunks ──► pgvector
                                                       │
                                                       ├──► narrative retrieval (cited)
                                                       └──► YoY diff (Item 1A, Item 1, MD&A)

Bloomberg (local only)
├── consensus estimates (BEst) ──► variant perception, forward metrics
├── transcripts ──────────────────► management framing, analyst concerns
├── issue-level debt / spreads ───► cost of debt
├── comp financials & multiples ──► comps module
└── price history ────────────────► beta, drawdown analysis

Market data ──► peer drawdown windows, entry timing
```

**Boundary:** Bloomberg-derived content is processed **locally only** (Ollama via `LLM_BASE_URL`). Redistribution restrictions make piping terminal data to a third-party LLM API a plausible licence violation. Embeddings already run locally, so this costs nothing architecturally. Confirm your own entitlements before wiring anything.

---

## 4. Required Changes to Equity-Filings-RAG

| # | Change | Priority | Why |
|---|---|---|---|
| R1 | **XBRL facts table + companyfacts ingestion** | Critical | Enforces P2. Nothing else works without it |
| R2 | **EDGAR HTML ingestion path** parallel to PDF/OCR | Critical | US filings are HTML; OCR is unnecessary and lossy |
| R3 | **Item-anchored segmentation for US filings** | Critical | Replaces heuristic segmentation (README's stated weak point). 10-K Item boundaries are regex-reliable. Enables Item-filtered retrieval |
| R4 | **Per-entity quota in retrieval** (SQL window function) | Critical | Already on the roadmap as "next steps." For Section 2's multi-company panel it is a blocker, not a nicety — one document dominating top-k breaks cross-company comparison |
| R5 | **Numeric verification pass** (data-audit function) | Critical | Extract every numeric claim from a draft; match against facts table or cited chunk; flag mismatches, unsupported figures, stale periods. Deterministic, no LLM judgment |
| R6 | **Extend `alerts.py` to Item 1A / Item 1 / MD&A diffs** | High | Feeds §5.7b and §6.2. Module exists; retarget it |
| R7 | **Eval harness** — labelled question set, recall@k | High | Also on the roadmap. Trust in retrieval must be measured before prose is built on it |
| R8 | Retain PDF/OCR path | — | Needed for HK names and Bloomberg PDF exports |

R1–R5 are the critical path. R3 and R4 are both already identified in the repo's own "known limitations," which is a good sign — the existing roadmap points the right direction.

---

## 5. LLM Boundary Map

| Task | LLM permitted? |
|---|---|
| Summarise business model from Item 1 | Yes |
| Extract a financial figure | **No** — facts table |
| Compute a growth rate, margin, multiple | **No** — code |
| Propose candidate thesis pillars | Yes, then QC-filtered |
| Decide the archetype | Yes, with human approval |
| Compute WACC, DCF, comps | **No** — code |
| Narrate a computed result | Yes |
| Assign probability weights | Human |
| Approve comp set | Human |
| Set position size | **No** — code, from quantified downside |
| Decide to trade | Human |

**Single rule:** the LLM may describe, propose, and narrate. It may never compute, and it may never be the last check on a number.

---

## 6. Gaps and Open Risks

**G1 — Transcripts have no free source.** Three sections lean on them; EDGAR does not carry them. Currently Bloomberg-only, which means the pipeline cannot run end-to-end without terminal access. Consider a vendor API fallback if you want unattended operation.

**G2 — Industry sizing is the weakest automated input.** Bottom-up TAM construction resists automation. Expect this to stay manual, and treat it as the section most in need of human review.

**G3 — Consensus estimates are the hardest dependency to replace.** Variant perception (§3.5) is *definitionally* impossible without them. If Bloomberg access lapses, the framework degrades to conventional analysis.

**G4 — The Excel/Python dual track can silently diverge.** Mitigated by C11, but that test must exist from day one, not be retrofitted.

**G5 — Position horizon vs. framework depth.** A full pitch is days of work; position trades turn over in months. Watch the ratio of research cost to holding period — this is the main practical risk to the project actually being used. Mitigation: the industry primer cache (§2.8) and a screening tier that produces a short-form output for names that do not warrant the full treatment.

**G6 — Overfitting the framework to a bull market.** Every rule here was designed against recent examples. Backtest the *pitch* process the way you would backtest a strategy: run it on names as of a past date using only then-available data, and check whether the conclusions held.

**G7 — Sector coverage.** IT only. Financials will require framework rework, not just a KPI list.

---

## 7. Build Sequence

**Phase 0 — Data foundation (R1, R2, R3).** XBRL facts table, EDGAR HTML ingestion, Item-anchored segmentation. *Exit criterion:* pull any US filer's segment revenue and profit, 5 years, fully cited, in one command.

**Phase 1 — Verification (R5, R7, C10, C12).** Numeric verification pass and eval harness. *Deliberately before generation* — you cannot trust output you cannot check. *Exit criterion:* the verifier catches a deliberately corrupted figure in a test document.

**Phase 2 — Valuation engine (§4).** WACC (both betas), DCF, reverse DCF, comps with pairing enforcement, scenarios, sensitivity, Excel export, C11 reconciliation. *Exit criterion:* reproduces the TSMC model's published number, then flags all eight findings in §2.

**Phase 3 — Sections 1 and 2.** Extraction, KPI taxonomy, industry panel, peer drawdown, primer caching (R4).

**Phase 4 — Sections 3 and 5.** Thesis bridge, archetype logic, risk table, YoY diffs (R6), consistency checks C1–C9.

**Phase 5 — Assembly and monitoring.** Document generation, QC report, and the handoff to the trading system: falsifier thresholds become alerts, review dates become scheduled tasks.

Phase 2 before Phases 3–4 is deliberate: the valuation engine is the most testable component and has a known-good test case, so it de-risks the hardest part of the build first.

---

## 8. Connection to the Trading System

This framework is the **idea-generation input** to the AI PM architecture, and it hands over three structured objects:

1. **Falsifier thresholds** (§3.7, §5.3) → monitoring rules and alerts
2. **Position size and stop level** (§4.11, §5.9) → the deterministic risk layer
3. **Probability-weighted expected value** (§4.10) → cross-idea ranking for capital allocation

Reiterating the boundary from the original design: **no LLM in the execution path.** This framework produces a decision object; a deterministic system acts on it, and you approve the trade.

---

## 9. Verdict

The framework is **buildable and internally consistent.** The QC layer is validated against a real model and catches every material defect in it. The critical path is R1–R5, and Phase 1 (verification before generation) is the sequencing decision that most determines whether the output can be trusted.

**Biggest risk is not technical — it is G5.** The framework is rigorous enough to be slow. Build the screening tier early so that depth is spent only on names that earn it.
