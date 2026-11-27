package com.example.circular_scanner;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.spy;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import org.junit.jupiter.api.Test;

class PublicationClientTests {
    private static final URI LISTING = URI.create("https://www.sebi.gov.in/legal/circulars.html");
    private static final URI DETAIL = LISTING.resolve("/legal/circulars/nov-2026/update_1.html");
    private static final URI DIRECT = LISTING.resolve("/files/direct.pdf");
    private static final URI EMBEDDED = LISTING.resolve("/files/embedded.pdf?download=1");
    private static final Set<String> HOSTS = Set.of("www.sebi.gov.in");
    private static final ScannerRepository.Source SOURCE = new ScannerRepository.Source(
            "sebi", "SEBI", "SEBI", LISTING.toString(), "www.sebi.gov.in", "/legal/circulars/.*[.]html",
            true, null, null, null, "NEVER_RUN", null, 0, 0);

    @Test
    void discoversDirectAndEmbeddedPdfsFromOfficialHosts() throws Exception {
        var client = spy(new PublicationClient());
        doReturn(response(LISTING, """
                <a href="/files/direct.pdf#page=2">Direct circular</a>
                <a href="/legal/circulars/nov-2026/update_1.html">Policy update</a>
                <a href="https://other.example/legal/circulars/untrusted.html">External</a>
                """)).when(client).fetch(eq(LISTING), eq(HOSTS), anyInt());
        doReturn(response(DETAIL, """
                <iframe src="/files/embedded.pdf?download=1"></iframe>
                <object data="https://other.example/document.pdf"></object>
                """)).when(client).fetch(eq(DETAIL), eq(HOSTS), anyInt());

        var result = client.discover(SOURCE);

        assertThat(result.pageFailures()).isZero();
        assertThat(result.candidates()).containsExactly(new PublicationClient.Candidate(DIRECT, "Direct circular"),
                new PublicationClient.Candidate(EMBEDDED, "Policy update"));
    }

    @Test
    void rejectsHtmlReturnedFromPdfUrl() throws Exception {
        var client = spy(new PublicationClient());
        doReturn(response(DIRECT, "<html>Service unavailable</html>"))
                .when(client).fetch(eq(DIRECT), eq(HOSTS), anyInt());

        assertThatThrownBy(() -> client.download(SOURCE, new PublicationClient.Candidate(DIRECT, "Circular")))
                .isInstanceOf(java.io.IOException.class).hasMessageContaining("PDF header");
    }

    private static PublicationClient.Response response(URI uri, String value) {
        return new PublicationClient.Response(uri, value.getBytes(StandardCharsets.UTF_8));
    }
}
