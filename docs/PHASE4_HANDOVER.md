# Claude Code Handover — Phase 4: Sections 3 and 5

**Date:** 2026-09-10 · **Repo:** `github.com/Bobksl/Stock-Pitch-Engine` (public) ·
**Spec:** `docs/Equity_Research_Framework_v1.5.md` — **v1.5**

> Paste everything below the line into Claude Code at the repo root.

---

## BEGIN PROMPT

You are continuing an automated equity research pipeline. Phases 0 through 3 are complete
and merged to `main`, tagged `v0.1-phase-0` … `v0.4-phase-3`. The suite is green: **900
passed, 0 skipped**. Phase 4 is now open.

### Read first, in this order

1. **`CLAUDE.md`** — the constraints, and which document wins when they disagree. Read it
   before anything else.
2. **`PROGRESS.md`** — cross-session memory. The Phase 3 entry at the top is the current
   state of the world, and its "beliefs that turned out to be wrong" list is the most
   useful page in the repository. Every one of those produced a *plausible* number.
3. **`docs/Equity_Research_Framework_v1.5.md`** §3, §5, §6 and §8 — the spec, and the
   authority over everything including `CLAUDE.md`. **Check the version header says v1.5.**
   v1.0–v1.4 are superseded; the changelog says what changed and why.
4. **`docs/Workflow_Audit_v1.0.md`** §5 (LLM boundary map), §6 (gaps G1–G7) and the build
   sequence at §7. Not re-versioned. **Where audit and spec disagree, the spec wins.**

### What Phase 4 is

The Audit's Phase 4: **Sections 3 and 5** — thesis bridge, archetype logic, risk table,
Item 1A year-over-year diffs (R6), and cross-section consistency checks C1–C9.

The phase-numbering argument the Phase 3 handover had to settle is settled. The README
table and the Audit agree now: phase 3 was sections 1 and 2, phase 4 is sections 3 and 5,
phase 5 is assembly. Nothing to resolve.

### The exit criterion does not exist yet — propose one and get it approved

Each phase has had exactly one falsifiable exit criterion, and reporting against it rather
than against a sense of doneness is the house rule.

- Phase 0: *pull any US filer's segment revenue and profit, 5 years, cited, in one command.*
- Phase 1: *the verifier catches a deliberately corrupted figure in a test document.*
- Phase 2: *reproduce TSMC's published TWD 1,732.66, then flag all eight Audit §2 findings.*
- Phase 3: *draft sections 1 and 2 for AVGO in one command, every figure resolving, all five
  §1.5/§2.6 exhibits present, and one degraded draft per new rule tripping exactly it.*

Phase 3's criterion had to be **proposed and argued** because there was no published answer
to reproduce, and it settled on *verifiability plus detection*. Phase 4 has the same problem
and one extra: it is the first phase whose output must **agree with a previous phase's**.

A candidate worth arguing with: *produce a Section 3 and Section 5 for AVGO in which the
bridge components sum to the headline forecast, every driver names a model line, C3 proves
the DCF's forecast drivers are exactly the bridge components, C7 proves the top-ranked risks
are the bear case, and each new §3.9/§5.10 rule has a draft that trips exactly it.*

Note what makes it different from Phase 3's: **C3 and C7 are agreement checks against the
Phase 2 valuation engine**, which already exists and already passes its own tests. This is
the first time the two halves of the pipeline have to agree with each other, and that is
where the interesting failures will be. Say so explicitly when you propose the criterion.

### What already exists — build on it, do not rebuild it

Phase 4 is much less greenfield than it looks.

**`src/pitch/`** — the pitch layer. Separate from `src/sections/`, which means Item-anchored
segmentation of a *filing*.

- **`draft.py`** — the rendering contract, and the one to understand first. The LLM writes
  prose containing named **slots** and no numerals; `render()` substitutes the figure and
  its citation marker together. A numeral surviving in a template is a hard failure reported
  as `llm_computed_arithmetic`. Markers are **content-addressed** (§6.4), so editing prose
  never renumbers them. Exhibits are passed as `blocks`, and "which figures are used" is
  measured by scanning the final body for markers. **Section 3 and 5 prose goes through this
  same path — do not invent a second one.**
- **`types.py`** — §1.4h `TypeField`. Three verdicts, not two.
- **`overview.py` / `section2.py`** — Section 1 and 2 evidence assembly and their exhibits.
  Read these for the shape a section module takes.
- **`panel.py` / `industry.py`** — §2.4 period alignment and the industry panel.
- **`drawdown.py`** — §2.4/§2.5i peer drawdown. §5.4 says a *demonstrated* mitigant is one
  where "the company came through a prior episode of exactly this", and §2.5i's drawdown
  analysis is named as the evidence base. **Section 5 reads this, it does not recompute it.**
- **`compset.py`** — §2.3 two-tier comp set. §2.5h `structural_members()` vs the whole panel.
- **`kpi.py`** + `config/kpi_taxonomy.yaml` — the §7 taxonomy.
- **`primer.py`** — §2.8 versioned primer, content-addressed.

**`src/qc/`** — the gate.

- **`rules.py`** — the Class A / Class B registry. §3.9 and §5.10 fail conditions become
  entries here. **Read the reasoning comment about the Phase 3 prose rules before adding
  one**, and apply the test v1.3 wrote into §6.5: if no reason in the closed exception
  vocabulary could ever excuse a breach, it is Class A and Class B would be a door onto
  nothing.
- **`prose_rules.py`** — the §1.6 rules. §5.4's "management is aware is not a mitigant" is
  the same shape as `banned_language`; copy the pattern.
- **`cells.py`** — model cells, recomputed never stored. **Two closed vocabularies now**:
  `OPS` over scalars and `SERIES_OPS` over price series (v1.5). They deliberately refuse to
  mix.
- **`claims.py` / `resolve.py` / `recency.py` / `report.py`** — the numeric gate, unchanged
  in shape since Phase 1.

**Data.** Nine US filers, five 10-K years each, 0 reconciliation mismatches: AAPL, AMD,
AVGO, IBM, MRVL, MSFT, NVDA, ORCL, QCOM. A local `prices` table with ten tickers ×1,259
daily bars including SPY. AVGO fully chunked and embedded.

**`scripts/draft_pitch.py`** — the Phase 3 exit-criterion command. Extend it; do not fork it.

### What does NOT exist, and Section 3 needs it on day one

This is the most important paragraph in this handover.

**There is no evidence artifact.** §3.2's Step 0 is "dump every structured field from
Sections 1–2, then reason down the list to a conclusion" — and it exists *specifically* to
stop the model picking a narrative first and back-filling support, which the spec names as
its default failure mode. Right now Section 1's structured fields live only in memory inside
a `Section1Evidence` object for the duration of one command. **There is nothing on disk for
Section 3 to read.** Building that carriage is Phase 4's first task, and its design is a
decision to raise, not to assume.

**§1.4b `DriverMix` and §1.4d `ContractStructure` were never built.** They were deferred
through Phase 3 with the reason recorded: they are *judgment* fields — an LLM proposes, a
human approves — so they are inputs to evidence rather than outputs of it, and building a
schema with no consumer would have been speculative. **Section 3 is the consumer.** §3.4
requires two tags per driver and the first is "internal vs external, **inherited from
§1.4b**". You cannot build the bridge without building these first, and now you have a real
consumer to argue the schema against.

**`sizing_without_derivation` is registered and has no checker.** §2.5a/b market sizing needs
a TAM with bottom-up components (units × price, or customers × ACV) before the rule can
fire. `tests/test_phase3_exit_criterion.py` asserts this as the one pending rule so it
cannot be quietly forgotten — if you implement it, that assertion must be updated.

**No consistency-check module.** C10, C11 and C12 are enforced inside `src/qc`; C1 is
enforced in `compset.py`. C2 through C9 have no home at all. §8 says all of them are Class A
and any failure blocks publication. Decide early whether they become a module or entries in
the existing rule registry.

**ROIC is absent from the §2.4 panel** and prints as `NOT COMPUTED` with its reason: invested
capital needs stockholders' equity and `concept_map.yaml` maps none. If Section 5's
accounting-quality screen (§5.7a) needs balance-sheet concepts, add them there — it is a
reviewable diff, and the map is the only place tag resolution lives.

**One booby trap in that map, found 2026-09-10 and deliberately left unfixed.** The
`depreciation_amortisation` concept resolves for only three of the seven comp-set names.
The other four tag this instead:

```
AVGO:  Depreciation (n=90)      IBM:   Depreciation (n=158)
ORCL:  Depreciation (n=168)     MRVL:  OtherDepreciationAndAmortization (n=52)
```

**Do not add `us-gaap:Depreciation` to that concept.** Depreciation is not D&A. For Broadcom
in particular, amortisation of acquired intangibles from VMware, CA and Symantec is enormous,
so depreciation alone as an EBITDA add-back understates EBITDA badly and yields an EV/EBITDA
that looks entirely plausible and is wrong — then gets compared across the panel and
believed. That is the failure class this whole project exists to prevent, and it is one
tempting line away.

The honest treatment is a modelling decision rather than a mapping tweak: D&A for EBITDA is
depreciation **plus** amortisation of intangibles, or the cash-flow-statement line where a
filer tags it. It belongs with §4.8 in Phase 5, tested on Broadcom, where the intangibles are
large enough that a wrong answer is obvious.

### The rules that will bite in Phase 4 specifically

Phase 3 wrote the first rules about *prose*. Phase 4 writes the first rules about *agreement
between sections*, and that is a different kind of failure.

- **§3.4's bridge must sum to the headline forecast.** Arithmetic, Class A, and the first
  cross-section arithmetic check in the pipeline. `cells.py` already has `sum`; use it, so
  the total is recomputed rather than asserted.
- **C3 is the hard one.** "DCF forecast drivers = Section 3 bridge components, exactly."
  Phase 2's `src/valuation/` already builds a DCF from `ValuationInputs`. Making the two
  agree means one of them has to become the source of the other, and §4.5 says which: *"The
  DCF's forecast drivers ARE the Section 3 bridge. Not new assumptions."*
- **§3.9 and §5.10's shape conditions.** "More than one primary archetype", "more than 3
  pillars", "risk with no early-warning signal". Apply the v1.3 §6.5 test to each, and
  remember Phase 3's split: three of §2.7's five conditions became **construction-time
  invariants** with no rule at all, because a defect that cannot be built cannot reach the
  gate. §5.2's "risks attack pillars, not companies — mechanically enforceable via the
  required pillar reference" is asking for exactly that treatment.
- **§5.4's assertion-mitigants.** "Management is aware" and "they have a strong team" are
  flagged automatically. Same shape as `banned_language`; it belongs in `prose_rules.py`.
- **The LLM decides the archetype, with human approval** (Audit §5). That is the same pattern
  as §2.3's comp set: auto-propose, human approves, refuse to construct without approval.
  `compset.py` shows how — a member without `approved_by` raises.
- **§6.1's banned language and §6.2's carve-out** apply to Section 3 and 5 prose exactly as
  they applied to Section 1's. `prose_rules.py` already enforces them.

### Three design forks to raise before coding — do not resolve any unilaterally

**1. How structured fields travel from Section 1 to Section 3.** The evidence-artifact gap
above. A serialised YAML under `data/pitches/<TICKER>/<as_of>/` was sketched in the Phase 3
plan and never built, so nothing constrains you. Whatever you choose has to answer: what
does §3.2's Step 0 read, how does C1 check the type field against what Section 3 used, and
what stops a stale artifact being read as current. `primer.py` solves a near-identical
problem with content addressing and an expiry that blocks — read it before designing.

**2. Consensus estimates (Audit G3) — and the one thing worth asking Bloomberg for.**
§3.5 variant perception is *"definitionally impossible"* without consensus, and the Audit
calls this the hardest dependency in the framework to replace.

**Verified against the live moomoo gateway, 2026-09-10:**
`get_research_analyst_consensus.py US.AVGO` returns consensus rating, analyst count, rating
distribution and target prices — high 630 / average 528 / low 400 across 28 analysts,
updated 2026-09-09. **Also verified: it does NOT return forward revenue or EPS estimates by
fiscal year**, which is what §3.5 actually asks for; the earnings endpoints return price
behaviour and IV crush, not estimates.

So G3 is **partly** closed. The target-price consensus is real, carries no Bloomberg
dependency, and is directly usable for §4.9's upside comparison. The forward-estimate
consensus is not covered by anything the project has, and that is the gap Phase 4 has to
decide about.

**The AVGO RV comps re-pull was cancelled on 2026-09-10, and this is why it matters here.**
That export was the standing Bloomberg ask, and three of the four things it existed to
supply are now better answered without it: comp-set membership (it was a 2-year correlation
screen — GOOGL, AMZN, META, PLTR, Samsung — not a comp set, and there is now an approved
§2.3 set), the missing growth column, and the missing profitability column. Its currency
mixing and its calendarisation against an October fiscal year end are moot for the same
reason. Checked on the live corpus: revenue, net income, diluted shares, cash and long-term
debt are present for all seven names and operating income for six, so **enterprise value is
computable** from facts plus moomoo prices, and EV/Sales, EV/EBIT and P/E with it — every
figure a recomputed model cell rather than a stored external record, which is the difference
§6.4 exists to enforce.

**If you want one thing from Bloomberg, ask for BEst forward revenue and EPS by fiscal year
for the six approved comp-set members.** That closes G3. A re-pulled RV screen carrying
trailing multiples on the wrong companies does not.

**3. Boilerplate outranks substance.** Deferred through two phases and now due: the
safe-harbour paragraph beats real risk disclosure in retrieval, which threatens §5.7b's Item
1A year-over-year diff — a load-bearing Section 5 input. Candidate remedies are the roadmap
reranker or an index-time boilerplate classifier; neither is chosen. Note that R4's
per-entity quota now exists in `src/retrieval/chat.py` and is **off by default**, and the
labelled question set has 9 corpus-wide questions of which 7 are multi-filer. If you measure
a reranker, measure it on those, not on the full 49.

### What Phase 3 learned that will save you a day

Every one of these produced a plausible number or a plausible reading. They are in
`PROGRESS.md` in full.

- **A wrong figure that resolves is the failure mode.** Both single-series readings of a
  recovery time gave a table that looked right; one said AMD never recovered from 2022 and
  the other silently measured a different drawdown. Cross-check any new statistic against an
  independent path before believing the table.
- **Measure the thing you are claiming.** The R4 watch item was the top-*document* share at
  49.1%; the number that actually breaks a cross-company panel is the top-*entity* share at
  98.4%. And the quota "cost hit rate" only when applied to the 40 of 44 questions that name
  a single company.
- **Filers disagree about what a profit measure is.** QCOM reports segment EBT, IBM tags no
  `OperatingIncomeLoss` at all, and QCOM's segment revenue does not sum to its consolidated
  total *and is complete as filed*. Do not map one to the other; §4.8's
  `comp_definitions_inconsistent` is Class A.
- **Test-first with hand-checked values, and check the constant against the filing.** Two
  guessed constants were caught by the RED run this way (AVGO's R&D is 10,977, not 9,728),
  and one test fixture was wrong while the code was right.
- **The heredoc/escaping trap.** Multi-line Python written through a shell heredoc mangles
  `\n` and line-continuation backslashes. Use the file-writing tools for anything with
  escapes.

### Live case study data (AVGO)

`../Case Study - AVGO Stock Pitch/`, **outside the repo and it must stay there** — the DES
PDF carries "Not for redistribution."

- **Beta complete and correct** — raw 1.818, 5y weekly vs SPX, 260 points. Use RAW; the code
  applies Blume and Bloomberg's "Adjusted 1.545" is already Blume.
- **The RV comps export is retired.** It had finished multiples but no growth and no
  profitability column, and it was a 2-year correlation screen rather than a comp set. A
  re-pull was promised for months and was **cancelled on 2026-09-10**: the approved §2.3 comp
  set replaces its membership, and growth, profitability and enterprise value are all
  computable from EDGAR facts plus the local price table, in USD, calendar-aligned. Do not
  reinstate it. See design fork 2 for the ask that replaced it.
- ECFC gives **real** GDP only (2.1%). Terminal growth must be derived nominal (~4.4%) and
  declared as such, or it is Audit defect 4 verbatim.

### Working style

- **Ask before deviating from the spec.** When the spec genuinely has a hole, *amend the spec
  in the same pass* — v1.3, v1.4 and v1.5 all exist because Phase 3 hit one, and each
  amendment names the code that found it. Do not carry a local extension.
- **Test-first on anything numeric, with hand-checked expected values.** Never derive an
  expected value from the implementation.
- **Only the acceptance test asserts the whole thing.** Every other test scopes to the rules
  it is about, or it churns whenever a rule is added.
- **Run pytest to a file and check `$?`.** `pytest -q | tail && git commit` reads *tail's*
  exit code; a red suite got committed that way once.
- Interpreter: `C:\Users\user\venvs\filings-rag\Scripts\python.exe`. The system `python`
  lacks the dependencies. Postgres runs in Docker: `docker start filings-db`.
- Small commits, each mapped to a phase step and a spec section, with the reasoning in the
  message — why the design is this shape, and what was tried and rejected.
- File a finding whenever a filing or a test surprises you, titled as the rule so it is
  findable in six months.
- Update `PROGRESS.md` at session end: done, next, decisions, and the beliefs that turned out
  to be wrong.

### State of the tree

Clean. `main` is pushed and tagged `v0.4-phase-3`; the Phase 3 branch is on the remote. There
is no uncommitted work.

Two things carry an owner dependency rather than a code one:

- **`config/comp_sets/avgo.yaml` names the owner as approver on six members**, and the
  justifications were written by the previous agent because §2.3 refuses an unapproved
  member and the code needed one to run. It has not been reviewed by a human. Treat it as a
  working placeholder, not a decision — particularly NVDA, tiered direct-only on the grounds
  that a tenfold size gap disqualifies a valuation reference.
- **`research_cli.py ingest` cannot link chunks to Items.** It segments at step 5/5 but
  chunking is a separate later step, so `apply_to_chunks` never fires in that flow. Every
  filer ingested through the CLI and embedded afterwards needs a manual
  `router.segment_html(doc_id, apply_to_chunks=True)` pass; AVGO's five documents got one.
  The fix is one line but belongs in its own commit with its own test, because `chunk_embed`
  also serves the HK PDF path that `PROGRESS.md` records as needing to stay byte-identical.

### First task

Read the spec and the audit, then **propose a Phase 4 plan**: the exit criterion you want to
be held to, how the Section 1–2 evidence artifact is carried and invalidated, how §1.4b and
§1.4d are typed now that Section 3 consumes them, how the §3.3 archetype is proposed and
approved, where C2–C9 live, how §3.9 and §5.10 fail conditions split between gate rules and
construction-time invariants, and your recommendation on the three design forks above.

**Do not write code yet. Show the plan and wait for approval.**

## END PROMPT
