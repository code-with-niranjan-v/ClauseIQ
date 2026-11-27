package com.example.clauseiq_backend;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Reads the tables the ingestion worker writes, and owns review_decision. */
@Repository
class ApiRepository {
    record Document(String documentId, String documentVersionId, String regulator, String title, String sourceUrl,
                    String processingStatus, Integer pageCount, Integer obligationCount, int findingCount,
                    int pendingFindingCount, OffsetDateTime createdAt, OffsetDateTime processedAt,
                    String processingError, Integer processingAttempts, String eventStatus) {}

    record Citation(int pageNumber, String clauseNumber, String quotedText) {}

    record Obligation(UUID id, String documentId, String documentVersionId, String documentTitle, String regulator,
                      String summary, String requiredAction, String responsibleEntity, String deadline,
                      String applicability, double confidence, String extractionMethod, String coverageStatus,
                      String coverageExplanation, Citation citation, UUID findingId) {}

    record FindingSummary(UUID id, String title, String findingType, String coverageStatus, String severity,
                          String status, double confidence, String assignedRole, String documentVersionId,
                          String documentTitle, String regulator, String obligationSummary, String clauseNumber,
                          OffsetDateTime createdAt) {}

    record PolicySection(String sectionNumber, String heading, String content, double similarity) {}

    record Control(String id, String name, String description, String ownerRole, String frequency,
                   String policySection) {}

    record Recommendation(String draftPolicyText, String recommendedAction, String assignedRole,
                          String suggestedDeadline, JsonNode requiredEvidence, double confidence) {}

    record Decision(UUID id, String decision, String reviewer, String comment, JsonNode originalValue,
                    JsonNode editedValue, OffsetDateTime decidedAt) {}

    record FindingDetail(UUID id, String title, String findingType, String coverageStatus, String severity,
                         String status, double confidence, String explanation, String policySection,
                         String policyQuote, OffsetDateTime createdAt, Obligation obligation,
                         List<PolicySection> policies, List<Control> controls, Recommendation recommendation,
                         JsonNode originalAiOutput, List<Decision> decisions) {}

    record Count(String name, long count) {}

    private static final String OBLIGATION_SELECT = """
            SELECT o.*, c.page_number, c.clause_number, c.quoted_text, d.title AS document_title, d.regulator,
                   f.id AS finding_id
            FROM obligation o
            JOIN citation c ON c.obligation_id = o.id
            JOIN regulatory_document d ON d.id = o.document_id
            LEFT JOIN finding f ON f.obligation_id = o.id
            """;

    private static final RowMapper<Obligation> OBLIGATION = (rs, row) -> new Obligation(
            rs.getObject("id", UUID.class), rs.getString("document_id"), rs.getString("document_version_id"),
            rs.getString("document_title"), rs.getString("regulator"), rs.getString("summary"),
            rs.getString("required_action"), rs.getString("responsible_entity"), rs.getString("deadline"),
            rs.getString("applicability"), rs.getDouble("confidence"), rs.getString("extraction_method"),
            rs.getString("coverage_status"), rs.getString("coverage_explanation"),
            new Citation(rs.getInt("page_number"), rs.getString("clause_number"), rs.getString("quoted_text")),
            rs.getObject("finding_id", UUID.class));

    private static final RowMapper<Control> CONTROL = (rs, row) -> new Control(
            rs.getString("id"), rs.getString("name"), rs.getString("description"), rs.getString("owner_role"),
            rs.getString("frequency"), rs.getString("policy_section"));

    private final JdbcTemplate jdbc;
    private final ObjectMapper json;

    ApiRepository(JdbcTemplate jdbc, ObjectMapper json) {
        this.jdbc = jdbc;
        this.json = json;
    }

    List<Document> documents() {
        return jdbc.query("""
                SELECT d.id AS document_id, v.id AS version_id, d.regulator, d.title, d.source_url,
                       v.processing_status, v.page_count, v.obligation_count, v.created_at, v.processed_at,
                       e.last_error, e.attempts, e.status AS event_status,
                       (SELECT count(*) FROM finding f WHERE f.document_version_id = v.id) AS finding_count,
                       (SELECT count(*) FROM finding f WHERE f.document_version_id = v.id
                            AND f.status = 'PENDING_REVIEW') AS pending_count
                FROM regulatory_document_version v JOIN regulatory_document d ON d.id = v.document_id
                LEFT JOIN LATERAL (
                    SELECT last_error, attempts, status FROM processed_event
                    WHERE document_version_id = v.id
                    ORDER BY started_at DESC, event_id DESC LIMIT 1
                ) e ON true
                ORDER BY v.created_at DESC, v.id
                """, (rs, row) -> new Document(
                rs.getString("document_id"), rs.getString("version_id"), rs.getString("regulator"),
                rs.getString("title"), rs.getString("source_url"), rs.getString("processing_status"),
                rs.getObject("page_count", Integer.class), rs.getObject("obligation_count", Integer.class),
                rs.getInt("finding_count"), rs.getInt("pending_count"),
                rs.getObject("created_at", OffsetDateTime.class), rs.getObject("processed_at", OffsetDateTime.class),
                rs.getString("last_error"), rs.getObject("attempts", Integer.class), rs.getString("event_status")));
    }

    List<Obligation> obligations(String documentVersionId, String coverageStatus) {
        var where = new ArrayList<String>();
        var arguments = new ArrayList<Object>();
        if (documentVersionId != null) {
            where.add("o.document_version_id = ?");
            arguments.add(documentVersionId);
        }
        if (coverageStatus != null) {
            where.add("o.coverage_status = ?");
            arguments.add(coverageStatus);
        }
        String filter = where.isEmpty() ? "" : " WHERE " + String.join(" AND ", where);
        return jdbc.query(OBLIGATION_SELECT + filter + " ORDER BY o.created_at DESC, c.page_number, c.start_offset",
                OBLIGATION, arguments.toArray());
    }

    List<FindingSummary> findings(String status, String documentVersionId) {
        var where = new ArrayList<String>();
        var arguments = new ArrayList<Object>();
        if (status != null) {
            where.add("f.status = ?");
            arguments.add(status);
        }
        if (documentVersionId != null) {
            where.add("f.document_version_id = ?");
            arguments.add(documentVersionId);
        }
        String filter = where.isEmpty() ? "" : " WHERE " + String.join(" AND ", where);
        return jdbc.query("""
                SELECT f.*, r.assigned_role, d.title AS document_title, d.regulator, o.summary AS obligation_summary,
                       c.clause_number
                FROM finding f
                JOIN obligation o ON o.id = f.obligation_id
                JOIN citation c ON c.obligation_id = o.id
                JOIN regulatory_document d ON d.id = f.document_id
                LEFT JOIN recommendation r ON r.finding_id = f.id
                """ + filter + """
                 ORDER BY CASE f.severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END,
                          f.created_at DESC, f.id
                """, (rs, row) -> new FindingSummary(
                rs.getObject("id", UUID.class), rs.getString("title"), rs.getString("finding_type"),
                rs.getString("coverage_status"), rs.getString("severity"), rs.getString("status"),
                rs.getDouble("confidence"), rs.getString("assigned_role"), rs.getString("document_version_id"),
                rs.getString("document_title"), rs.getString("regulator"), rs.getString("obligation_summary"),
                rs.getString("clause_number"), rs.getObject("created_at", OffsetDateTime.class)), arguments.toArray());
    }

    Optional<FindingDetail> finding(UUID id) {
        return jdbc.query("""
                SELECT f.*, r.draft_policy_text, r.recommended_action, r.assigned_role, r.suggested_deadline,
                       r.required_evidence::text AS required_evidence, r.confidence AS recommendation_confidence,
                       f.original_ai_output::text AS finding_ai, r.original_ai_output::text AS recommendation_ai
                FROM finding f LEFT JOIN recommendation r ON r.finding_id = f.id WHERE f.id = ?
                """, (rs, row) -> detail(rs), id).stream().findFirst();
    }

    private FindingDetail detail(ResultSet rs) throws SQLException {
        UUID id = rs.getObject("id", UUID.class);
        UUID obligationId = rs.getObject("obligation_id", UUID.class);
        Obligation obligation = jdbc.query(OBLIGATION_SELECT + " WHERE o.id = ?", OBLIGATION, obligationId)
                .stream().findFirst().orElse(null);
        List<PolicySection> policies = jdbc.query("""
                SELECT k.section_number, k.heading, k.content, m.similarity
                FROM obligation_mapping m JOIN document_chunk k ON k.id::text = m.target_id
                WHERE m.obligation_id = ? AND m.target_type = 'POLICY_SECTION' AND m.matched
                ORDER BY m.similarity DESC
                """, (row, index) -> new PolicySection(row.getString("section_number"), row.getString("heading"),
                row.getString("content"), row.getDouble("similarity")), obligationId);
        List<Control> controls = jdbc.query("""
                SELECT c.* FROM obligation_mapping m JOIN control c ON c.id = m.target_id
                WHERE m.obligation_id = ? AND m.target_type = 'CONTROL' AND m.matched ORDER BY c.id
                """, CONTROL, obligationId);
        Recommendation recommendation = rs.getString("recommended_action") == null ? null : new Recommendation(
                rs.getString("draft_policy_text"), rs.getString("recommended_action"), rs.getString("assigned_role"),
                rs.getString("suggested_deadline"), tree(rs.getString("required_evidence")),
                rs.getDouble("recommendation_confidence"));
        var original = json.createObjectNode();
        original.set("finding", tree(rs.getString("finding_ai")));
        original.set("recommendation", tree(rs.getString("recommendation_ai")));
        return new FindingDetail(id, rs.getString("title"), rs.getString("finding_type"),
                rs.getString("coverage_status"), rs.getString("severity"), rs.getString("status"),
                rs.getDouble("confidence"), rs.getString("explanation"), rs.getString("policy_section"),
                rs.getString("policy_quote"), rs.getObject("created_at", OffsetDateTime.class), obligation, policies,
                controls, recommendation, original, decisions(id));
    }

    List<Decision> decisions(UUID findingId) {
        return jdbc.query("""
                SELECT id, decision, reviewer, comment, original_value::text AS original_value,
                       edited_value::text AS edited_value, decided_at
                FROM review_decision WHERE finding_id = ? ORDER BY decided_at, id
                """, (rs, row) -> new Decision(rs.getObject("id", UUID.class), rs.getString("decision"),
                rs.getString("reviewer"), rs.getString("comment"), tree(rs.getString("original_value")),
                tree(rs.getString("edited_value")), rs.getObject("decided_at", OffsetDateTime.class)), findingId);
    }

    /** Moves a pending finding to its decided status. Returns false if it was already decided. */
    boolean decide(UUID findingId, String status) {
        return jdbc.update("UPDATE finding SET status = ? WHERE id = ? AND status = 'PENDING_REVIEW'",
                status, findingId) == 1;
    }

    void updateFinding(UUID findingId, String title, String severity) {
        jdbc.update("UPDATE finding SET title = COALESCE(?, title), severity = COALESCE(?, severity) WHERE id = ?",
                title, severity, findingId);
    }

    void updateRecommendation(UUID findingId, String draftPolicyText, String recommendedAction, String assignedRole,
                              String suggestedDeadline, String requiredEvidenceJson) {
        jdbc.update("""
                UPDATE recommendation SET draft_policy_text = COALESCE(?, draft_policy_text),
                    recommended_action = COALESCE(?, recommended_action),
                    assigned_role = COALESCE(?, assigned_role),
                    suggested_deadline = COALESCE(?, suggested_deadline),
                    required_evidence = COALESCE(?::jsonb, required_evidence)
                WHERE finding_id = ?
                """, draftPolicyText, recommendedAction, assignedRole, suggestedDeadline, requiredEvidenceJson,
                findingId);
    }

    void recordDecision(UUID findingId, String decision, String reviewer, String comment, JsonNode original,
                        JsonNode edited) {
        jdbc.update("""
                INSERT INTO review_decision (id, finding_id, decision, reviewer, comment, original_value, edited_value)
                VALUES (?, ?, ?, ?, ?, ?::jsonb, ?::jsonb)
                """, UUID.randomUUID(), findingId, decision, reviewer, comment, json.writeValueAsString(original),
                edited == null ? null : json.writeValueAsString(edited));
    }

    List<String> roles() {
        return jdbc.queryForList("SELECT name FROM organizational_role ORDER BY name", String.class);
    }

    List<Control> controls() {
        return jdbc.query("SELECT * FROM control ORDER BY id", CONTROL);
    }

    Map<String, Object> summary() {
        return Map.of(
                "documents", counts("SELECT processing_status, count(*) FROM regulatory_document_version GROUP BY 1"),
                "obligations", counts("""
                        SELECT COALESCE(coverage_status, 'NOT_ASSESSED'), count(*) FROM obligation GROUP BY 1
                        """),
                "findingsByStatus", counts("SELECT status, count(*) FROM finding GROUP BY 1"),
                "findingsBySeverity", counts("SELECT severity, count(*) FROM finding GROUP BY 1"));
    }

    private List<Count> counts(String sql) {
        return jdbc.query(sql + " ORDER BY 1", (rs, row) -> new Count(rs.getString(1), rs.getLong(2)));
    }

    private JsonNode tree(String value) {
        return value == null ? null : json.readTree(value);
    }
}
