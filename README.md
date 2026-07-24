# Equity Filings RAG

A source-citing research assistant for long PDF filings. It ingests annual reports
(text PDFs **and** scanned / broken-encoding ones via OCR), stores everything in
**PostgreSQL + pgvector**, embeds locally with **BGE-M3**, and answers questions with
**any OpenAI-compatible LLM** — where every claim is cited back to document, section, and
page. It also produces per-section summaries and an **alerts feed** that flags material
year-over-year changes between filings.

It's a compact, framework-free reference implementation of a production-shaped RAG system:
OCR ingestion, metadata + section tagging, chunking, vector retrieval, grounded generation
with citations, and change detection — about 800 lines of readable Python + SQL, no
LangChain/LlamaIndex.

> **Demo corpus (what the screenshots/examples use):** 6 Hong Kong annual reports
> (Tencent 0700, Bilibili 9626, HSBC 0005 × FY2024/FY2025) → ~2,400 embedded chunks,
> 36 section summaries, 9 YoY change alerts. You supply your own PDFs; none are shipped.

**→ New here? Read [SETUP.md](SETUP.md) to install, then [USAGE.md](USAGE.md) to use it.**

## Stack

| Layer | Choice | Why |
|---|---|---|
| Generation | **Any OpenAI-compatible LLM** (DeepSeek, OpenAI, OpenRouter, Groq, Ollama, …) | Pick your provider in `.env`; no code change |
| Embeddings | `BAAI/bge-m3` local, CPU (1024-dim) | Bilingual/cross-lingual, 8192-token inputs, free & private — no embeddings API needed |
| Store | PostgreSQL + pgvector (HNSW, cosine) | One relational DB for metadata + text + vectors + alerts; queryable with plain SQL |
| Ingestion | pdfplumber + Tesseract OCR fallback | Per page: too little text or broken-font garbage ⇒ OCR |
| RAG loop | Raw Python + SQL (no frameworks) | Transparent and easy to modify — every line is yours |
| UI | Streamlit | Chat + clickable source panel + alerts feed |

Switching LLM providers is one line in `.env` (`LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`) —
see the provider table in [.env.example](.env.example). Embeddings always run locally and are
independent of the LLM.

## Layout

```
├── README.md           # this file
├── SETUP.md            # install guide (Docker/Postgres, Python, OCR tools, config)
├── USAGE.md            # scenario-based usage guide (inputs → expected results)
├── schema.sql          # Postgres + pgvector DDL (run once)
├── requirements.txt
├── .env.example        # copy to .env; provider table inside (never commit .env)
├── sample_pdfs/        # put your own PDFs here (git-ignored)
├── scripts/
│   ├── test_llm.py         # verify your LLM provider/key work
│   └── retrieval_qa.py     # retrieval quality spot-check
└── src/
    ├── config.py       # env-driven settings
    ├── llm.py          # thin wrapper over any OpenAI-compatible chat API
    ├── db.py           # psycopg3 connection + pgvector registration
    ├── ingest.py       # PDF text extraction + OCR fallback (broken-font detection)
    ├── sections.py     # heading-heuristic section segmentation
    ├── chunk_embed.py  # page-attributed chunking + BGE-M3 → pgvector
    ├── rag_chat.py     # retrieve → prompt → LLM → cited answer
    ├── alerts.py       # section summaries + YoY change alerts
    └── app.py          # Streamlit UI (chat + sources + alerts)
```

## Quickstart

Full install is in [SETUP.md](SETUP.md). Once the environment is ready:

```bash
# from the project root, with the virtualenv activated and Postgres running

# 1. verify your LLM provider (reads LLM_* from .env)
python scripts/test_llm.py

# 2. index a PDF end-to-end (name it TICKER_HK_YEAR_annual.pdf, e.g. 0700_HK_2025_annual.pdf)
python -m src.ingest sample_pdfs/0700_HK_2025_annual.pdf   # prints a doc_id
python -m src.chunk_embed --doc-id 1
python -m src.sections --doc-id 1 --apply

# 3. ask a question (cited answer on the command line)
python -m src.rag_chat "What were the main revenue drivers?" --ticker 0700.HK

# 4. summaries + year-over-year alerts (needs two years of the same issuer)
python -m src.alerts summarize --doc-id 1
python -m src.alerts diff --ticker 0700.HK --from-year 2024 --to-year 2025

# 5. launch the UI (http://localhost:8501)
streamlit run src/app.py
```

On Windows, prefix Python commands with `-X utf8` (e.g. `python -X utf8 -m src.ingest ...`)
so console encoding doesn't choke on non-ASCII text.

## Known limitations & next steps

- **Section detection is heuristic** (heading patterns + hysteresis, not ML). Clean reports
  segment perfectly; complex interleaved ones are coherent but imperfect. Next: table-of-contents
  parsing or font-size features.
- **Rotated tables in OCR'd docs** can yield garbled chunks that occasionally rank in top-k
  (the grounding prompt is told to ignore gibberish). Next: rotation detection or an index-time
  chunk-quality filter.
- **Multi-entity questions** can let one document dominate pure top-k. Next: per-entity quota via
  a SQL window function.
- **No reranker or eval harness yet.** Next: a labeled question set for recall@k, then an
  over-retrieve → rerank stage.
- **Citations are chunk-level page ranges** (`p.5-6`), not sentence-level offsets.

## War stories (what real filings taught this pipeline)

1. **A broken/obfuscated font CMap** makes every text extractor (pdfplumber, pypdf, poppler)
   return `(cid:NN)` garbage. The pipeline measures that garbage per page and auto-routes those
   pages to OCR — because a citation is only trustworthy if the underlying text is.
2. **Repeated page-headers fake section headings** in OCR'd docs — fixed with a minimum-run
   hysteresis rule so a header on every page doesn't start a new "section" each time.
3. **`ON DELETE CASCADE` on a label FK deleted embeddings** when re-segmenting. The schema now
   uses `ON DELETE SET NULL` for section links: labels must never own data.

## License

MIT — see [LICENSE](LICENSE). You supply your own filings and your own API key; no documents or
credentials are included in this repository.
