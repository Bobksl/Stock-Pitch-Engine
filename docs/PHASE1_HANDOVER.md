# Phase 1 handover prompt

Paste everything below the line into a fresh Claude Code session started in
`C:\Users\user\OneDrive - The University of Hong Kong - Connect\桌面\Projects\AI Hedge Fund\Equity Filings RAG`.

---

You are continuing an automated equity research pipeline that produces institutional-quality
stock pitches with an auditable valuation model. I am the analyst; you are building the system I
will operate. Phase 0 is complete and pushed. You are starting **Phase 1 — Verification**.

## Read first, in this order

1. `docs/Equity_Research_Framework_v1.0.md` — the authoritative specification. Every rule in it is
   deliberate and was argued through. Do not simplify, reinterpret, or "improve" a rule without
   asking me first.
2. `docs/Workflow_Audit_v1.0.md` — architecture, build sequence, required repo changes R1–R8, and
   the validated QC findings. Phase 1 is **R5 + R7** in §7.
3. `PROGRESS.md` — cross-session memory. The top section describes Phase 0 as delivered.
4. `CLAUDE.md` — repo conventions, including the frozen decisions. Read it before touching
   anything; I lost time in Phase 0 by not reading it early.

## Environment — exact, do not improvise

- **Interpreter:** `C:\Users\user\venvs\filings-rag\Scripts\python.exe`. This venv lives outside
  OneDrive deliberately. Do **not** create a `.venv` in the project.
- **Database:** PostgreSQL 18 + pgvector in Docker, container `filings-db`
  (`pgvector/pgvector:pg18`), database `filings`. Start it with `docker start filings-db` if
  Docker Desktop was restarted. Credentials come from `.env` (git-ignored).
- **Tests:** `python -m pytest tests/ -q` → 119 passing. Keep them green.
- **Shell:** Windows. Prefix Python with `-X utf8`. Heredocs into `python -` work; complex
  quoting sometimes does not, so prefer writing a file.
- Network access to SEC works. `EDGAR_USER_AGENT` is set in `.env`.

## State of the world after Phase 0

Branch `phase-0-data-foundation` (9 commits, pushed to
`github.com/Bobksl/Equity-Filings-RAG`, **not merged to main**). Start Phase 1 on a new branch
off it: `git checkout -b phase-1-verification`.

Corpus in the database:

| | |
|---|---|
| Filers | MSFT (789019), NVDA (1045810), AAPL (320193), AMD (2488) |
| Filings | 20 10-Ks, 5 years each, fetched and cached under `data/edgar_cache/` |
| Facts | 22,592 instance (11,114 dimensional) + 108,913 companyfacts |
| Reconciliation | 10,473 consolidated facts compared against SEC, **0 mismatches** |
| Sections | 42 HK (heuristic, page-anchored) + 451 US (Item-anchored, char offsets) |
| Chunks | 2,429 PDF + 3,306 HTML, all embedded (BGE-M3, local, 1024-dim) |

Modules built in Phase 0:

```
schema_facts.sql          facts / filings / xbrl_labels / concept_map
                          + facts_current view and facts_asof(date) function
config/concept_map.yaml   canonical concept -> ordered XBRL tag candidates, axes, qualifier_axes
src/edgar/client.py       rate-limited, disk-cached SEC HTTP
src/edgar/discover.py     ticker -> CIK -> filing list
src/edgar/fetch.py        download primary doc; upsert companies/documents/filings
src/edgar/ixbrl.py        inline-XBRL parser -> XbrlFact objects
src/edgar/companyfacts.py SEC consolidated series (reconciliation oracle)
src/edgar/reconcile.py    instance vs companyfacts, raises on mismatch
src/edgar/html_text.py    filing HTML -> text with stable char offsets
src/edgar/sections_us.py  Item-anchored segmenter
src/facts/store.py        idempotent fact upsert
src/facts/concepts.py     concept map loading and resolution
src/facts/api.py          get_fact / get_series / get_segment_panel -> Fact objects
src/segment.py            router: documents.format -> which segmenter
scripts/research_cli.py   ingest + segments commands (the Phase 0 exit criterion)
```

**The API you will build on:** `src/facts/api.py` returns `Fact` objects, never bare numbers.
Each carries `value, unit, qname, period_start, period_end, segments, accession, filed_date,
source` and a `.citation` property rendering
`accession | tag | period | axis=member`. Pass `as_of=date(...)` to any query for the
point-in-time view (only what had been filed by that date).

Try it before writing code:

```bash
python scripts/research_cli.py segments --ticker MSFT --years 5 --cite
python scripts/research_cli.py segments --ticker MSFT --years 1 --as-of 2024-12-31
```

## Non-negotiable architecture rules

1. **The LLM never computes a number that reaches an output.** All arithmetic in Python. The LLM
   describes, proposes, and narrates — nothing else. Audit §5 has the full boundary map.
2. **Numbers come from the XBRL facts table; narrative comes from RAG.** Vector retrieval is
   never the source of a figure.
3. **Every figure is traceable** to a facts-table row (accession, tag, period) or a model cell.
   Untraceable figures are a build error.
4. **Bloomberg-derived data is processed locally only** (Ollama via `LLM_BASE_URL`). Never send
   it to a hosted LLM API.
5. **Fail loudly.** QC failures block publication. No warnings that can be ignored.

## Working style

- Ask before deviating from the spec. If a rule seems wrong or impractical, raise it — do not
  silently reinterpret it.
- Test-first on anything numeric. Every calculation gets a unit test with a hand-checked
  expected value.
- Small, reviewable commits, each mapped to a phase step and a spec section. Commit message
  style: `P1.x <what> (<spec ref>)` plus paragraphs explaining non-obvious decisions.
- Flag ambiguity rather than guessing.
- When you finish a phase, report against its exit criterion from Audit §7, not against your own
  sense of doneness.

## Do not touch

- `src/sections.py` and `src/ingest.py` — the HK PDF/OCR path. Audit R8 requires keeping it.
- `schema.sql` — the public demo schema stays standalone. New DDL goes in `schema_facts.sql`
  (or a new file), applied on top.
- The 42 HK sections. `tests/fixtures/hk_baseline.json` snapshots them and a test asserts they
  stay byte-identical. If that test fails, you broke something.

## Phase 1 — scope

Audit §7: **"Phase 1 — Verification (R5, R7, C10, C12). Numeric verification pass and eval
harness. *Deliberately before generation* — you cannot trust output you cannot check."**

**Exit criterion: the verifier catches a deliberately corrupted figure in a test document.**

| Step | Deliverable |
|---|---|
| P1.1 | Numeric claim extraction from a Markdown draft — currencies, percentages, multiples, share counts, scaled units ("$245.1 billion", "1,732.66", "23.5%", "4.2x") — returning character spans so a failure localises to a position in the draft |
| P1.2 | Resolution of each claim against the facts table within a tolerance derived from how the figure is written: "$245.1 billion" resolves against 245,122,000,000; "$245.9 billion" does not |
| P1.3 | Staleness (C12) and citation coverage (C10): every figure from the latest filed period; any prior-year figure must appear with its current-year comparative (§6.3) |
| P1.4 | Eval harness (R7): labelled question set over the 20-filing corpus, recall@k, so retrieval trust is measured before prose is built on it |

**Decisions I have already made — do not re-open:**

- The verifier operates on a **Markdown draft**.
- Any figure that cannot be resolved is a **hard failure**. No allowlist, no severity levels, no
  warnings that can be ignored.

**One open question, which needs an answer before P1.2 is written, not after:**

Bloomberg-sourced figures — consensus estimates (§3.5 variant perception), peer multiples, beta
inputs — have no facts-table row by construction. The proposal on the table is a second
provenance class: a figure may resolve to a facts row, a model cell, **or** a declared
external-source record carrying source and as-of date; a figure with no provenance at all still
hard-fails. Raise this with me early and get a decision.

## Gotchas discovered in Phase 0 — do not re-learn these

1. **SEC `companyfacts` publishes non-dimensional facts only** — consolidated totals, no segment
   members. That is why the pipeline parses inline-XBRL instances directly and keeps companyfacts
   as an independent reconciliation oracle.
2. **`sign="-"` in inline XBRL is part of the value**, not a display hint. Display-only negation
   is the `negatedLabel` role in the label linkbase and is never applied at storage time.
3. **Duplicate facts at different precision are legal.** MSFT reports goodwill as 50,969 million
   in the statements and $51.0 billion in the notes. `ixbrl.dedupe()` keeps the most precise
   value after checking agreement at the coarser precision.
4. **companyfacts rounds sub-cent fractions.** MSFT's par value is $0.00000625; the API publishes
   `0.000006`. `reconcile.agrees()` handles this and counts such cases separately.
5. **Filers restate.** MSFT restated its segments after FY2024, so the same fiscal year reads
   differently on the current basis and the as-filed basis. Both reconcile. Use `as_of` whenever
   the question is "what did the market know then".
6. **Filers rename segment members.** NVDA re-filed FY2024 under `...SegmentMember` instead of
   `...Member`, so `facts_current` holds two vintages. `api.latest_vintage()` takes each period's
   breakdown from a single filing; without it the panel double-counts.
7. **NVDA files its financial statements under Item 15**, not Item 8 — its Item 8 is a
   208-character cross-reference. Never assume Item 8 for financial statements.
8. **MSFT's Part III block looks like a table of contents** (Items 9B, 9C, 10–15 within a few
   hundred characters). The TOC detector requires Item 1, ascending order, tight spacing, and a
   short span near the front.

## Also outstanding (not Phase 1 work, but decisions I owe you)

- **`docs/` is uncommitted.** The framework and audit specs sit in the repo locally but were not
  committed, because the repo is public and its convention excludes internal docs. Ask me if it
  becomes relevant.
- **Two Phase 2 spec ambiguities are logged**, to be settled before the QC gate is built:
  §4.6 says flag terminal value above **70–75%** of EV while §4.13 says **75%**; and §4.13 blocks
  on TV share or WACC−g spread *"without explicit discussion"*, which implies a documented-
  exception mechanism that sits in tension with "no warnings that can be ignored".

Start by reading the four documents, then propose the Phase 1 implementation plan — module
layout, the claim-extraction grammar, the resolution and tolerance rules, and how the corruption
test will be constructed. Do not write code until I approve the plan.
