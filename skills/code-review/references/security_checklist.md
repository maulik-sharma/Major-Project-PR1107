# Code Review Security Checklist

## Top Vulnerability Vectors
1. **Injection Vulnerabilities**:
   - SQL: Ensure parameterized queries and ORM bindings; never concatenate raw SQL strings.
   - Command Execution: Avoid `shell=True` in subprocess calls; validate all shell arguments.
   - Path Traversal: Resolve paths and verify `.is_relative_to(base_dir)`.
2. **Secrets & Keys**:
   - Verify no API keys, private tokens, or connection strings in source code or commits.
   - Ensure keys reside only in gitignored environment variables.
3. **Authentication & Authorization**:
   - Verify token expiry, permission scopes, and session invalidation.
   - Verify defense-in-depth on public API endpoints.
