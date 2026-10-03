"""Application entrypoint for ModelMesh Desktop GUI client."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure src is in sys.path when script is run directly
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QApplication

from modelmesh.core.engine import ChatEngine
from modelmesh.core.keys import load_env
from modelmesh.core.registry import load_default_registry
from modelmesh.core.routing.router import Router
from modelmesh.core.storage import Storage
from modelmesh.ui.main_window import MainWindow
from modelmesh.ui.theme import apply_theme

# Load environment keys
load_env()


def get_db_path() -> Path:
    """Resolve SQLite database path under app data location."""
    app_data = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not app_data:
        app_dir = Path.cwd() / "data"
    else:
        app_dir = Path(app_data) / "modelmesh"

    try:
        app_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        app_dir = Path.cwd() / "data"
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
