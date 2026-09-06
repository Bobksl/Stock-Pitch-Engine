# Claude Code Handover — Phase 3: Sections 1 and 2

**Date:** 2026-09-06 · **Repo:** `github.com/Bobksl/stock-pitch-engine` (public, renamed from
`Equity-Filings-RAG`) · **Spec:** `docs/Equity_Research_Framework_v1.2.md` — **v1.2**

> Paste everything below the line into Claude Code at the repo root.

---

## BEGIN PROMPT

You are continuing an automated equity research pipeline. Phases 0, 1 and 2 are complete and
merged to `main`, tagged `v0.1-phase-0` … `v0.3-phase-2`. The suite is green: **566 passed,
64 skipped**. Phase 3 is now open.

### Read first, in this order

1. **`CLAUDE.md`** — the constraints. It states which document wins when they disagree, and
   the gotchas that cost real time. Read it before anything else.
2. **`PROGRESS.md`** — cross-session memory. Current state, decisions taken, war stories.
   The Phase 2 entry at the top is the most recent state of the world.
3. **`docs/Equity_Research_Framework_v1.2.md`** §1, §2, §6, §7 — the spec, and the authority
   over everything including `CLAUDE.md`. **Check the version header says v1.2.** v1.0 and
   v1.1 are superseded; their changelogs say what changed.
4. **`docs/Workflow_Audit_v1.0.md`** §3 (data lineage) and the build sequence around line 178.
   Not re-versioned — it still describes the v1.0 provenance model in §3 and §5. **Where audit
   and spec disagree, the spec wins.**

### What Phase 3 is — and a naming conflict to resolve first

The Audit's build sequence and the README's phase table disagree, and you should settle this
before writing anything:

| | Phase 3 | Phase 4 | Phase 5 |
|---|---|---|---|
| **Audit** (line 184–188) | **Sections 1 and 2** — extraction, KPI taxonomy, industry panel, peer drawdown, primer caching (R4) | Sections 3 and 5 — thesis bridge, archetype logic, risk table, YoY diffs, consistency checks C1–C9 | Assembly and monitoring |
| **README** (phase table) | "narrative — section drafting" | "assembly — full pitch, risks, monitoring" | — |

The Audit is the more specific and the more load-bearing document, and its sequencing rationale
is explicit. **Build the Audit's Phase 3: Sections 1 and 2.** Then fix the README table in the
same pass so the two stop disagreeing — this is a documentation bug, not a scope decision.

### The exit criterion does not exist yet — propose one and get it approved

Phases 0, 1 and 2 each had a single falsifiable exit criterion, and reporting against it rather
than against a sense of doneness is the house rule. The Audit gives Phase 3 a component list and
no criterion. **Your first deliverable is to propose one.** It should be a single command whose
output is checkable by hand against a real filing, in the shape of the previous three:

- Phase 0: *pull any US filer's segment revenue and profit, 5 years, fully cited, in one command.*
- Phase 1: *the verifier catches a deliberately corrupted figure in a test document.*
- Phase 2: *reproduce TSMC's published TWD 1,732.66, then flag all eight Audit §2 findings.*

A candidate worth arguing with: *produce a Section 1 and Section 2 draft for AVGO in which every
figure resolves to a fact anchor, the QC gate passes, and the §1.4h type classification is
derived from profit-weighted segment reality rather than GICS.* Note the asymmetry — Phase 2 had
a known-good published answer to reproduce and Phase 3 has nothing equivalent, so the criterion
has to lean on **verifiability of every figure** rather than on matching a target. Say so
explicitly when you propose it.

### What already exists — build on it, do not rebuild it

Phase 3 is much less greenfield than it looks. Read these before designing anything:

- **`src/facts/api.py`** — `get_fact`, `get_series`, and **`get_segment_panel`**, which already
  returns a `SegmentPanel` of revenue *and* operating income by segment. §1.3's hardest
  requirement ("segment revenue **and** operating profit — required, not optional") is largely
  already served.
- **`src/sections/us.py` / `router.py`** — Item-anchored segmentation. §1.2's Item 1 / 1A / 7
  inputs come from here. `SegmentationError` is deliberate: a wrong-but-plausible segmentation
  is worse than a hard failure, and there is a test asserting it never silently falls back.
- **`src/qc/`** — `claims` · `anchors` · `resolve` · `external` · `recency` · `rules` ·
  `exceptions` · `findings` · `report`. This is the whole Phase 1 verification layer and it is
  what makes a narrative section trustworthy. §1.6's recency rule is `recency.py` already.
- **`src/qc/rules.py`** — the Class A / Class B registry. §1.6 and §2.7 fail conditions become
  entries here. Read the reasoning comments in that file before adding one.
- **`src/retrieval/`** — chat, the retrieval SQL, and the eval harness with a measured baseline
  (hit@5 88.6%, MRR 0.820 over 44 labelled questions). Narrative evidence comes through here.
- **`src/valuation/comps.py`** — §4.8's comp set. §2.3's **valuation-reference tier** is the
  same object; do not build a second comp-set concept.

### The rules that will bite in Phase 3 specifically

Phase 2 was arithmetic, where the constraints were easy to feel. Phase 3 is the first phase that
generates prose, which is exactly where they get violated quietly.

- **The LLM never computes a number that appears in an output.** It narrates figures already
  computed in Python. The judgment layers (§1.4, §2.5) are the LLM's job; every figure inside
  them is resolved, not generated. Retrieval is never the source of a figure.
- **Every figure resolves to one of three provenance classes** — fact, derived, external —
  anchor-based, never a search of the facts table. Derived figures are recomputed, never stored.
- **`Decimal`, never float.** Two sanctioned crossings only: `from_spreadsheet`,
  `to_spreadsheet`.
- **QC failures block; there is exactly one passing state.** If something must be reported
  without blocking, it is a `Measurement`, not a warning tier. Class A is never exceptionable —
  a record naming a Class A rule fails to *parse*. Do not add a severity ladder; it was
  considered and rejected.
- **§1.4 b, d and h are structured fields, not prose.** They are consumed by Sections 3 and 4.
  Model them as data with a schema; the narrative renders from them.
- **§1.6 and §2.7 turn evidence rules into gate rules.** "Pricing-power claim without a
  supporting number" and "segment revenue shown without segment profit" are Class A: they are
  correctness, not shape. "Comp set inherited from GICS without type-field justification" is
  arguably Class B. Argue each one explicitly rather than defaulting.
- **§6.1 banned language and §6.2 the marketing carve-out** apply to generated prose for the
  first time here.

### Two design forks to raise before coding — do not resolve either unilaterally

**1. Peer drawdown needs market data the pipeline does not have.** §2.4 requires peak-to-trough
drawdown, recovery time, downside capture, correlation and beta over defined stress windows, and
§2.5i calls it *"the first place market data enters, and the only input that reveals what the
market actually believes."* There is no price table in `schema.sql` or `schema_facts.sql` and no
market-data ingestion anywhere in `src/`. Bloomberg is the owner's available source and
**licensed terminal data can never enter this public repo** — `scripts/pre-commit` hard-blocks
those paths, and that is licensing exposure, not privacy. So Phase 3 needs a decision on where
price history comes from and how it stays out of git. `src/qc/external.py` and the `beta.py`
external-record route are the shape to reuse, but the ingestion question is open. **Raise it.**

**2. Period alignment (§2.4) is a correctness trap with a stated default.** The spec is
unusually specific: exclusion of an off-cycle peer is the default, and mis-assignment to a
calendar period is *never* acceptable because it silently corrupts every cross-sectional
comparison built on the panel. The SEC `frames` tolerance window must be documented in code.
This is the §4.8 "same calendar period across all peers" enforcement mechanism, so it is
load-bearing for Phase 4 too. Get the tolerance right before building the panel on top of it.

Also still open and explicitly **not Phase 3's to decide**: the finding *"Boilerplate outranks
substance: the safe-harbour paragraph beats real risk disclosure."* It threatens §5.7b's Item 1A
diff. Candidate remedies are the roadmap reranker or an index-time boilerplate classifier.
**Phase 4 design fork — flag it, do not resolve it.**

### Live case study data (AVGO)

`../Case Study - AVGO Stock Pitch/`, **outside the repo and it must stay there** — the DES PDF
carries "Not for redistribution." Reviewed 2026-09-02; see `PROGRESS.md` for the full note:

- **Beta complete and correct** — raw 1.818, 5y weekly vs SPX, 260 points. Use RAW; the code
  applies Blume, and Bloomberg's "Adjusted 1.545" is already Blume.
- **DES**: price 370.34 · market cap 1,761.9B · EV 1,807.2B · 4,757.6M shares · FY-end 10/2025 ·
  segments Semiconductor Solutions 36.86B / Infrastructure Software 27.03B (57.7 / 42.3).
  That 57.7/42.3 revenue split against the *profit* split is exactly the §1.4h test case.
- **Blocked**: the RV comps export has finished multiples but no growth and no profitability
  column, so §4.8's regression and growth-adjusted cross-check are both uncomputable. It is
  also a 2Y-correlation screen, not a comp set — which makes it a live illustration of §2.3's
  two-tier rule. A re-pull was promised.
- ECFC gives **real** GDP only (2.1%). Terminal growth must be derived nominal (~4.4%) and
  declared as such, or it is defect 4 verbatim.

### Working style

- **Ask before deviating from the spec.** Every rule was argued through. When the spec has a
  genuine hole, *amend the spec in the same pass* — v1.2 exists because §4.13 was missing a rule
  the exit criterion required. Do not carry a local extension.
- **Test-first on anything numeric, with hand-checked expected values.** Never derive an
  expected value from the implementation.
- **Only the acceptance test asserts exact totals.** Every other test scopes to the rules it is
  about, or it churns whenever a rule is added.
- **Run pytest to a file and check `$?`.** `pytest -q | tail && git commit` reads *tail's* exit
  code; a red suite got committed that way once.
- Interpreter: `C:\Users\user\venvs\filings-rag\Scripts\python.exe`. The system `python` lacks
  the dependencies.
- Small commits, each mapped to a phase and a spec section, with the reasoning in the message.
- File a finding whenever a filing or a test surprises you, titled as the rule so it is findable
  in six months.
- Update `PROGRESS.md` at session end: done, next, decisions.

### One piece of uncommitted work in the tree

A CI fix was made on 2026-09-06 and **may still be uncommitted** — check `git status` first.
CI was red on every push since the workflow was added in `61c2dba` while the developer
environment was green, because the workflow installs a deliberate subset of dependencies and
several modules imported missing drivers at module scope, killing collection before any skip
guard could run. Three files: `src/db.py` (driver imports deferred into `get_conn`), a new
`pytest.ini` (`testpaths = tests`, so `scripts/test_llm.py` stops being collected as a test),
and `.github/workflows/tests.yml` (adds `tiktoken` and `openai`). Verified 566 passed / 64
skipped in both a CI-equivalent venv and the developer environment. If it is uncommitted, land
it on its own before starting Phase 3 — a green baseline is the point.

### First task

Read the spec and the audit, then **propose a Phase 3 plan**: the exit criterion you want to be
held to, module layout under `src/sections/`, how §1.4's structured fields (b, d, h) are typed
and carried to Sections 3 and 4, how §1.6 and §2.7 fail conditions map onto Class A / Class B in
`src/qc/rules.py`, how the §7 KPI taxonomy is represented, how §2.8 primer versioning works, and
your recommendation on the two design forks above.

**Do not write code yet. Show the plan and wait for approval.**

## END PROMPT
