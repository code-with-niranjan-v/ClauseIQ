# ClauseIQ

From the repository root, copy `.env.example` to `.env` and fill in `OPENAI_API_KEY`. The template already includes sample credentials for local PostgreSQL, Neo4j, and MinIO. Compose passes the API key only to the ingestion worker, and Git ignores the root `.env`.

Start the complete stack with one command:

```sh
docker compose up --build -d --wait
```

| Service | Default local URL |
| --- | --- |
| Frontend | http://localhost:5173/test |
| Backend health | http://localhost:8080/actuator/health |
| Scanner health | http://localhost:8081/actuator/health |
| Ingestion health and consumer status | http://localhost:8000/health |
| Neo4j Browser | http://localhost:7474 |

The frontend shows scanner status, ingested circulars, cited obligations, policy coverage, and findings awaiting review. It uses the backend through the same-origin `/api` proxy. To scan the official RBI circular listing, click **Scan RBI** on the dashboard or run `curl -fsS -X POST http://localhost:8081/api/admin/sources/rbi/scan`. Docker starts both PostgreSQL databases, Kafka, MinIO, and Neo4j on the same Compose network and retains their data in named volumes. The root stack creates its own volumes when run alongside the standalone projects.

Use `docker compose logs -f circular-ingestion` to see ingestion startup and processing. Check its health response for the consumer state. A healthy HTTP process can still be reconnecting to a dependency or waiting for a valid OpenAI key. Stop the stack with `docker compose down`.

## Import a circular downloaded in your browser

If the RBI download host sends the scanner an HTML page, open the circular URL in your browser and save the PDF. Pass its original RBI PDF URL, title, and local file to the scanner:

```powershell
curl.exe --fail-with-body -F "url=$pdfUrl" -F "title=$title" -F "file=@$pdfPath" http://127.0.0.1:8081/api/admin/sources/rbi/import-pdf
```

Set `$pdfUrl`, `$title`, and `$pdfPath` to your circular's values before running the command. A response of `{"added":true}` means the PDF was stored and queued for ingestion. The dashboard lists the circular once the worker receives the event. The source row continues to report the last automatic or manual scan.

## If Neo4j fails to start

Run `docker compose ps neo4j` and `docker compose logs --tail=100 neo4j` to see why. If Docker reports a port conflict, set free values for `NEO4J_HTTP_PORT` and `NEO4J_BOLT_PORT` in the root `.env`. These change the host ports. The ingestion worker still uses `neo4j:7687` inside Compose.

For a fresh data volume, use a `NEO4J_PASSWORD` of at least eight characters. If the worker reports an authentication error against an existing volume, use the password that was set when that volume was initialized. Editing `.env` alone cannot change the stored Neo4j password.
