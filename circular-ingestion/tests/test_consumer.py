import asyncio
import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.consumer import DocumentConsumer
from tests.fakes import make_event


class FakeKafkaConsumer:
    def __init__(self, values):
        self.messages = [SimpleNamespace(value=value, key=b"key", topic="regulatory.document.ingested", offset=index)
                         for index, value in enumerate(values)]
        self.commits = 0

    async def getone(self):
        if not self.messages:
            raise asyncio.CancelledError
        return self.messages.pop(0)

    async def commit(self):
        self.commits += 1


class FakeKafkaProducer:
    def __init__(self):
        self.sent = []

    async def send_and_wait(self, topic, key, value, headers):
        self.sent.append((topic, value, dict(headers)))


class FakeProcessor:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.events = []
        self.last_error = "PdfError: unreadable"

    def process(self, event):
        self.events.append(event.event_id)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def run(values, outcomes):
    consumer = DocumentConsumer(Settings(_env_file=None))
    consumer._consumer, consumer._producer = FakeKafkaConsumer(values), FakeKafkaProducer()
    processor = FakeProcessor(outcomes)

    async def consume():
        with pytest.raises((asyncio.CancelledError, ConnectionError)):
            await consumer._consume(processor)

    asyncio.run(consume())
    return consumer, processor


def payload(event_id):
    return json.dumps(make_event(b"pdf", eventId=event_id).model_dump(by_alias=True, mode="json")).encode()


def test_scanner_payload_is_processed_and_committed():
    consumer, processor = run([payload("evt-1"), payload("evt-1")], ["COMPLETED", "SKIPPED"])

    assert processor.events == ["evt-1", "evt-1"]
    assert consumer._consumer.commits == 2
    assert consumer.processed == 1 and consumer._producer.sent == []


def test_malformed_and_failed_events_go_to_the_dead_letter_topic():
    consumer, processor = run([b"not json", b'{"eventId": "evt-2"}', payload("evt-3")], ["DEAD_LETTERED"])

    assert processor.events == ["evt-3"]  # invalid payloads never reach the pipeline
    topics = {topic for topic, _, _ in consumer._producer.sent}
    assert topics == {"regulatory.document.ingested.dlq"}
    assert consumer._producer.sent[2][2]["error"] == b"PdfError: unreadable"
    assert consumer._producer.sent[2][2]["eventId"] == b"evt-3"
    assert consumer._consumer.commits == 3 and consumer.dead_lettered == 3


def test_offset_is_not_committed_when_the_database_is_down():
    consumer, _ = run([payload("evt-4")], [ConnectionError("database unavailable")])

    assert consumer._consumer.commits == 0
