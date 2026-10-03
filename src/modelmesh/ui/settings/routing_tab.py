"""Routing configuration tab in settings."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class RoutingTab(QWidget):
    """Tab for setting global router preferences and cooldown parameters."""

    config_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        layout.addWidget(QLabel("<strong>Router Configuration</strong>"))

        form = QFormLayout()

        self.default_strat = QComboBox()
        self.default_strat.addItems(["cheapest_first", "expensive_first", "random", "manual"])
        form.addRow("Default Routing Strategy:", self.default_strat)

        self.safety_margin = QSpinBox()
        self.safety_margin.setRange(0, 10000)
        self.safety_margin.setValue(500)
        form.addRow("Safety Margin Tokens:", self.safety_margin)

        self.cooldown_sec = QSpinBox()
        self.cooldown_sec.setRange(5, 3600)
        self.cooldown_sec.setValue(60)
        form.addRow("Health Failure Cooldown (sec):", self.cooldown_sec)

        layout.addLayout(form)
        layout.addStretch()
