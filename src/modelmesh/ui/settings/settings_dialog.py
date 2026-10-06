"""Settings modal dialog assembling Providers, Endpoints, Routing, and Appearance tabs."""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.registry import ModelRegistry
from modelmesh.ui.settings.appearance_tab import AppearanceTab
from modelmesh.ui.settings.models_tab import ModelsTab
from modelmesh.ui.settings.providers_tab import ProvidersTab
from modelmesh.ui.settings.routing_tab import RoutingTab
from modelmesh.ui.settings.scores_tab import ScoresTab


class SettingsDialog(QDialog):
    """Main Settings modal dialog for ModelMesh."""

    settings_updated = pyqtSignal()
    theme_changed = pyqtSignal(str)

    def __init__(
        self,
        registry: ModelRegistry,
        tool_registry: Optional[Any] = None,
        skill_loader: Optional[Any] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle("ModelMesh Settings")
        self.resize(800, 560)

        self.registry = registry

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.tabs = QTabWidget()

        # 1. Providers Tab
        self.providers_tab = ProvidersTab(registry=self.registry, parent=self)
        self.providers_tab.config_changed.connect(self._on_tab_config_changed)
        self.tabs.addTab(self.providers_tab, "Providers")

        # 2. Endpoints Tab
        self.models_tab = ModelsTab(registry=self.registry, parent=self)
        self.models_tab.config_changed.connect(self._on_tab_config_changed)
        self.tabs.addTab(self.models_tab, "Endpoints")

        # 3. Scores Tab
        self.scores_tab = ScoresTab(registry=self.registry, parent=self)
        self.scores_tab.config_changed.connect(self._on_tab_config_changed)
        self.tabs.addTab(self.scores_tab, "Scores")

        # 4. Routing Tab
        self.routing_tab = RoutingTab(parent=self)
        self.routing_tab.config_changed.connect(self._on_tab_config_changed)
        self.tabs.addTab(self.routing_tab, "Routing")

        # 5. Appearance Tab
        self.appearance_tab = AppearanceTab(parent=self)
        self.appearance_tab.theme_changed.connect(self.theme_changed)
        self.tabs.addTab(self.appearance_tab, "Appearance")

        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    def _on_tab_config_changed(self) -> None:
        self.models_tab.refresh()
        self.providers_tab.refresh()
        self.scores_tab.refresh()
        self.settings_updated.emit()

