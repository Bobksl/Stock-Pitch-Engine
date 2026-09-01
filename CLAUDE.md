# Stock Pitch Engine — instructions for AI coding sessions

A spec-driven equity research pipeline: filings in, a verified stock pitch and an auditable
Excel model out. The deterministic QC gate is the product; the RAG is a component.

## Which document wins

Several files in this repository claim authority and they do not agree. In order:

1. **`docs/Equity_Research_Framework_v1.2.md`** — the spec. Wins over everything, including
   this file. Check the version header; v1.0 and v1.1 are superseded and their changelogs
   say what changed. Do not build against them.
2. **`docs/Workflow_Audit_v1.0.md`** — architecture, data lineage, and the eight findings
   the valuation engine is tested against. **Not re-versioned:** it still describes the v1.0
   provenance model in §3 and §5. Where audit and spec disagree, the spec wins.
3. **`PROGRESS.md`** — current state, decisions taken, and the gotchas that cost real time.
   Read it first in any session.
4. `ARCHITECTURE.md`, `equity_filings_rag_architecture.md`, `project_guideline.md` —
   **historical.** They describe the July 2026 Hong Kong RAG demo and call themselves
   authoritative. They are not, for anything in phases 0–2. Useful for the rationale behind
   the stack choices below and nothing else.

## Hard constraints — the framework ones

These are the reasons the project exists. Breaking one silently is worse than not shipping.

- **The LLM never computes a number that appears in an output.** It narrates figures already
  computed in Python. Retrieval is never the source of a figure (spec P1, P2).
- **All financial arithmetic in `Decimal`, never float.** `money.D()` refuses a float. There
  are exactly two sanctioned crossings, both named: `from_spreadsheet` and `to_spreadsheet`.
  Anywhere else, a float is a bug.
- **Every figure resolves to one of three provenance classes** — fact, derived, external —
  and resolution is anchor-based, never a search of the facts table. Derived figures are
  recomputed, never stored (spec §6.4).
- **Class A is never exceptionable.** Class B is, by a declared record with a required
  expiry. The guarantee is structural: a record naming a Class A rule fails to *parse*, so
  no code path can consult one. Do not add an override, a severity, or a warning tier —
  each was considered and rejected, and the reasoning is in `src/qc/rules.py` (spec §6.5).
- **QC failures block.** There is exactly one passing state. An observation that cannot
  block is a warning by another name; if something must always be reported without blocking,
  it is a `Measurement`, which makes no claim about acceptability.
- **No calculation tab without C11 coverage in the same commit.** Calc cells hold formulas,
  never pasted values — otherwise recalculation agrees trivially and the reconciliation
  tests nothing. A missing recalculation engine raises; it does not skip.
- **Licensed terminal data never enters the repository.** This repo is public and Bloomberg
  exports carry a no-redistribution notice. `scripts/pre-commit` blocks those paths
  (`git config core.hooksPath scripts`). Encode the arithmetic you need as test constants —
  `tests/test_comps.py` does this with the Reddit worked example.
- Bloomberg-derived *text* is processed locally only (Ollama via `LLM_BASE_URL`).

## Hard constraints — the stack (decided, do not re-litigate)

- LLM: DeepSeek `deepseek-v4-flash` via the OpenAI SDK, `base_url=https://api.deepseek.com`.
  Never the deprecated `deepseek-chat` / `deepseek-reasoner` aliases.
- Embeddings: local `BAAI/bge-m3` (sentence-transformers, CPU, fp16, 1024-dim). DeepSeek has
  no embeddings API.
- Store: PostgreSQL + pgvector only (`schema.sql`, `schema_facts.sql`; HNSW + cosine).
- RAG loop: raw Python + SQL. **No LangChain / LlamaIndex** — the owner must be able to
  explain every line in an interview.
- Secrets from `.env` via python-dotenv. Never hardcode a key; the hook blocks `.env` too.
- Filings: manual download only for HKEX — their ToU prohibits scraping. Never write a
  scraper for hkexnews.hk. EDGAR is fetched through the rate-limited cached client.
- **Interpreter: `C:\Users\user\venvs\filings-rag\Scripts\python.exe`** (outside OneDrive
  deliberately). The system `python` lacks the dependencies.

## Working style

- **Ask before deviating from the spec.** If a rule seems wrong, raise it. Every rule was
  argued through. When the spec genuinely has a hole, *amend the spec* in the same pass
  rather than carrying a local extension — v1.2 exists because §4.13 was missing a rule the
  exit criterion required.
- **Test-first on anything numeric, with hand-checked expected values.** Never derive an
  expected value from the implementation.
- Small commits, each mapped to a phase and a spec section. Commit messages carry the
  reasoning — why the design is this shape, and what was tried and rejected.
- **Only the acceptance test asserts exact totals.** Every other test scopes to the rules it
  is about, or it churns whenever a rule is added.
- **Run pytest to a file and check `$?`.** `pytest -q | tail && git commit` reads *tail's*
  exit code; a red suite got committed that way once.
- Update `PROGRESS.md` at session end — done, next, decisions. It is the cross-session memory.
- File a finding whenever a filing or a test surprises you, titled as the rule so it is
  findable later.
- The owner is a beginner with Postgres and VS Code — give exact commands for DB work.

## Gotchas that will cost you an hour

- **`numpy.float64` subclasses `float`.** NumPy 2's repr is `np.float64(6973.97)`, which
  `Decimal` cannot parse. `from_spreadsheet` coerces with `float()` first — do not remove it.
- **openpyxl writes 16 significant digits** whatever you hand it, `Decimal` or `float`.
  `to_spreadsheet` matches that format so the workbook round-trip is exact.
- **`Decimal` context precision is set process-wide in `money.py`.** Without it, `divide`
  and `power` run at 50 digits while every `+ - *` runs at 28.
- **The console codepage here is GBK.** `U+2212` (minus sign) raises `UnicodeEncodeError` on
  print; use ASCII hyphens in anything a CLI renders. `PYTHONIOENCODING=utf-8` helps.
- **`formulas` recalculation takes ~8s** per workbook. Keep C11 fixtures small.
- **Two defect-numbering schemes exist** for the same eight TSMC findings — the audit's §2
  headings and the exit-criterion table disagree by one. The mapping lives in
  `src/qc/rules.py` and nowhere else. Use the exit-criterion numbering.
