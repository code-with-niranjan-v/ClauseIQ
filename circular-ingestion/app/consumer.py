import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.models import IngestionEvent

logger = logging.getLogger(__name__)


class DocumentConsumer:
    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            settings.kafka_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_group_id,
            enable_auto_commit=False,
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        )
        await self._consumer.start()
        self._task = asyncio.create_task(self._consume_one_at_a_time())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self._consumer:
            await self._consumer.stop()

    async def _consume_one_at_a_time(self) -> None:
        assert self._consumer is not None
        async for message in self._consumer:
            try:
                event = IngestionEvent.model_validate(message.value)
                await self.process_event(event)
                await self._consumer.commit()
            except Exception:
                logger.exception("Failed to process Kafka event")

    async def process_event(self, event: IngestionEvent) -> None:
        logger.info("Processing document %s (event %s)", event.document_id, event.event_id)
        # Fetch the PDF by document ID from MinIO, extract text, chunk, and
        # persist extraction results. Processing remains intentionally sequential.
