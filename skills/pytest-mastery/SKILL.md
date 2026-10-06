---
name: pytest-mastery
description: Modern Python testing practices using pytest, fixtures, mocking, parametrization, and async test design.
---

# Pytest Mastery Specialist

Guidelines for designing robust, fast, and maintainable pytest suites.

## Core Tenets
1. **Isolated & Deterministic**: Every test must run independently in any order without leaking state.
2. **Explicit Fixtures**: Prefer explicit fixtures over setup/teardown boilerplate or inheritance.
3. **Parametrization for Edge Cases**: Use `@pytest.mark.parametrize` to cover boundary conditions.

## References
- See [Fixtures and Mocking Guide](references/fixtures_and_mocking.md) for fixture scopes, factories, and unittest.mock / monkeypatch patterns.
- See [Async and Parametrized Testing](references/async_and_parametrized.md) for pytest-asyncio/anyio and table-driven testing.
