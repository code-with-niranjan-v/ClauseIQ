# ClauseIQ backend

Spring Boot API for the frontend. It reads the documents, obligations and findings that `circular-ingestion` stores, records review decisions, and forwards source administration to `circular-scanner`.

The backend uses the ingestion worker's PostgreSQL database. The worker creates the tables this API reads. The backend creates one table of its own, `review_decision`.

## Endpoints

All responses are JSON. The base URL is `http://localhost:8080`.

| Method and path | Purpose |
| --- | --- |
| `GET /api/summary` | Counts of documents by status, obligations by coverage, and findings by status and severity |
| `GET /api/documents` | Circulars with processing status, page count and finding counts |
| `GET /api/obligations` | Obligations with citation and coverage. Filters: `documentVersionId`, `coverageStatus` |
| `GET /api/findings` | Findings, highest severity first. Filters: `status`, `documentVersionId` |
| `GET /api/findings/{id}` | One finding with everything the review screen needs |
| `POST /api/findings/{id}/approve` | Accept the finding as drafted |
| `POST /api/findings/{id}/edit-and-approve` | Change the draft, then accept it |
| `POST /api/findings/{id}/reject` | Reject the finding |
| `GET /api/roles` | Role directory, for the "assigned role" dropdown |
| `GET /api/controls` | Control register |
| `GET /api/admin/sources` | Regulator sources and their last scan result, from the scanner |
| `POST /api/admin/sources/{id}/scan` | Run a scan now. Returns when the scan finishes, which can take minutes |
| `GET /actuator/health` | Health check |

### Finding detail

`GET /api/findings/{id}` returns:

| Field | Content |
| --- | --- |
| `title`, `findingType`, `coverageStatus`, `severity`, `status`, `confidence`, `explanation` | The finding |
| `policySection`, `policyQuote` | The internal policy citation, when there is one |
| `obligation` | Summary, required action, deadline, and `citation` with `pageNumber`, `clauseNumber` and `quotedText` |
| `policies` | Matched policy sections with `sectionNumber`, `heading`, `content` and `similarity` |
| `controls` | Matched controls with `id`, `name`, `description`, `ownerRole` and `frequency` |
| `recommendation` | `draftPolicyText`, `recommendedAction`, `assignedRole`, `suggestedDeadline`, `requiredEvidence`, `confidence` |
| `originalAiOutput` | What the model returned, unchanged by any edit |
| `decisions` | Review history, each with `decision`, `reviewer`, `comment`, `originalValue`, `editedValue`, `decidedAt` |

`status` is one of `PENDING_REVIEW`, `APPROVED`, `APPROVED_WITH_CHANGES` or `REJECTED`.

### Review requests

Approve. `comment` is optional:

```json
{"reviewer": "meena", "comment": "Agreed"}
```

Reject. `comment` is required:

```json
{"reviewer": "meena", "comment": "Not applicable to this entity"}
```

Edit and approve. Send `reviewer` and only the fields that change:

```json
{
  "reviewer": "meena",
  "comment": "Tightened the wording",
  "title": "Incident reporting deadline missing",
  "severity": "HIGH",
  "draftPolicyText": "Incidents must be reported to the regulator within 6 hours of detection.",
  "recommendedAction": "Update section 6 of the handbook",
  "assignedRole": "SOC Manager",
  "suggestedDeadline": "30 days",
  "requiredEvidence": ["Approved policy version"]
}
```

`assignedRole` must be a name from `GET /api/roles`. `severity` must be `HIGH`, `MEDIUM` or `LOW`.

Each review endpoint returns the updated finding detail. A finding can be reviewed once. A second decision returns HTTP 409.

### Errors

Every error has the same shape:

```json
{"status": 409, "error": "Conflict", "message": "This finding has already been reviewed"}
```

| Status | When |
| --- | --- |
| 400 | Missing `reviewer`, missing reject `comment`, unknown role, invalid severity, no edited fields, malformed body or ID |
| 404 | Unknown finding or source |
| 409 | Finding already reviewed, or the source is disabled or already scanning |
| 503 | The scanner is not reachable, or the ingestion worker has not created its tables yet |

## Run

With Compose, the backend starts with the worker from `circular-ingestion/`:

```sh
cd ../circular-ingestion
docker compose up --build -d --wait
curl -fsS http://localhost:8080/api/summary
```

To run it on its own, point it at the worker's database and the scanner:

```sh
export SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:5432/clauseiq
export SPRING_DATASOURCE_USERNAME=clauseiq
export SPRING_DATASOURCE_PASSWORD=...
export CLAUSEIQ_SCANNER_URL=http://localhost:8081
sh ./mvnw spring-boot:run
```

`CLAUSEIQ_CORS_ALLOWED_ORIGINS` lists the frontend origins that can call the API. The default is `http://localhost:5173,http://localhost:3000`.

## Tests

The tests need a disposable PostgreSQL with pgvector. They create the worker's tables from `../circular-ingestion/app/schema.sql`, insert their own rows and remove them afterwards.

```sh
export SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:5432/clauseiq_test
export SPRING_DATASOURCE_USERNAME=clauseiq
export SPRING_DATASOURCE_PASSWORD=...
sh ./mvnw test
```

## Limitations

- There is no login. `reviewer` is whatever name the request sends, as the plan's demo authentication allows. Do not expose this API beyond a demo network.
- Source administration is limited to what the scanner offers: list sources and run a scan. Creating, editing and disabling sources, scan-run history and the scanner's own document list are not available yet.
- Approving a finding does not publish its draft text as policy. The draft stays in `recommendation`.
- The lists are not paginated.
- The Docker image and the Compose service have not been built or started. The API was tested with Maven and by running the jar against a database filled by the ingestion worker.
