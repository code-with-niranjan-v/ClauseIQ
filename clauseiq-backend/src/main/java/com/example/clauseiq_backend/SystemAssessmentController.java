package com.example.clauseiq_backend;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

/** Compare a bank's SRE document, architecture diagram and ER diagram with circular obligations. */
@RestController
@RequestMapping("/api/system-assessments")
class SystemAssessmentController {
    private final RestClient ingestion;
    private final ObjectMapper json;

    SystemAssessmentController(@Value("${clauseiq.ingestion-url}") String url, ObjectMapper json) {
        var factory = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
                        .connectTimeout(Duration.ofSeconds(5)).build());
        factory.setReadTimeout(Duration.ofSeconds(60));
        this.ingestion = RestClient.builder().baseUrl(url).requestFactory(factory).build();
        this.json = json;
    }

    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    ResponseEntity<String> create(@RequestParam(defaultValue = "") String name,
                                  @RequestParam(required = false) MultipartFile sre,
                                  @RequestParam(required = false) MultipartFile architecture,
                                  @RequestParam(required = false) MultipartFile er) {
        var parts = new LinkedMultiValueMap<String, Object>();
        parts.add("name", name);
        add(parts, "sre", sre);
        add(parts, "architecture", architecture);
        add(parts, "er", er);
        if (parts.size() == 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Upload at least one of the SRE document, architecture diagram or ER diagram.");
        }
        return forward(ingestion.post().uri("/system-assessments").contentType(MediaType.MULTIPART_FORM_DATA)
                .body(parts), HttpStatus.ACCEPTED);
    }

    @GetMapping
    ResponseEntity<String> list() {
        return forward(ingestion.get().uri("/system-assessments"), HttpStatus.OK);
    }

    @GetMapping("/{id}")
    ResponseEntity<String> get(@PathVariable UUID id) {
        return forward(ingestion.get().uri("/system-assessments/{id}", id), HttpStatus.OK);
    }

    private static void add(LinkedMultiValueMap<String, Object> parts, String name, MultipartFile file) {
        if (file != null && !file.isEmpty()) {
            parts.add(name, file.getResource());
        }
    }

    private ResponseEntity<String> forward(RestClient.RequestHeadersSpec<?> request, HttpStatus success) {
        try {
            return ResponseEntity.status(success).contentType(MediaType.APPLICATION_JSON)
                    .body(request.retrieve().body(String.class));
        } catch (RestClientResponseException e) {
            int status = e.getStatusCode().value();
            HttpStatus mapped = switch (status) {
                case 400, 404, 413 -> HttpStatus.valueOf(status);
                case 503 -> HttpStatus.SERVICE_UNAVAILABLE;
                default -> HttpStatus.BAD_GATEWAY;
            };
            throw new ResponseStatusException(mapped, detail(e.getResponseBodyAsString()));
        } catch (RestClientException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "The ingestion worker is not reachable.");
        }
    }

    private String detail(String body) {
        try {
            var node = json.readTree(body).path("detail");
            if (node.isString() && !node.asString().isBlank()) {
                return node.asString();
            }
        } catch (RuntimeException e) {
            // Not JSON.
        }
        return "The system assessment request failed.";
    }
}
