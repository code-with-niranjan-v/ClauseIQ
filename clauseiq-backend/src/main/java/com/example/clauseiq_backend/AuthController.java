package com.example.clauseiq_backend;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.authentication.logout.SecurityContextLogoutHandler;
import org.springframework.security.web.context.SecurityContextRepository;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
class AuthController {
    record Credentials(String username, String password) {}

    record Me(String username, String displayName, String role) {
        static Me of(UserStore.AppUser user) {
            return new Me(user.username(), user.displayName(), user.role());
        }
    }

    record NewUser(String username, String displayName, String role, String password) {}

    record UserChange(String displayName, String role, Boolean enabled, String password) {}

    private static final int MAX_FAILURES = 5;
    private static final Duration LOCKOUT = Duration.ofMinutes(1);
    private static final int MIN_PASSWORD = 10;

    private record Failures(int count, Instant lockedUntil) {}

    private final AuthenticationManager authentication;
    private final SecurityContextRepository contexts;
    private final UserStore users;
    private final PasswordEncoder encoder;
    private final Map<String, Failures> failures = new ConcurrentHashMap<>();

    AuthController(AuthenticationManager authentication, SecurityContextRepository contexts, UserStore users,
                   PasswordEncoder encoder) {
        this.authentication = authentication;
        this.contexts = contexts;
        this.users = users;
        this.encoder = encoder;
    }

    @GetMapping("/api/auth/me")
    ResponseEntity<?> me() {
        Authentication current = SecurityContextHolder.getContext().getAuthentication();
        if (current == null || current instanceof AnonymousAuthenticationToken || !current.isAuthenticated()) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of(
                    "status", 401, "error", "Unauthorized", "message", "Sign in to continue."));
        }
        return users.find(current.getName()).filter(UserStore.AppUser::enabled).<ResponseEntity<?>>map(
                user -> ResponseEntity.ok(Me.of(user))).orElseGet(() -> ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(Map.of("status", 401, "error", "Unauthorized", "message", "Sign in to continue.")));
    }

    @PostMapping("/api/auth/login")
    Me login(@RequestBody Credentials credentials, HttpServletRequest request, HttpServletResponse response) {
        String username = UserStore.normalize(credentials == null ? null : credentials.username());
        String password = credentials == null || credentials.password() == null ? "" : credentials.password();
        Failures previous = failures.get(username);
        if (previous != null && previous.lockedUntil() != null && previous.lockedUntil().isAfter(Instant.now())) {
            throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS,
                    "Too many failed attempts. Try again in a minute.");
        }
        Authentication result;
        try {
            result = authentication.authenticate(UsernamePasswordAuthenticationToken.unauthenticated(username, password));
        } catch (AuthenticationException e) {
            failures.merge(username, new Failures(1, null), (old, one) -> old.count() + 1 >= MAX_FAILURES
                    ? new Failures(0, Instant.now().plus(LOCKOUT)) : new Failures(old.count() + 1, null));
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "The username or password is not correct.");
        }
        failures.remove(username);
        if (request.getSession(false) != null) {
            request.changeSessionId();   // a new session id after sign-in prevents session fixation
        }
        var context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(result);
        SecurityContextHolder.setContext(context);
        contexts.saveContext(context, request, response);
        users.recordLogin(username);
        return Me.of(users.find(username).orElseThrow());
    }

    @PostMapping("/api/auth/logout")
    ResponseEntity<Void> logout(HttpServletRequest request, HttpServletResponse response) {
        new SecurityContextLogoutHandler().logout(request, response,
                SecurityContextHolder.getContext().getAuthentication());
        return ResponseEntity.noContent().build();
    }

    // ------------------------------------------------------------ user management (ADMIN, see SecurityConfig)

    @GetMapping("/api/admin/users")
    List<UserStore.AppUser> list() {
        return users.list();
    }

    @PostMapping("/api/admin/users")
    ResponseEntity<UserStore.AppUser> create(@RequestBody NewUser user) {
        String username = UserStore.normalize(user == null ? null : user.username());
        if (!username.matches("[a-z0-9._-]{3,40}")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Usernames are 3 to 40 lower-case letters, digits, dots, hyphens or underscores.");
        }
        if (users.find(username).isPresent()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "That username is taken.");
        }
        String role = role(user.role());
        String displayName = displayName(user.displayName(), username);
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(users.create(username, displayName, role, encoder.encode(password(user.password()))));
    }

    @PatchMapping("/api/admin/users/{id}")
    UserStore.AppUser update(@PathVariable UUID id, @RequestBody UserChange change) {
        var target = users.find(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown user"));
        String role = change.role() == null ? null : role(change.role());
        boolean losesAdmin = target.role().equals("ADMIN") && target.enabled()
                && ((role != null && !role.equals("ADMIN")) || Boolean.FALSE.equals(change.enabled()));
        if (losesAdmin && users.enabledAdmins() <= 1) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Keep at least one enabled administrator.");
        }
        if (losesAdmin && target.username().equals(users.current().username())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "You cannot remove your own administrator access. Ask another administrator.");
        }
        users.update(id, change.displayName() == null ? null : displayName(change.displayName(), target.username()),
                role, change.enabled(), change.password() == null ? null : encoder.encode(password(change.password())));
        return users.find(id).orElseThrow();
    }

    private static String role(String role) {
        String value = role == null ? "" : role.strip().toUpperCase(java.util.Locale.ROOT);
        if (!UserStore.ROLES.contains(value)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "role must be ADMIN, REVIEWER or VIEWER");
        }
        return value;
    }

    private static String displayName(String name, String username) {
        String value = name == null ? "" : name.strip().replaceAll("\\s+", " ");
        return value.isEmpty() ? username : value.substring(0, Math.min(value.length(), 80));
    }

    private static String password(String password) {
        if (password == null || password.length() < MIN_PASSWORD) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Passwords need at least " + MIN_PASSWORD + " characters.");
        }
        return password;
    }
}
