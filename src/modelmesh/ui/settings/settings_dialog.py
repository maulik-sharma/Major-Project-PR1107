"""Settings modal dialog assembling Providers, Models, Routing, Tools, and Appearance tabs."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal
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
from modelmesh.ui.settings.tools_tab import ToolsTab


class SettingsDialog(QDialog):
    """Main Settings modal dialog for ModelMesh."""

    settings_updated = pyqtSignal()

    def __init__(
        self,
        registry: ModelRegistry,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ModelMesh Settings")
        self.resize(750, 520)

        self.registry = registry

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self.tabs = QTabWidget()

        self.providers_tab = ProvidersTab(registry=self.registry, parent=self)
        self.providers_tab.config_changed.connect(self._on_tab_config_changed)
        self.tabs.addTab(self.providers_tab, "Providers")

        self.models_tab = ModelsTab(registry=self.registry, parent=self)
        self.models_tab.config_changed.connect(self._on_tab_config_changed)
        self.tabs.addTab(self.models_tab, "Models & Endpoints")

        self.routing_tab = RoutingTab(parent=self)
        self.tabs.addTab(self.routing_tab, "Routing")

        self.tools_tab = ToolsTab(parent=self)
        self.tabs.addTab(self.tools_tab, "Tools")

        self.appearance_tab = AppearanceTab(parent=self)
        self.tabs.addTab(self.appearance_tab, "Appearance")

        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    def _on_tab_config_changed(self) -> None:
        self.models_tab.refresh()
        self.providers_tab.refresh()
        self.settings_updated.emit()
