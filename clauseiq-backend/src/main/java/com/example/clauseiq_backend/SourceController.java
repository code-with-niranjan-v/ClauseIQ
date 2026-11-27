package com.example.clauseiq_backend;

import java.net.http.HttpClient;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;

/**
 * Source administration. circular-scanner owns the sources and runs the scans, so these
 * endpoints forward to it. The frontend then needs only this backend's address.
 */
@RestController
@RequestMapping("/api/admin/sources")
class SourceController {
    private final RestClient scanner;

    SourceController(@Value("${clauseiq.scanner-url}") String scannerUrl) {
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

    @PostMapping("/{id}/scan")
    ResponseEntity<String> scan(@PathVariable String id) {
        return forward(scanner.post().uri("/api/admin/sources/{id}/scan", id));
    }

    private static ResponseEntity<String> forward(RestClient.RequestHeadersSpec<?> request) {
        try {
            String body = request.retrieve().body(String.class);
            return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(body);
        } catch (RestClientResponseException e) {
            // Unknown source (404), disabled or already running (409).
            String message = switch (e.getStatusCode().value()) {
                case 404 -> "Unknown source";
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
