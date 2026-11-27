package com.example.clauseiq_backend;

import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Read-only lists for the documents, obligations and lookup screens. */
@RestController
@RequestMapping("/api")
class CatalogController {
    private final ApiRepository repository;

    CatalogController(ApiRepository repository) {
        this.repository = repository;
    }

    @GetMapping("/summary")
    Map<String, Object> summary() {
        return repository.summary();
    }

    @GetMapping("/documents")
    List<ApiRepository.Document> documents() {
        return repository.documents();
    }

    @GetMapping("/obligations")
    List<ApiRepository.Obligation> obligations(@RequestParam(required = false) String documentVersionId,
                                               @RequestParam(required = false) String coverageStatus) {
        return repository.obligations(documentVersionId, coverageStatus);
    }

    @GetMapping("/roles")
    List<String> roles() {
        return repository.roles();
    }

    @GetMapping("/controls")
    List<ApiRepository.Control> controls() {
        return repository.controls();
    }
}
