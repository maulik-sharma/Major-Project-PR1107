"""Routing configuration tab in settings with persistent preferences."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modelmesh.ui.settings.tools_tab import get_app_settings


class RoutingTab(QWidget):
    """Tab for setting global router preferences and cooldown parameters."""

    config_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<strong>Router Configuration</strong>"))

        settings = get_app_settings()

        form = QFormLayout()

        self.default_strat = QComboBox()
        self.default_strat.addItems(["cheapest_first", "expensive_first", "random", "manual"])
        saved_strat = str(settings.value("router/strategy", "cheapest_first"))
        idx = self.default_strat.findText(saved_strat)
        if idx >= 0:
            self.default_strat.setCurrentIndex(idx)
        self.default_strat.currentTextChanged.connect(self._on_strategy_changed)
        form.addRow("Default Routing Strategy:", self.default_strat)

        self.safety_margin = QSpinBox()
        self.safety_margin.setRange(0, 10000)
        self.safety_margin.setValue(int(settings.value("router/safety_margin", 500)))
        self.safety_margin.valueChanged.connect(self._on_safety_margin_changed)
        form.addRow("Safety Margin Tokens:", self.safety_margin)

        self.cooldown_sec = QSpinBox()
        self.cooldown_sec.setRange(5, 3600)
        self.cooldown_sec.setValue(int(settings.value("router/cooldown_sec", 60)))
        self.cooldown_sec.valueChanged.connect(self._on_cooldown_changed)
        form.addRow("Health Failure Cooldown (sec):", self.cooldown_sec)

        layout.addLayout(form)
        layout.addStretch()

    def _on_strategy_changed(self, strat: str) -> None:
        get_app_settings().setValue("router/strategy", strat)
        self.config_changed.emit()

    def _on_safety_margin_changed(self, val: int) -> None:
        get_app_settings().setValue("router/safety_margin", val)
        self.config_changed.emit()

    def _on_cooldown_changed(self, val: int) -> None:
        get_app_settings().setValue("router/cooldown_sec", val)
        self.config_changed.emit()
