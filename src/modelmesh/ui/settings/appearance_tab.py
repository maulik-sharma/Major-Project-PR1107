"""Appearance and theme settings tab."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class AppearanceTab(QWidget):
    """Tab for appearance and theme preferences."""

    theme_changed = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        layout.addWidget(QLabel("<strong>Theme & Display</strong>"))

        form = QFormLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark (Default)", "Light"])
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        form.addRow("Application Theme:", self.theme_combo)

        layout.addLayout(form)
        layout.addStretch()

    def _on_theme_changed(self, text: str) -> None:
        theme = "light" if "Light" in text else "dark"
        self.theme_changed.emit(theme)
