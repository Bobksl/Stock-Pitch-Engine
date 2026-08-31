-- ============================================================================
-- Equity Filings RAG — US filings / XBRL facts extension  (Phase 0, R1+R2+R3)
--
-- Applied ON TOP of schema.sql, which is left untouched: the HK PDF demo keeps
-- working standalone. Run once, after schema.sql:
--     psql -U postgres -d filings -f schema_facts.sql
-- Idempotent — safe to re-run.
--
-- Framework P2/P3: every number in an output resolves to a facts row
-- (accession, tag, period) or a model cell. This file is that guarantee's
-- storage layer.
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 1. Additive extensions to the existing (HK/PDF) tables
--    start_page / end_page / chunks.page were already nullable, so HTML
--    documents that have no pages need no change there.
-- ---------------------------------------------------------------------------

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS cik             INTEGER,
    ADD COLUMN IF NOT EXISTS country         TEXT,       -- 'US' | 'HK'
    ADD COLUMN IF NOT EXISTS sic             TEXT,
    ADD COLUMN IF NOT EXISTS fiscal_year_end TEXT;       -- 'MM-DD', e.g. '06-30'

-- Partial unique index rather than a UNIQUE constraint: existing HK rows have
-- no CIK, and CREATE INDEX IF NOT EXISTS is idempotent while ADD CONSTRAINT is not.
CREATE UNIQUE INDEX IF NOT EXISTS companies_cik_key
    ON companies (cik) WHERE cik IS NOT NULL;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS cik        INTEGER,
    ADD COLUMN IF NOT EXISTS accession  TEXT,
    ADD COLUMN IF NOT EXISTS format     TEXT NOT NULL DEFAULT 'pdf',
    ADD COLUMN IF NOT EXISTS form_type  TEXT,            -- 10-K | 10-Q | 8-K | S-1
    ADD COLUMN IF NOT EXISTS period_end DATE,
    ADD COLUMN IF NOT EXISTS filed_date DATE,
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS sha256     TEXT;

-- doc_type was CHECK IN ('annual','interim'); US filings need the EDGAR forms.
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_doc_type_check;
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_format_check;
ALTER TABLE documents
    ADD CONSTRAINT documents_doc_type_check
        CHECK (doc_type IN ('annual', 'interim', '10-K', '10-Q', '8-K', 'S-1')),
    ADD CONSTRAINT documents_format_check
        CHECK (format IN ('pdf', 'html'));

CREATE UNIQUE INDEX IF NOT EXISTS documents_accession_key
    ON documents (accession) WHERE accession IS NOT NULL;

-- Item-anchored segmentation (R3) lives alongside the heuristic PDF segmenter.
-- section_type is still written by BOTH segmenters, so rag_chat / alerts / app
-- need no changes; section_key is the Item-precise handle new code filters on.
ALTER TABLE sections
    ADD COLUMN IF NOT EXISTS section_key TEXT,           -- 'item_1a', 'item_7', ...
    ADD COLUMN IF NOT EXISTS segmenter   TEXT NOT NULL DEFAULT 'heuristic_pdf',
    ADD COLUMN IF NOT EXISTS start_char  INTEGER,
    ADD COLUMN IF NOT EXISTS end_char    INTEGER;

ALTER TABLE sections DROP CONSTRAINT IF EXISTS sections_segmenter_check;
ALTER TABLE sections
    ADD CONSTRAINT sections_segmenter_check
        CHECK (segmenter IN ('heuristic_pdf', 'item_anchor_us'));

CREATE INDEX IF NOT EXISTS sections_doc_key ON sections (doc_id, section_key);

-- HTML chunks are anchored by character offset, PDF chunks by page.
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS start_char INTEGER,
    ADD COLUMN IF NOT EXISTS end_char   INTEGER;


-- ---------------------------------------------------------------------------
-- 2. filings — one row per fetched EDGAR accession (provenance + idempotency)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS filings (
    accession    TEXT PRIMARY KEY,               -- '0000950170-24-087843'
    cik          INTEGER NOT NULL,
    form         TEXT    NOT NULL,               -- 10-K | 10-Q | 8-K | S-1
    fy           INTEGER,
    fp           TEXT,                           -- FY | Q1..Q4
    period_end   DATE,
    filed_date   DATE    NOT NULL,
    primary_doc  TEXT    NOT NULL,               -- 'msft-20240630.htm'
    primary_url  TEXT    NOT NULL,
    cached_path  TEXT,                           -- data/edgar_cache/<sha256>
    sha256       TEXT,
    is_ixbrl     BOOLEAN,                        -- FALSE => separate instance .xml (pre-2019)
    doc_id       INTEGER REFERENCES documents(doc_id) ON DELETE SET NULL,
    facts_loaded BOOLEAN NOT NULL DEFAULT FALSE,
    fetched_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS filings_cik_form_period
    ON filings (cik, form, period_end DESC);


-- ---------------------------------------------------------------------------
-- 3. facts — THE numeric source of truth (P2: numbers from XBRL, never RAG)
--
--    segments holds the XBRL dimensions as {axis_qname: member_qname}. JSONB
--    rather than fixed columns because ASC 606 disaggregation routinely tags
--    one figure by segment AND geography AND timing at once.
--
--    No FK on accession: companyfacts-sourced rows can reference filings that
--    were never downloaded.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS facts (
    fact_id       BIGSERIAL PRIMARY KEY,
    cik           INTEGER NOT NULL,
    accession     TEXT    NOT NULL,              -- citation anchor (P3)
    doc_id        INTEGER REFERENCES documents(doc_id) ON DELETE SET NULL,
    taxonomy      TEXT    NOT NULL,              -- us-gaap | dei | srt | <ext prefix>
    tag           TEXT    NOT NULL,
    unit          TEXT    NOT NULL,              -- USD | shares | USD/shares | pure
    period_type   TEXT    NOT NULL CHECK (period_type IN ('duration', 'instant')),
    period_start  DATE,                          -- NULL for instant facts
    period_end    DATE    NOT NULL,
    fy            INTEGER,
    fp            TEXT,
    form          TEXT,
    filed_date    DATE    NOT NULL,              -- point-in-time key (see 5.)
    -- Signed as reported: an ix:nonFraction sign="-" attribute is part of the
    -- VALUE (the displayed text is the absolute value), not a display hint.
    -- Display-only negation is the negatedLabel role in the label linkbase and
    -- is never applied at storage time.
    value         NUMERIC NOT NULL,              -- NUMERIC, never float
    decimals      INTEGER,
    segments      JSONB   NOT NULL DEFAULT '{}',
    -- md5 over the canonical jsonb text: jsonb normalises key order, so this is
    -- stable, and the cast is immutable enough for a generated column on PG 18.
    segments_hash TEXT GENERATED ALWAYS AS (md5(segments::text)) STORED,
    source        TEXT    NOT NULL CHECK (source IN ('instance', 'companyfacts')),
    context_id    TEXT,                          -- exact XBRL context, instance-parsed
    ingested_at   TIMESTAMPTZ DEFAULT now(),

    UNIQUE (cik, accession, taxonomy, tag, unit,
            period_start, period_end, segments_hash, source)
);

CREATE INDEX IF NOT EXISTS facts_cik_tag_period ON facts (cik, tag, period_end DESC);
CREATE INDEX IF NOT EXISTS facts_accession      ON facts (accession);
CREATE INDEX IF NOT EXISTS facts_segments_gin   ON facts USING gin (segments);
-- Consolidated (no-dimension) facts are the hot path for reconciliation and for
-- every headline figure; segments = '{}' is exact and cheap.
CREATE INDEX IF NOT EXISTS facts_consolidated
    ON facts (cik, tag, period_end DESC) WHERE segments = '{}'::jsonb;


-- ---------------------------------------------------------------------------
-- 4. Label + concept resolution
-- ---------------------------------------------------------------------------

-- So a panel reads 'Intelligent Cloud', not 'msft:IntelligentCloudMember'.
CREATE TABLE IF NOT EXISTS xbrl_labels (
    cik       INTEGER NOT NULL,
    qname     TEXT    NOT NULL,
    role      TEXT    NOT NULL DEFAULT 'standard',
    label     TEXT    NOT NULL,
    accession TEXT,
    PRIMARY KEY (cik, qname, role)
);

-- Filers disagree on tags for the same economic concept (Revenues vs
-- RevenueFromContractWithCustomerExcludingAssessedTax vs ...IncludingAssessedTax).
-- Resolution is deterministic, versioned in config/concept_map.yaml, and
-- reviewable — never an LLM guess, never a fallback chain buried in code.
CREATE TABLE IF NOT EXISTS concept_map (
    map_id   SERIAL PRIMARY KEY,
    concept  TEXT    NOT NULL,          -- 'revenue', 'segment_operating_profit', ...
    cik      INTEGER,                   -- NULL = default rule for every filer
    taxonomy TEXT    NOT NULL DEFAULT 'us-gaap',
    tag      TEXT    NOT NULL,
    priority INTEGER NOT NULL,          -- lower wins
    note     TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS concept_map_key
    ON concept_map (concept, COALESCE(cik, 0), taxonomy, tag);


-- ---------------------------------------------------------------------------
-- 5. Restatement resolution / point-in-time
--
--    The same period is re-reported in later filings (MSFT FY2024 revenue
--    appears under three accessions). Every version is kept; these resolve it.
--    The same figure also arrives from two sources (the filing itself and SEC's
--    companyfacts). They must agree — reconcile.py enforces that — but the
--    instance row is preferred so a citation points at the actual document.
--    facts_asof exists from day one because Audit G6 — backtesting the pitch
--    process on a past date using only then-available data — is impossible
--    without it, and the 6.3 staleness check is the same query.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW facts_current AS
SELECT DISTINCT ON (cik, taxonomy, tag, unit, period_start, period_end, segments_hash) *
FROM facts
ORDER BY cik, taxonomy, tag, unit, period_start, period_end, segments_hash,
         filed_date DESC, (source = 'instance') DESC, fact_id DESC;

CREATE OR REPLACE FUNCTION facts_asof(as_of DATE)
RETURNS SETOF facts
LANGUAGE sql STABLE AS $$
    SELECT DISTINCT ON (cik, taxonomy, tag, unit, period_start, period_end, segments_hash) *
    FROM facts
    WHERE filed_date <= as_of
    ORDER BY cik, taxonomy, tag, unit, period_start, period_end, segments_hash,
             filed_date DESC, (source = 'instance') DESC, fact_id DESC;
$$;
