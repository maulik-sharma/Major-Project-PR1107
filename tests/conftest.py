"""Shared pytest fixtures: keep tests hermetic (no real keys, no real settings)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

# Offscreen Qt with no Chromium sandbox, set before any QApplication exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")


@pytest.fixture(scope="session")
def qapp() -> Any:
    """Single QApplication shared by every UI test."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv + ["--no-sandbox", "--disable-gpu"])
    app.setApplicationName("ModelMesh")
    app.setOrganizationName("ModelMesh")
    return app

from modelmesh.core import keys

# Env vars that would let a test reach a real external service.
_CREDENTIAL_VARS = (
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_AUTH_TOKEN",
    "ARTIFICIAL_ANALYSIS_API_KEY",
)


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Hide the developer's .env and credentials so no test can call a real service."""
    monkeypatch.setattr(keys, "get_default_env_path", lambda: tmp_path / "missing.env")
    for var in _CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _isolated_routing_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Give each test a private copy of routing.yaml so saves never touch the repo."""
    from modelmesh.core.config import routing_config

    repo_cfg = Path(__file__).resolve().parent.parent / "config" / "routing.yaml"
    private = tmp_path / "routing.yaml"
    shutil.copyfile(repo_cfg, private)
    monkeypatch.setattr(routing_config, "find_routing_config_path", lambda: private)


@pytest.fixture(autouse=True)
def _isolated_app_settings(tmp_path: Path) -> Iterator[None]:
    """Point QSettings at a temp file so tests never touch the user's real settings."""
    from modelmesh.ui.settings.tools_tab import set_custom_settings_path

    set_custom_settings_path(tmp_path / "settings.ini")
    yield
    set_custom_settings_path(None)
