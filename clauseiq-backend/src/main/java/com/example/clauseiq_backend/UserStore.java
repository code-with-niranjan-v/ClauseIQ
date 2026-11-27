package com.example.clauseiq_backend;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Repository;

/** Sign-in accounts. Roles: ADMIN manages users and processing, REVIEWER decides, VIEWER reads. */
@Repository
class UserStore implements UserDetailsService {
    static final Set<String> ROLES = Set.of("ADMIN", "REVIEWER", "VIEWER");

    record AppUser(UUID id, String username, String displayName, String role, boolean enabled,
                   OffsetDateTime createdAt, OffsetDateTime lastLoginAt) {
        /** How the user appears in review decisions, link decisions and reports. */
        String signature() {
            return displayName.equals(username) ? username : displayName + " (" + username + ")";
        }
    }

    private static final RowMapper<AppUser> USER = (rs, row) -> new AppUser(
            rs.getObject("id", UUID.class), rs.getString("username"), rs.getString("display_name"),
            rs.getString("role"), rs.getBoolean("enabled"), rs.getObject("created_at", OffsetDateTime.class),
            rs.getObject("last_login_at", OffsetDateTime.class));

    private final JdbcTemplate jdbc;

    UserStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public UserDetails loadUserByUsername(String username) {
        return jdbc.query("SELECT username, password_hash, role, enabled FROM app_user WHERE username = ?",
                (rs, row) -> User.withUsername(rs.getString("username")).password(rs.getString("password_hash"))
                        .roles(rs.getString("role")).disabled(!rs.getBoolean("enabled")).build(),
                normalize(username)).stream().findFirst()
                .orElseThrow(() -> new UsernameNotFoundException("Unknown user"));
    }

    static String normalize(String username) {
        return username == null ? "" : username.strip().toLowerCase(java.util.Locale.ROOT);
    }

    Optional<AppUser> find(String username) {
        return jdbc.query("SELECT * FROM app_user WHERE username = ?", USER, normalize(username)).stream().findFirst();
    }

    Optional<AppUser> find(UUID id) {
        return jdbc.query("SELECT * FROM app_user WHERE id = ?", USER, id).stream().findFirst();
    }

    /** The signed-in user. Every endpoint that calls this requires authentication. */
    AppUser current() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        return find(authentication == null ? null : authentication.getName())
                .orElseThrow(() -> new IllegalStateException("No signed-in user"));
    }

    List<AppUser> list() {
        return jdbc.query("SELECT * FROM app_user ORDER BY role, username", USER);
    }

    long count() {
        return jdbc.queryForObject("SELECT count(*) FROM app_user", Long.class);
    }

    long enabledAdmins() {
        return jdbc.queryForObject("SELECT count(*) FROM app_user WHERE role = 'ADMIN' AND enabled", Long.class);
    }

    AppUser create(String username, String displayName, String role, String passwordHash) {
        UUID id = UUID.randomUUID();
        jdbc.update("INSERT INTO app_user (id, username, display_name, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                id, normalize(username), displayName, passwordHash, role);
        return find(id).orElseThrow();
    }

    void update(UUID id, String displayName, String role, Boolean enabled, String passwordHash) {
        jdbc.update("""
                UPDATE app_user SET display_name = COALESCE(?, display_name), role = COALESCE(?, role),
                    enabled = COALESCE(?, enabled), password_hash = COALESCE(?, password_hash)
                WHERE id = ?
                """, displayName, role, enabled, passwordHash, id);
    }

    void recordLogin(String username) {
        jdbc.update("UPDATE app_user SET last_login_at = now() WHERE username = ?", normalize(username));
    }
}
