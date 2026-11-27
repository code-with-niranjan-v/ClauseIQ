# ClauseIQ

From the repository root, copy `.env.example` to `.env` and fill in `OPENAI_API_KEY`. The template already includes sample credentials for local PostgreSQL, Neo4j, and MinIO. Compose passes the API key only to the ingestion worker, and Git ignores the root `.env`.

Start the complete stack with one command:

```sh
docker compose up --build -d --wait
```

| Service | Default local URL |
| --- | --- |
| Frontend | http://localhost:5173 |
| Backend health | http://localhost:8080/actuator/health |
| Scanner health | http://localhost:8081/actuator/health |
| Ingestion health and consumer status | http://localhost:8000/health |
| Neo4j Browser | http://localhost:7474 |

The frontend shows scanner status, ingested circulars, cited obligations, policy coverage, and findings awaiting review. It uses the backend through the same-origin `/api` proxy. To trigger a scan, run `curl -fsS -X POST http://localhost:8081/api/admin/sources/sebi/scan`. Docker starts both PostgreSQL databases, Kafka, MinIO, and Neo4j on the same Compose network and retains their data in named volumes. The root stack creates its own volumes when run alongside the standalone projects.

Use `docker compose logs -f circular-ingestion` to see ingestion startup and processing. Check its health response for the consumer state. A healthy HTTP process can still be reconnecting to a dependency or waiting for a valid OpenAI key. Stop the stack with `docker compose down`.
