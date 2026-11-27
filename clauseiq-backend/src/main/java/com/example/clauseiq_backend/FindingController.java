package com.example.clauseiq_backend;

import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/findings")
class FindingController {
    private final ApiRepository repository;
    private final ReviewService reviews;

    FindingController(ApiRepository repository, ReviewService reviews) {
        this.repository = repository;
        this.reviews = reviews;
    }

    @GetMapping
    List<ApiRepository.FindingSummary> findings(@RequestParam(required = false) String status,
                                                @RequestParam(required = false) String documentVersionId) {
        return repository.findings(status, documentVersionId);
    }

    @GetMapping("/{id}")
    ApiRepository.FindingDetail finding(@PathVariable UUID id) {
        return repository.finding(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown finding"));
    }

    @PostMapping("/{id}/approve")
    ApiRepository.FindingDetail approve(@PathVariable UUID id, @RequestBody ReviewService.Review review) {
        return reviews.approve(id, review);
    }

    @PostMapping("/{id}/edit-and-approve")
    ApiRepository.FindingDetail editAndApprove(@PathVariable UUID id, @RequestBody ReviewService.Edit edit) {
        return reviews.editAndApprove(id, edit);
    }

    @PostMapping("/{id}/reject")
    ApiRepository.FindingDetail reject(@PathVariable UUID id, @RequestBody ReviewService.Review review) {
        return reviews.reject(id, review);
    }
}
