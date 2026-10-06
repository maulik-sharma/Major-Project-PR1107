# Async & Parametrized Testing in Pytest

## Table-Driven Parametrization
```python
import pytest

@pytest.mark.parametrize("input_val,expected", [
    ("", False),
    ("valid@example.com", True),
    ("invalid_email", False),
    ("user+tag@domain.org", True),
])
def test_email_validation(input_val, expected):
    assert is_valid_email(input_val) == expected
```

## Async Tests with pytest-anyio
- Mark async tests with `@pytest.mark.anyio`.
- Use async fixtures for async connection setup and cleanup teardown loops.
