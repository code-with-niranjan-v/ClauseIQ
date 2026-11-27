package com.example.clauseiq_backend;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

/**
 * Circular changes, extraction quality, live database scans and board reports. The ingestion worker does
 * the work; this controller applies sign-in and roles (see SecurityConfig) and passes the signed-in user on.
 */
@RestController
class GovernanceController {
    record LinkDecision(Boolean confirm) {}

    record ScanRequest(String target) {}

    private static final Set<String> FORMATS = Set.of("pdf", "docx");

    private final RestClient ingestion;
    private final ObjectMapper json;
    private final UserStore users;

    GovernanceController(@Value("${clauseiq.ingestion-url}") String url, ObjectMapper json, UserStore users) {
        var factory = new JdkClientHttpRequestFactory(HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(5)).build());
        // A data scan can include one model call; a diff embeds both circulars' obligations.
        factory.setReadTimeout(Duration.ofSeconds(120));
        this.ingestion = RestClient.builder().baseUrl(url).requestFactory(factory).build();
        this.json = json;
        this.users = users;
    }

    // ------------------------------------------------------------ circular changes

    @GetMapping("/api/lineage/links")
    ResponseEntity<String> links() {
        return forward(ingestion.get().uri("/lineage/links"));
    }

    @PostMapping("/api/lineage/refresh")
    ResponseEntity<String> refresh() {
        return forward(ingestion.post().uri("/lineage/refresh"));
    }

    @PostMapping("/api/lineage/links/{id}/decision")
    ResponseEntity<String> decide(@PathVariable UUID id, @RequestBody LinkDecision decision) {
        if (decision == null || decision.confirm() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Say whether to confirm the link.");
        }
        return forward(ingestion.post().uri("/lineage/links/{id}/decision", id).header("X-ClauseIQ-User", user())
                .contentType(MediaType.APPLICATION_JSON).body(Map.of("confirm", decision.confirm())));
    }

    @GetMapping("/api/lineage/links/{id}/diff")
    ResponseEntity<String> diff(@PathVariable UUID id) {
        return forward(ingestion.get().uri("/lineage/links/{id}/diff", id));
    }

    // ------------------------------------------------------------ extraction quality

    @GetMapping("/api/quality")
    ResponseEntity<String> quality() {
        return forward(ingestion.get().uri("/quality"));
    }

    // ------------------------------------------------------------ live database scans

    @GetMapping("/api/data-scans/targets")
    ResponseEntity<String> targets() {
        return forward(ingestion.get().uri("/data-scans/targets"));
    }

    @GetMapping("/api/data-scans")
    ResponseEntity<String> scans() {
        return forward(ingestion.get().uri("/data-scans"));
    }

    @GetMapping("/api/data-scans/{id}")
    ResponseEntity<String> scan(@PathVariable UUID id) {
        return forward(ingestion.get().uri("/data-scans/{id}", id));
    }

    @PostMapping("/api/data-scans")
    ResponseEntity<String> runScan(@RequestBody ScanRequest request) {
        if (request == null || request.target() == null || request.target().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Choose a configured scan target.");
        }
        return forward(ingestion.post().uri("/data-scans").header("X-ClauseIQ-User", user())
                .contentType(MediaType.APPLICATION_JSON).body(Map.of("target", request.target())));
    }

    // ------------------------------------------------------------ board reports

    @GetMapping("/api/reports/posture.{format}")
    ResponseEntity<byte[]> postureReport(@PathVariable String format) {
        return download(format, "/reports/posture." + format);
    }

    @GetMapping("/api/reports/system-assessments/{id}.{format}")
    ResponseEntity<byte[]> systemReport(@PathVariable UUID id, @PathVariable String format) {
        return download(format, "/reports/system-assessments/" + id + "." + format);
    }

    private ResponseEntity<byte[]> download(String format, String path) {
        if (!FORMATS.contains(format)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Reports are available as pdf or docx.");
        }
        try {
            var response = ingestion.get().uri(path).header("X-ClauseIQ-User", user()).retrieve().toEntity(byte[].class);
            var headers = new HttpHeaders();
            headers.setContentType(response.getHeaders().getContentType());
            headers.set(HttpHeaders.CONTENT_DISPOSITION, response.getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION));
            headers.setCacheControl("no-store");
            return new ResponseEntity<>(response.getBody(), headers, HttpStatus.OK);
        } catch (RestClientResponseException e) {
            throw error(e);
        } catch (RestClientException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "The ingestion worker is not reachable.");
        }
    }

    private String user() {
        return users.current().signature();
    }

    private ResponseEntity<String> forward(RestClient.RequestHeadersSpec<?> request) {
        try {
            return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(request.retrieve().body(String.class));
        } catch (RestClientResponseException e) {
            throw error(e);
        } catch (RestClientException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "The ingestion worker is not reachable.");
        }
    }

    private ResponseStatusException error(RestClientResponseException e) {
        int status = e.getStatusCode().value();
        HttpStatus mapped = switch (status) {
            case 400, 404, 409 -> HttpStatus.valueOf(status);
            case 503 -> HttpStatus.SERVICE_UNAVAILABLE;
            default -> HttpStatus.BAD_GATEWAY;
        };
        String message = "The request to the ingestion worker failed.";
        try {
            var node = json.readTree(e.getResponseBodyAsString()).path("detail");
            if (node.isString() && !node.asString().isBlank()) {
                message = node.asString();
            }
        } catch (RuntimeException ignored) {
            // Not JSON.
        }
        return new ResponseStatusException(mapped, message);
    }
}
