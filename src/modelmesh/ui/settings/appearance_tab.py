"""Appearance and theme settings tab with persistence and live switching."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from modelmesh.ui.settings.tools_tab import get_app_settings
from modelmesh.ui.theme import apply_theme


class AppearanceTab(QWidget):
    """Tab for appearance and theme preferences."""

    theme_changed = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<strong>Theme & Display</strong>"))

        form = QFormLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark (Default)", "Light"])

        saved_theme = str(get_app_settings().value("appearance/theme", "dark"))
        if saved_theme == "light":
            self.theme_combo.setCurrentText("Light")
        else:
            self.theme_combo.setCurrentText("Dark (Default)")

        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        form.addRow("Application Theme:", self.theme_combo)

        layout.addLayout(form)
        layout.addStretch()

    def _on_theme_changed(self, text: str) -> None:
        theme = "light" if "Light" in text else "dark"
        get_app_settings().setValue("appearance/theme", theme)
        app = QApplication.instance()
        if app:
            apply_theme(app, theme)
        self.theme_changed.emit(theme)
