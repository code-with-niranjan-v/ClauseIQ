# Circular ingestion

Python worker for the AI processing workstream in [PLAN.md](../PLAN.md). It consumes the events that `circular-scanner` publishes, reads each circular from MinIO, extracts cited obligations, compares them with internal policies and controls, and stores findings for human review.

It uses OpenAI for obligation extraction, coverage assessment, drafting and embeddings. `OPENAI_API_KEY` is required.

For each event the worker runs a LangGraph workflow in [app/workflow.py](app/workflow.py). The node names are the ones in the plan:

| Node | What it does |
| --- | --- |
| `load_document` | Downloads the PDF from MinIO and checks its SHA-256 against the event. |
| `parse_pages` | Extracts text page by page. |
| `detect_clauses` | Splits each page into clause-aware chunks with exact character offsets. |
| `extract_obligations` | Asks the model for obligations, one page at a time. |
| `validate_citations` | Rejects any obligation whose quote is not on the cited page. |
| `index_regulatory_content` | Embeds the chunks. |
| `retrieve_internal_evidence` | Finds the closest policy sections and controls for each obligation in pgvector. |
| `map_policies_and_controls` | Asks the model how far the retrieved policy sections cover the obligation. |
| `check_role_coverage` | Checks that each matched control has an owner in the role directory. |
| `assess_gap` | Applies the gap rules to set the coverage status, finding type and severity. |
| `draft_recommendation` | Asks the model for draft policy wording, an action and a role for each gap. |
| `persist_results` | Writes to Neo4j, then to PostgreSQL in one transaction that also marks the event completed. |
| `await_human_review` | Ends the graph. Findings are stored as `PENDING_REVIEW` for the review API. |

Before the workflow starts, the worker skips any event it has already processed.

## Contract with circular-scanner

The worker reads the payload that the scanner's `OutboxPublisher` sends to `regulatory.document.ingested`:

| Field | Use |
| --- | --- |
| `eventId` | Idempotency key. The scanner sets it to the version row ID and can resend it, because delivery is at least once. |
| `documentId`, `documentVersionId` | Stored on every chunk, obligation and citation. |
| `regulator`, `title`, `sourceUrl` | Document metadata. |
| `minioBucket`, `minioObjectKey` | Where the PDF is, for example `regulatory-originals` and `RBI/{documentId}/version-1/original.pdf`. |
| `checksum` | Plain SHA-256 hex. The download is rejected if it does not match. |

The event must have `eventType` `REGULATORY_DOCUMENT_INGESTED`. Unknown fields are ignored.

## Run with Compose

The scanner's Compose project owns Kafka and MinIO and does not publish their ports to the host, so the worker joins the scanner's network.

1. Start the scanner from `circular-scanner/` first.
2. Copy `.env.example` to `.env` here. Set `OPENAI_API_KEY`, `POSTGRES_PASSWORD` and `NEO4J_PASSWORD`, and set `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` to the scanner's values.
3. Check the scanner's network name with `docker network ls` and set `SCANNER_NETWORK` if it is not `circular-scanner_default`.

```sh
docker compose up --build -d --wait
curl -fsS http://localhost:8000/health
curl -fsS -X POST http://localhost:8081/api/admin/sources/rbi/scan
```

This also starts the backend API from `clauseiq-backend/` on `http://localhost:8080`. See its [README](../clauseiq-backend/README.md) for the endpoints.

`/health` reports the consumer state (`RUNNING`, `DEGRADED` while it reconnects), the number of processed and dead-lettered events, and the last error. Neo4j Browser is at `http://localhost:7474`.

This Compose file starts its own PostgreSQL because the scanner's `postgres:17` image has no pgvector. To share one database, change the scanner's image to `pgvector/pgvector:pg17` and point `DATABASE_URL` at it. The table names do not collide.

## Try it on one PDF

This runs the whole workflow on a local file with no Kafka, MinIO or database. It needs only an OpenAI key, and it reads the policies, controls and roles from `sample-data/`.

```sh
pip install -r requirements-dev.txt
export OPENAI_API_KEY=...
python -m app.cli sample-data/circulars/sample-circular.pdf
```

It prints each obligation with its citation, coverage and, for a gap, the drafted finding.

## Configuration

Settings are environment variables, read in [app/config.py](app/config.py).

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | Required |
| `LLM_MODEL` | `gpt-4o-mini` | Chat model for extraction, assessment and drafting |
| `LLM_TEMPERATURE` | `0` | Set to `1` for models that reject other values |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | `text-embedding-3-small`, `1536` | Embeddings and the pgvector column size |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Broker |
| `KAFKA_TOPIC` | `regulatory.document.ingested` | Scanner topic |
| `KAFKA_DEAD_LETTER_TOPIC` | `regulatory.document.ingested.dlq` | Events that failed every attempt |
| `MAX_ATTEMPTS` | `3` | First attempt plus two retries |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | `minio:9000`, empty | PDF store |
| `DATABASE_URL` | `postgresql://clauseiq:clauseiq@postgres:5432/clauseiq` | PostgreSQL with pgvector |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | empty | Empty URI skips graph writes |
| `KNOWLEDGE_DIR` | `sample-data` | Policy handbook, control register and roles |
| `SEED_KNOWLEDGE_ON_START` | `true` | Load `KNOWLEDGE_DIR` at startup |
| `POLICY_TOP_K`, `CONTROL_TOP_K` | `4`, `3` | Evidence retrieved per obligation |
| `CONSUMER_ENABLED` | `true` | `false` starts only the health API |

`gpt-4o-mini` is the default because it is cheap. Set `LLM_MODEL` to a stronger model for better legal reading. The worker makes one call per page for extraction, one per obligation for assessment and one per gap for drafting.

`EMBEDDING_DIMENSIONS` sets the size of the `document_chunk.embedding` column when the table is first created. A database created with the earlier 384-dimension default needs its `document_chunk` table dropped before the worker starts.

`EXTRACTION_MODE=rules` and `EMBEDDING_PROVIDER=hash` are offline substitutes for development and tests. Assessment and drafting always need OpenAI.

## Internal knowledge

The worker loads three files from `KNOWLEDGE_DIR` at startup:

| File | Content |
| --- | --- |
| `policy_handbook.md` | One `## N. Heading` per policy section |
| `controls.csv` | `control_id`, `name`, `description`, `owner_role`, `frequency`, `policy_section` |
| `roles.csv` | `name` |

The files in `sample-data/` are mock data written for the demo: eight policy sections, seven controls and nine roles. Replace them with the compliance team's versions in the same format. The worker embeds them again only when a file or the embedding model changes.

`sample-data/circulars/sample-circular.pdf` is a mock circular written to exercise each outcome against that handbook: one covered obligation, a retention conflict, a missing reporting deadline, a control with no owner (`CTRL-006`) and an obligation with no policy. Regenerate it with `python scripts/make_sample_circular.py`.

## Extraction and citations

The model reads one page at a time and returns structured obligations with a quote. The page text is passed as data, and the prompt tells the model not to follow instructions inside it.

Every obligation goes through the check in [app/citations.py](app/citations.py). The page number comes from the page that was sent, the quote must occur on that page (ignoring only whitespace differences from line wraps), and the clause number comes from the parsed chunk, not from the model. A clause that was not detected is stored as null. Rejected obligations are logged and counted in `regulatory_document_version.rejected_obligation_count`.

## Coverage and gaps

For each obligation the model sees only the retrieved policy sections and controls and returns a coverage reading, the ids it relied on and a policy quote. The worker then checks that reading in [app/assessment.py](app/assessment.py):

- Ids that were not supplied are dropped.
- A policy quote that is not in the matched section is dropped.
- The final status and finding type come from fixed rules, not from the model.

| Condition | Coverage status | Finding type | Severity |
| --- | --- | --- | --- |
| Model reads the policy as contradicting the obligation | `CONFLICTING` | `POLICY_CONFLICT` | HIGH |
| Model finds no policy section | `NOT_COVERED` | `POLICY_GAP` | HIGH |
| Model reads the policy as incomplete | `PARTIALLY_COVERED` | `PARTIAL_POLICY_GAP` | MEDIUM |
| Policy covers it, no control matched | `PARTIALLY_COVERED` | `CONTROL_DESIGN_GAP` | MEDIUM |
| Control matched, no owner in the role directory | `PARTIALLY_COVERED` | `OWNERSHIP_GAP` | MEDIUM |
| Model cannot decide, or claims coverage with no valid policy section | `UNVERIFIED` | `IMPLEMENTATION_UNVERIFIED` | LOW |
| Policy, control and owner all present | `COVERED` | none | none |

`COVERED` means the documents cover the obligation. The stored explanation says that implementation evidence was not assessed.

Each finding gets a drafted title, description, policy wording, action, deadline and evidence list. The assigned role must be in the role directory. If the model names anything else, the worker uses the owner of the matched control, or the Compliance Officer, and keeps the model's original answer in `original_ai_output`.

## Storage

The worker creates its tables at startup from [app/schema.sql](app/schema.sql).

| Table | Content |
| --- | --- |
| `processed_event` | Idempotency and attempt count per event |
| `regulatory_document`, `regulatory_document_version` | Circular metadata and processing status |
| `document_chunk` | Circular, policy and control text with embeddings |
| `obligation`, `citation` | Extracted obligations, their coverage status and source quotes |
| `internal_document`, `control`, `organizational_role` | Loaded internal knowledge |
| `obligation_mapping` | Policy sections and controls retrieved per obligation, with `matched` |
| `finding`, `recommendation` | Gaps with status `PENDING_REVIEW`, and the drafted remediation |

The backend's review API updates `finding.status` and the edited recommendation fields, and writes each decision to its own `review_decision` table. `original_ai_output` on `finding` and `recommendation` keeps what the model returned before any human edit.

Drafted policy text is stored only in `recommendation`. It is never written as a `POLICY` chunk, so the employee chatbot's filter (`document_type = 'POLICY'` and `approval_status = 'APPROVED'`) cannot return it.

Neo4j holds the relationships from the plan: `RegulatoryDocument CONTAINS Clause`, `Clause CREATES Obligation`, `Obligation MAPS_TO PolicySection`, `Obligation SATISFIED_BY Control`, `Control OWNED_BY Role`, `Obligation HAS_GAP Finding`, `Finding RESOLVED_BY Recommendation` and `Recommendation ASSIGNED_TO Role`. Node IDs are the PostgreSQL IDs.

## Failures

A failed document is retried up to `MAX_ATTEMPTS`. After that the original message goes to the dead-letter topic with the error in its headers, and the event is marked `DEAD_LETTERED`. Results are written only when the whole document succeeds, so a failed document leaves no chunks or obligations. A dead-lettered event can be replayed to the main topic.

Malformed events go straight to the dead-letter topic. If PostgreSQL or Kafka is down, the offset is not committed and the event is redelivered.

A MinIO, Neo4j or OpenAI outage counts as a document failure, so three failed attempts during an outage dead-letter the event. A missing `OPENAI_API_KEY` stops the consumer from starting, and `/health` shows the reason.

## Tests

```sh
pip install -r requirements-dev.txt
pytest
```

The database tests run only when `TEST_DATABASE_URL` points at a disposable PostgreSQL with pgvector. They truncate the worker's tables.

## Not verified

- No OpenAI call has been made, because no key was available. The prompts, the model's judgement on the sample circular and the embedding-based retrieval are untested against the real API. The tests use a scripted model and offline embeddings.
- The worker has not been run against a live Kafka, MinIO or Neo4j. The Kafka loop is tested with fakes, and the Neo4j queries have not been executed.
- The Compose file passes `docker compose config` but has not been started.

## Limitations

- Scanned PDFs have no text layer and fail with `PdfError`. OCR is out of scope.
- Clause detection covers numbered clauses (`4`, `4.2`, `Clause 4.2`) and bracketed items (`(a)`, `(iv)`). Tables and multi-column layouts are not handled.
- A large circular means many OpenAI calls, made one after another.
- SRS and SRE comparison, the employee chatbot and the sensitive-field scanner are not part of this worker yet.
