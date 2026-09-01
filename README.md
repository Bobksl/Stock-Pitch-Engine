# Stock Pitch Engine

[![tests](https://github.com/Bobksl/Stock-Pitch-Engine/actions/workflows/tests.yml/badge.svg)](https://github.com/Bobksl/Stock-Pitch-Engine/actions/workflows/tests.yml)

A research pipeline that produces equity pitches in which **every number is verified against
the filing it came from**. Not a filings reader — a deterministic quality gate with a
research pipeline attached to it.

## How it works

Two loops that never touch. **Numbers come from the inline-XBRL instance** of the filing,
parsed into a facts table; **narrative comes from vector retrieval** over Item-anchored
chunks. The LLM writes prose about figures that were already computed — it never computes
one, and retrieval is never the source of a figure. Every figure in an output resolves to
one of exactly three declared provenance classes, and an unresolvable figure blocks
publication rather than raising a warning.

The valuation engine runs entirely in `Decimal`. The workbook it exports carries live
formulas, and a reconciliation test recalculates it headlessly and asserts Excel and Python
agree — because two calculation tracks that can drift silently are worse than one.

## The demo

Point it at a real DCF and ask what is wrong with it. This is the actual output against
a competent, well-organised student model of TSMC:

```
Published target  TWD 1,732.66  — reproduced from the workbook's own inputs
TV corrected      TWD 2,359.34  — defect 1 repaired, nothing else changed

MEASUREMENTS  — reported every run, pass or fail
  Terminal value share (as built):      81.78%  (threshold 75.00%)
  Terminal value share (TV corrected):  86.75%  (threshold 75.00%)
  WACC less terminal growth:             3.13pp (threshold 4.00pp)

BLOCKING (8)
  [A] terminal_value_from_discounted_flow (4.13)
      terminal value at B18 is `=N16*(1+B17)/(B13-B17)`, built from N16 — the
      already-discounted final cash flow, not N14. The final period's factor is
      applied twice. Correcting it alone moves the target from TWD 1,732.66 to
      TWD 2,359.34
  [A] equity_weight_not_market_cap (4.3)
      equity weight at B6 is `=36.31-B5`, netting debt out of market
      capitalisation. D/(D+E) 2.78% against 2.71% on market cap
  [A] stub_period_overstates_cash_flow (4.5)
      discount factor at I15 is `=1/POWER(1+B13,1/6)`, a 16.67% stub, while
      I16 is `=I14*I15` — the whole period's cash flow
  ... 5 more

AUDIT FAILED — publication blocked
```

**It reproduces the model's published target to the cent first, then criticises it.** That
order is the whole argument: a tool that reports defects without reproducing the number is
indistinguishable from a tool with a parsing bug, and the modeller has no reason to believe
it.

The finding that justifies the layer is the first pair. The terminal value was built from
an already-discounted cash flow — a 36% understatement — while the model was *also*
terminal-value dominated at 86.8% of enterprise value. Two errors partially offsetting,
landing in a believable range, surviving ordinary human review. No amount of careful
reading catches a compounding error whose output looks plausible.

```bash
python -m pytest tests/test_tsmc_exit_criterion.py -q     # 29 passed
```

## Every rule is Class A or Class B

- **Class A — correctness.** The figure is wrong or unverifiable. **Never exceptionable.**
  No allowlist, no severity ladder, no override.
- **Class B — model shape.** The model is unusual, not wrong. Satisfiable by a declared
  exception record: condition, reason from a closed vocabulary, detail, author, date, and a
  **required expiry**.

There is exactly one passing state. An exception is not a dismissed warning — it is a
positive, structured, attributed assertion, and it is **published in the output**, not
merely consumed by the gate:

> Exception: `long_duration_asset` — terminal value is 86.75% of enterprise value, above
> the 75.00% threshold.

The guarantee is structural rather than procedural. A record naming a Class A rule **fails
to parse**, so no code path exists in which a Class A finding could consult one.

## Data lineage

```
SEC EDGAR
├── inline-XBRL instance ──► facts table (Postgres) ──► ALL NUMBERS
│         │                          ├──► company / industry extraction
│         │                          ├──► DCF and comps inputs
│         └── companyfacts ──────────┴──► reconciliation oracle (not a source)
│
└── filing HTML ──► Item-anchored segmentation ──► chunks ──► pgvector
                                                      ├──► narrative retrieval (cited)
                                                      └──► YoY diff (Item 1A, Item 1, MD&A)

Declared external records ──► consensus · market prices · beta inputs · peer
   (git-ignored, licensed)      multiples · macro series          — and nothing else
```

`companyfacts` is deliberately **not** a source: it drops the dimensional qualifiers that
segment figures depend on, so segment breakdowns are unobtainable from it. It is kept as an
independent reconciliation oracle, and disagreement is a hard failure.

## Status

| Phase | What it built | State |
|---|---|---|
| 0 — data foundation | Facts table, EDGAR client, inline-XBRL parser, Item-anchored segmentation | ✅ merged |
| 1 — verification | Numeric claim extraction, anchor-based resolution, provenance classes, eval harness | ✅ merged |
| 2 — valuation | WACC, beta, DCF, reverse DCF, comps, price target, scenarios, Excel export + reconciliation | ✅ complete |
| 3 — narrative | Section drafting against the verified figures | planned |
| 4 — assembly | Full pitch assembly, risks, monitoring | planned |

**566 passing tests.** 10,473 consolidated facts cross-checked against SEC `companyfacts` with **0
mismatches**. Retrieval baseline measured, not assumed: **hit@5 88.6%, MRR 0.820** over 44
labelled questions.

## Quickstart

Full install in [SETUP.md](SETUP.md). EDGAR is the primary path and needs no OCR:

```bash
# US filers, end to end, from nothing
python scripts/research_cli.py ingest   --ticker AVGO
python scripts/research_cli.py segments --ticker AVGO --cite

# audit somebody else's DCF
python -c "from src.valuation.excel.audit import audit_workbook; \
           print(audit_workbook('tests/fixtures/tsmc_model.xlsx', \
                                published_price_cell='B27').render())"

# verify a draft: every figure resolves, or it does not publish (needs Postgres)
python scripts/verify_draft.py tests/fixtures/draft_msft_golden.md --externals tests/fixtures/external_test.yaml

# measure retrieval rather than trusting it
python scripts/run_eval.py
```

The **PDF/OCR route is secondary**, for filings EDGAR does not carry (Hong Kong listings,
terminal exports). It is unchanged and still works:

```bash
python -m src.ingest.pdf sample_pdfs/0700_HK_2025_annual.pdf
python -m src.ingest.chunk_embed --doc-id 1
python -m src.sections.router --doc-id 1 --apply
streamlit run src/app.py
```

On Windows prefix with `-X utf8`, or non-ASCII filings will choke the console encoding.

## Layout

```
src/
  ingest/       pdf.py · chunk_embed.py · edgar/ (client, fetch, ixbrl, reconcile)
  sections/     us.py (Item-anchored) · hk.py (heuristic) · router.py
  facts/        store · concepts · typed api
  retrieval/    chat.py · alerts.py · eval/
  qc/           claims · anchors · cells · external · resolve · recency ·
                rules · exceptions · findings · valuation_rules · report
  valuation/    money · inputs · wacc · beta · dcf · reverse_dcf · comps ·
                target · scenarios · excel/ (reader, audit, workbook, recalc)
```

## What real filings and real models taught this pipeline

1. **Search-based verification does not work, and the measurement is not close.** Take 200
   real MSFT facts, corrupt each by 0.8bn, and ask whether *any* fact still falls inside the
   claim's tolerance band: **192 of 200 corrupted "$X.Y billion" claims still find a home.**
   MSFT alone has 17,279 current USD facts — at the granularity a pitch headline is written
   to, the table is dense enough that a wrong number almost always lands somewhere innocent.
   So the draft carries its provenance and the verifier checks the *cited* row.

2. **Two errors that partially offset are worse than one that does not.** The TSMC model's
   double-discounted terminal value understated the target by 36% while the model was
   simultaneously terminal-value dominated. Either error alone would have looked wrong.
   Together they produced a plausible number.

3. **A broken font CMap** makes every text extractor return `(cid:NN)` garbage. The pipeline
   measures that garbage per page and routes those pages to OCR — a citation is only
   trustworthy if the underlying text is.

4. **`numpy.float64` subclasses `float`**, and NumPy 2 changed its `repr` to
   `np.float64(6973.97)`, which `Decimal` cannot parse. The recalculation engine returns
   numpy scalars for *some* cells and plain floats for others, so exactly one cell silently
   vanished from the Excel reconciliation while every other cell reconciled cleanly. A
   conversion that drops what it cannot parse is worse than one that fails.

5. **The engine advertised 50 digits of precision and delivered 28.** `divide` and `power`
   opened a local context; every plain `+`, `-` and `*` ran at Decimal's default. It
   surfaced as a return decomposition whose terms summed with a residual of `1e-26` where
   the arithmetic should have given `1e-47` — a discrepancy that reads as rounding and is
   actually a silent precision boundary.

6. **`ON DELETE CASCADE` on a label foreign key deleted 211 embedded chunks** during a
   re-segmentation. Section links are now `ON DELETE SET NULL`: labels must never own data.

7. **Boilerplate outranks substance.** Asking about AMD inventory risk or NVDA cyber
   governance returns the forward-looking-statements safe harbour, which enumerates every
   risk topic generically and therefore matches everything. Unresolved, and tracked as a
   design fork rather than papered over.

## Known limitations

- **Narrative generation is not built yet.** Phases 3 and 4 are planned; today the pipeline
  verifies, values and audits, and does not draft a full pitch.
- **Boilerplate dominates risk retrieval** (war story 7). Candidate remedies are a reranker
  or an index-time boilerplate classifier; neither is chosen.
- **The comp-set minimum of five is a judgement call.** The framework requires a minimum and
  names no number.
- **Excel reconciliation uses `formulas`, a pure-Python engine.** LibreOffice is preferred
  when present and is stronger evidence; reconciling Python against another Python program
  is a weaker claim, and the code says so.
- **Section detection outside EDGAR is heuristic.** US filings use Item anchors, which are
  regex-reliable; the PDF route uses heading patterns with hysteresis.
- **Citations are chunk-level page ranges**, not sentence-level offsets.

## Scope and disclaimer

Educational and research tooling. **Nothing here is investment advice**, and no output of
this repository should be treated as a recommendation to buy or sell any security.

No terminal-derived data is included. Bloomberg exports carry redistribution restrictions;
declared external records live in a git-ignored directory and `scripts/pre-commit` blocks
those paths from ever being committed. You supply your own filings, your own market data and
your own API key.

## License

MIT — see [LICENSE](LICENSE).
