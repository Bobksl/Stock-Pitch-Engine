# Usage Guide — Equity Filings RAG

What this system does, when to reach for it, and exactly what to expect from each input.

## Before anything: start the stack

```bat
:: 1. Start Docker Desktop, then the database
docker start filings-db

:: 2. Activate the Python environment
C:\Users\user\venvs\filings-rag\Scripts\activate

:: 3. (UI users) launch the app — opens at http://localhost:8501
streamlit run src/app.py
```

First question after a launch takes ~90 s (the embedding model loads once); every question
after that returns in ~15–40 s. All commands below run from the project root.

---

## Scenario 1 — "What does the filing say about X?" (cited Q&A)

**When:** you need a fact from an annual report and you need to be able to verify it —
revenue drivers, margins, dividends, capital ratios, stated risks, segment performance.

**How (UI):** type the question into the 💬 Chat tab. Optionally set the ticker/year filters
in the sidebar to restrict the search. **How (CLI):**

```bat
python -X utf8 -m src.rag_chat "What dividend did Tencent declare for 2025?" --ticker 0700.HK
```

**Expected result:** a concise answer where *every claim* carries an inline tag like
`[0700.HK 2025 annual | MD&A | p.7-8]`, plus the list of retrieved chunks with their cosine
distances. In the UI, the right-hand Sources panel shows each cited chunk's actual text —
open the source PDF at the cited page to verify. Real examples the corpus answers correctly:

| Input | Expected output |
|---|---|
| "What dividend did Tencent declare for 2025?" | HKD 5.30 per share, cited to p.7 and p.119 |
| "How did Bilibili's gross margin change in 2025?" | 36.6% vs 32.7%, drivers, gross profit +27% to RMB11.11B |
| "What was HSBC's CET1 ratio in 2025?" | 14.9%, stable; RWA growth offset by capital generation |

If the corpus doesn't contain the answer, the system says **"Not found in the provided
filings."** — it will not guess. That refusal is a feature: no citation, no claim.

**Tips:** name the company or set the ticker filter (multi-company questions can let one
issuer dominate retrieval); one topic per question beats compound questions; raise top-k in
the sidebar (8 → 12–16) if a niche topic comes back "not found".

## Scenario 2 — "Compare X across companies or years"

**When:** cross-sectional or YoY questions — growth rates, strategy shifts, risk language.

**How:** ask with both subjects named, no ticker filter:
"Compare the 2025 revenue growth and main drivers of Tencent and Bilibili."

**Expected result:** a per-company breakdown with citations drawn from *both* issuers'
filings (e.g. Tencent +13.9% to RMB751.8bn vs Bilibili +13% to RMB30.35bn, segment splits,
each figure tagged to its own document).

## Scenario 3 — "What changed since last year?" (alerts feed)

**When:** a new annual report lands and you want the material deltas without re-reading
300 pages.

**How (UI):** open the 🔔 Alerts tab. **How (regenerate via CLI):** see Scenario 4 steps 3–4.

**Expected result:** one alert per section with material changes, quoting figures — e.g. for
Tencent FY2024→25: revenue growth acceleration (8%→14%), capex growth collapse (+221%→+3%),
a new RMB3.3B pledged-equity risk absent in FY2024. Sections with nothing material are
suppressed ("NO MATERIAL CHANGES"). Every alert links to its source section and page span.

## Scenario 4 — "Add a new filing to the corpus"

**When:** you downloaded a new annual report from HKEXnews (manually — never scrape).

**How:** name the file `{code}_HK_{year}_annual.pdf` (e.g. `0941_HK_2025_annual.pdf`), put it
in `sample_pdfs/`, then:

```bat
python -X utf8 -u -m src.ingest sample_pdfs/0941_HK_2025_annual.pdf   :: prints doc_id, e.g. 41
python -X utf8 -u -m src.chunk_embed --doc-id 41                      :: ~25 min per 200 pages (CPU)
python -X utf8 -u -m src.sections --doc-id 41 --apply
python -X utf8 -u -m src.alerts summarize --doc-id 41
:: if the prior year is also indexed:
python -X utf8 -u -m src.alerts diff --ticker 0941.HK --from-year 2024 --to-year 2025
```

**Expected result:** ingest reports pages stored and how many needed OCR (scanned pages and
broken-font pages are detected automatically); embedding reports chunk count; sections prints
the detected page map; summarize writes per-section summaries + a `new_filing` alert; diff
writes `change_detected` alerts. The new document immediately becomes searchable in chat and
visible in the 📄 Corpus tab. Re-running any step on the same file is safe (idempotent).

## Scenario 5 — "Audit the data / run SQL yourself"

**When:** you want to verify a citation at the database level, or explore with SQL.

**How:** VS Code PostgreSQL extension (host `127.0.0.1`, port `5432`, user `postgres`,
password `devpass`, db `filings`) or `docker exec -it filings-db psql -U postgres -d filings`.

```sql
-- does the cited page really contain the figure?
SELECT page_num FROM pages p JOIN documents d USING (doc_id)
WHERE d.ticker='0700.HK' AND d.fiscal_year=2025 AND raw_text LIKE '%5.30%';
```

**Expected result:** one relational schema holds everything — `documents`, `pages`, `sections`,
`chunks` (with pgvector embeddings), `summaries`, `alerts` — so every AI output is traceable
to raw stored text with plain SQL.

## What this system is NOT for

- **Facts outside the indexed filings** (news, prices, other companies) — it will refuse.
- **Sentence-level page precision** — citations are chunk-level page ranges (`p.5-6`).
- **Heavy numerical analysis** — it quotes and compares reported figures; it does not build
  models. Export via SQL if you need computation.
- **Investment advice** — it is a document research tool; outputs are filed disclosures.
