import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from psycopg import Error as DatabaseError

from app.chat import PolicyAssistant
from app.config import settings
from app.consumer import DocumentConsumer
from app.llm import ConfigurationError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

consumer = DocumentConsumer(settings)
_assistant: PolicyAssistant | None = None
_assistant_lock = threading.Lock()


def get_assistant() -> PolicyAssistant:
    """Built on first use, so a missing OpenAI key is reported by /chat rather than at startup."""
    global _assistant
    with _assistant_lock:
        if _assistant is None:
            from app.db import PostgresRepository
            from app.embeddings import build_embedder
            from app.llm import build_chat_model

            _assistant = PolicyAssistant(
                PostgresRepository(settings.database_url, settings.embedding_dimensions),
                build_embedder(settings), build_chat_model(settings),
                min_similarity=settings.chat_min_similarity, top_k=settings.chat_top_k)
        return _assistant


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


class Question(BaseModel):
    question: str


@app.post("/chat")
def chat(request: Question) -> dict:
    """Answer from approved policy text only. A plain def, so FastAPI runs the blocking calls in a thread."""
    try:
        return get_assistant().ask(request.question)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except DatabaseError as error:
        logging.exception("Policy Q&A could not read the approved policies")
        raise HTTPException(status_code=503, detail="The approved policy store is not available.") from error
    except Exception as error:  # OpenAI authentication, rate-limit and network errors
        logging.exception("Policy Q&A failed")
        raise HTTPException(status_code=502, detail="The language model request failed. Try again shortly.") from error


@app.get("/health")
async def health() -> dict:
    """Liveness. The process is up even while the consumer is reconnecting; see `consumer.state`."""
    return {"status": "ok", "consumer": consumer.status()}
