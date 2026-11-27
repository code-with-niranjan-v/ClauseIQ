# ClauseIQ

From the repository root, copy `.env.example` to `.env` and fill in `OPENAI_API_KEY`. The template already includes sample credentials for local PostgreSQL, Neo4j, and MinIO. Compose passes the API key only to the ingestion worker, and Git ignores the root `.env`.

Start the complete stack with one command:

```sh
docker compose up --build -d --wait
```

| Service | Default local URL |
| --- | --- |
| RegDesk workbench | http://localhost:5173/workbench |
| Pipeline testing dashboard | http://localhost:5173/test |
| Backend health | http://localhost:8080/actuator/health |
| Scanner health | http://localhost:8081/actuator/health |
| Ingestion health and consumer status | http://localhost:8000/health |
| Neo4j Browser | http://localhost:7474 |

The frontend shows scanner status, ingested circulars, cited obligations, policy coverage, and findings awaiting review. It uses the backend through the same-origin `/api` proxy. To scan the official RBI circular listing, click **Scan RBI** on the dashboard or run `curl -fsS -X POST http://localhost:8081/api/admin/sources/rbi/scan`. Docker starts both PostgreSQL databases, Kafka, MinIO, and Neo4j on the same Compose network and retains their data in named volumes. The root stack creates its own volumes when run alongside the standalone projects.

Use `docker compose logs -f circular-ingestion` to see ingestion startup and processing. Check its health response for the consumer state. A healthy HTTP process can still be reconnecting to a dependency or waiting for a valid OpenAI key. Stop the stack with `docker compose down`.

## Policy Q&A

Press `/` in the RegDesk workbench, or click **Ask the approved policies**, to ask a policy question. The assistant answers only from approved policy text: sections of the policy handbook, and the policy wording of findings a reviewer approved or edited and approved. Each approved update cites the circular it came from. Pending and rejected findings, AI drafts and raw circular text are never used.

Every answer lists its sources. If no approved source passes the similarity threshold, or the sources do not answer the question, the assistant says so and refers the employee to the Compliance Officer or Data Protection Officer. Set `CHAT_MIN_SIMILARITY` (default `0.3`) and `CHAT_TOP_K` (default `5`) in `.env` to tune retrieval. The backend endpoint is `POST /api/chat` with `{"question": "..."}`.

## System assessment

Open **System assessment** in the RegDesk workbench to compare a system's design with the ingested circulars. Upload any of an SRE document, an architecture diagram and an ER diagram, each as a PDF, PNG, JPEG or WebP file of up to 20 MiB, or click **Use demo bank files** to load the fictional NeoPay bank in [demo-bank](demo-bank/README.md).

The ingestion worker reads text documents directly and reads diagrams with the OpenAI vision model, turning each into factual statements about the system. It then picks the circular obligations closest to those statements, at most `SYSTEM_MAX_OBLIGATIONS` (default `20`) above `SYSTEM_MIN_SIMILARITY` (default `0.3`), and asks the model whether the design meets, partly meets, misses or conflicts with each one. Every judgement must cite the system evidence it relies on. Severity and the phased improvement plan are rule-based. An assessment takes a minute or two and costs one model call per diagram and per compared obligation.

## Import a circular downloaded in your browser

The Docker scanner retries failed RBI PDF downloads with Playwright. If RBI publishes the circular text on its official notification page, the scanner can render that text to a PDF and queue it as an **RBI web version**, with a link to the official notification. If the circular is available only as a PDF and the scanner cannot retrieve it, open the circular URL in your browser and save the file. Pass its original RBI PDF URL, title, and local file to the scanner:

```powershell
curl.exe --fail-with-body -F "url=$pdfUrl" -F "title=$title" -F "file=@$pdfPath" http://127.0.0.1:8081/api/admin/sources/rbi/import-pdf
```

Set `$pdfUrl`, `$title`, and `$pdfPath` to your circular's values before running the command. A response of `{"added":true}` means the PDF was stored and queued for ingestion. The dashboard lists the circular once the worker receives the event. The source row continues to report the last automatic or manual scan.

## Scanner DNS

Some resolvers fail to resolve `www.sebi.gov.in`, so the scanner container uses 1.1.1.1 and 9.9.9.9 for DNS. If your network allows only its own DNS servers, set `SCANNER_DNS_PRIMARY` and `SCANNER_DNS_SECONDARY` in the root `.env`.

## If Neo4j fails to start

Run `docker compose ps neo4j` and `docker compose logs --tail=100 neo4j` to see why. If Docker reports a port conflict, set free values for `NEO4J_HTTP_PORT` and `NEO4J_BOLT_PORT` in the root `.env`. These change the host ports. The ingestion worker still uses `neo4j:7687` inside Compose.

For a fresh data volume, use a `NEO4J_PASSWORD` of at least eight characters. If the worker reports an authentication error against an existing volume, use the password that was set when that volume was initialized. Editing `.env` alone cannot change the stored Neo4j password.
