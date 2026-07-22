-- Equity Filings RAG — PostgreSQL + pgvector schema
-- Run once:  psql -U postgres -d filings -f schema.sql
-- (Create the DB first:  CREATE DATABASE filings;)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS companies (
    ticker        TEXT PRIMARY KEY,          -- e.g. '0700.HK'
    company_name  TEXT NOT NULL,
    sector        TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id        SERIAL PRIMARY KEY,
    ticker        TEXT REFERENCES companies(ticker),
    fiscal_year   INTEGER,
    doc_type      TEXT CHECK (doc_type IN ('annual', 'interim')),
    source_path   TEXT NOT NULL,
    page_count    INTEGER,
    is_scanned    BOOLEAN DEFAULT FALSE,     -- TRUE if OCR path was used
    ingested_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pages (
    page_id       SERIAL PRIMARY KEY,
    doc_id        INTEGER REFERENCES documents(doc_id) ON DELETE CASCADE,
    page_num      INTEGER NOT NULL,
    raw_text      TEXT,
    extraction    TEXT CHECK (extraction IN ('pdfplumber', 'ocr')),
    UNIQUE (doc_id, page_num)
);

CREATE TABLE IF NOT EXISTS sections (
    section_id    SERIAL PRIMARY KEY,
    doc_id        INTEGER REFERENCES documents(doc_id) ON DELETE CASCADE,
    section_type  TEXT,                      -- 'MD&A' | 'Risk Factors' | 'Financial Statements' | 'Corporate Governance' | 'Other'
    start_page    INTEGER,
    end_page      INTEGER,
    text          TEXT
);

-- Chunks carry the embedding directly (pgvector) plus full citation metadata.
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id      SERIAL PRIMARY KEY,
    doc_id        INTEGER REFERENCES documents(doc_id) ON DELETE CASCADE,
    -- SET NULL, not CASCADE: chunks belong to their document; re-segmenting must never delete embeddings
    section_id    INTEGER REFERENCES sections(section_id) ON DELETE SET NULL,
    page          INTEGER,                   -- first page the chunk appears on (citation anchor)
    end_page      INTEGER,                   -- last page the chunk touches (cite "p.5-6" when it spans)
    content       TEXT NOT NULL,
    token_count   INTEGER,
    embedding     vector(1024)               -- BGE-M3 = 1024 dims; MUST match EMBEDDING_DIM
);

-- HNSW cosine index (pgvector >= 0.5). Defaults m=16, ef_construction=64 are fine at this corpus size.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS summaries (
    summary_id    SERIAL PRIMARY KEY,
    doc_id        INTEGER REFERENCES documents(doc_id) ON DELETE CASCADE,
    section_id    INTEGER REFERENCES sections(section_id) ON DELETE SET NULL,
    summary_text  TEXT NOT NULL,
    model         TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id      SERIAL PRIMARY KEY,
    doc_id        INTEGER REFERENCES documents(doc_id) ON DELETE CASCADE,
    section_id    INTEGER REFERENCES sections(section_id) ON DELETE SET NULL,
    alert_type    TEXT CHECK (alert_type IN ('new_filing', 'change_detected')),
    alert_text    TEXT NOT NULL,
    page_ref      INTEGER,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Reference retrieval query (metadata-filtered similarity search — the JD's citation pattern):
-- SELECT c.chunk_id, c.page, s.section_type, d.ticker, d.fiscal_year, c.content,
--        c.embedding <=> %(qvec)s::vector AS distance
-- FROM chunks c
-- JOIN documents d ON d.doc_id = c.doc_id
-- LEFT JOIN sections s ON s.section_id = c.section_id
-- WHERE (%(ticker)s IS NULL OR d.ticker = %(ticker)s)
--   AND (%(year)s   IS NULL OR d.fiscal_year = %(year)s)
-- ORDER BY c.embedding <=> %(qvec)s::vector
-- LIMIT 8;
