package com.example.circular_scanner;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
class ScannerRepository {
    record Source(String id, String name, String regulator, String listingUrl, String allowedHosts,
                  String detailLinkPattern, boolean enabled, OffsetDateTime lastRunAt,
                  OffsetDateTime lastFinishedAt, OffsetDateTime lastSuccessAt, String lastRunStatus,
                  String lastError, int lastDiscovered, int lastNewDocuments) {}

    record Document(UUID id, UUID documentId, String regulator, String url, String title, String checksum,
                    String bucket, String key, OffsetDateTime createdAt) {}

    record QueueEntry(UUID id, String title, String regulator, OffsetDateTime queuedAt, boolean published) {}

    private static final RowMapper<Source> SOURCE = (rs, row) -> new Source(
            rs.getString("id"), rs.getString("name"), rs.getString("regulator"), rs.getString("listing_url"),
            rs.getString("allowed_hosts"), rs.getString("detail_link_pattern"), rs.getBoolean("enabled"),
            rs.getObject("last_run_at", OffsetDateTime.class), rs.getObject("last_finished_at", OffsetDateTime.class),
            rs.getObject("last_success_at", OffsetDateTime.class), rs.getString("last_run_status"),
            rs.getString("last_error"), rs.getInt("last_discovered"), rs.getInt("last_new_documents"));

    private final JdbcTemplate jdbc;

    ScannerRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    List<Source> sources() {
        return jdbc.query("SELECT * FROM regulatory_source ORDER BY id", SOURCE);
    }

    Optional<Source> source(String id) {
        return jdbc.query("SELECT * FROM regulatory_source WHERE id = ?", SOURCE, id).stream().findFirst();
    }

    void started(String id) {
        jdbc.update("""
                UPDATE regulatory_source SET last_run_at = now(), last_finished_at = NULL,
                    last_run_status = 'RUNNING', last_error = NULL, last_discovered = 0, last_new_documents = 0
                WHERE id = ?
                """, id);
    }

    void finished(String id, String status, String error, int discovered, int added) {
        jdbc.update("""
                UPDATE regulatory_source SET last_finished_at = now(), last_run_status = ?,
                    last_success_at = CASE WHEN ? = 'SUCCESS' THEN now() ELSE last_success_at END,
                    last_error = ?, last_discovered = ?, last_new_documents = ?
                WHERE id = ?
                """, status, status, error, discovered, added, id);
    }

    boolean known(String source, String checksum) {
        return Boolean.TRUE.equals(jdbc.queryForObject("""
                SELECT EXISTS (SELECT 1 FROM scanned_document WHERE source_id = ? AND checksum = ?)
                """, Boolean.class, source, checksum));
    }

    boolean requeueUpload(String source, String checksum, OffsetDateTime cutoff) {
        return jdbc.update("""
                UPDATE scanned_document SET requeued_at = clock_timestamp(), published_at = NULL
                WHERE source_id = ? AND checksum = ?
                  AND COALESCE(requeued_at, created_at) <= ?
                """, source, checksum, cutoff) > 0;
    }

    int nextVersion(UUID documentId) {
        return jdbc.queryForObject("""
                SELECT COALESCE(MAX(version_number), 0) + 1 FROM scanned_document WHERE document_id = ?
                """, Integer.class, documentId);
    }

    void insert(UUID id, UUID documentId, int version, String source, String url, String title,
                String checksum, String bucket, String key) {
        jdbc.update("""
                INSERT INTO scanned_document
                    (id, document_id, version_number, source_id, source_url, title, checksum, object_bucket, object_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, id, documentId, version, source, url, title, checksum, bucket, key);
    }

    Optional<Document> nextPending() {
        return jdbc.query("""
                SELECT d.*, s.regulator, COALESCE(d.requeued_at, d.created_at) AS queued_at
                FROM scanned_document d JOIN regulatory_source s ON d.source_id = s.id
                WHERE d.published_at IS NULL ORDER BY queued_at, d.id LIMIT 1 FOR UPDATE OF d SKIP LOCKED
                """, (rs, row) -> new Document(rs.getObject("id", UUID.class),
                rs.getObject("document_id", UUID.class), rs.getString("regulator"),
                rs.getString("source_url"), rs.getString("title"), rs.getString("checksum"),
                rs.getString("object_bucket"), rs.getString("object_key"),
                rs.getObject("queued_at", OffsetDateTime.class))).stream().findFirst();
    }

    List<QueueEntry> queueEntries() {
        return jdbc.query("""
                SELECT d.id, d.title, s.regulator, COALESCE(d.requeued_at, d.created_at) AS queued_at,
                       d.published_at IS NOT NULL AS published
                FROM scanned_document d JOIN regulatory_source s ON s.id = d.source_id
                ORDER BY queued_at, d.id
                """, (rs, row) -> new QueueEntry(rs.getObject("id", UUID.class), rs.getString("title"),
                rs.getString("regulator"), rs.getObject("queued_at", OffsetDateTime.class),
                rs.getBoolean("published")));
    }

    void published(UUID id) {
        jdbc.update("UPDATE scanned_document SET published_at = now() WHERE id = ?", id);
    }
}
