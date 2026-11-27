import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
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


# ---------------------------------------------------------------- circular lineage

def _lineage_store():
    from app.graph_store import build_graph_store
    from app.lineage_store import LineageStore

    graph = None
    try:
        graph = build_graph_store(settings)
    except Exception:
        logging.exception("Neo4j is not available; confirmed links are stored in PostgreSQL only")
    return LineageStore(settings.database_url, graph)


def _user(value: str | None) -> str | None:
    """The signed-in user, as forwarded by the backend."""
    return " ".join((value or "").split())[:120] or None


@app.post("/lineage/refresh")
def refresh_lineage() -> dict:
    try:
        return _lineage_store().refresh()
    except DatabaseError as error:
        raise HTTPException(status_code=503, detail="The circular store is not available.") from error


@app.get("/lineage/links")
def lineage_links() -> list[dict]:
    try:
        return _lineage_store().list()
    except DatabaseError as error:
        raise HTTPException(status_code=503, detail="The circular store is not available.") from error


class LinkDecision(BaseModel):
    confirm: bool


@app.post("/lineage/links/{link_id}/decision")
def decide_lineage_link(link_id: uuid.UUID, decision: LinkDecision,
                        x_clauseiq_user: str | None = Header(default=None)) -> dict:
    from app.lineage_store import LinkAlreadyDecided, LinkNotFound

    try:
        return _lineage_store().decide(str(link_id), decision.confirm, _user(x_clauseiq_user) or "unknown user")
    except LinkNotFound as error:
        raise HTTPException(status_code=404, detail="Unknown circular link.") from error
    except LinkAlreadyDecided as error:
        raise HTTPException(status_code=409, detail="This link has already been decided.") from error


@app.get("/lineage/links/{link_id}/diff")
def lineage_diff(link_id: uuid.UUID) -> dict:
    from app.embeddings import build_embedder
    from app.lineage_store import LinkNotFound

    try:
        return _lineage_store().diff(str(link_id), build_embedder(settings))
    except LinkNotFound as error:
        raise HTTPException(status_code=404, detail="Unknown circular link.") from error
    except ConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


# ---------------------------------------------------------------- extraction quality

@app.get("/quality")
def extraction_quality() -> dict:
    from app import quality

    try:
        return quality.report(settings.database_url)
    except DatabaseError as error:
        raise HTTPException(status_code=503, detail="The circular store is not available.") from error


# ---------------------------------------------------------------- live database scans

@app.get("/data-scans/targets")
def scan_targets() -> list[dict]:
    from app.data_scan import parse_targets

    return [{"name": name} for name in parse_targets(settings.scan_targets)]


class ScanRequest(BaseModel):
    target: str


@app.post("/data-scans")
def run_data_scan(request: ScanRequest, x_clauseiq_user: str | None = Header(default=None)) -> dict:
    from app.data_scan import DataScanStore, parse_targets, read_catalogue, scan

    targets = parse_targets(settings.scan_targets)
    if request.target not in targets:
        raise HTTPException(status_code=404, detail="Unknown scan target. Targets are configured in SCAN_TARGETS.")
    store = DataScanStore(settings.database_url)
    try:
        database, columns = read_catalogue(targets[request.target])
    except DatabaseError as error:
        logging.warning("Data scan of %s failed: %s", request.target, error)
        scan_id = store.save(request.target, _user(x_clauseiq_user), None, [], [], False,
                             error="Could not read the target database's catalogue. Check SCAN_TARGETS and that "
                                   "the database is reachable.")
        return store.get(scan_id)
    model = None
    if settings.scan_use_ai and settings.openai_api_key:
        from app.llm import build_chat_model

        model = build_chat_model(settings)
    try:
        results, used_ai = scan(columns, model)
    except Exception:
        logging.exception("AI classification failed; keeping the rule-based results")
        results, used_ai = scan(columns, None)
    return store.get(store.save(request.target, _user(x_clauseiq_user), database, columns, results, used_ai))


@app.get("/data-scans")
def list_data_scans() -> list[dict]:
    from app.data_scan import DataScanStore

    return DataScanStore(settings.database_url).list()


@app.get("/data-scans/{scan_id}")
def get_data_scan(scan_id: uuid.UUID) -> dict:
    from app.data_scan import DataScanStore

    result = DataScanStore(settings.database_url).get(str(scan_id))
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown data scan.")
    return result


# ---------------------------------------------------------------- board reports

def _report_response(report, fmt: str, filename: str) -> Response:
    from app.reports import RENDERERS

    if fmt not in RENDERERS:
        raise HTTPException(status_code=404, detail="Use pdf or docx.")
    media_type, render = RENDERERS[fmt]
    return Response(render(report), media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}.{fmt}"'})


@app.get("/reports/posture.{fmt}")
def posture_report(fmt: str, x_clauseiq_user: str | None = Header(default=None)) -> Response:
    from app.reports import posture_report as build

    if fmt not in ("pdf", "docx"):
        raise HTTPException(status_code=404, detail="Use pdf or docx.")
    return _report_response(build(settings.database_url, _user(x_clauseiq_user)), fmt, "clauseiq-compliance-posture")


@app.get("/reports/system-assessments/{assessment_id}.{fmt}")
def system_assessment_report(assessment_id: uuid.UUID, fmt: str,
                             x_clauseiq_user: str | None = Header(default=None)) -> Response:
    from app.reports import system_report

    if fmt not in ("pdf", "docx"):
        raise HTTPException(status_code=404, detail="Use pdf or docx.")
    assessment = get_system_store().get(str(assessment_id))
    if assessment is None:
        raise HTTPException(status_code=404, detail="Unknown system assessment.")
    if assessment["status"] != "COMPLETED":
        raise HTTPException(status_code=409, detail="The assessment has not completed.")
    slug = "".join(c if c.isalnum() else "-" for c in assessment["name"].lower()).strip("-")[:60] or "system"
    return _report_response(system_report(assessment, _user(x_clauseiq_user)), fmt,
                            f"clauseiq-system-assessment-{slug}")


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
