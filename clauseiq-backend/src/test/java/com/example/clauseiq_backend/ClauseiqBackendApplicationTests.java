package com.example.clauseiq_backend;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Runs against a disposable PostgreSQL with pgvector (SPRING_DATASOURCE_URL, _USERNAME, _PASSWORD).
 * The tables are created from the ingestion worker's own schema file, so the API is tested
 * against the real table definitions.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ClauseiqBackendApplicationTests {
    static final HttpServer scannerStub = startScannerStub();

    @LocalServerPort int port;
    @Autowired JdbcTemplate jdbc;
    @Autowired ObjectMapper json;

    final String documentId = "doc-" + UUID.randomUUID();
    final String versionId = "ver-" + UUID.randomUUID();
    final UUID policyChunk = UUID.randomUUID();
    final UUID circularChunk = UUID.randomUUID();
    final UUID gapObligation = UUID.randomUUID();
    final UUID coveredObligation = UUID.randomUUID();
    final UUID findingId = UUID.randomUUID();
    final String controlId = "CTRL-T-" + UUID.randomUUID();
    final String role = "Test SOC Manager " + UUID.randomUUID();
    final String otherRole = "Test Compliance Officer " + UUID.randomUUID();

    @DynamicPropertySource
    static void scannerUrl(DynamicPropertyRegistry registry) {
        registry.add("clauseiq.scanner-url", () -> "http://127.0.0.1:" + scannerStub.getAddress().getPort());
    }

    static HttpServer startScannerStub() {
        try {
            var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext("/api/admin/sources", exchange -> {
                String path = exchange.getRequestURI().getPath();
                int status = path.endsWith("/missing/scan") ? 404 : path.endsWith("/busy/scan") ? 409 : 200;
                byte[] body = (path.endsWith("/scan")
                        ? "{\"id\":\"sebi\",\"lastRunStatus\":\"SUCCESS\"}"
                        : "[{\"id\":\"sebi\",\"regulator\":\"SEBI\"}]").getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().add("Content-Type", "application/json");
                exchange.sendResponseHeaders(status, body.length);
                exchange.getResponseBody().write(body);
                exchange.close();
            });
            server.start();
            return server;
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    @AfterAll
    static void stopScannerStub() {
        scannerStub.stop(0);
    }

    @BeforeEach
    void insertFixture() throws Exception {
        String workerSchema = Files.readString(Path.of("..", "circular-ingestion", "app", "schema.sql"))
                .replace("{dimensions}", "8").replace("{{}}", "{}");
        jdbc.execute(workerSchema);
        jdbc.update("INSERT INTO organizational_role (name) VALUES (?), (?)", role, otherRole);
        jdbc.update("INSERT INTO control (id, name, description, owner_role, frequency, policy_section) "
                + "VALUES (?, 'Incident reporting', 'Report incidents to the regulator', ?, 'Per incident', '6')",
                controlId, role);
        jdbc.update("INSERT INTO regulatory_document (id, regulator, title, source_url) "
                + "VALUES (?, 'RBI', 'Test circular', 'https://example.gov.in/c.pdf')", documentId);
        jdbc.update("INSERT INTO regulatory_document_version (id, document_id, minio_bucket, minio_object_key, "
                + "checksum, processing_status, page_count, obligation_count, processed_at) "
                + "VALUES (?, ?, 'b', 'k', 'c', 'COMPLETED', 2, 2, now())", versionId, documentId);
        jdbc.update("INSERT INTO document_chunk (id, document_id, document_version_id, document_type, page_number, "
                + "clause_number, content, approval_status) VALUES (?, ?, ?, 'CIRCULAR', 1, '3.1', 'text', 'APPROVED')",
                circularChunk, documentId, versionId);
        jdbc.update("INSERT INTO document_chunk (id, document_id, document_type, section_number, heading, content, "
                + "approval_status) VALUES (?, 'policy-handbook', 'POLICY', '6', 'Incident response', "
                + "'Incidents are reported as soon as practicable.', 'APPROVED')", policyChunk);
        for (UUID obligation : new UUID[] {gapObligation, coveredObligation}) {
            boolean gap = obligation.equals(gapObligation);
            jdbc.update("INSERT INTO obligation (id, document_id, document_version_id, chunk_id, summary, "
                    + "required_action, deadline, confidence, extraction_method, coverage_status, "
                    + "coverage_explanation) VALUES (?, ?, ?, ?, ?, 'Do it', ?, 0.9, 'LLM', ?, 'Explained')",
                    obligation, documentId, versionId, circularChunk,
                    gap ? "Report incidents within 6 hours" : "Review audit logs quarterly",
                    gap ? "within 6 hours" : null, gap ? "PARTIALLY_COVERED" : "COVERED");
            jdbc.update("INSERT INTO citation (id, obligation_id, document_id, document_version_id, page_number, "
                    + "clause_number, quoted_text, start_offset, end_offset) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 10)",
                    UUID.randomUUID(), obligation, documentId, versionId, gap ? 1 : 2, gap ? "3.1" : "2.1",
                    gap ? "shall report within 6 hours" : "shall review logs every quarter");
        }
        jdbc.update("INSERT INTO obligation_mapping (id, obligation_id, target_type, target_id, section_number, "
                + "similarity, matched) VALUES (?, ?, 'POLICY_SECTION', ?, '6', 0.71, true), "
                + "(?, ?, 'CONTROL', ?, '6', 0.64, true), (?, ?, 'CONTROL', 'CTRL-UNMATCHED', null, 0.2, false)",
                UUID.randomUUID(), gapObligation, policyChunk.toString(), UUID.randomUUID(), gapObligation, controlId,
                UUID.randomUUID(), gapObligation);
        jdbc.update("INSERT INTO finding (id, obligation_id, document_id, document_version_id, finding_type, "
                + "coverage_status, severity, title, explanation, policy_section, policy_quote, confidence, "
                + "original_ai_output) VALUES (?, ?, ?, ?, 'PARTIAL_POLICY_GAP', 'PARTIALLY_COVERED', 'MEDIUM', "
                + "'No reporting deadline', 'The policy has no timeframe.', '6', 'as soon as practicable', 0.8, "
                + "'{\"coverageStatus\":\"PARTIALLY_COVERED\"}'::jsonb)", findingId, gapObligation, documentId, versionId);
        jdbc.update("INSERT INTO recommendation (id, finding_id, draft_policy_text, recommended_action, "
                + "assigned_role, suggested_deadline, required_evidence, confidence, original_ai_output) "
                + "VALUES (?, ?, 'AI draft wording', 'Update the policy', ?, '30 days', "
                + "'[\"Approved policy version\"]'::jsonb, 0.7, '{\"assignedRole\":\"AI role\"}'::jsonb)",
                UUID.randomUUID(), findingId, role);
    }

    @AfterEach
    void removeFixture() {
        jdbc.update("DELETE FROM review_decision WHERE finding_id = ?", findingId);
        jdbc.update("DELETE FROM document_chunk WHERE id IN (?, ?)", circularChunk, policyChunk); // cascades
        jdbc.update("DELETE FROM regulatory_document_version WHERE id = ?", versionId);
        jdbc.update("DELETE FROM regulatory_document WHERE id = ?", documentId);
        jdbc.update("DELETE FROM control WHERE id = ?", controlId);
        jdbc.update("DELETE FROM organizational_role WHERE name IN (?, ?)", role, otherRole);
    }

    @Test
    void listsDocumentsObligationsAndLookups() throws Exception {
        JsonNode document = find(get("/api/documents").body, "documentVersionId", versionId);
        assertThat(document.path("title").asString()).isEqualTo("Test circular");
        assertThat(document.path("processingStatus").asString()).isEqualTo("COMPLETED");
        assertThat(document.path("findingCount").asInt()).isEqualTo(1);
        assertThat(document.path("pendingFindingCount").asInt()).isEqualTo(1);

        JsonNode obligations = get("/api/obligations?documentVersionId=" + versionId).body;
        assertThat(obligations).hasSize(2);
        JsonNode gap = find(obligations, "id", gapObligation.toString());
        assertThat(gap.path("citation").path("clauseNumber").asString()).isEqualTo("3.1");
        assertThat(gap.path("citation").path("quotedText").asString()).isEqualTo("shall report within 6 hours");
        assertThat(gap.path("findingId").asString()).isEqualTo(findingId.toString());
        assertThat(find(obligations, "id", coveredObligation.toString()).path("findingId").isNull()).isTrue();
        assertThat(get("/api/obligations?documentVersionId=" + versionId + "&coverageStatus=COVERED").body).hasSize(1);

        assertThat(get("/api/roles").body.toString()).contains(role);
        assertThat(find(get("/api/controls").body, "id", controlId).path("ownerRole").asString()).isEqualTo(role);
        assertThat(get("/api/summary").body.path("findingsByStatus").toString()).contains("PENDING_REVIEW");
        assertThat(get("/actuator/health").status).isEqualTo(200);
    }

    @Test
    void findingDetailShowsCitationPolicyControlAndDraft() throws Exception {
        JsonNode summary = find(get("/api/findings?status=PENDING_REVIEW&documentVersionId=" + versionId).body,
                "id", findingId.toString());
        assertThat(summary.path("assignedRole").asString()).isEqualTo(role);
        assertThat(summary.path("clauseNumber").asString()).isEqualTo("3.1");

        JsonNode detail = get("/api/findings/" + findingId).body;
        assertThat(detail.path("obligation").path("citation").path("pageNumber").asInt()).isEqualTo(1);
        assertThat(detail.path("policies")).hasSize(1);
        assertThat(detail.path("policies").get(0).path("heading").asString()).isEqualTo("Incident response");
        assertThat(detail.path("controls")).hasSize(1); // the unmatched control is not shown
        assertThat(detail.path("controls").get(0).path("id").asString()).isEqualTo(controlId);
        assertThat(detail.path("recommendation").path("requiredEvidence").get(0).asString())
                .isEqualTo("Approved policy version");
        assertThat(detail.path("originalAiOutput").path("recommendation").path("assignedRole").asString())
                .isEqualTo("AI role");
        assertThat(detail.path("decisions")).isEmpty();

        var missing = get("/api/findings/" + UUID.randomUUID());
        assertThat(missing.status).isEqualTo(404);
        assertThat(missing.body.path("message").asString()).isEqualTo("Unknown finding");
        assertThat(get("/api/findings/not-a-uuid").status).isEqualTo(400);
    }

    @Test
    void approveRecordsTheDecisionAndCannotBeRepeated() throws Exception {
        var noReviewer = post("/api/findings/" + findingId + "/approve", "{}");
        assertThat(noReviewer.status).isEqualTo(400);
        assertThat(noReviewer.body.path("message").asString()).isEqualTo("reviewer is required");
        assertThat(post("/api/findings/" + findingId + "/approve", "not json").status).isEqualTo(400);

        var approved = post("/api/findings/" + findingId + "/approve", "{\"reviewer\":\"meena\",\"comment\":\"ok\"}");
        assertThat(approved.status).isEqualTo(200);
        assertThat(approved.body.path("status").asString()).isEqualTo("APPROVED");
        JsonNode decision = approved.body.path("decisions").get(0);
        assertThat(decision.path("decision").asString()).isEqualTo("APPROVED");
        assertThat(decision.path("reviewer").asString()).isEqualTo("meena");
        assertThat(decision.path("originalValue").path("draftPolicyText").asString()).isEqualTo("AI draft wording");

        assertThat(post("/api/findings/" + findingId + "/reject",
                "{\"reviewer\":\"meena\",\"comment\":\"changed my mind\"}").status).isEqualTo(409);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM review_decision WHERE finding_id = ?", Integer.class,
                findingId)).isEqualTo(1);
    }

    @Test
    void editAndApproveKeepsTheOriginalAndValidatesTheRole() throws Exception {
        String path = "/api/findings/" + findingId + "/edit-and-approve";
        assertThat(post(path, "{\"reviewer\":\"meena\",\"assignedRole\":\"Chief Wizard\"}").status).isEqualTo(400);
        assertThat(post(path, "{\"reviewer\":\"meena\",\"severity\":\"URGENT\"}").status).isEqualTo(400);
        assertThat(post(path, "{\"reviewer\":\"meena\"}").status).isEqualTo(400); // nothing edited
        assertThat(get("/api/findings/" + findingId).body.path("status").asString()).isEqualTo("PENDING_REVIEW");

        var edited = post(path, json.writeValueAsString(java.util.Map.of(
                "reviewer", "meena", "draftPolicyText", "Incidents must be reported within 6 hours.",
                "assignedRole", otherRole, "severity", "HIGH")));
        assertThat(edited.status).isEqualTo(200);
        assertThat(edited.body.path("status").asString()).isEqualTo("APPROVED_WITH_CHANGES");
        assertThat(edited.body.path("severity").asString()).isEqualTo("HIGH");
        JsonNode recommendation = edited.body.path("recommendation");
        assertThat(recommendation.path("draftPolicyText").asString()).isEqualTo("Incidents must be reported within 6 hours.");
        assertThat(recommendation.path("assignedRole").asString()).isEqualTo(otherRole);
        assertThat(recommendation.path("recommendedAction").asString()).isEqualTo("Update the policy"); // untouched
        JsonNode decision = edited.body.path("decisions").get(0);
        assertThat(decision.path("originalValue").path("draftPolicyText").asString()).isEqualTo("AI draft wording");
        assertThat(decision.path("originalValue").path("severity").asString()).isEqualTo("MEDIUM");
        assertThat(decision.path("editedValue").path("assignedRole").asString()).isEqualTo(otherRole);
        assertThat(edited.body.path("originalAiOutput").path("recommendation").path("assignedRole").asString())
                .isEqualTo("AI role");
    }

    @Test
    void rejectNeedsACommentAndLeavesTheDraftUnchanged() throws Exception {
        String path = "/api/findings/" + findingId + "/reject";
        assertThat(post(path, "{\"reviewer\":\"meena\"}").status).isEqualTo(400);

        var rejected = post(path, "{\"reviewer\":\"meena\",\"comment\":\"Not applicable to us\"}");
        assertThat(rejected.body.path("status").asString()).isEqualTo("REJECTED");
        assertThat(rejected.body.path("recommendation").path("draftPolicyText").asString()).isEqualTo("AI draft wording");
        assertThat(rejected.body.path("decisions").get(0).path("comment").asString()).isEqualTo("Not applicable to us");
    }

    @Test
    void sourceEndpointsForwardToTheScanner() throws Exception {
        assertThat(get("/api/admin/sources").body.get(0).path("id").asString()).isEqualTo("sebi");
        assertThat(post("/api/admin/sources/sebi/scan", "").body.path("lastRunStatus").asString()).isEqualTo("SUCCESS");
        assertThat(post("/api/admin/sources/missing/scan", "").status).isEqualTo(404);
        var busy = post("/api/admin/sources/busy/scan", "");
        assertThat(busy.status).isEqualTo(409);
        assertThat(busy.body.path("message").asString()).contains("already running");
    }

    record Reply(int status, JsonNode body) {}

    Reply get(String path) throws Exception {
        return send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + path)).GET().build());
    }

    Reply post(String path, String body) throws Exception {
        return send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + path))
                .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body)).build());
    }

    Reply send(HttpRequest request) throws Exception {
        var response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString());
        return new Reply(response.statusCode(), json.readTree(response.body()));
    }

    static JsonNode find(JsonNode array, String field, String value) {
        for (JsonNode item : array) {
            if (value.equals(item.path(field).asString())) {
                return item;
            }
        }
        throw new AssertionError("No item with " + field + "=" + value + " in " + array);
    }
}
