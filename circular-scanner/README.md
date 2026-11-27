# Circular scanner

The scanner checks official publication listings daily at 06:00 India Standard Time. It fetches PDFs, uploads new content to MinIO, and queues a Kafka event for each stored document. PostgreSQL stores the source configuration, the latest scan result, document metadata, and pending events.

## Publication sources

| Source ID | Publisher | Seed listing |
| --- | --- | --- |
| `rbi` | Reserve Bank of India | [Notifications and circulars](https://www.rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx) |
| `sebi` | Securities and Exchange Board of India | [Legal circulars](https://www.sebi.gov.in/legal/circulars.html) |
| `irdai` | Insurance Regulatory and Development Authority of India | [Circulars](https://irdai.gov.in/circulars) |
| `dpdp` | Ministry of Electronics and Information Technology | [Data protection framework, including the Digital Personal Data Protection Act, 2023](https://www.meity.gov.in/data-protection-framework) |

The seeds are in [data.sql](src/main/resources/data.sql). Adjust `listing_url`, `allowed_hosts`, `detail_link_pattern`, or `enabled` in `regulatory_source` if a publisher moves its listing or documents. The scanner follows matching detail links one level deep and recognizes direct PDF links and embedded PDF URLs. It inspects up to 40 detail links and downloads up to 100 candidate documents per source per run. Historical pagination, JavaScript-rendered listings, and non-PDF content are outside this workflow. The first scan imports PDFs it discovers in that window, including existing publications. A listing that returns no PDF links records a failure so a broken parser or moved URL is visible.

Outbound access to the regulator listings was denied in the cloud development environment. Check each source after deploying to a network that can reach the official hosts.

## Run with Compose

From `circular-scanner/`, copy `.env.example` to `.env` and fill in the three credential values. Use a MinIO password of at least eight characters.

```sh
docker compose up --build -d --wait
curl -fsS http://localhost:8081/actuator/health
curl -fsS http://localhost:8081/api/admin/sources
curl -fsS -X POST http://localhost:8081/api/admin/sources/rbi/scan
```

Compose starts the scanner and its three dependencies. The scanner API binds to loopback, and PostgreSQL, MinIO, and Kafka are confined to the Compose network. The manual endpoint is synchronous and returns the latest source result after processing finishes. An unknown source returns HTTP 404. A running or disabled source returns HTTP 409. For a completed attempt, inspect `lastRunStatus` for `SUCCESS`, `PARTIAL`, or `FAILED` and use `lastError` and the scanner logs to diagnose failures. Use `GET /api/admin/sources` to view scan timestamps and counters. Status reflects discovery and storage, while Kafka delivery retries independently.

Set `SCANNER_CRON` and `SCANNER_ZONE` in `.env` to change the schedule. Set `SCANNER_CRON=-` for manual-only operation. To run the Maven tests, point `SPRING_DATASOURCE_URL`, `SPRING_DATASOURCE_USERNAME`, and `SPRING_DATASOURCE_PASSWORD` at a disposable PostgreSQL database and run `sh ./mvnw test`. The workflow test uses PostgreSQL and mocks MinIO and Kafka.

## Storage and delivery

The scanner calculates SHA-256 for each fetched PDF. It stores identical content once per source and detects changed bytes even when the publisher reuses a URL. Each stored PDF is referenced by an event on `regulatory.document.ingested`. Events contain the stable event ID, document and version IDs, regulator, title, source URL, bucket, object key, checksum, and discovery timestamp. PostgreSQL keeps unpublished rows until Kafka acknowledges them. Delivery is at least once. A process crash after Kafka acknowledges but before PostgreSQL commits can resend the same `eventId`.

The scanner publishes the PDF reference. Downstream parsing and ingestion are separate services.
