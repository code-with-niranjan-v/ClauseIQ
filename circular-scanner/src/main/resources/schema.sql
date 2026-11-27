CREATE TABLE IF NOT EXISTS regulatory_source (
    id text PRIMARY KEY,
    name text NOT NULL,
    regulator text NOT NULL,
    listing_url text NOT NULL,
    allowed_hosts text NOT NULL,
    detail_link_pattern text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    last_run_at timestamptz,
    last_finished_at timestamptz,
    last_success_at timestamptz,
    last_run_status text NOT NULL DEFAULT 'NEVER_RUN',
    last_error text,
    last_discovered integer NOT NULL DEFAULT 0,
    last_new_documents integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scanned_document (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL,
    version_number integer NOT NULL,
    source_id text NOT NULL REFERENCES regulatory_source(id),
    source_url text NOT NULL,
    title text NOT NULL,
    checksum char(64) NOT NULL,
    object_bucket text NOT NULL,
    object_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    UNIQUE (source_id, checksum),
    UNIQUE (document_id, version_number)
);

CREATE INDEX IF NOT EXISTS scanned_document_outbox_idx
    ON scanned_document (created_at, id) WHERE published_at IS NULL;
