package com.example.circular_scanner;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.HttpURLConnection;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.springframework.stereotype.Component;

@Component
class PublicationClient {
    record Candidate(URI uri, String title) {}
    record Discovery(List<Candidate> candidates, int pageFailures) {}
    record Response(URI uri, byte[] bytes) {}
    static class InvalidPdfResponse extends IOException {
        InvalidPdfResponse() {
            super("Document response did not start with a PDF header");
        }
    }

    private static final int MAX_HTML = 4 * 1024 * 1024;
    static final int MAX_PDF = 30 * 1024 * 1024;
    private static final int MAX_DETAIL_PAGES = 40;
    private static final int MAX_DOCUMENTS = 100;
    private static final Pattern PDF_URL = Pattern.compile("(?i)[.]pdf(?:$|[/?#& ])");
    private static final byte[] PDF_HEADER = "%PDF-".getBytes(StandardCharsets.US_ASCII);

    Discovery discover(ScannerRepository.Source source) throws IOException, InterruptedException {
        Set<String> hosts = hosts(source);
        Response page = fetch(URI.create(source.listingUrl()), hosts, MAX_HTML);
        if (isPdfBody(page.bytes())) {
            return new Discovery(List.of(new Candidate(page.uri(), source.name())), 0);
        }
        Map<URI, Candidate> pdfs = new LinkedHashMap<>();
        Map<URI, String> details = new LinkedHashMap<>();
        Pattern detailPattern = Pattern.compile(source.detailLinkPattern());
        Document listing = html(page);
        collectPdfs(listing, hosts, pdfs, "");
        for (Element link : listing.select("a[href]")) {
            URI uri = linkUri(link, "href", hosts);
            if (uri != null && !uri.equals(page.uri()) && !isPdf(uri)
                    && detailPattern.matcher(uri.toString()).find()) {
                details.putIfAbsent(uri, link.text().strip());
            }
        }

        int failures = 0;
        for (var detail : details.entrySet().stream().limit(MAX_DETAIL_PAGES).toList()) {
            try {
                Response response = fetch(detail.getKey(), hosts, MAX_HTML);
                if (isPdfBody(response.bytes())) {
                    String title = detail.getValue().isBlank() ? response.uri().getPath() : detail.getValue();
                    pdfs.putIfAbsent(response.uri(), new Candidate(response.uri(), title));
                } else {
                    collectPdfs(html(response), hosts, pdfs, detail.getValue());
                }
            } catch (IOException e) {
                failures++;
            }
        }
        return new Discovery(pdfs.values().stream().limit(MAX_DOCUMENTS).toList(), failures);
    }

    byte[] download(ScannerRepository.Source source, Candidate candidate) throws IOException, InterruptedException {
        byte[] bytes = fetch(candidate.uri(), hosts(source), MAX_PDF).bytes();
        if (!isPdfBody(bytes)) {
            throw new InvalidPdfResponse();
        }
        return bytes;
    }

    static boolean isPdfBody(byte[] bytes) {
        return bytes.length >= PDF_HEADER.length && Arrays.mismatch(bytes, 0, PDF_HEADER.length,
                PDF_HEADER, 0, PDF_HEADER.length) == -1;
    }

    private static Document html(Response response) throws IOException {
        return Jsoup.parse(new java.io.ByteArrayInputStream(response.bytes()), null, response.uri().toString());
    }

    private static void collectPdfs(Document page, Set<String> hosts, Map<URI, Candidate> pdfs, String context) {
        for (Element link : page.select("a[href], iframe[src], embed[src], object[data]")) {
            String attribute = switch (link.normalName()) {
                case "a" -> "href";
                case "object" -> "data";
                default -> "src";
            };
            URI uri = linkUri(link, attribute, hosts);
            if (uri == null || !isPdf(uri)) {
                continue;
            }
            String title = link.text().strip();
            if (title.isEmpty() || title.matches("(?i)(pdf|download(?: pdf)?|view(?: pdf)?|click here)")) {
                title = context.isBlank() ? page.title() : context;
            }
            pdfs.putIfAbsent(uri, new Candidate(uri, title.isBlank() ? uri.getPath() : title));
        }
    }

    private static URI linkUri(Element link, String attribute, Set<String> hosts) {
        try {
            URI uri = URI.create(link.absUrl(attribute).split("#", 2)[0]).normalize();
            return allowed(uri, hosts) ? uri : null;
        } catch (IllegalArgumentException e) {
            return null;
        }
    }

    private static boolean isPdf(URI uri) {
        return PDF_URL.matcher(uri.getPath()).find()
                || (uri.getQuery() != null && PDF_URL.matcher(uri.getQuery()).find());
    }

    private static Set<String> hosts(ScannerRepository.Source source) {
        return Arrays.stream(source.allowedHosts().split(",")).map(String::strip)
                .map(host -> host.toLowerCase(Locale.ROOT)).collect(Collectors.toUnmodifiableSet());
    }

    static boolean isAllowedPdf(ScannerRepository.Source source, URI uri) {
        return allowed(uri, hosts(source)) && isPdf(uri);
    }

    private static boolean allowed(URI uri, Set<String> hosts) {
        return "https".equalsIgnoreCase(uri.getScheme()) && uri.getHost() != null
                && hosts.contains(uri.getHost().toLowerCase(Locale.ROOT))
                && uri.getRawUserInfo() == null && (uri.getPort() == -1 || uri.getPort() == 443);
    }

    Response fetch(URI uri, Set<String> hosts, int limit) throws IOException, InterruptedException {
        for (int redirects = 0; redirects <= 5; redirects++) {
            if (!allowed(uri, hosts)) {
                throw new IOException("Publication host is outside the configured HTTPS allowlist");
            }
            if (Thread.currentThread().isInterrupted()) {
                throw new InterruptedException("Publication request interrupted");
            }
            var connection = (HttpURLConnection) uri.toURL().openConnection();
            connection.setConnectTimeout(10_000);
            connection.setReadTimeout(20_000);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("User-Agent", "ClauseIQ-CircularScanner/1.0");
            try {
                int status = connection.getResponseCode();
                if (status == 301 || status == 302 || status == 303 || status == 307 || status == 308) {
                    String location = connection.getHeaderField("Location");
                    if (location == null) {
                        throw new IOException("Redirect missing Location");
                    }
                    uri = uri.resolve(location);
                    continue;
                }
                if (status != 200) {
                    throw new IOException("Publication host " + uri.getHost() + " returned HTTP " + status);
                }
                try (InputStream stream = connection.getInputStream()) {
                    byte[] bytes = stream.readNBytes(limit + 1);
                    if (bytes.length > limit) {
                        throw new IOException("Publication response exceeded " + limit + " bytes");
                    }
                    return new Response(uri, bytes);
                }
            } finally {
                connection.disconnect();
            }
        }
        throw new IOException("Too many redirects from publication host");
    }
}
