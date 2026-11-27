package com.example.clauseiq_backend;

import java.net.http.HttpClient;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/admin/processing")
class ProcessingController {
    record Setting(Boolean paused) {}

    private final RestClient ingestion;

    ProcessingController(@Value("${clauseiq.ingestion-url}") String url) {
        var factory = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
                        .connectTimeout(Duration.ofSeconds(5)).build());
        factory.setReadTimeout(Duration.ofSeconds(15));
        ingestion = RestClient.builder().baseUrl(url).requestFactory(factory).build();
    }

    @GetMapping
    ResponseEntity<String> status() {
        return forward(ingestion.get().uri("/processing"));
    }

    @PutMapping
    ResponseEntity<String> update(@RequestBody Setting setting) {
        if (setting.paused() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Specify whether processing should be paused");
        }
        return forward(ingestion.put().uri("/processing").contentType(MediaType.APPLICATION_JSON).body(setting));
    }

    @PostMapping("/clear")
    ResponseEntity<String> clear() {
        return forward(ingestion.post().uri("/processing/clear"));
    }

    private static ResponseEntity<String> forward(RestClient.RequestHeadersSpec<?> request) {
        try {
            return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(request.retrieve().body(String.class));
        } catch (RestClientResponseException e) {
            if (e.getStatusCode().value() == 409) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "The worker is disabled or a queue clear is in progress");
            }
            if (e.getStatusCode().value() == 503) {
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "The worker could not save the queue change");
            }
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "The ingestion worker returned an error");
        } catch (RestClientException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "The ingestion worker is not reachable");
        }
    }
}
