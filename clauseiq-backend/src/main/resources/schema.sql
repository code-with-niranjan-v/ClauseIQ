-- Owned by the backend. finding_id refers to finding.id, which the ingestion worker creates,
-- so there is no foreign key: the backend must be able to start before the worker has run.
CREATE TABLE IF NOT EXISTS review_decision (
    id uuid PRIMARY KEY,
    finding_id uuid NOT NULL,
    decision text NOT NULL,            -- APPROVED, APPROVED_WITH_CHANGES, REJECTED
    reviewer text NOT NULL,
    comment text,
    original_value jsonb NOT NULL,     -- the finding and recommendation as they were before the decision
    edited_value jsonb,                -- the fields the reviewer changed
    decided_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS review_decision_finding_idx ON review_decision (finding_id, decided_at);

-- Sign-in accounts. Passwords are stored as delegating-encoder hashes ({bcrypt}...).
CREATE TABLE IF NOT EXISTS app_user (
    id uuid PRIMARY KEY,
    username text NOT NULL UNIQUE,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL,                -- ADMIN, REVIEWER, VIEWER
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);
