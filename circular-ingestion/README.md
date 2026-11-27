# Circular Ingestion

Basic Python FastAPI service scaffold for the ClauseIQ monorepo.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health: `http://localhost:8000/health`

## Run with Docker

```powershell
docker build -t circular-ingestion .
docker run --env-file .env.example -p 8000:8000 circular-ingestion
```

## Tests

```powershell
pytest
```
