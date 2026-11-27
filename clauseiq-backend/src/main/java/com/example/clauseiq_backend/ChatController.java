package com.example.clauseiq_backend;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

/** Employee policy Q&A. The ingestion worker answers from approved policy text only. */
@RestController
@RequestMapping("/api/chat")
class ChatController {
    record Question(String question) {}

    private static final int MAX_QUESTION = 1000;

    private final RestClient ingestion;
    private final ObjectMapper json;

    ChatController(@Value("${clauseiq.ingestion-url}") String url, ObjectMapper json) {
        var factory = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
                        .connectTimeout(Duration.ofSeconds(5)).build());
        // One embedding and one model call, each with retries.
        factory.setReadTimeout(Duration.ofSeconds(90));
        this.ingestion = RestClient.builder().baseUrl(url).requestFactory(factory).build();
        this.json = json;
    }

    @PostMapping
    ResponseEntity<String> ask(@RequestBody Question question) {
        String text = question == null || question.question() == null ? "" : question.question().strip();
        if (text.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Ask a question.");
        }
        if (text.length() > MAX_QUESTION) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Keep the question under " + MAX_QUESTION + " characters.");
        }
        try {
            String answer = ingestion.post().uri("/chat").contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of("question", text)).retrieve().body(String.class);
            return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(answer);
        } catch (RestClientResponseException e) {
            int status = e.getStatusCode().value();
            HttpStatus mapped = status == 400 ? HttpStatus.BAD_REQUEST
                    : status == 503 ? HttpStatus.SERVICE_UNAVAILABLE : HttpStatus.BAD_GATEWAY;
            throw new ResponseStatusException(mapped, detail(e.getResponseBodyAsString()));
        } catch (RestClientException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "The ingestion worker is not reachable.");
        }
    }

    /** FastAPI errors carry {"detail": "..."}. */
    private String detail(String body) {
        try {
            var node = json.readTree(body).path("detail");
            if (node.isString() && !node.asString().isBlank()) {
                return node.asString();
            }
        } catch (RuntimeException e) {
            // Not JSON.
        }
        return "Policy Q&A failed.";
    }
}
