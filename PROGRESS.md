# PROGRESS — Equity Filings RAG

> Cross-session memory. Update before ending any AI session: status, decisions, next steps.

> **The spec is at v1.2** (`docs/Equity_Research_Framework_v1.2.md`). Do not build against v1.0
> or v1.1 — the 70% terminal-value tier was deleted at v1.1 and Class A/B rule classes replaced
> the "explicit discussion" wording. The changelog at the top of the spec lists every change.

---

## Status: PHASE 2 COMPLETE — valuation engine ✅ (2026-09-02)

Branch `phase-2-valuation` off `main`, 16 commits, **not pushed**. 566 passed, 64 skipped.
Exit criterion met AND every section 4 component built.

**Exit criterion:** "reproduce the TSMC model's published TWD 1,732.66, then flag all eight
Audit §2 findings." **Both halves done.**

```bash
python -m pytest tests/test_tsmc_exit_criterion.py -q     # 29 passed
python -m pytest -q                                       # 566 passed, 64 skipped
```

```
Published target  TWD 1,732.66  - reproduced from the workbook's own inputs
TV corrected      TWD 2,359.34  - defect 1 repaired, nothing else changed
All corrected     TWD 2,321.64  - every convention framework 4 requires

Terminal value share (as built):      81.78%  (threshold 75.00%)
Terminal value share (TV corrected):  86.75%  (threshold 75.00%)
WACC less terminal growth:             3.13pp (threshold 4.00pp)

defect 1 [A] terminal_value_from_discounted_flow   defect 5 [A] beta_not_derived
defect 2 [B] terminal_value_share                  defect 6 [A] equity_weight_not_market_cap
defect 3 [B] wacc_growth_spread                    defect 7 [A] stub_period_overstates_cash_flow
defect 4 [A] real_growth_on_nominal_flows          defect 8 [B] single_method_valuation
```

**Built:** `src/valuation/` — `money` (the Decimal boundary) · `inputs` (declared inputs +
`Conventions`) · `wacc` · `beta` (§4.4, both routes) · `dcf` · `reverse_dcf` (§4.7) · `comps`
(§4.8) · `target` (§4.9) · `scenarios` (§4.10) · `excel/` (`reader`, `audit`, `formulas`,
`workbook`, `readback`, `recalc`). `src/qc/` gained `rules` (the registry), `exceptions`
(Class B records), `findings`, `valuation_rules`. Fixture `tests/fixtures/tsmc_model.xlsx`,
sanitised — it carried the owner's email in `docProps`.

**Every tab framework 4.12 names now exists** — Inputs · WACC · Model · Comps · DCF ·
Scenarios · Sensitivity · Summary, plus Reverse DCF and Target — and each arrived with its C11
coverage in the same commit that added it. `PENDING_SHEETS` is empty and a test asserts it.

The Sensitivity tab is the strongest C11 evidence here: changing WACC changes every discount
factor, so its 25 cells cannot be a lookup table even in principle. Each column rebuilds its
own factor block and PV of the forecast; all 25 reconcile at 6.3e-16 worst case.

### The design decision that carried the phase
**`ValuationInputs` is what the analyst asserted; `Conventions` is how those numbers are
combined.** Each `Conventions` field is an enumerated choice with one answer the framework
endorses and at least one that a real model uses instead. One engine then produces both halves
of Audit §2.2's table — same inputs, different conventions — and **the defect list is a diff
against `Conventions.SPEC` rather than a hand-maintained catalogue**. Defects 1, 6 and 7 fall
out of that diff; a model cannot quietly implement a fourth defective behaviour that nobody
wrote a checker for.

### Decisions taken this phase (approved before coding)
- **Class A / Class B refuse at LOAD time, not check time.** An exception record naming a
  Class A rule does not parse, so no code path exists in which a Class A finding could consult
  one. Same trick `external.py` uses to reject a figure XBRL could have answered. This closes
  the §4.13 "explicit discussion" ambiguity Phase 1 left open.
- **Measurements are a separate type from findings** and cannot block. §4.6 wants the TV share
  printed every run; the deleted 70% tier proved a non-blocking tier is a warning by another
  name. A measurement makes no claim about acceptability — it states a value.
- **Defects 4 and 5 route through §6.4 provenance, not new machinery.** Neither is visible in
  any arithmetic. The rule for beta is "it must be a model cell" — `external.py` legitimately
  permits a `beta_input` record; using one *directly as the beta* is the violation.
- **The exporter refuses to write a defective model.** `reader.py` may READ one — that is the
  audit — but emitting a double-discounted terminal value would ship the defect.
- **Exactly-eight is asserted once**, in the acceptance test. Every other test scopes to its own
  rules. Three tests churned before this was applied consistently.

### Spec amendments made this phase (v1.1 → v1.2)
- **§4.5 + §4.13** — stub-period convention stated, matching Class A rule added. A real hole:
  Audit §2.10 asserts every one of its findings is caught by a rule already in the framework
  and omits its own finding 6, so the claim was false rather than the rule merely unwritten.
- **§4.13** — beta-from-a-terminal listed separately from WACC-from-a-terminal.

Both Phase 1 ambiguities are now closed: the 70/75 conflict (v1.1 deleted the 70% tier) and
the "without explicit discussion" wording (§6.5 exception records).

### Corrected mid-phase, worth not re-deriving
As built, terminal value is **81.78% of EV — already above the 75% threshold**. An earlier note
called it "an unremarkable 81.8%", implying the arithmetic error concealed the breach. It did
not: it *understated* the dominance (81.8% against a true 86.8%), and the rule fires on the
published model either way. What the error really masked was the **target price** — 1,732.66
against 2,359.34, a 36% understatement landing in a believable range.

Also measured: terminal growth must fall to **zero** before this model stops breaching 75%. At
g = 1% it is still 75.08%. No reasonable growth assumption makes this DCF carried by its
explicit forecast.

### Hard-won gotchas (Phase 2)
- **`numpy.float64` subclasses `float`**, and NumPy 2's repr is `np.float64(6973.97)` —
  unparseable by `Decimal`. `from_spreadsheet` needs an explicit `float()` coercion. The recalc
  engine returns numpy scalars for *some* cells, so exactly one cell silently vanished from the
  reconciliation. C11 caught it only because that cell was asserted by name.
- **openpyxl formats every numeric cell to 16 significant digits**, whatever it is handed,
  `Decimal` or `float`. `to_spreadsheet` must match that format, not `repr(float(x))` (17
  digits), or the round-trip is inexact and needs a tolerance — which would then absorb real
  transcription errors too.
- **The console codepage here is GBK.** `U+2212` (minus sign) raises `UnicodeEncodeError` on
  print. Use ASCII hyphens in anything a CLI renders.
- **`formulas` recalculation takes ~8s** even for a small workbook. Keep C11 fixtures small.
- **Run pytest to a file and check `$?`.** Piping to `tail` and chaining with `&&` reads
  *tail's* exit code; a red suite was committed that way once.
- The two `P2.5` commits (`261d92c` spec v1.2, `4b8bba8` Excel export) collide by label. The
  step order changed mid-phase and history was not rewritten to match.

### Two more precision bugs, found late and worth not re-finding
- **The engine advertised 50 digits and delivered 28.** `divide` and `power` opened a local
  context at `PRECISION`; every plain `+`, `-` and `*` ran at Decimal's default. It surfaced as
  a return-decomposition residual of 1e-26 where the arithmetic should give 1e-47 — a
  discrepancy that reads as rounding and is actually a silent precision boundary. `money.py`
  now sets the process context. Global state, accepted deliberately: the alternative puts the
  invariant in dozens of places where one omission restores the bug silently.
- **Excel operator precedence.** `difference(a, b)` emits `a-b`, so an unbracketed `B8-B5`
  rendered as `=B13-B8-B5`. The Target tab's identity row exists to catch a decomposition that
  does not add up, and it caught itself first, returning -204.9 instead of 0.

### Next: Workstream B (repo repositioning)
- **B1 rename** to `stock-pitch-engine` — needs a GitHub UI action first, then
  `git remote set-url`. Cannot be done from here.
- **B2 README** led by the QC gate and the TSMC demo, not the RAG.
- **B3 package layout** as one mechanical commit, no behaviour change.
- **B4 git hygiene** — pre-commit hook blocking licensed terminal data, `.gitignore`, CI,
  phase tags, disclaimer.

### Live case study: AVGO (data review, 2026-09-02)
`../Case Study - AVGO Stock Pitch/` (OUTSIDE the repo, and it must stay there — the DES PDF
carries "Not for redistribution"). Reviewed against what the engine consumes:
- **Beta: complete and correct.** Raw 1.818, 5y weekly vs SPX, 260 points, SE 0.130. The raw
  series is in `grid.xlsx`, and recomputing OLS from it reproduces Bloomberg to four decimals.
  Use RAW — the code applies Blume, and Bloomberg's "Adjusted 1.545" is already Blume.
- **DES**: price 370.34, market cap 1,761.9B, EV 1,807.2B, 4,757.6M shares, FY-end 10/2025,
  segments Semiconductor Solutions 36.86B / Infrastructure Software 27.03B (57.7/42.3).
- **Blocked**: the RV comps export carries finished multiples but no growth and no
  profitability column, so both the regression (primary) and growth-adjusted (cross-check)
  are uncomputable. It is also a 2Y-correlation screen rather than a comp set (GOOGL, AMZN,
  META, PLTR, Samsung...), mixes four listing currencies, and calendarisation is almost
  certainly off against an October fiscal year end. Re-pull promised for Thursday.
- ECFC gives **real** GDP only (2.1%) — terminal growth must be derived nominal (~4.4%) and
  declared as such, or it is defect 4 verbatim.
- Unlike TSMC, WACC - g lands near 6.6pp, well clear of the 4pp floor.

**Still open, not mine to decide:** the Finding *"Boilerplate outranks substance"* has no
decision attached and threatens §5.7b's Item 1A diff, a load-bearing input to Section 5.
Candidate remedies are the roadmap reranker or an index-time boilerplate classifier.
**Phase 4 design fork.**

---

## Status: PHASE 1 COMPLETE — verification before generation ✅ (2026-08-31)

Branch `phase-1-verification` off `phase-0-data-foundation`, 5 commits, **not pushed**.
Audit R5 (numeric verification) and R7 (eval harness) are done; C10 and C12 are enforced.

**Exit criterion (Audit §7):** "the verifier catches a deliberately corrupted figure in a
test document." Met, and exceeded — the suite corrupts *every* figure in the golden draft
one at a time and requires a 100% catch rate.

```bash
python scripts/verify_draft.py tests/fixtures/draft_msft_golden.md \
    --externals tests/fixtures/external_test.yaml     # QC PASSED, exit 0
python scripts/run_eval.py                            # hit@5 88.6%, MRR 0.820
```

**Built (P1.1–P1.5):** `src/qc/` — `claims` (extraction with char spans) · `tolerance`
(half-ulp from written precision) · `anchors` (citation index) · `cells` (model cells,
recomputed) · `external` (declared external records) · `resolve` · `recency` (C12) ·
`report` — plus `src/eval/harness.py`, `eval/questions.yaml` (44 labelled questions),
`scripts/verify_draft.py`, `scripts/run_eval.py`. 255 tests (was 119).

### The measurement that set the architecture
Search-based resolution — take a figure, look for a matching fact — **does not work**.
Corrupting 200 real MSFT facts by 0.8bn, 192/200 corrupted `$X.Y billion` claims still find
*some* fact inside their tolerance band (MSFT alone has 17,279 current USD facts). A
search-based verifier would pass a corrupted headline figure ~96% of the time. So the draft
carries its provenance and the verifier checks the **cited** row — which is what §6.4 already
required and what §9's citation index already provided a place for.

### Decisions taken this phase (approved before coding)
- **Anchors:** figures carry a Markdown footnote `[^F7]`; a `## Citation index` YAML block maps
  it to provenance. Renders as a real pitch, parses trivially, survives editing.
- **Three provenance classes:** facts row · model cell · declared external record. Anything
  else hard-fails. No allowlist, no severities.
- **Model cells are RECOMPUTED**, not trusted — a wrong margin recorded faithfully must not
  verify clean. Closed op vocabulary (`sum/difference/product/ratio/growth`), no eval.
- **External records** need `kind` from a closed vocabulary of things XBRL cannot answer
  (consensus/market price/beta/peer market/macro). That restriction is the whole safeguard:
  without it the class is an allowlist. Store is **git-ignored** (`data/external/`) because
  Bloomberg values are licensed and this repo is public — a real, deliberate loss of the
  reviewable-diff property `concept_map.yaml` enjoys.
- **Scale:** table column headers carry it (`Revenue ($m)`); a financial figure in an
  unlabelled column is `scale_undeclared` and fails. A failure names the scale that *would*
  have resolved it as a hint, but never applies it.
- **Tolerance:** half-ulp of the last written digit, interval closed at both ends (a boundary
  value is a rounding tie; failing over a tie-break convention is noise).

### Retrieval baseline (R7) — measured, not assumed
44 labelled questions over the 20 filings. **hit@5 88.6% · hit@10 93.2% · MRR 0.820**
(year-pinned hit@10 100%, year-agnostic 90.6%). Mean top-doc share of top-10 **49.1%** — the
R4 watch item, check before Section 2's cross-company panel.

Gold labels are `(ticker, fiscal_year, section_key)` + optional pattern, **never chunk ids**
(a chunk id rots the moment chunking is tuned — the very change this harness evaluates).
`fiscal_year: any` where five near-identical vintages make the year meaningless; the 12
year-pinned questions set the `year` retrieval filter, as production does.

**Five genuine misses, all labels confirmed against the corpus:**
- *Boilerplate outranks substance* — AMD inventory risk and NVDA cyber governance both return
  the forward-looking-statements safe harbour, which enumerates every risk topic generically.
- *Numeric tables answer narrative questions* — "what drove NVIDIA's gross margin" returns a
  buyback table, an auditor signature block, a geographic revenue table, all at distance ~0.39
  where good matches sit near 0.34. Nothing matched; the ranking is noise. **A live
  demonstration of P2** — this is why numbers must never come from RAG.
- MSFT FX risk (Item 7A is short; Item 1A language dominates) and AMD goodwill (Item 8).

**Next:** Phase 2 — valuation engine (§4). Exit criterion: reproduce the TSMC model's published
1,732.66, then flag all eight Audit §2 findings. Two spec ambiguities still owed a decision
(logged in `docs/PHASE1_HANDOVER.md`): §4.6 says flag TV > **70–75%** of EV while §4.13 says
**75%**; and §4.13 blocks "without explicit discussion", implying a documented-exception
mechanism that sits in tension with "no warnings that can be ignored".

---

## Status: PHASE 0 COMPLETE — equity-research pipeline layered on ✅ (2026-08-31)

The repo now carries a second, larger project on top of the RAG demo: the **AI Equity Research
pipeline** (`docs/Equity_Research_Framework_v1.0.md` + `docs/Workflow_Audit_v1.0.md`). Phase 0
(data foundation, Audit R1–R3) is done and its exit criterion is met.

**Exit criterion (Audit §7):** "pull any US filer's segment revenue and profit, 5 years, fully
cited, in one command."

```bash
python scripts/research_cli.py ingest   --ticker AMD           # cold, from nothing
python scripts/research_cli.py segments --ticker MSFT --cite   # panel + citations
```

**Built (P0.1–P0.9):** `schema_facts.sql` (facts / filings / xbrl_labels / concept_map, plus the
`facts_current` view and `facts_asof(date)`) · `src/edgar/` (rate-limited cached client,
discovery, fetch, inline-XBRL parser, companyfacts, reconcile, html_text, sections_us) ·
`src/facts/` (store, concepts, typed api) · `src/segment.py` router · `config/concept_map.yaml` ·
`scripts/research_cli.py` · 119 tests.

**Verified:** 20 filings across MSFT / NVDA / AAPL / AMD · 10,473 consolidated facts compared
against SEC companyfacts with **0 mismatches** · segment revenue reconciles to the consolidated
total in every filer-year · the 42 HK sections are byte-identical to their pre-migration baseline.

**Key decisions specific to this layer**
- companyfacts publishes NON-dimensional facts only, so segment data comes from parsing the
  inline-XBRL instance; companyfacts is kept as an independent reconciliation oracle.
- `sign="-"` in iXBRL is part of the value, not a display hint.
- Facts are never overwritten on re-report: `facts_asof(date)` gives the as-filed view (Audit G6).
- Two segmenters coexist: `format='pdf'` → `src/sections.py` (untouched), `format='html'` →
  `src/edgar/sections_us.py`. Both write `section_type`, so rag_chat / alerts / app are unchanged.
- Interpreter is the documented one: `C:/Users/user/venvs/filings-rag/Scripts/python.exe`.

**Next:** Phase 1 (Audit R5 / R7) — numeric verification pass and eval harness, deliberately
before any document generation.

---

## Status: COMPLETE + OPEN-SOURCED ✅ (2026-07-18)

**Purpose pivoted:** from internship portfolio → public open-source RAG reference project.
All 6 modules work end-to-end and are browser-verified. **Corpus:** 6 annual reports
(0700/9626/0005 × FY2024-25), 2,429 chunks (all section-tagged), 36 section summaries,
9 YoY change alerts + 6 new-filing alerts. **UI:** Streamlit chat + source panel + alerts feed.

**Provider-agnostic (S7):** LLM is now any OpenAI-compatible endpoint via `LLM_BASE_URL`/
`LLM_MODEL`/`LLM_API_KEY` (was hardcoded DeepSeek). New `src/llm.py` wrapper; `config.py`
reads `LLM_*` and is key-lazy (ingest/embed/segment run with no LLM key). Embeddings stay local.
Smoke test renamed `scripts/test_llm.py`; UI caption shows the live model name.

**Public repo** (github.com/Bobksl/Equity-Filings-RAG, commit 252ff72): src/*, schema.sql,
requirements.txt, README/SETUP/USAGE, .env.example (provider table, empty key), MIT LICENSE,
scripts/test_llm.py + retrieval_qa.py. Excluded: DEMO.md, PROGRESS.md, CLAUDE.md, ARCHITECTURE.md,
project_guideline.md, backfill script, .env. Verified: real key absent from committed tree.

## Remaining / optional
- [ ] Screenshot of the cited-answer UI in the README (biggest bang for a public repo)
- [ ] Optional polish: per-entity retrieval quota (SQL window fn) · chunk-quality filter for
      OCR letter-soup · labeled eval set · reranker · generalize `FILENAME_RE` beyond `_HK_`

## Key decisions (frozen)
Any OpenAI-compatible LLM via `.env` (default DeepSeek `deepseek-v4-flash`) · local BGE-M3
embeddings (1024-dim, CPU) · PostgreSQL + pgvector in Docker (`filings-db`) · pdfplumber +
Tesseract OCR fallback (`OCR_LANG` default `chi_tra+eng`) · raw Python+SQL RAG loop (no
frameworks) · Streamlit · manual downloads only (respect source ToU).

## Hard-won gotchas (read before touching the pipeline)
- Run everything as `python -X utf8 -u -m src.<module>`; venv at `C:\Users\user\venvs\filings-rag` (outside OneDrive).
- After reboot: Docker Desktop → `docker start filings-db`. Use `PGHOST=127.0.0.1` — `localhost` resolves to ::1 first on Windows and Docker's IPv6 mapping can hang forever.
- DeepSeek thinking mode bills reasoning tokens against `max_tokens` — keep ≥5000.
- Tesseract language data at `C:\tools\tessdata` via `TESSDATA_PREFIX` (never `--tessdata-dir` through pytesseract).
- HSBC ARs have broken font CMaps → `(cid:NN)` garbage from every extractor; ingest detects this per page and routes to OCR (~7 s/page).
- Repeated page headers fake section headings on OCR docs → `MIN_SECTION_PAGES=3` hysteresis in `sections.py`.
- `section_id` FKs are `ON DELETE SET NULL` on purpose — a CASCADE once deleted 211 embedded chunks during re-segmentation.
- Embedding ≈ 40 s/batch of 8 on this CPU (~25 min per 200-page filing); one-time per doc.

## Session history (detail lives in git log from here on)
1. **S1 (Jul 16):** scaffold, venv, deps, DeepSeek key verified, docs harmonized (pgvector over Chroma).
2. **S2:** Docker+pgvector up, schema loaded, Tesseract/poppler installed, 3× FY2025 filings added.
3. **S3 (Day 1):** walking skeleton — ingest→chunk→embed→cited answer, verified on Tencent; HSBC cid-garbage discovery + OCR re-ingest.
4. **S4 (Day 2):** sections + hysteresis, page-range citations, 10-question retrieval QA, cascade-FK incident + recovery.
5. **S5 (Day 3):** `alerts.py` — summaries + YoY diffs (Tencent pair), grounding prompt tightened.
6. **S6 (Day 3+4):** FY2024 corpus completed, all-issuer alerts, Streamlit UI built & verified, IPv6 fix, README/DEMO/USAGE finalized, pushed to GitHub.
