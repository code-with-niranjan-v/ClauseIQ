package com.example.clauseiq_backend;

import java.net.http.HttpClient;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.multipart.MultipartFile;

/**
 * Source administration. circular-scanner owns the sources and runs the scans, so these
 * endpoints forward to it. The frontend then needs only this backend's address.
 */
@RestController
@RequestMapping("/api/admin/sources")
class SourceController {
    record QueueEntry(UUID id, String title, String regulator, OffsetDateTime queuedAt, boolean published,
                      String publicationError) {}
    private record ProcessingAttempt(String status, OffsetDateTime startedAt) {}

    private final RestClient scanner;
    private final JdbcTemplate jdbc;

    SourceController(@Value("${clauseiq.scanner-url}") String scannerUrl, JdbcTemplate jdbc) {
        this.jdbc = jdbc;
        var factory = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build());
        // A manual scan is synchronous in the scanner and can take minutes.
        factory.setReadTimeout(Duration.ofMinutes(10));
        scanner = RestClient.builder().baseUrl(scannerUrl).requestFactory(factory).build();
    }

    @GetMapping
    ResponseEntity<String> sources() {
        return forward(scanner.get().uri("/api/admin/sources"));
    }

    @GetMapping("/queue-entries")
    List<QueueEntry> queueEntries() {
        QueueEntry[] entries;
        try {
            entries = scanner.get().uri("/api/admin/sources/queue-entries").retrieve().body(QueueEntry[].class);
        } catch (ResourceAccessException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "The circular scanner is not reachable");
        } catch (RestClientResponseException e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "The scanner could not list queue entries");
        }
        if (entries == null || entries.length == 0) {
            return List.of();
        }
        var cutoff = jdbc.queryForObject("SELECT (SELECT cleared_before FROM ingestion_queue WHERE id)",
                OffsetDateTime.class);
        var ids = List.of(entries).stream()
                .filter(entry -> cutoff == null || entry.queuedAt().isAfter(cutoff)).toList();
        if (ids.isEmpty()) {
            return List.of();
        }
        var attempts = new HashMap<String, ProcessingAttempt>();
        jdbc.query(connection -> {
            var statement = connection.prepareStatement("""
                    SELECT event_id, status, started_at FROM processed_event WHERE event_id = ANY(?)
                    """);
            statement.setArray(1, connection.createArrayOf("text",
                    ids.stream().map(entry -> entry.id().toString()).toArray(String[]::new)));
            return statement;
        }, rs -> {
            attempts.put(rs.getString("event_id"),
                    new ProcessingAttempt(rs.getString("status"), rs.getObject("started_at", OffsetDateTime.class)));
        });
        return ids.stream().filter(entry -> {
            var attempt = attempts.get(entry.id().toString());
            return attempt == null || (!attempt.status().equals("COMPLETED")
                    && attempt.startedAt().isBefore(entry.queuedAt()));
        }).toList();
    }

    @PostMapping("/{id}/scan")
    ResponseEntity<String> scan(@PathVariable String id) {
        return forward(scanner.post().uri("/api/admin/sources/{id}/scan", id));
    }

    @PostMapping(path = "/upload-pdf", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    ResponseEntity<String> uploadPdf(@RequestParam MultipartFile file,
                                     @RequestParam(required = false)
                                     @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime clearedBefore) {
        var parts = new LinkedMultiValueMap<String, Object>();
        parts.add("file", file.getResource());
        if (clearedBefore != null) {
            parts.add("clearedBefore", clearedBefore.toString());
        }
        return forward(scanner.post().uri("/api/admin/sources/upload-pdf")
                .contentType(MediaType.MULTIPART_FORM_DATA).body(parts));
    }

    private static ResponseEntity<String> forward(RestClient.RequestHeadersSpec<?> request) {
        try {
            String body = request.retrieve().body(String.class);
            return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(body);
        } catch (RestClientResponseException e) {
            // Unknown source (404), disabled or already running (409).
            String message = switch (e.getStatusCode().value()) {
                case 404 -> "Unknown source";
                case 400 -> "Select a valid PDF file";
                case 413 -> "PDF exceeds 30 MiB";
                case 409 -> "The source is disabled or a scan is already running";
                default -> "The scanner returned HTTP " + e.getStatusCode().value();
            };
            int status = e.getStatusCode().is4xxClientError() ? e.getStatusCode().value() : 502;
            throw new ResponseStatusException(HttpStatus.valueOf(status), message);
        } catch (ResourceAccessException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "The circular scanner is not reachable");
        }
    }
}
