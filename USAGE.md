# Usage Guide

What this system does, when to reach for it, and exactly what to expect from each input.
New here? Install first with [SETUP.md](SETUP.md). The specific answers below come from the
demo corpus (Tencent 0700, Bilibili 9626, HSBC 0005 × FY2024/25); with your own PDFs the shape
of the output is identical.

## Before anything: start the stack

```bash
# 1. Start Docker Desktop, then the database
docker start filings-db

# 2. Activate the virtualenv (created in SETUP.md)
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)

# 3. (UI users) launch the app — opens at http://localhost:8501
streamlit run src/app.py
```

The first question after any launch takes ~90 s (the embedding model loads once); every
question after that returns in ~15–40 s. Run all commands from the project root. On Windows,
add `-X utf8` to Python commands so the console doesn't choke on non-ASCII text.

**Using a different LLM?** Everything below is provider-agnostic. Set `LLM_BASE_URL` /
`LLM_MODEL` / `LLM_API_KEY` in `.env` (DeepSeek, OpenAI, OpenRouter, Groq, Ollama, … — table in
[.env.example](.env.example)) and run `python scripts/test_llm.py` to confirm. No code changes.

---

## Scenario 1 — "What does this filing say about X?" (cited Q&A)

**When:** you need a fact from a long report and you need to verify it — revenue drivers,
margins, dividends, capital ratios, stated risks, segment performance.

**How (UI):** type into the 💬 Chat tab; optionally set the ticker/year filters in the sidebar.
**How (CLI):**

```bash
python -X utf8 -m src.rag_chat "What dividend did Tencent declare for 2025?" --ticker 0700.HK
```

**Expected result:** a concise answer where *every claim* carries an inline tag like
`[0700.HK 2025 annual | MD&A | p.7-8]`, followed by the retrieved chunks and their cosine
distances. In the UI, the right-hand **Sources** panel shows each cited chunk's actual text —
open the source PDF at that page to verify. Examples from the demo corpus:

| Input | Expected output |
|---|---|
| "What dividend did Tencent declare for 2025?" | HKD 5.30 per share, cited to p.7 and p.119 |
| "How did Bilibili's gross margin change in 2025?" | 36.6% vs 32.7%, drivers, gross profit +27% to RMB11.11B |
| "What was HSBC's CET1 ratio in 2025?" | 14.9%, stable; RWA growth offset by capital generation |

If the corpus doesn't contain the answer, the system replies **"Not found in the provided
filings."** and stops — it will not guess. No citation, no claim.

**Tips:** name the entity or set the ticker filter (multi-entity questions can let one document
dominate retrieval); one topic per question beats compound questions; raise top-k in the sidebar
(8 → 12–16) if a niche topic comes back "not found".

## Scenario 2 — "Compare X across entities or years"

**When:** cross-sectional or year-over-year questions — growth rates, strategy shifts, risk
language.

**How:** ask with both subjects named and no ticker filter:
"Compare the 2025 revenue growth and main drivers of Tencent and Bilibili."

**Expected result:** a per-entity breakdown with citations drawn from *both* documents (e.g.
Tencent +13.9% to RMB751.8bn vs Bilibili +13% to RMB30.35bn, with segment splits, each figure
tagged to its own source).

## Scenario 3 — "What changed since last year?" (alerts feed)

**When:** a new report lands and you want the material deltas without re-reading hundreds of
pages.

**How (UI):** open the 🔔 Alerts tab. **How (regenerate via CLI):** see Scenario 4, last two
commands.

**Expected result:** one alert per section that changed materially, quoting figures — e.g. for
Tencent FY2024→25: revenue growth acceleration (8%→14%), capex growth collapse (+221%→+3%), and
a new pledged-equity risk (RMB3.3B) absent the prior year. Sections with nothing material are
suppressed. Every alert links to its source section and page span.

## Scenario 4 — "Add a document to the corpus"

**When:** you have a new PDF to index.

**How:** name it `{TICKER}_HK_{YEAR}_{annual|interim}.pdf` (e.g. `0941_HK_2025_annual.pdf`), drop
it in `sample_pdfs/`, then:

```bash
python -X utf8 -u -m src.ingest sample_pdfs/0941_HK_2025_annual.pdf   # prints a doc_id, e.g. 41
python -X utf8 -u -m src.chunk_embed --doc-id 41                      # ~25 min per 200 pages (CPU)
python -X utf8 -u -m src.sections --doc-id 41 --apply
python -X utf8 -u -m src.alerts summarize --doc-id 41
# if the prior year of the same issuer is also indexed:
python -X utf8 -u -m src.alerts diff --ticker 0941.HK --from-year 2024 --to-year 2025
```

**Expected result:** ingest reports pages stored and how many needed OCR (scanned and broken-font
pages are detected automatically); embedding reports chunk count; sections prints the detected
page map; summarize writes per-section summaries + a `new_filing` alert; diff writes
`change_detected` alerts. The document is immediately searchable in chat and shows in the 📄
Corpus tab. Re-running any step on the same file is safe (idempotent).

> **Filenames / non-HK markets:** the parser (`FILENAME_RE` in `src/ingest.py`) expects the
> `TICKER_HK_YEAR_type` shape and tags the ticker as `TICKER.HK`. For other markets, edit that one
> regex (and the optional `COMPANY_NAMES` lookup) — the rest of the pipeline is market-agnostic.

## Scenario 5 — "Audit the data / run SQL yourself"

**When:** you want to verify a citation at the source, or explore with plain SQL.

**How:** the VS Code PostgreSQL extension (host `127.0.0.1`, port `5432`, user `postgres`,
password `devpass`, db `filings`) or `docker exec -it filings-db psql -U postgres -d filings`.

```sql
-- does the cited page really contain the figure?
SELECT page_num FROM pages p JOIN documents d USING (doc_id)
WHERE d.ticker='0700.HK' AND d.fiscal_year=2025 AND raw_text LIKE '%5.30%';
```

**Expected result:** one relational schema holds everything — `documents`, `pages`, `sections`,
`chunks` (with pgvector embeddings), `summaries`, `alerts` — so every AI output traces back to
raw stored text with plain SQL.

## What this system is NOT for

- **Facts outside the indexed documents** (news, live prices, un-indexed entities) — it refuses.
- **Sentence-level page precision** — citations are chunk-level page ranges (`p.5-6`).
- **Heavy numerical analysis** — it quotes and compares reported figures; it does not build models.
  Pull data via SQL if you need computation.
- **Financial or investment advice** — it is a document-research tool; its outputs are extracts
  from filings you supply.
