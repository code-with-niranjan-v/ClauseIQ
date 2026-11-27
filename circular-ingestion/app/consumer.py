import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pydantic import ValidationError

from app import workflow
from app.config import Settings
from app.db import PostgresRepository
from app.embeddings import build_embedder
from app.extraction import build_extractor
from app.graph_store import build_graph_store
from app.models import IngestionEvent
from app.storage import MinioStore

logger = logging.getLogger(__name__)


class EventProcessor:
    """Processes one event with idempotency and bounded retries. Blocking; run it off the event loop."""

    def __init__(self, repository, pipeline, max_attempts: int, backoff_seconds: float,
                 sleep=time.sleep) -> None:
        self._repository = repository
        self._pipeline = pipeline
        self._max_attempts = max(1, max_attempts)
        self._backoff = backoff_seconds
        self._sleep = sleep
        self.last_error = ""

    def process(self, event: IngestionEvent) -> str:
        """Returns COMPLETED, SKIPPED or DEAD_LETTERED. Raises nothing for a document failure."""
        error = ""
        for attempt in range(1, self._max_attempts + 1):
            if not self._repository.begin_event(event):
                logger.info("Event %s was already processed. Skipping.", event.event_id)
                return "SKIPPED"
            try:
                result = workflow.run(self._pipeline, event)
                logger.info("Document %s: %s pages, %s chunks, %s obligations, %s rejected",
                            event.document_id, result.page_count, len(result.chunks),
                            len(result.obligations), len(result.rejected))
                return "COMPLETED"
            except Exception as failure:
                error = f"{type(failure).__name__}: {failure}"
                final = attempt == self._max_attempts
                logger.exception("Attempt %s of %s failed for event %s", attempt, self._max_attempts, event.event_id)
                self._repository.fail_event(event, error, final)
                if not final:
                    self._sleep(self._backoff * attempt)
        self.last_error = error
        return "DEAD_LETTERED"


class DocumentConsumer:
    """Consumes `regulatory.document.ingested` one event at a time."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None
        self._task: asyncio.Task | None = None
        self.state = "STOPPED"
        self.processed = 0
        self.dead_lettered = 0
        self.last_event_id: str | None = None
        self.last_error: str | None = None

    async def start(self) -> None:
        self.state = "STARTING"
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self._close()
        self.state = "STOPPED"

    async def _close(self) -> None:
        for client in (self._consumer, self._producer):
            if client:
                try:
                    await client.stop()
                except Exception:
                    logger.exception("Could not stop a Kafka client cleanly")
        self._consumer = self._producer = None

    async def _run(self) -> None:
        """Connect and consume. Reconnects after infrastructure failures so the health API stays up."""
        while True:
            try:
                processor = await asyncio.to_thread(self._build_processor)
                await self._connect()
                self.state = "RUNNING"
                await self._consume(processor)
            except asyncio.CancelledError:
                raise
            except Exception as failure:
                self.state = "DEGRADED"
                self.last_error = f"{type(failure).__name__}: {failure}"
                logger.exception("Consumer stopped. Reconnecting in 10 seconds.")
                await self._close()
                await asyncio.sleep(10)

    def _build_processor(self) -> EventProcessor:
        settings = self._settings
        repository = PostgresRepository(settings.database_url, settings.embedding_dimensions)
        repository.ensure_schema()
        graph = build_graph_store(settings)
        if hasattr(graph, "ensure_schema"):
            graph.ensure_schema()
        pipeline = workflow.build_workflow(workflow.Dependencies(
            store=MinioStore(settings), extractor=build_extractor(settings), embedder=build_embedder(settings),
            repository=repository, graph=graph, chunk_max_chars=settings.chunk_max_chars))
        return EventProcessor(repository, pipeline, settings.max_attempts, settings.retry_backoff_seconds)

    async def _connect(self) -> None:
        settings = self._settings
        self._producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers, acks="all")
        await self._producer.start()
        self._consumer = AIOKafkaConsumer(
            settings.kafka_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_poll_records=1,
            # A large circular with an LLM call per page can take minutes.
            max_poll_interval_ms=30 * 60 * 1000,
        )
        await self._consumer.start()

    async def _consume(self, processor: EventProcessor) -> None:
        assert self._consumer is not None
        while True:
            message = await self._consumer.getone()
            try:
                event = IngestionEvent.model_validate(json.loads(message.value))
            except (ValueError, ValidationError) as failure:
                # A malformed payload can never succeed, so it is not retried.
                await self._dead_letter(message, None, f"Invalid event: {failure}")
                await self._consumer.commit()
                continue
            self.last_event_id = event.event_id
            # Database or Kafka outages raise here and leave the offset uncommitted, so the event is redelivered.
            outcome = await asyncio.to_thread(processor.process, event)
            if outcome == "DEAD_LETTERED":
                self.last_error = processor.last_error
                await self._dead_letter(message, event, processor.last_error)
            elif outcome == "COMPLETED":
                self.processed += 1
            await self._consumer.commit()

    async def _dead_letter(self, message, event: IngestionEvent | None, error: str) -> None:
        assert self._producer is not None
        logger.error("Dead-lettering offset %s of %s: %s", message.offset, message.topic, error)
        await self._producer.send_and_wait(
            self._settings.kafka_dead_letter_topic,
            key=message.key,
            value=message.value,
            headers=[
                ("error", error[:1000].encode()),
                ("eventId", (event.event_id if event else "").encode()),
                ("sourceTopic", message.topic.encode()),
                ("sourceOffset", str(message.offset).encode()),
                ("failedAt", datetime.now(timezone.utc).isoformat().encode()),
            ],
        )
        self.dead_lettered += 1

    def status(self) -> dict:
        return {"state": self.state, "processed": self.processed, "deadLettered": self.dead_lettered,
                "lastEventId": self.last_event_id, "lastError": self.last_error}
