-- Tables owned by the ingestion worker. {dimensions} is replaced with EMBEDDING_DIMENSIONS.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS processed_event (
    event_id text PRIMARY KEY,
    document_id text NOT NULL,
    document_version_id text NOT NULL,
    status text NOT NULL,              -- PROCESSING, COMPLETED, FAILED, DEAD_LETTERED
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS regulatory_document (
    id text PRIMARY KEY,
    regulator text NOT NULL,
    title text NOT NULL,
    source_url text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS regulatory_document_version (
    id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES regulatory_document(id),
    minio_bucket text NOT NULL,
    minio_object_key text NOT NULL,
    checksum text NOT NULL,
    processing_status text NOT NULL,   -- PROCESSING, COMPLETED, FAILED
    page_count integer,
    obligation_count integer,
    rejected_obligation_count integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);

CREATE TABLE IF NOT EXISTS document_chunk (
    id uuid PRIMARY KEY,
    document_id text NOT NULL,
    document_version_id text,
    document_type text NOT NULL,       -- CIRCULAR, POLICY, CONTROL, SRS, SRE
    page_number integer,
    section_number text,
    clause_number text,
    heading text,
    content text NOT NULL,
    start_offset integer,
    end_offset integer,
    embedding vector({dimensions}),
    metadata jsonb NOT NULL DEFAULT '{{}}',
    approval_status text NOT NULL,     -- DRAFT, APPROVED
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS document_chunk_version_idx ON document_chunk (document_version_id);
CREATE INDEX IF NOT EXISTS document_chunk_filter_idx ON document_chunk (document_type, approval_status);
CREATE INDEX IF NOT EXISTS document_chunk_embedding_idx ON document_chunk USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS obligation (
    id uuid PRIMARY KEY,
    document_id text NOT NULL,
    document_version_id text NOT NULL,
    chunk_id uuid NOT NULL REFERENCES document_chunk(id) ON DELETE CASCADE,
    summary text NOT NULL,
    required_action text NOT NULL,
    responsible_entity text,
    deadline text,
    applicability text,
    confidence real NOT NULL,
    extraction_method text NOT NULL,   -- LLM, RULES
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS obligation_version_idx ON obligation (document_version_id);

CREATE TABLE IF NOT EXISTS citation (
    id uuid PRIMARY KEY,
    obligation_id uuid NOT NULL REFERENCES obligation(id) ON DELETE CASCADE,
    document_id text NOT NULL,
    document_version_id text NOT NULL,
    page_number integer NOT NULL,
    clause_number text,
    quoted_text text NOT NULL,
    start_offset integer,
    end_offset integer
);

CREATE INDEX IF NOT EXISTS citation_obligation_idx ON citation (obligation_id);
