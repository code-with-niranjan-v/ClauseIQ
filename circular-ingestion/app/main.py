import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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


# ---------------------------------------------------------------- system assessments

MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
_assessments = ThreadPoolExecutor(max_workers=1, thread_name_prefix="system-assessment")
_system_lock = threading.Lock()
_system_ready = False


def get_system_store():
    """The store, after marking assessments that a previous process left unfinished."""
    global _system_ready
    from app.system_store import SystemAssessmentStore

    store = SystemAssessmentStore(settings.database_url)
    with _system_lock:
        if not _system_ready:
            if store.interrupt_unfinished():
                logging.warning("Marked unfinished system assessments from a previous run as failed")
            _system_ready = True
    return store


def build_system_assessor(store):
    from app.embeddings import build_embedder
    from app.llm import build_chat_model
    from app.system_assessment import SystemAssessor

    model = build_chat_model(settings)
    return SystemAssessor(store, build_embedder(settings), model, model,
                          min_similarity=settings.system_min_similarity,
                          max_obligations=settings.system_max_obligations)


def _content_type(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _run_assessment(assessment_id: str, artifacts) -> None:
    store = get_system_store()
    try:
        assessor = build_system_assessor(store)
        result = assessor.run(artifacts, progress=lambda stage: store.stage(assessment_id, stage))
        store.save(assessment_id, artifacts, result)
    except Exception as error:
        logging.exception("System assessment %s failed", assessment_id)
        from app.system_assessment import AssessmentInputError

        message = str(error) if isinstance(error, (AssessmentInputError, ConfigurationError)) \
            else f"The assessment failed: {type(error).__name__}. See the ingestion worker logs."
        store.fail(assessment_id, message)


@app.post("/system-assessments", status_code=202)
async def create_system_assessment(
        name: str = Form(""), sre: UploadFile | None = File(None), architecture: UploadFile | None = File(None),
        er: UploadFile | None = File(None)) -> dict:
    from app.system_assessment import Artifact

    artifacts = []
    for kind, upload in (("SRE", sre), ("ARCHITECTURE", architecture), ("ER", er)):
        if upload is None or not upload.filename:
            continue
        data = await upload.read(MAX_ARTIFACT_BYTES + 1)
        if len(data) > MAX_ARTIFACT_BYTES:
            raise HTTPException(status_code=413, detail=f"{upload.filename} exceeds 20 MiB.")
        content_type = _content_type(data)
        if content_type is None:
            raise HTTPException(status_code=400, detail=f"{upload.filename} must be a PDF, PNG, JPEG or WebP file.")
        artifacts.append(Artifact(kind=kind, filename=upload.filename[:200], content_type=content_type, data=data))
    if not artifacts:
        raise HTTPException(status_code=400, detail="Upload at least one of the SRE document, architecture diagram "
                                                    "or ER diagram.")
    name = " ".join(name.split())[:120] or "Untitled system"
    try:
        store = get_system_store()
        assessment_id = store.create(name, artifacts)
    except DatabaseError as error:
        logging.exception("Could not create a system assessment")
        raise HTTPException(status_code=503, detail="The assessment store is not available.") from error
    _assessments.submit(_run_assessment, assessment_id, artifacts)
    return {"id": assessment_id, "status": "QUEUED"}


@app.get("/system-assessments")
def list_system_assessments() -> list[dict]:
    try:
        return get_system_store().list()
    except DatabaseError as error:
        raise HTTPException(status_code=503, detail="The assessment store is not available.") from error


@app.get("/system-assessments/{assessment_id}")
def get_system_assessment(assessment_id: uuid.UUID) -> dict:
    try:
        result = get_system_store().get(str(assessment_id))
    except DatabaseError as error:
        raise HTTPException(status_code=503, detail="The assessment store is not available.") from error
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown system assessment.")
    return result


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
