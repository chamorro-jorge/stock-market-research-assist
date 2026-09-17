-- Esquema Lakebase (Postgres + pgvector) para el capstone de watchlist.
-- Ejecutar una vez contra la instancia de Lakebase. Es idempotente.
--
-- Nota sobre embeddings: dimensión 1024 = databricks-gte-large-en.
-- Cambiar de modelo obliga a ALTER de la columna y a regenerar todos los vectores.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- usuarios

CREATE TABLE IF NOT EXISTS users (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT        NOT NULL UNIQUE,
    display_name    TEXT,
    -- Se actualiza en cada carga de la app desde M1, aunque no se use hasta M4.
    last_visit_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS watchlists (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL DEFAULT 'Default',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

-- La unicidad hace idempotente a add_to_watchlist: ON CONFLICT DO NOTHING.
CREATE TABLE IF NOT EXISTS watchlist_tickers (
    watchlist_id BIGINT      NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    ticker       TEXT        NOT NULL,
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (watchlist_id, ticker)
);

-- ------------------------------------------------------------ datos de mercado

-- Origen: Massive /v3/reference/tickers/{ticker}
CREATE TABLE IF NOT EXISTS companies (
    ticker          TEXT PRIMARY KEY,
    name            TEXT,
    description     TEXT,          -- texto no estructurado -> document_chunks
    sector          TEXT,
    industry        TEXT,
    market_cap      NUMERIC,
    homepage_url    TEXT,
    fundamentals    JSONB,         -- Massive /vX/reference/financials
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Origen: Massive /v2/aggs/ticker/{t}/range/1/day/...
-- PK compuesta = upsert idempotente al reejecutar el job.
CREATE TABLE IF NOT EXISTS price_snapshots (
    ticker       TEXT        NOT NULL,
    snapshot_date DATE       NOT NULL,
    open         NUMERIC,
    high         NUMERIC,
    low          NUMERIC,
    close        NUMERIC,
    volume       BIGINT,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_price_ticker_date
    ON price_snapshots (ticker, snapshot_date DESC);

-- Origen: Massive /v2/reference/news
CREATE TABLE IF NOT EXISTS news_articles (
    id              TEXT PRIMARY KEY,      -- id de Massive -> dedupe natural
    ticker          TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    description     TEXT,
    article_url     TEXT,
    publisher       TEXT,
    published_at    TIMESTAMPTZ NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_news_ticker_published
    ON news_articles (ticker, published_at DESC);

-- ------------------------------------------------------- contexto vectorial

-- Una sola tabla para TODO el texto embebido. doc_type distingue la fuente,
-- de forma que una búsqueda semántica cubra perfiles, noticias y filings a la vez.
CREATE TABLE IF NOT EXISTS document_chunks (
    id            BIGSERIAL PRIMARY KEY,
    ticker        TEXT        NOT NULL,
    doc_type      TEXT        NOT NULL
                  CHECK (doc_type IN ('profile', 'news', 'filing', 'earnings')),
    source_id     TEXT        NOT NULL,   -- news_articles.id, ticker, accession nº...
    chunk_index   INT         NOT NULL DEFAULT 0,
    chunk_text    TEXT        NOT NULL,
    published_at  TIMESTAMPTZ,            -- permite filtrar "desde la última visita"
    embedding     VECTOR(1024),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Evita reembeber lo ya procesado al reejecutar el job.
    UNIQUE (doc_type, source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_ticker_type
    ON document_chunks (ticker, doc_type);

-- HNSW para similitud coseno. Crear DESPUÉS de la primera carga masiva.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

-- --------------------------------------------- salidas del agente (escrituras)

CREATE TABLE IF NOT EXISTS research_notes (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker      TEXT        NOT NULL,
    note_text   TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notes_user_ticker
    ON research_notes (user_id, ticker, created_at DESC);

CREATE TABLE IF NOT EXISTS analysis_reports (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker        TEXT        NOT NULL,
    title         TEXT        NOT NULL,
    body          TEXT        NOT NULL,   -- informe generado por el agente
    -- Qué chunks citó: trazabilidad de la respuesta.
    source_chunk_ids BIGINT[],
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reports_user_ticker
    ON analysis_reports (user_id, ticker, created_at DESC);
