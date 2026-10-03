---
name: code-review
description: Performs rigorous code review checking architecture layering, security vulnerabilities, edge cases, type hints, and performance bottlenecks.
---

# Code Review Checklist Skill

When conducting a code review:
1. **Architecture & Layering**:
   - Verify that UI modules do not leak into Core.
   - Verify that core modules do not import GUI frameworks.
2. **Secrets & Security**:
   - Verify no API keys, credentials, or private URLs are hardcoded in source.
   - Ensure all secrets are loaded from environment variables / `.env`.
3. **Robustness & Error Handling**:
   - Check that external API calls catch and normalize exceptions.
   - Verify timeout and cancellation handling.
4. **Type Safety & Documentation**:
   - Ensure complete Python type annotations (`typing` / `types.py`).
   - Check for docstrings on public classes, functions, and interfaces.
5. **Testing**:
   - Verify unit tests cover success, edge cases, and failure modes.
