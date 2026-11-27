package com.example.circular_scanner;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.HttpURLConnection;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
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
import org.jsoup.parser.Parser;
import org.jsoup.safety.Safelist;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@Component
class PublicationClient {
    @Value("${scanner.browser-fallback:false}")
    private boolean browserFallback;

    record WebVersion(URI uri, String html) {}
    record Candidate(URI uri, String title, WebVersion webVersion) {
        Candidate(URI uri, String title) {
            this(uri, title, null);
        }
    }
    record Discovery(List<Candidate> candidates, int pageFailures) {}
    record Response(URI uri, byte[] bytes) {}
    static class InvalidPdfResponse extends IOException {
        InvalidPdfResponse() {
            this("Document response did not start with a PDF header");
        }

        InvalidPdfResponse(String message) {
            super(message);
        }
    }
    /** Attached to a download failure when the browser fallback was tried and also failed. */
    static class BrowserFailure extends IOException {
        BrowserFailure(Throwable cause) {
            super("Browser fallback failed", cause);
        }
    }

    private static final JsonMapper JSON = JsonMapper.builder().build();

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
        if (isJsonBody(page.bytes())) {
            collectJsonPdfs(page.bytes(), hosts, detailPattern, pdfs);
            return new Discovery(distinct(pdfs.values()), 0);
        }
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
        if (source.id().equals("rbi")) {
            try {
                var feed = fetch(URI.create("https://rbi.org.in/notifications_rss.xml"), hosts, MAX_HTML);
                var xml = Jsoup.parse(new java.io.ByteArrayInputStream(feed.bytes()), null,
                        feed.uri().toString(), Parser.xmlParser());
                Map<URI, String> recent = new LinkedHashMap<>();
                for (Element item : xml.select("channel > item")) {
                    Element link = item.selectFirst("link");
                    Element title = item.selectFirst("title");
                    if (link != null && title != null) {
                        URI uri = URI.create(link.text().strip());
                        if (allowed(uri, hosts) && detailPattern.matcher(uri.toString()).find()) {
                            recent.putIfAbsent(uri, title.text().strip());
                        }
                    }
                }
                details.forEach(recent::putIfAbsent);
                details = recent;
            } catch (IOException | IllegalArgumentException e) {
                // The ordinary index still supplies candidates when the optional feed is unavailable.
            }
        }
        for (var detail : details.entrySet().stream().limit(MAX_DETAIL_PAGES).toList()) {
            try {
                Response response = fetch(detail.getKey(), hosts, MAX_HTML);
                if (isPdfBody(response.bytes())) {
                    String title = detail.getValue().isBlank() ? response.uri().getPath() : detail.getValue();
                    pdfs.putIfAbsent(response.uri(), new Candidate(response.uri(), title));
                } else {
                    Document document = html(response);
                    collectPdfs(document, hosts, pdfs, detail.getValue());
                    if (source.id().equals("rbi")) {
                        attachRbiWebVersion(document, response.uri(), hosts, pdfs);
                    }
                }
            } catch (IOException e) {
                failures++;
            }
        }
        return new Discovery(distinct(pdfs.values()), failures);
    }

    /**
     * Web versions first, then one candidate per URL ignoring case. RBI links the same PDF as both
     * /rdocs/Notification/ and /rdocs/notification/, which would otherwise be stored twice.
     */
    private static List<Candidate> distinct(java.util.Collection<Candidate> candidates) {
        Set<String> seen = new java.util.HashSet<>();
        return candidates.stream()
                .sorted(java.util.Comparator.comparing(candidate -> candidate.webVersion() == null))
                .filter(candidate -> seen.add(candidate.uri().toString().toLowerCase(Locale.ROOT)))
                .limit(MAX_DOCUMENTS).toList();
    }

    byte[] download(ScannerRepository.Source source, Candidate candidate) throws IOException, InterruptedException {
        return download(source, candidate, true);
    }

    byte[] download(ScannerRepository.Source source, Candidate candidate, boolean allowBrowser)
            throws IOException, InterruptedException {
        Set<String> allowedHosts = hosts(source);
        try {
            byte[] bytes = fetch(candidate.uri(), allowedHosts, MAX_PDF).bytes();
            if (!isPdfBody(bytes)) {
                throw isBotChallenge(bytes)
                        ? new InvalidPdfResponse(candidate.uri().getHost() + " returned a bot-protection page instead of the PDF")
                        : new InvalidPdfResponse();
            }
            return bytes;
        } catch (IOException original) {
            if (!allowBrowser || !browserFallback || !source.id().equals("rbi")
                    || !isAllowedPdf(source, candidate.uri())) {
                throw original;
            }
            try {
                return downloadInBrowser(candidate.uri(), allowedHosts);
            } catch (IOException browserError) {
                original.addSuppressed(new BrowserFailure(browserError));
                throw original;
            }
        }
    }

    static boolean browserFailed(Throwable error) {
        return Arrays.stream(error.getSuppressed()).anyMatch(BrowserFailure.class::isInstance);
    }

    /** F5 BIG-IP bot defense answers with an HTML page that loads its script from /TSPD/. */
    private static boolean isBotChallenge(byte[] bytes) {
        String head = new String(bytes, 0, Math.min(bytes.length, 4096), StandardCharsets.ISO_8859_1);
        return head.contains("/TSPD/") || head.contains("TSPD_101");
    }

    private static boolean isJsonBody(byte[] bytes) {
        for (byte value : bytes) {
            if (!Character.isWhitespace(value)) {
                return value == '{' || value == '[';
            }
        }
        return false;
    }

    /**
     * Reads a JSON listing, such as the MeitY CMS search API. An object is a publication when its
     * "link" or "slug" matches the source's detail pattern; every allowed PDF URL inside it is a candidate.
     */
    private static void collectJsonPdfs(byte[] body, Set<String> hosts, Pattern detailPattern,
                                        Map<URI, Candidate> pdfs) throws IOException {
        JsonNode root;
        try {
            root = JSON.readTree(body);
        } catch (JacksonException e) {
            throw new IOException("Listing returned JSON that could not be parsed", e);
        }
        var pending = new java.util.ArrayDeque<JsonNode>(List.of(root));
        while (!pending.isEmpty()) {
            JsonNode node = pending.pop();
            String title = node.isObject() ? node.path("title").asString("").strip() : "";
            String link = node.isObject() ? node.path("link").asString("") + " " + node.path("slug").asString("") : "";
            if (!title.isEmpty() && detailPattern.matcher(link).find()) {
                for (String value : strings(node)) {
                    try {
                        URI uri = URI.create(value.strip()).normalize();
                        if (allowed(uri, hosts) && isPdf(uri)) {
                            pdfs.putIfAbsent(uri, new Candidate(uri, title));
                        }
                    } catch (IllegalArgumentException e) {
                        // Not a URL.
                    }
                }
                continue;
            }
            if (node.isContainer()) {
                node.forEach(pending::add);
            }
        }
    }

    private static List<String> strings(JsonNode node) {
        var values = new ArrayList<String>();
        var pending = new java.util.ArrayDeque<JsonNode>(List.of(node));
        while (!pending.isEmpty()) {
            JsonNode current = pending.pop();
            if (current.isString()) {
                values.add(current.asString());
            } else if (current.isContainer()) {
                current.forEach(pending::add);
            }
        }
        return values;
    }

    private static byte[] downloadInBrowser(URI uri, Set<String> hosts) throws IOException, InterruptedException {
        var arguments = new ArrayList<>(List.of(uri.toString(), Integer.toString(MAX_PDF)));
        arguments.addAll(hosts);
        return runPdfScript("download-pdf.cjs", arguments);
    }

    private static byte[] runPdfScript(String script, List<String> arguments) throws IOException, InterruptedException {
        var output = Files.createTempFile("clauseiq-rbi-", ".pdf");
        Process process = null;
        try {
            var command = new ArrayList<>(List.of("timeout", "--kill-after=2s", "14s", "node",
                    "/app/" + script, output.toString()));
            command.addAll(arguments);
            var builder = new ProcessBuilder(command)
                    .redirectOutput(ProcessBuilder.Redirect.DISCARD)
                    .redirectError(ProcessBuilder.Redirect.INHERIT);
            builder.environment().keySet().retainAll(Set.of("PATH", "HOME", "LANG", "PLAYWRIGHT_BROWSERS_PATH"));
            process = builder.start();
            if (process.waitFor() != 0) {
                throw new IOException("Playwright did not produce a PDF");
            }
            try (var stream = Files.newInputStream(output)) {
                byte[] bytes = stream.readNBytes(MAX_PDF + 1);
                if (bytes.length > MAX_PDF || !isPdfBody(bytes)) {
                    throw new InvalidPdfResponse();
                }
                return bytes;
            }
        } finally {
            if (process != null && process.isAlive()) {
                process.destroy();
            }
            Files.deleteIfExists(output);
        }
    }

    byte[] renderWebVersion(WebVersion version) throws IOException, InterruptedException {
        var input = Files.createTempFile("clauseiq-rbi-", ".html");
        try {
            Files.writeString(input, version.html());
            return runPdfScript("render-notification.cjs", List.of(input.toString()));
        } finally {
            Files.deleteIfExists(input);
        }
    }

    private static void attachRbiWebVersion(Document page, URI uri, Set<String> hosts, Map<URI, Candidate> pdfs) {
        Element content = page.selectFirst("table.td");
        Element download = page.selectFirst("a[id^=APDF_][href]");
        if (content == null || download == null || content.select("p").size() < 3 || content.text().length() < 200) {
            return;
        }
        URI pdf = linkUri(download, "href", hosts);
        if (pdf == null || !pdfs.containsKey(pdf)) {
            return;
        }
        String safeHtml = Jsoup.clean(content.outerHtml(),
                Safelist.relaxed().removeTags("img").removeAttributes("a", "href"));
        var web = new WebVersion(uri, safeHtml);
        pdfs.replaceAll((key, existing) -> key.toString().equalsIgnoreCase(pdf.toString())
                ? new Candidate(key, existing.title(), web) : existing);
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
            URI uri = unwrapViewer(linkUri(link, attribute, hosts), hosts);
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

    /**
     * SEBI embeds circulars in a PDF.js viewer, /web/?file=https://.../circular.pdf. The viewer returns
     * HTML, so use the PDF it points to, or nothing when that PDF is not on an allowed host.
     */
    static URI unwrapViewer(URI uri, Set<String> hosts) {
        if (uri == null || uri.getRawQuery() == null) {
            return uri;
        }
        for (String parameter : uri.getRawQuery().split("&")) {
            if (parameter.regionMatches(true, 0, "file=", 0, 5)) {
                try {
                    String value = java.net.URLDecoder.decode(parameter.substring(5), StandardCharsets.UTF_8);
                    URI target = uri.resolve(value).normalize();
                    return allowed(target, hosts) && isPdf(target) ? target : null;
                } catch (IllegalArgumentException e) {
                    return null;
                }
            }
        }
        return uri;
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
