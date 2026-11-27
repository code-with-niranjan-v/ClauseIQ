package com.example.circular_scanner;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.HexFormat;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import javax.sql.DataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

@Service
class ScanService {
    static class AlreadyRunning extends RuntimeException {}
    static class Disabled extends RuntimeException {}
    private static final Logger log = LoggerFactory.getLogger(ScanService.class);

    private final ScannerRepository repository;
    private final PublicationClient publications;
    private final PdfStore store;
    private final DataSource dataSource;
    private final Set<String> active = ConcurrentHashMap.newKeySet();

    ScanService(ScannerRepository repository, PublicationClient publications, PdfStore store, DataSource dataSource) {
        this.repository = repository;
        this.publications = publications;
        this.store = store;
        this.dataSource = dataSource;
    }

    @Scheduled(cron = "${scanner.cron}", zone = "${scanner.zone}")
    void daily() {
        for (var source : repository.sources()) {
            if (source.enabled()) {
                try {
                    scan(source);
                } catch (AlreadyRunning e) {
                    log.info("Skipping scheduled scan for {} because a scan is running", source.id());
                } catch (Exception e) {
                    log.error("Could not run scheduled scan for {}", source.id(), e);
                }
            }
        }
    }

    ScannerRepository.Source scan(ScannerRepository.Source source) throws SQLException {
        requireEnabled(source);
        return withSourceLock(source, () -> {
            run(source);
            return repository.source(source.id()).orElseThrow();
        });
    }

    boolean importPdf(ScannerRepository.Source source, PublicationClient.Candidate candidate, byte[] pdf)
            throws SQLException {
        requireEnabled(source);
        return withSourceLock(source, () -> ingest(source, candidate, pdf));
    }

    boolean uploadPdf(ScannerRepository.Source source, String title, byte[] pdf, OffsetDateTime clearedBefore)
            throws SQLException {
        return withSourceLock(source, () -> {
            String hash = checksum(pdf);
            if (clearedBefore != null && repository.requeueUpload(source.id(), hash, clearedBefore)) {
                return true;
            }
            return ingest(source, new PublicationClient.Candidate(null, title), pdf, hash);
        });
    }

    @FunctionalInterface
    private interface SourceOperation<T> {
        T run() throws SQLException;
    }

    private static void requireEnabled(ScannerRepository.Source source) {
        if (!source.enabled()) {
            throw new Disabled();
        }
    }

    private <T> T withSourceLock(ScannerRepository.Source source, SourceOperation<T> operation) throws SQLException {
        if (!active.add(source.id())) {
            throw new AlreadyRunning();
        }
        try (Connection lock = dataSource.getConnection()) {
            if (!tryLock(lock, source.id())) {
                throw new AlreadyRunning();
            }
            try {
                return operation.run();
            } finally {
                try (var statement = lock.prepareStatement("SELECT pg_advisory_unlock(921774, hashtext(?))")) {
                    statement.setString(1, source.id());
                    statement.execute();
                }
            }
        } finally {
            active.remove(source.id());
        }
    }

    private static boolean tryLock(Connection connection, String id) throws SQLException {
        try (var statement = connection.prepareStatement("SELECT pg_try_advisory_lock(921774, hashtext(?))")) {
            statement.setString(1, id);
            try (var result = statement.executeQuery()) {
                result.next();
                return result.getBoolean(1);
            }
        }
    }

    private void run(ScannerRepository.Source source) {
        repository.started(source.id());
        int discovered = 0;
        int added = 0;
        int processed = 0;
        String error = null;
        try {
            var result = publications.discover(source);
            discovered = result.candidates().size();
            if (discovered == 0) {
                error = "No PDF links found. Check the listing URL, site access and parsing rules.";
            } else if (result.pageFailures() > 0) {
                error = "Could not read " + result.pageFailures() + " publication detail page(s).";
            }
            for (var candidate : result.candidates()) {
                try {
                    if (ingest(source, candidate, publications.download(source, candidate))) {
                        added++;
                    }
                    processed++;
                } catch (InterruptedException e) {
                    throw e;
                } catch (PublicationClient.InvalidPdfResponse e) {
                    error = "A download URL returned a response without a PDF header. "
                            + "If it opens in your browser, download the PDF and use the manual import command in the README.";
                    log.warn("Could not process a PDF for {} from {}: {}", source.id(), candidate.uri(), e.getMessage());
                } catch (Exception e) {
                    error = "Could not process one or more PDFs. See scanner logs.";
                    log.warn("Could not process a PDF for {} from {}", source.id(), candidate.uri(), e);
                }
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            error = "Scan was interrupted.";
        } catch (Exception e) {
            error = "Could not read the source. See scanner logs.";
            log.warn("Discovery failed for {}", source.id(), e);
        }
        String status = error == null ? "SUCCESS" : processed > 0 ? "PARTIAL" : "FAILED";
        repository.finished(source.id(), status, error, discovered, added);
    }

    private boolean ingest(ScannerRepository.Source source, PublicationClient.Candidate candidate, byte[] pdf) {
        return ingest(source, candidate, pdf, checksum(pdf));
    }

    private static String checksum(byte[] pdf) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(pdf));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
    }

    private boolean ingest(ScannerRepository.Source source, PublicationClient.Candidate candidate, byte[] pdf, String hash) {
        if (repository.known(source.id(), hash)) {
            return false;
        }
        String url = candidate.uri() == null ? "" : candidate.uri().toString();
        UUID documentId = stableId(source.id(), url.isEmpty() ? hash : url);
        UUID versionId = stableId(source.id(), hash);
        int version = repository.nextVersion(documentId);
        String key = source.regulator() + "/" + documentId + "/version-" + version + "/original.pdf";
        try {
            store.put(key, pdf);
        } catch (Exception e) {
            throw new IllegalStateException("Could not store circular PDF", e);
        }
        repository.insert(versionId, documentId, version, source.id(), url, candidate.title(), hash, store.bucket(), key);
        return true;
    }

    private static UUID stableId(String sourceId, String value) {
        return UUID.nameUUIDFromBytes((sourceId + ":" + value).getBytes(StandardCharsets.UTF_8));
    }
}
