# Circular ingestion

Python worker for Phase 2 of [PLAN.md](../PLAN.md). It consumes the events that `circular-scanner` publishes, reads each circular from MinIO, and stores cited obligations.

For each event the worker:

1. Skips the event if it was already processed.
2. Downloads the PDF from MinIO and checks its SHA-256 against the event.
3. Extracts text page by page.
4. Splits each page into clause-aware chunks with exact character offsets.
5. Extracts obligations, with an LLM or with the rule-based fallback.
6. Rejects any obligation whose quote does not occur on the cited page.
7. Embeds the chunks.
8. Writes clauses and obligations to Neo4j, then writes chunks, obligations and citations to PostgreSQL and marks the event completed in the same transaction.

Steps 2 to 8 are a LangGraph workflow in [app/workflow.py](app/workflow.py) with the node names from the plan: `load_document`, `parse_pages`, `detect_clauses`, `extract_obligations`, `validate_citations`, `index_regulatory_content`, `persist_results`. The Day 2 nodes (`retrieve_internal_evidence` to `await_human_review`) are not built yet and attach after `persist_results`.

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
2. Copy `.env.example` to `.env` here. Set `POSTGRES_PASSWORD` and `NEO4J_PASSWORD`, and set `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` to the scanner's values.
3. Check the scanner's network name with `docker network ls` and set `SCANNER_NETWORK` if it is not `circular-scanner_default`.

```sh
docker compose up --build -d --wait
curl -fsS http://localhost:8000/health
curl -fsS -X POST http://localhost:8081/api/admin/sources/sebi/scan
```

`/health` reports the consumer state (`RUNNING`, `DEGRADED` while it reconnects), the number of processed and dead-lettered events, and the last error. Neo4j Browser is at `http://localhost:7474`.

This Compose file starts its own PostgreSQL because the scanner's `postgres:17` image has no pgvector. To share one database, change the scanner's image to `pgvector/pgvector:pg17` and point `DATABASE_URL` at it. The table names do not collide.

## Try it on one PDF

This runs the pipeline on a local file with no Kafka, MinIO or database and prints the obligations as JSON:

```sh
pip install -r requirements-dev.txt
python -m app.cli path/to/circular.pdf
```

## Configuration

Settings are environment variables, read in [app/config.py](app/config.py).

| Variable | Default | Purpose |
| --- | --- | --- |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Broker |
| `KAFKA_TOPIC` | `regulatory.document.ingested` | Scanner topic |
| `KAFKA_DEAD_LETTER_TOPIC` | `regulatory.document.ingested.dlq` | Events that failed every attempt |
| `MAX_ATTEMPTS` | `3` | First attempt plus two retries |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | `minio:9000`, empty | PDF store |
| `DATABASE_URL` | `postgresql://clauseiq:clauseiq@postgres:5432/clauseiq` | PostgreSQL with pgvector |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | empty | Empty URI skips graph writes |
| `LLM_MODEL`, `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY` | empty, `openai` | Chat model for extraction |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | `hash`, `text-embedding-3-small`, `384` | Chunk embeddings |
| `CONSUMER_ENABLED` | `true` | `false` starts only the health API |

Only the OpenAI provider package is installed. `LLM_BASE_URL` covers OpenAI-compatible local servers. For another provider, add its LangChain package to `requirements.txt` and set `LLM_PROVIDER`.

## Extraction and citations

With `LLM_MODEL` set, the model reads one page at a time and returns structured obligations with a quote. The page text is passed as data, and the prompt tells the model not to follow instructions inside it.

Without `LLM_MODEL`, the rule-based extractor flags sentences with mandatory wording such as "shall", "must" and "is required to". It quotes whole sentences, sets confidence to 0.5, and leaves the responsible entity empty. It is a fallback for demos and tests, not a substitute for the model.

Both paths go through the same check in [app/citations.py](app/citations.py). The page number comes from the page that was sent, the quote must occur on that page (ignoring only whitespace differences from line wraps), and the clause number comes from the parsed chunk, not from the model. A clause that was not detected is stored as null. Rejected obligations are logged and counted in `regulatory_document_version.rejected_obligation_count`.

## Storage

The worker creates its tables at startup from [app/schema.sql](app/schema.sql): `processed_event`, `regulatory_document`, `regulatory_document_version`, `document_chunk`, `obligation` and `citation`.

Circular chunks are stored with `document_type = 'CIRCULAR'` and `approval_status = 'APPROVED'`. The employee chatbot must still filter on `document_type = 'POLICY'`.

Neo4j holds `(RegulatoryDocument)-[:CONTAINS]->(Clause)-[:CREATES]->(Obligation)`. Node IDs are the PostgreSQL IDs of the document, chunk and obligation.

## Failures

A failed document is retried up to `MAX_ATTEMPTS`. After that the original message goes to the dead-letter topic with the error in its headers, and the event is marked `DEAD_LETTERED`. Results are written only when the whole document succeeds, so a failed document leaves no chunks or obligations. A dead-lettered event can be replayed to the main topic.

Malformed events go straight to the dead-letter topic. If PostgreSQL or Kafka is down, the offset is not committed and the event is redelivered.

A MinIO, Neo4j or LLM outage counts as a document failure, so three failed attempts during an outage dead-letter the event.

## Tests

```sh
pip install -r requirements-dev.txt
pytest
```

The database tests run only when `TEST_DATABASE_URL` points at a disposable PostgreSQL with pgvector. They truncate the worker's tables.

## Not verified

- The worker has not been run against a live Kafka, MinIO or Neo4j. The Kafka loop is tested with fakes, and the Neo4j queries have not been executed.
- The Compose file passes `docker compose config` but has not been started.
- The LLM path is tested with a fake model, not a real one.

## Limitations

- Scanned PDFs have no text layer and fail with `PdfError`. OCR is out of scope.
- The `hash` embedding matches shared words, not meaning. Switch to a real model before the Day 2 mapping work.
- Clause detection covers numbered clauses (`4`, `4.2`, `Clause 4.2`) and bracketed items (`(a)`, `(iv)`). Tables and multi-column layouts are not handled.
