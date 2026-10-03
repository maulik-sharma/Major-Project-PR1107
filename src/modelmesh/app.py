"""Application entrypoint for ModelMesh Desktop GUI client."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Disable Chromium setuid sandbox restrictions in Linux containers
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from dotenv import load_dotenv
from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtWidgets import QApplication

# Load environment keys
env_file = Path.cwd() / ".env"
load_dotenv(dotenv_path=env_file, override=True)

from modelmesh.core.engine import ChatEngine
from modelmesh.core.registry import load_default_registry
from modelmesh.core.routing.router import Router
from modelmesh.core.storage import Storage
from modelmesh.ui.main_window import MainWindow
from modelmesh.ui.theme import apply_theme


def get_db_path() -> Path:
    """Resolve SQLite database path under app data location."""
    app_data = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not app_data:
        app_dir = Path.cwd() / "data"
    else:
        app_dir = Path(app_data) / "modelmesh"

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir / "modelmesh.db"


def main() -> None:
    """Initialize ModelMesh desktop client and run Qt event loop."""
    # Ensure sandbox flags passed to Chromium
    sys_args = list(sys.argv)
    if "--no-sandbox" not in sys_args:
        sys_args.append("--no-sandbox")

    app = QApplication(sys_args)
    app.setApplicationName("ModelMesh")
    app.setOrganizationName("ModelMesh")
    apply_theme(app, "dark")

    # Initialize Core Services
    registry = load_default_registry()
    db_path = get_db_path()
    storage = Storage(db_path=db_path)
    router = Router(registry=registry)
    engine = ChatEngine(registry=registry, router=router, storage=storage)

    # Initialize and Show Main Window
    window = MainWindow(
        registry=registry,
        router=router,
        engine=engine,
        storage=storage,
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
