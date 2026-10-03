"""Tests for environment variable and .env secret key management."""

import os
from pathlib import Path
from modelmesh.core.keys import (
    get_env_key,
    has_provider_auth,
    load_env,
    set_env_key,
    set_provider_keys,
)


def test_get_env_key_and_auth_check(monkeypatch) -> None:
    monkeypatch.setenv("TEST_KEY_VAR", "test-secret-123")
    monkeypatch.delenv("MISSING_VAR", raising=False)

    assert get_env_key("TEST_KEY_VAR") == "test-secret-123"
    assert get_env_key("MISSING_VAR") is None

    assert has_provider_auth([]) is True
    assert has_provider_auth(["TEST_KEY_VAR"]) is True
    assert has_provider_auth(["TEST_KEY_VAR", "MISSING_VAR"]) is False


def test_set_env_key_updates_file_and_environ(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# Initial comments\nEXISTING_VAR=foo\n", encoding="utf-8")

    monkeypatch.delenv("NEW_VAR", raising=False)
    monkeypatch.setenv("EXISTING_VAR", "foo")

    # Update existing
    set_env_key("EXISTING_VAR", "updated_foo", env_path=env_file)
    assert os.getenv("EXISTING_VAR") == "updated_foo"

    # Add new
    set_env_key("NEW_VAR", "secret_bar", env_path=env_file)
    assert os.getenv("NEW_VAR") == "secret_bar"

    # Verify file content
    content = env_file.read_text(encoding="utf-8")
    assert "# Initial comments" in content
    assert "EXISTING_VAR=updated_foo" in content
    assert "NEW_VAR=secret_bar" in content


def test_set_provider_keys_batch(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    set_provider_keys(
        {"KEY_A": "val_a", "KEY_B": "val_b"},
        env_path=env_file,
    )
    content = env_file.read_text(encoding="utf-8")
    assert "KEY_A=val_a" in content
    assert "KEY_B=val_b" in content
    assert os.getenv("KEY_A") == "val_a"
    assert os.getenv("KEY_B") == "val_b"
