package com.example.circular_scanner;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"scanner.cron=-", "scanner.outbox-delay=3600000"})
class ScannerWorkflowTests {
    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper json;
    @Autowired OutboxPublisher publisher;
    @MockitoBean PublicationClient publications;
    @MockitoBean PdfStore store;
    @MockitoBean KafkaTemplate<String, String> kafka;

    @Test
    void manualScanDeduplicatesAndRetriesKafkaDelivery() throws Exception {
        String id = "workflow-test-" + java.util.UUID.randomUUID();
        String pdfUrl = "https://example.gov.in/circular.pdf";
        jdbc.update("""
                INSERT INTO regulatory_source (id, name, regulator, listing_url, allowed_hosts, detail_link_pattern)
                VALUES (?, 'Workflow fixture', 'TEST', 'https://example.gov.in/listing', 'example.gov.in', 'unused')
                """, id);
        var candidate = new PublicationClient.Candidate(URI.create(pdfUrl), "Test circular");
        when(publications.discover(any())).thenReturn(new PublicationClient.Discovery(List.of(candidate), 0));
        when(publications.download(any(), eq(candidate))).thenReturn("%PDF-1.7\nfixture".getBytes(StandardCharsets.UTF_8));
        when(store.bucket()).thenReturn("regulatory-originals");
        when(kafka.send(eq("regulatory.document.ingested"), anyString(), anyString()))
                .thenReturn(CompletableFuture.failedFuture(new IllegalStateException("Broker unavailable")),
                        CompletableFuture.completedFuture(null));

        try {
            var first = scan(id);
            assertThat(first.path("lastRunStatus").asText()).isEqualTo("SUCCESS");
            assertThat(first.path("lastNewDocuments").asInt()).isEqualTo(1);
            assertThat(scan(id).path("lastNewDocuments").asInt()).isZero();
            verify(store, times(1)).put(anyString(), any());

            publisher.publishPending();
            assertThat(document(id).get("published_at")).isNull();
            publisher.publishPending();
            assertThat(document(id).get("published_at")).isNotNull();

            var event = ArgumentCaptor.forClass(String.class);
            verify(kafka, times(2)).send(eq("regulatory.document.ingested"), anyString(), event.capture());
            assertThat(event.getAllValues().get(0)).isEqualTo(event.getValue());
            var payload = json.readTree(event.getValue());
            assertThat(payload.path("eventId").asText()).isEqualTo(document(id).get("id").toString());
            assertThat(payload.path("sourceUrl").asText()).isEqualTo(pdfUrl);
            assertThat(payload.path("minioObjectKey").asText()).isEqualTo(document(id).get("object_key"));
            assertThat(payload.path("documentId").asText()).isEqualTo(document(id).get("document_id").toString());

            when(publications.download(any(), eq(candidate)))
                    .thenReturn("%PDF-1.7\nupdated fixture".getBytes(StandardCharsets.UTF_8));
            assertThat(scan(id).path("lastNewDocuments").asInt()).isEqualTo(1);
            var versions = jdbc.queryForList("""
                    SELECT document_id, version_number, object_key FROM scanned_document
                    WHERE source_id = ? ORDER BY version_number
                    """, id);
            assertThat(versions).extracting(row -> row.get("version_number")).containsExactly(1, 2);
            assertThat(versions.get(1).get("document_id")).isEqualTo(versions.get(0).get("document_id"));
            assertThat(versions.get(1).get("object_key").toString()).endsWith("/version-2/original.pdf");
        } finally {
            jdbc.update("DELETE FROM scanned_document WHERE source_id = ?", id);
            jdbc.update("DELETE FROM regulatory_source WHERE id = ?", id);
        }
    }

    private tools.jackson.databind.JsonNode scan(String id) throws Exception {
        var uri = URI.create("http://127.0.0.1:" + port + "/api/admin/sources/" + id + "/scan");
        var response = HttpClient.newHttpClient().send(
                HttpRequest.newBuilder(uri).POST(HttpRequest.BodyPublishers.noBody()).build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).isEqualTo(200);
        return json.readTree(response.body());
    }

    private Map<String, Object> document(String id) {
        return jdbc.queryForMap("SELECT id, document_id, object_key, published_at FROM scanned_document WHERE source_id = ?", id);
    }
}
