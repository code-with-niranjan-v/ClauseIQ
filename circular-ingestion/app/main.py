import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from psycopg import Error as DatabaseError

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


class ProcessingSetting(BaseModel):
    paused: bool


@app.get("/processing")
async def processing() -> dict:
    return consumer.status()


@app.put("/processing")
async def update_processing(setting: ProcessingSetting) -> dict:
    if not settings.consumer_enabled:
        raise HTTPException(status_code=409, detail="The ingestion worker is disabled")
    if not consumer.set_paused(setting.paused):
        raise HTTPException(status_code=409, detail="A queue clear is in progress")
    return consumer.status()


@app.post("/processing/clear")
async def clear_processing_queue() -> dict:
    if not settings.consumer_enabled:
        raise HTTPException(status_code=409, detail="The ingestion worker is disabled")
    try:
        if not await consumer.clear_queue():
            raise HTTPException(status_code=409, detail="A queue clear is in progress")
    except DatabaseError as error:
        logging.exception("Could not save the ingestion queue cutoff")
        raise HTTPException(status_code=503, detail="Could not clear the processing queue") from error
    return consumer.status()


@app.get("/health")
async def health() -> dict:
    """Liveness. The process is up even while the consumer is reconnecting; see `consumer.state`."""
    return {"status": "ok", "consumer": consumer.status()}
