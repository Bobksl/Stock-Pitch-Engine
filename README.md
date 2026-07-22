# Equity Filings RAG Research System

A source-citing research assistant for Hong Kong equity filings: ingests bilingual (EN/繁中) annual reports (text PDFs + OCR fallback for scanned/broken-encoding ones), stores everything in **PostgreSQL + pgvector**, embeds locally with **BGE-M3**, and answers questions via **DeepSeek `deepseek-v4-flash`** with every claim cited back to document, section, and page — plus an alerts feed that flags material year-over-year changes between filings.

Built as a portfolio project for a research-system engineering internship application.
**How to use it: see [USAGE.md](USAGE.md).**

**Status: working demo.** Corpus: 6 annual reports (Tencent 0700, Bilibili 9626, HSBC 0005 × FY2024/FY2025), ~2,400 embedded chunks, 36 section summaries, 9 YoY change alerts. UI: Streamlit chat with a clickable source panel + alerts feed + corpus overview.

## Stack (decided — see ARCHITECTURE.md for rationale)

| Layer | Choice | Why |
|---|---|---|
| Generation | DeepSeek `deepseek-v4-flash` (OpenAI SDK) | Cheap, 1M context, JSON output; DeepSeek has **no embeddings endpoint** |
| Embeddings | `BAAI/bge-m3` local, CPU, fp16 (1024-dim) | Bilingual EN/繁中 cross-lingual retrieval, 8192-token inputs, free |
| Store | PostgreSQL + pgvector (HNSW, cosine) | One relational DB for metadata + chunks + vectors + alerts; real SQL |
| Ingestion | pdfplumber + Tesseract (`chi_tra+eng`) fallback | Per-page: <100 chars extracted ⇒ treat as scanned ⇒ OCR |
| RAG loop | Raw Python + SQL (no LangChain/LlamaIndex) | Transparency; every line explainable in interview |
| UI | Streamlit | Chat + source panel + alerts feed |

## Layout

```
├── README.md           # this file
├── USAGE.md            # scenario-based usage guide (inputs → expected results)
├── schema.sql          # Postgres + pgvector DDL (run once)
├── requirements.txt
├── .env.example        # copy to .env and fill in (never commit .env)
├── sample_pdfs/        # manually downloaded HKEX filings (git-ignored; see USAGE.md)
├── scripts/
│   ├── test_deepseek.py    # API-key smoke test
│   └── retrieval_qa.py     # 10-question retrieval quality check
└── src/
    ├── config.py       # env-driven settings
    ├── db.py           # psycopg3 connection + pgvector registration
    ├── ingest.py       # Module 1: PDF text extraction + OCR fallback (broken-font detection)
    ├── sections.py     # Module 2: heading-heuristic section segmentation
    ├── chunk_embed.py  # Module 3: page-attributed chunking + BGE-M3 → pgvector
    ├── rag_chat.py     # Module 4: retrieve → prompt → DeepSeek → cited answer
    ├── alerts.py       # Module 5: section summaries + YoY change alerts
    └── app.py          # Module 6: Streamlit UI (chat + sources + alerts)
```

## Quickstart

```bat
:: 1. activate venv (lives outside OneDrive on purpose)
C:\Users\user\venvs\filings-rag\Scripts\activate

:: 2. verify the LLM works
python scripts\test_deepseek.py

:: 3. start Postgres (after installing Docker Desktop — see SETUP.md)
docker start filings-db

:: 4. ingest a filing end-to-end (Day 1 target)
python -m src.ingest sample_pdfs\0700_HK_2025_annual.pdf
python -m src.chunk_embed --doc-id 1
python -m src.rag_chat "What were the main revenue drivers?"

:: 5. summaries + YoY alerts
python -m src.alerts summarize --doc-id 1
python -m src.alerts diff --ticker 0700.HK --from-year 2024 --to-year 2025

:: 6. UI
streamlit run src\app.py
```

## Known limitations & next steps (honest by design)

- **Section detection is heuristic** (heading patterns + hysteresis, not ML). It nails clean
  reports (Tencent/Bilibili) and produces coherent-but-imperfect maps on complex interleaved
  ones (HSBC). Next: table-of-contents parsing or font-size features.
- **Rotated tables in OCR'd docs** can yield garbled chunks that occasionally rank in top-k
  (the grounding prompt is instructed to ignore gibberish). Next: Tesseract OSD rotation
  detection or an index-time chunk-quality filter.
- **Multi-company questions** can let one issuer dominate pure top-k retrieval. Next: per-ticker
  quota via a SQL window function.
- **No reranker, no eval harness yet.** Next: a 20-question labeled set for recall@k, then an
  over-retrieve → rerank stage.
- **Page citations are chunk-level ranges** (`p.5-6`), not sentence-level offsets.

## War stories (what real filings taught this pipeline)

1. **HSBC AR 2025 has a broken/obfuscated font CMap** — every text extractor (pdfplumber, pypdf,
   poppler) returns garbage for 363/377 pages. The pipeline detects `(cid:NN)` density and
   auto-routes those pages to OCR. Citations require trustworthy text, so garbage detection must
   gate extraction.
2. **Repeated page-headers fake section headings** in OCR'd docs — fixed with a minimum-run
   hysteresis rule.
3. **`ON DELETE CASCADE` on a label FK deleted embeddings** when re-segmenting — schema now uses
   `SET NULL` for section links. Labels must never own data.
