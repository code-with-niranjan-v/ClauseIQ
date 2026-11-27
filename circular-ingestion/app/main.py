import logging

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Circular Ingestion", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
