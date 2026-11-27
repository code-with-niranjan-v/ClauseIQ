package com.example.clauseiq_backend;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Map;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.ProviderManager;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.crypto.factory.PasswordEncoderFactories;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.security.web.csrf.CsrfException;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.security.web.csrf.CsrfTokenRequestAttributeHandler;
import org.springframework.security.web.csrf.CsrfTokenRequestHandler;
import org.springframework.security.web.csrf.XorCsrfTokenRequestAttributeHandler;
import org.springframework.util.StringUtils;
import tools.jackson.databind.ObjectMapper;

/**
 * Session sign-in for the same-origin UI. The session cookie is HttpOnly. CSRF protection uses the
 * XSRF-TOKEN cookie, which the UI echoes in the X-XSRF-TOKEN header (axios does this for same-origin requests).
 *
 * VIEWER reads everything and may ask Policy Q&A. REVIEWER may also change data: review findings, scan,
 * upload, assess, confirm circular changes. ADMIN may also manage users and the processing queue.
 */
@Configuration
class SecurityConfig {
    private static final Logger log = LoggerFactory.getLogger(SecurityConfig.class);

    @Bean
    PasswordEncoder passwordEncoder() {
        return PasswordEncoderFactories.createDelegatingPasswordEncoder();
    }

    @Bean
    AuthenticationManager authenticationManager(UserStore users, PasswordEncoder encoder) {
        var provider = new DaoAuthenticationProvider(users);
        provider.setPasswordEncoder(encoder);
        return new ProviderManager(provider);
    }

    @Bean
    SecurityContextRepository securityContextRepository() {
        return new HttpSessionSecurityContextRepository();
    }

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http, SecurityContextRepository contexts, ObjectMapper json)
            throws Exception {
        http.csrf(csrf -> csrf.csrfTokenRepository(CookieCsrfTokenRepository.withHttpOnlyFalse())
                        .csrfTokenRequestHandler(new SpaCsrfTokenRequestHandler()))
                .securityContext(context -> context.securityContextRepository(contexts))
                .authorizeHttpRequests(requests -> requests
                        .requestMatchers("/actuator/health", "/actuator/health/**", "/error").permitAll()
                        .requestMatchers("/api/auth/**").permitAll()
                        .requestMatchers("/api/admin/users/**").hasRole("ADMIN")
                        .requestMatchers(HttpMethod.PUT, "/api/admin/processing").hasRole("ADMIN")
                        .requestMatchers(HttpMethod.POST, "/api/admin/processing/clear").hasRole("ADMIN")
                        .requestMatchers(HttpMethod.GET, "/api/**").authenticated()
                        .requestMatchers(HttpMethod.POST, "/api/chat").authenticated()
                        .requestMatchers("/api/**").hasAnyRole("REVIEWER", "ADMIN")
                        .anyRequest().denyAll())
                .exceptionHandling(errors -> errors
                        .authenticationEntryPoint((request, response, failure) ->
                                write(json, response, HttpStatus.UNAUTHORIZED, "Sign in to continue."))
                        .accessDeniedHandler((request, response, failure) -> write(json, response, HttpStatus.FORBIDDEN,
                                failure instanceof CsrfException
                                        ? "The session's security token is missing or stale. Reload the page."
                                        : "Your role does not allow this action.")))
                .formLogin(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable)
                .logout(AbstractHttpConfigurer::disable);
        return http.build();
    }

    private static void write(ObjectMapper json, HttpServletResponse response, HttpStatus status, String message)
            throws IOException {
        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        json.writeValue(response.getOutputStream(),
                Map.of("status", status.value(), "error", status.getReasonPhrase(), "message", message));
    }

    /** Creates the first administrator when there are no accounts. */
    @Bean
    ApplicationRunner firstAdministrator(UserStore users, PasswordEncoder encoder,
                                         @Value("${clauseiq.admin.username}") String username,
                                         @Value("${clauseiq.admin.password}") String password) {
        return arguments -> {
            if (users.count() > 0) {
                return;
            }
            String chosen = password;
            if (!StringUtils.hasText(chosen)) {
                byte[] random = new byte[15];
                new SecureRandom().nextBytes(random);
                chosen = Base64.getUrlEncoder().withoutPadding().encodeToString(random);
                log.warn("Created the first administrator '{}' with the generated password: {}  "
                        + "Sign in and change it, or set CLAUSEIQ_ADMIN_PASSWORD before the first start.",
                        UserStore.normalize(username), chosen);
            } else {
                log.info("Created the first administrator '{}' from CLAUSEIQ_ADMIN_PASSWORD", UserStore.normalize(username));
            }
            users.create(username, "Administrator", "ADMIN", encoder.encode(chosen));
        };
    }

    /**
     * Single-page-app CSRF handling from the Spring Security reference: the header carries the raw token,
     * rendered pages would carry the masked one. Loading the token on every request keeps the cookie set.
     */
    static final class SpaCsrfTokenRequestHandler implements CsrfTokenRequestHandler {
        private final CsrfTokenRequestHandler plain = new CsrfTokenRequestAttributeHandler();
        private final CsrfTokenRequestHandler xor = new XorCsrfTokenRequestAttributeHandler();

        @Override
        public void handle(HttpServletRequest request, HttpServletResponse response, Supplier<CsrfToken> token) {
            xor.handle(request, response, token);
            token.get();
        }

        @Override
        public String resolveCsrfTokenValue(HttpServletRequest request, CsrfToken token) {
            String header = request.getHeader(token.getHeaderName());
            return (StringUtils.hasText(header) ? plain : xor).resolveCsrfTokenValue(request, token);
        }
    }
}
