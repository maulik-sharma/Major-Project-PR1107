# Fixtures & Mocking Patterns

## Fixture Scopes & Factory Pattern
- Use function-scoped fixtures for state-modifying objects (e.g. databases, client sessions).
- Use session-scoped fixtures for expensive read-only setups (e.g. test container startup, read-only config registries).

```python
import pytest

@pytest.fixture
def user_factory():
    def _create_user(name: str, role: str = "member"):
        return {"name": name, "role": role, "active": True}
    return _create_user
```

## Mocking & Monkeypatching Best Practices
- Mock at the boundary of your system (external APIs, file writes, network calls).
- Avoid over-mocking internal helper functions.
- Prefer `monkeypatch.setattr()` or `pytest-mock` (`mocker` fixture) to keep mock lifecycle strictly scoped to the test.
