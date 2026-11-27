package com.example.circular_scanner;

import java.sql.SQLException;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
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
        return repository.sources();
    }

    @PostMapping("/{id}/scan")
    ScannerRepository.Source scan(@PathVariable String id) throws SQLException {
        var source = repository.source(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown source"));
        try {
            return scanner.scan(source);
        } catch (ScanService.AlreadyRunning e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Source scan already running");
        } catch (ScanService.Disabled e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Source is disabled");
        }
    }
}
