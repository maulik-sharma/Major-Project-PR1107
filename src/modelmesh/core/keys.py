"""Helper for reading and updating environment variables and .env secret keys."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import find_dotenv, load_dotenv


def get_default_env_path() -> Path:
    """Find the .env file in the workspace or default to current directory .env."""
    found = find_dotenv(usecwd=True)
    if found:
        return Path(found)
    return Path.cwd() / ".env"


def load_env(env_path: Optional[Path] = None) -> None:
    """Load environment variables from .env if present.

    System environment variables already in os.environ take precedence.
    """
    path = env_path or get_default_env_path()
    if path.exists():
        load_dotenv(dotenv_path=path, override=False)


def get_env_key(var_name: str) -> Optional[str]:
    """Retrieve an environment variable value, or None if empty/unset."""
    val = os.getenv(var_name)
    if val and val.strip():
        return val.strip()
    return None


def has_provider_auth(auth_env: List[str]) -> bool:
    """Check if all required environment variable names are set and non-empty.

    Providers with empty auth_env (like local Ollama or mock) return True.
    """
    if not auth_env:
        return True
    return all(get_env_key(var) is not None for var in auth_env)


def set_env_key(var_name: str, value: str, env_path: Optional[Path] = None) -> None:
    """Safely update or insert a variable into .env without corrupting comments or other keys.

    Also updates os.environ in the current process immediately.
    """
    path = env_path or get_default_env_path()
    # Update current process environment
    os.environ[var_name] = value

    lines: List[str] = []
    found = False
    if path.exists():
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()

    new_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            new_lines.append(line)
            continue
        if "=" in line:
            key, _ = line.split("=", 1)
            if key.strip() == var_name:
                new_lines.append(f"{var_name}={value}")
                found = True
                continue
        new_lines.append(line)

    if not found:
        new_lines.append(f"{var_name}={value}")

    # Write back preserving newline
    output_content = "\n".join(new_lines) + "\n"
    path.write_text(output_content, encoding="utf-8")


def set_provider_keys(keys: Dict[str, str], env_path: Optional[Path] = None) -> None:
    """Set multiple keys at once in .env and os.environ."""
    for var_name, value in keys.items():
        set_env_key(var_name, value, env_path=env_path)
