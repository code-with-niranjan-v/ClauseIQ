import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.consumer import DocumentConsumer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

consumer = DocumentConsumer(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.consumer_enabled:
        await consumer.start()
    yield
    if settings.consumer_enabled:
        await consumer.stop()


app = FastAPI(title="Circular Ingestion", version="0.2.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Liveness. The process is up even while the consumer is reconnecting; see `consumer.state`."""
    return {"status": "ok", "consumer": consumer.status()}
