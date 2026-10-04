"""Tools and workspace preferences tab in settings."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ToolsTab(QWidget):
    """Tab for enabling built-in tools and workspace folder selection."""

    config_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(QLabel("<strong>Built-in Tools</strong>"))

        self.calc_check = QCheckBox("Calculator (AST math parser)")
        self.calc_check.setChecked(True)
        layout.addWidget(self.calc_check)

        self.dt_check = QCheckBox("Current DateTime")
        self.dt_check.setChecked(True)
        layout.addWidget(self.dt_check)

        self.fetch_check = QCheckBox("URL Fetcher & Web Reader")
        self.fetch_check.setChecked(True)
        layout.addWidget(self.fetch_check)

        self.file_check = QCheckBox("Local Workspace File Reader")
        self.file_check.setChecked(True)
        layout.addWidget(self.file_check)

        layout.addWidget(QLabel("<strong>Workspace Folder for File Tool:</strong>"))
        ws_row = QHBoxLayout()
        self.ws_input = QLineEdit(str(Path.cwd()))
        ws_btn = QPushButton("Browse...")
        ws_btn.clicked.connect(self._on_browse)
        ws_row.addWidget(self.ws_input)
        ws_row.addWidget(ws_btn)
        layout.addLayout(ws_row)

        layout.addStretch()

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Workspace Folder", self.ws_input.text())
        if folder:
            self.ws_input.setText(folder)
