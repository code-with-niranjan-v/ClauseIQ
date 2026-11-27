package com.example.circular_scanner;

import java.io.IOException;
import java.net.URI;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/admin/sources")
class ScanController {
    private final ScannerRepository repository;
    private final ScanService scanner;

    ScanController(ScannerRepository repository, ScanService scanner) {
        this.repository = repository;
        this.scanner = scanner;
    }

    @GetMapping
    List<ScannerRepository.Source> sources() {
        return repository.sources().stream().filter(source -> !source.id().equals("uploads")).toList();
    }

    @GetMapping("/queue-entries")
    List<ScannerRepository.QueueEntry> queueEntries() {
        return repository.queueEntries();
    }

    @PostMapping("/{id}/scan")
    ScannerRepository.Source scan(@PathVariable String id) throws SQLException {
        var source = source(id);
        try {
            return scanner.scan(source);
        } catch (ScanService.AlreadyRunning e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Source scan already running");
        } catch (ScanService.Disabled e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Source is disabled");
        }
    }

    @PostMapping(path = "/{id}/import-pdf", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    Map<String, Boolean> importPdf(@PathVariable String id, @RequestParam String url,
                                   @RequestParam String title, @RequestParam MultipartFile file)
            throws IOException, SQLException {
        var source = source(id);
        URI uri;
        try {
            uri = URI.create(url).normalize();
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid publication URL");
        }
        if (!PublicationClient.isAllowedPdf(source, uri) || uri.getFragment() != null || title.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "An official PDF URL and title are required");
        }
        byte[] pdf = readPdf(file);
        try {
            return Map.of("added", scanner.importPdf(source, new PublicationClient.Candidate(uri, title.strip()), pdf));
        } catch (ScanService.AlreadyRunning | ScanService.Disabled e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "The source is disabled or busy");
        }
    }

    @PostMapping(path = "/upload-pdf", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    Map<String, Boolean> uploadPdf(@RequestParam MultipartFile file,
                                   @RequestParam(required = false)
                                   @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) OffsetDateTime clearedBefore)
            throws IOException, SQLException {
        byte[] pdf = readPdf(file);
        String original = file.getOriginalFilename();
        String title = original == null ? "" : original.replace('\\', '/');
        title = title.substring(title.lastIndexOf('/') + 1).strip();
        try {
            return Map.of("added", scanner.uploadPdf(source("uploads"),
                    title.isBlank() ? "Uploaded PDF" : title, pdf, clearedBefore));
        } catch (ScanService.AlreadyRunning e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Another PDF upload is being saved. Try again.");
        }
    }

    private static byte[] readPdf(MultipartFile file) throws IOException {
        if (file.getSize() > PublicationClient.MAX_PDF) {
            throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "PDF exceeds 30 MiB");
        }
        byte[] pdf = file.getBytes();
        if (!PublicationClient.isPdfBody(pdf)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "File did not start with a PDF header");
        }
        return pdf;
    }

    private ScannerRepository.Source source(String id) {
        return repository.source(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown source"));
    }
}
