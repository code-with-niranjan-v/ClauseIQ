package com.example.clauseiq_backend;

import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
class WebConfig implements WebMvcConfigurer {
    private static final Logger log = LoggerFactory.getLogger(WebConfig.class);
    private final String[] origins;

    WebConfig(@Value("${clauseiq.cors-allowed-origins}") String[] origins) {
        this.origins = origins;
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**").allowedOrigins(origins).allowedMethods("GET", "POST");
    }

    /** Every API error has the same JSON shape: status, error and message. */
    @RestControllerAdvice
    static class Errors {
        @ExceptionHandler(ResponseStatusException.class)
        ResponseEntity<Map<String, Object>> status(ResponseStatusException e) {
            HttpStatus status = HttpStatus.valueOf(e.getStatusCode().value());
            return body(status, e.getReason() == null ? status.getReasonPhrase() : e.getReason());
        }

        @ExceptionHandler({HttpMessageNotReadableException.class, MethodArgumentTypeMismatchException.class})
        ResponseEntity<Map<String, Object>> badRequest(Exception e) {
            return body(HttpStatus.BAD_REQUEST, "The request body or an identifier is not valid");
        }

        /** The worker creates the tables this API reads. Until it has started once, they do not exist. */
        @ExceptionHandler(BadSqlGrammarException.class)
        ResponseEntity<Map<String, Object>> badSql(BadSqlGrammarException e) {
            boolean missingTable = "42P01".equals(e.getSQLException().getSQLState());
            HttpStatus status = missingTable ? HttpStatus.SERVICE_UNAVAILABLE : HttpStatus.INTERNAL_SERVER_ERROR;
            String message = missingTable
                    ? "The ingestion worker has not created its tables yet. Start circular-ingestion first."
                    : "The query failed. See the backend logs.";
            if (!missingTable) {
                log.error("Query failed", e);
            }
            return body(status, message);
        }

        private static ResponseEntity<Map<String, Object>> body(HttpStatus status, String message) {
            return ResponseEntity.status(status).body(Map.of(
                    "status", status.value(), "error", status.getReasonPhrase(), "message", message));
        }
    }
}
