package com.example.circular_scanner;

import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;

@Component
class OutboxPublisher {
    private static final Logger log = LoggerFactory.getLogger(OutboxPublisher.class);

    private final ScannerRepository repository;
    private final KafkaTemplate<String, String> kafka;
    private final ObjectMapper json;
    private final TransactionTemplate transactions;
    private final String topic;

    OutboxPublisher(ScannerRepository repository, KafkaTemplate<String, String> kafka, ObjectMapper json,
                    TransactionTemplate transactions, @Value("${scanner.kafka-topic}") String topic) {
        this.repository = repository;
        this.kafka = kafka;
        this.json = json;
        this.transactions = transactions;
        this.topic = topic;
    }

    @Scheduled(fixedDelayString = "${scanner.outbox-delay}")
    void publishPending() {
        try {
            for (int count = 0; count < 50; count++) {
                if (!Boolean.TRUE.equals(transactions.execute(status -> publishNext()))) {
                    return;
                }
            }
        } catch (RuntimeException e) {
            log.warn("Kafka publication failed; unpublished documents remain queued", e);
        }
    }

    private boolean publishNext() {
        var pending = repository.nextPending();
        if (pending.isEmpty()) {
            return false;
        }
        var document = pending.orElseThrow();
        String id = document.id().toString();
        String payload = json.writeValueAsString(Map.ofEntries(
                Map.entry("eventId", id),
                Map.entry("eventType", "REGULATORY_DOCUMENT_INGESTED"),
                Map.entry("documentId", document.documentId().toString()),
                Map.entry("documentVersionId", id),
                Map.entry("regulator", document.regulator()),
                Map.entry("title", document.title()),
                Map.entry("sourceUrl", document.url()),
                Map.entry("minioBucket", document.bucket()),
                Map.entry("minioObjectKey", document.key()),
                Map.entry("checksum", document.checksum()),
                Map.entry("createdAt", document.createdAt().toString())));
        try {
            kafka.send(topic, document.documentId().toString(), payload).get(35, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Kafka publication interrupted", e);
        } catch (java.util.concurrent.ExecutionException | java.util.concurrent.TimeoutException e) {
            throw new IllegalStateException("Kafka did not acknowledge the document", e);
        }
        repository.published(document.id());
        return true;
    }
}
