# ClauseIQ

From the repository root, copy `.env.example` to `.env` and fill in all five required values. Put your OpenAI API key in `OPENAI_API_KEY`. Compose passes it to the ingestion worker. Use a long alphanumeric PostgreSQL password and passwords of at least eight characters for Neo4j and MinIO. The root `.env` is ignored by Git.

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

The current frontend is the Vite starter screen. The backend and scanner APIs can be called directly. To trigger a scan, run `curl -fsS -X POST http://localhost:8081/api/admin/sources/sebi/scan`. Docker starts both PostgreSQL databases, Kafka, MinIO, and Neo4j on the same Compose network and retains their data in named volumes. The root stack creates its own volumes when run alongside the standalone projects.

Use `docker compose logs -f circular-ingestion` to see ingestion startup and processing. Check its health response for the consumer state. A healthy HTTP process can still be reconnecting to a dependency or waiting for a valid OpenAI key. Stop the stack with `docker compose down`.
