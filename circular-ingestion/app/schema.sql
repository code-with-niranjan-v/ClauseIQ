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

CREATE INDEX IF NOT EXISTS processed_event_document_attempt_idx
    ON processed_event (document_version_id, started_at DESC, event_id DESC);

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
    metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
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
    coverage_status text,              -- COVERED, PARTIALLY_COVERED, NOT_COVERED, CONFLICTING, UNVERIFIED
    coverage_explanation text,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE obligation ADD COLUMN IF NOT EXISTS coverage_status text;
ALTER TABLE obligation ADD COLUMN IF NOT EXISTS coverage_explanation text;

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

-- Internal knowledge, loaded from the policy handbook, control register and role directory.
CREATE TABLE IF NOT EXISTS internal_document (
    id text PRIMARY KEY,
    document_type text NOT NULL,       -- POLICY, CONTROL
    title text NOT NULL,
    checksum text NOT NULL,
    approval_status text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS organizational_role (
    name text PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS control (
    id text PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL,
    owner_role text,                   -- NULL is an ownership gap
    frequency text,
    policy_section text
);

-- Evidence retrieved for an obligation. `matched` marks what the assessment relied on.
CREATE TABLE IF NOT EXISTS obligation_mapping (
    id uuid PRIMARY KEY,
    obligation_id uuid NOT NULL REFERENCES obligation(id) ON DELETE CASCADE,
    target_type text NOT NULL,         -- POLICY_SECTION, CONTROL
    target_id text NOT NULL,           -- document_chunk.id or control.id
    section_number text,
    similarity real NOT NULL,
    matched boolean NOT NULL
);

CREATE INDEX IF NOT EXISTS obligation_mapping_obligation_idx ON obligation_mapping (obligation_id);

CREATE TABLE IF NOT EXISTS finding (
    id uuid PRIMARY KEY,
    obligation_id uuid NOT NULL REFERENCES obligation(id) ON DELETE CASCADE,
    document_id text NOT NULL,
    document_version_id text NOT NULL,
    finding_type text NOT NULL,
    coverage_status text NOT NULL,
    severity text NOT NULL,
    title text NOT NULL,
    explanation text NOT NULL,
    policy_section text,
    policy_quote text,
    confidence real NOT NULL,
    status text NOT NULL DEFAULT 'PENDING_REVIEW',
    original_ai_output jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS finding_version_idx ON finding (document_version_id);
CREATE INDEX IF NOT EXISTS finding_status_idx ON finding (status);

CREATE TABLE IF NOT EXISTS recommendation (
    id uuid PRIMARY KEY,
    finding_id uuid NOT NULL REFERENCES finding(id) ON DELETE CASCADE,
    draft_policy_text text NOT NULL,
    recommended_action text NOT NULL,
    assigned_role text NOT NULL REFERENCES organizational_role(name),
    suggested_deadline text,
    required_evidence jsonb NOT NULL,
    confidence real NOT NULL,
    original_ai_output jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS recommendation_finding_idx ON recommendation (finding_id);
CREATE TABLE IF NOT EXISTS ingestion_queue (
    id boolean PRIMARY KEY CHECK (id),
    cleared_before timestamptz NOT NULL
);

-- System assessments: a bank's SRE document, architecture diagram and ER diagram compared with circulars.
CREATE TABLE IF NOT EXISTS system_assessment (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    status text NOT NULL,              -- QUEUED, PROCESSING, COMPLETED, FAILED
    stage text,
    error text,
    fact_count integer,
    compared_count integer,
    not_applicable_count integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS system_artifact (
    id uuid PRIMARY KEY,
    assessment_id uuid NOT NULL REFERENCES system_assessment(id) ON DELETE CASCADE,
    kind text NOT NULL,                -- SRE, ARCHITECTURE, ER
    filename text NOT NULL,
    content_type text NOT NULL,
    checksum text NOT NULL,
    size_bytes integer NOT NULL,
    method text,                       -- TEXT, VISION
    summary text
);

CREATE TABLE IF NOT EXISTS system_fact (
    id uuid PRIMARY KEY,
    assessment_id uuid NOT NULL REFERENCES system_assessment(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL REFERENCES system_artifact(id) ON DELETE CASCADE,
    page_number integer,
    content text NOT NULL
);

CREATE TABLE IF NOT EXISTS system_finding (
    id uuid PRIMARY KEY,
    assessment_id uuid NOT NULL REFERENCES system_assessment(id) ON DELETE CASCADE,
    obligation_id uuid NOT NULL REFERENCES obligation(id) ON DELETE CASCADE,
    status text NOT NULL,              -- MEETS, PARTIAL, GAP, CONFLICT, UNVERIFIED
    severity text,
    title text NOT NULL,
    explanation text NOT NULL,
    improvement text NOT NULL,
    owner_role text NOT NULL,
    effort text NOT NULL,
    confidence real NOT NULL,
    similarity real NOT NULL,
    system_quote text,
    evidence_fact_ids uuid[] NOT NULL,
    original_ai_output jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS system_finding_assessment_idx ON system_finding (assessment_id);

-- Extraction quality. ocr_page_count is NULL for versions processed before it was recorded.
ALTER TABLE regulatory_document_version ADD COLUMN IF NOT EXISTS ocr_page_count integer;

-- Models sometimes return the word "null" instead of no value. Earlier versions stored it.
UPDATE obligation SET deadline = NULL
WHERE lower(btrim(deadline)) IN ('null', 'none', 'n/a', 'na', 'not specified', 'not stated', 'not mentioned', '');
UPDATE obligation SET responsible_entity = NULL
WHERE lower(btrim(responsible_entity)) IN ('null', 'none', 'n/a', 'na', 'not specified', 'not stated', 'not mentioned', '');
UPDATE obligation SET applicability = NULL
WHERE lower(btrim(applicability)) IN ('null', 'none', 'n/a', 'na', 'not specified', 'not stated', 'not mentioned', '');

-- Circular lineage: which circulars supersede, withdraw, amend or refer to others.
CREATE TABLE IF NOT EXISTS document_identifier (
    document_id text NOT NULL REFERENCES regulatory_document(id) ON DELETE CASCADE,
    identifier text NOT NULL,          -- as printed, e.g. IRDAI/F&I/CIR/MISC/142/11/2026
    normalized text NOT NULL,          -- for matching: upper case, no spaces, no leading zeros
    PRIMARY KEY (document_id, normalized)
);

CREATE INDEX IF NOT EXISTS document_identifier_normalized_idx ON document_identifier (normalized);

CREATE TABLE IF NOT EXISTS circular_link (
    id uuid PRIMARY KEY,
    source_document_id text NOT NULL REFERENCES regulatory_document(id) ON DELETE CASCADE,
    relation text NOT NULL,            -- SUPERSEDES, WITHDRAWS, AMENDS, REFERS_TO
    cited_identifier text NOT NULL,
    cited_normalized text NOT NULL,
    target_document_id text REFERENCES regulatory_document(id) ON DELETE SET NULL,
    page_number integer,
    evidence text NOT NULL,
    status text NOT NULL DEFAULT 'PROPOSED',   -- PROPOSED, CONFIRMED, DISMISSED
    decided_by text,
    decided_at timestamptz,
    retired_obligations integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_document_id, cited_normalized)
);

ALTER TABLE obligation ADD COLUMN IF NOT EXISTS lifecycle_status text NOT NULL DEFAULT 'ACTIVE';  -- ACTIVE, RETIRED
ALTER TABLE obligation ADD COLUMN IF NOT EXISTS retired_by_link uuid;
ALTER TABLE obligation ADD COLUMN IF NOT EXISTS retired_at timestamptz;

-- Live database scans: metadata only, never row values.
CREATE TABLE IF NOT EXISTS data_scan (
    id uuid PRIMARY KEY,
    target text NOT NULL,
    status text NOT NULL,              -- COMPLETED, FAILED
    error text,
    database_name text,
    table_count integer,
    column_count integer,
    used_ai boolean NOT NULL DEFAULT false,
    requested_by text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS data_scan_field (
    id uuid PRIMARY KEY,
    scan_id uuid NOT NULL REFERENCES data_scan(id) ON DELETE CASCADE,
    schema_name text NOT NULL,
    table_name text NOT NULL,
    column_name text NOT NULL,
    data_type text NOT NULL,
    classification text NOT NULL,
    sensitivity text NOT NULL,         -- HIGH, MEDIUM, LOW
    protected boolean NOT NULL,
    reason text NOT NULL,
    confidence real NOT NULL,
    recommended_control text NOT NULL,
    method text NOT NULL               -- RULES, AI
);

CREATE INDEX IF NOT EXISTS data_scan_field_scan_idx ON data_scan_field (scan_id);
