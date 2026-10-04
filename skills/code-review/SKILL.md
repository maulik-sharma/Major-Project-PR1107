---
name: code-review
description: Comprehensive checklist for reviewing code quality, security vulnerabilities, edge cases, and performance optimizations.
---

# Code Review Specialist

When performing a code review:
1. **Architecture & Layering**: Verify separation of concerns and appropriate dependency flow.
2. **Correctness & Edge Cases**:
   - Check null/empty inputs, division by zero, boundary conditions.
   - Resource cleanup (files, network connections, memory leaks).
3. **Security Analysis**:
   - Injection vulnerabilities (SQL, command injection, eval).
   - Secret scrubbing (no API keys, tokens, or credentials hardcoded).
4. **Actionable Recommendations**:
   - Group findings by `Critical`, `Important`, and `Nitpick`.
   - Provide concrete code diffs for suggested fixes.
