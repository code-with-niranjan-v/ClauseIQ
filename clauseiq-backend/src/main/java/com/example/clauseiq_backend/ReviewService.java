package com.example.clauseiq_backend;

import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** Accept, edit or reject a finding. Each decision is recorded with the values it replaced. */
@Service
class ReviewService {
    record Review(String reviewer, String comment) {}

    record Edit(String reviewer, String comment, String title, String severity, String draftPolicyText,
                String recommendedAction, String assignedRole, String suggestedDeadline,
                List<String> requiredEvidence) {}

    private static final Set<String> SEVERITIES = Set.of("HIGH", "MEDIUM", "LOW");

    private final ApiRepository repository;
    private final ObjectMapper json;

    ReviewService(ApiRepository repository, ObjectMapper json) {
        this.repository = repository;
        this.json = json;
    }

    @Transactional
    ApiRepository.FindingDetail approve(UUID id, Review review) {
        var reviewer = reviewer(review == null ? null : review.reviewer());
        var before = claim(id, "APPROVED");
        repository.recordDecision(id, "APPROVED", reviewer, blankToNull(review.comment()), snapshot(before), null);
        return repository.finding(id).orElseThrow();
    }

    @Transactional
    ApiRepository.FindingDetail reject(UUID id, Review review) {
        var reviewer = reviewer(review == null ? null : review.reviewer());
        if (blankToNull(review.comment()) == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "comment is required to reject a finding");
        }
        var before = claim(id, "REJECTED");
        repository.recordDecision(id, "REJECTED", reviewer, review.comment().strip(), snapshot(before), null);
        return repository.finding(id).orElseThrow();
    }

    @Transactional
    ApiRepository.FindingDetail editAndApprove(UUID id, Edit edit) {
        var reviewer = reviewer(edit == null ? null : edit.reviewer());
        String severity = blankToNull(edit.severity());
        if (severity != null && !SEVERITIES.contains(severity)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "severity must be HIGH, MEDIUM or LOW");
        }
        // A reviewer can reassign the finding, but only to a role that exists.
        String role = blankToNull(edit.assignedRole());
        if (role != null && !repository.roles().contains(role)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "assignedRole is not in the role directory");
        }
        ObjectNode edited = json.createObjectNode();
        put(edited, "title", edit.title());
        put(edited, "severity", severity);
        put(edited, "draftPolicyText", edit.draftPolicyText());
        put(edited, "recommendedAction", edit.recommendedAction());
        put(edited, "assignedRole", role);
        put(edited, "suggestedDeadline", edit.suggestedDeadline());
        if (edit.requiredEvidence() != null) {
            edited.set("requiredEvidence", json.valueToTree(
                    edit.requiredEvidence().stream().filter(item -> item != null && !item.isBlank())
                            .map(String::strip).toList()));
        }
        if (edited.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "No edited fields were sent. Use the approve endpoint to accept the finding unchanged.");
        }
        var before = claim(id, "APPROVED_WITH_CHANGES");
        if (before.recommendation() == null && edited.propertyNames().stream()
                .anyMatch(name -> !name.equals("title") && !name.equals("severity"))) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "This finding has no recommendation to edit");
        }
        repository.updateFinding(id, text(edited, "title"), text(edited, "severity"));
        repository.updateRecommendation(id, text(edited, "draftPolicyText"), text(edited, "recommendedAction"),
                text(edited, "assignedRole"), text(edited, "suggestedDeadline"),
                edited.has("requiredEvidence") ? json.writeValueAsString(edited.get("requiredEvidence")) : null);
        repository.recordDecision(id, "APPROVED_WITH_CHANGES", reviewer, blankToNull(edit.comment()),
                snapshot(before), edited);
        return repository.finding(id).orElseThrow();
    }

    /** Loads the finding and moves it out of PENDING_REVIEW, or fails if it is missing or already decided. */
    private ApiRepository.FindingDetail claim(UUID id, String status) {
        var before = repository.finding(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown finding"));
        if (!repository.decide(id, status)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "This finding has already been reviewed");
        }
        return before;
    }

    private ObjectNode snapshot(ApiRepository.FindingDetail finding) {
        ObjectNode node = json.createObjectNode();
        node.put("title", finding.title());
        node.put("severity", finding.severity());
        node.put("status", finding.status());
        if (finding.recommendation() != null) {
            node.setAll((ObjectNode) json.valueToTree(finding.recommendation()));
        }
        return node;
    }

    private static String reviewer(String reviewer) {
        if (blankToNull(reviewer) == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "reviewer is required");
        }
        return reviewer.strip();
    }

    private static void put(ObjectNode node, String name, String value) {
        if (blankToNull(value) != null) {
            node.put(name, value.strip());
        }
    }

    private static String text(ObjectNode node, String name) {
        return node.has(name) ? node.get(name).asString() : null;
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value;
    }
}
