#!/bin/sh
# The NeoPay core database from the ER diagram: schema and comments only, no rows. Fictional.
# clauseiq_scanner can connect but cannot read any table: the ClauseIQ scan reads catalogue metadata only.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v scanner_password="$NEOPAY_SCANNER_PASSWORD" <<'SQL'
CREATE TABLE customers (
    customer_id uuid PRIMARY KEY,
    full_name text NOT NULL,
    date_of_birth date NOT NULL,
    aadhaar_number varchar(12) NOT NULL,
    pan varchar(10),
    mobile varchar(15) NOT NULL,
    email text,
    address text,
    pin_code varchar(6),
    is_minor boolean NOT NULL DEFAULT false,
    consent_checkbox_at timestamptz,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE customers IS 'Retail customers of NeoPay, including minors aged 10 to 17';
COMMENT ON COLUMN customers.aadhaar_number IS 'Full 12-digit Aadhaar, plain text, unmasked';
COMMENT ON COLUMN customers.password_hash IS 'bcrypt hash of the login password';
COMMENT ON COLUMN customers.consent_checkbox_at IS 'When the customer ticked the terms checkbox; no guardian consent is recorded';

CREATE TABLE accounts (
    account_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL REFERENCES customers,
    account_number varchar(18) NOT NULL,
    ifsc varchar(11) NOT NULL,
    balance numeric(14, 2) NOT NULL DEFAULT 0,
    debit_hold boolean NOT NULL DEFAULT false,
    hold_placed_at timestamptz
);
COMMENT ON COLUMN accounts.account_number IS 'Stored in clear';

CREATE TABLE transactions (
    txn_id uuid PRIMARY KEY,
    account_id uuid NOT NULL REFERENCES accounts,
    amount numeric(14, 2) NOT NULL,
    counterparty_vpa text,
    category text,
    device_ip inet,
    remarks text,
    mule_alert_flag boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON COLUMN transactions.counterparty_vpa IS 'UPI ID of the other party';
COMMENT ON COLUMN transactions.remarks IS 'Free text entered by the customer; may contain names and phone numbers';

CREATE TABLE loans (
    loan_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL REFERENCES customers,
    principal numeric(14, 2) NOT NULL,
    interest_rate numeric(5, 2) NOT NULL,
    penal_interest_rate numeric(5, 2) NOT NULL DEFAULT 2.00,
    capitalised_penal_amount numeric(14, 2) NOT NULL DEFAULT 0,
    monthly_income numeric(14, 2),
    cibil_score integer,
    kfs_version text
);

CREATE TABLE kyc_documents (
    document_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL REFERENCES customers,
    doc_type text NOT NULL,
    doc_ref text,
    passport_number_encrypted bytea,
    face_image_url text,
    verified_at timestamptz
);
COMMENT ON COLUMN kyc_documents.doc_ref IS 'Number printed on the identity document';

CREATE TABLE complaints (
    complaint_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL REFERENCES customers,
    category text,
    opened_at timestamptz NOT NULL,
    acknowledged_at timestamptz,
    resolved_at timestamptz,
    sla_days integer NOT NULL DEFAULT 45
);

CREATE TABLE audit_logs (
    log_id bigserial PRIMARY KEY,
    actor text NOT NULL,
    action text NOT NULL,
    entity text,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE audit_logs IS 'Deleted after 90 days';

CREATE ROLE clauseiq_scanner LOGIN PASSWORD :'scanner_password';
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE neopay TO clauseiq_scanner;
SQL
