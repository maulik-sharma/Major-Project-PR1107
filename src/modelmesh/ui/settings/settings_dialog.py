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
        storage: Optional[Any] = None,
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
        self.storage = storage

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
        self.scores_tab = ScoresTab(registry=self.registry, storage=self.storage, parent=self)
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
        # Refresh the other tabs only: the sender already shows its own state, and
        # reloading it would reset what the user is in the middle of editing.
        sender = self.sender()
        for tab in (self.models_tab, self.providers_tab, self.scores_tab, self.routing_tab):
            if tab is not sender:
                tab.refresh()
        self.settings_updated.emit()

    def done(self, code: int) -> None:
        """Apply pending edits and let background workers finish before closing."""
        self.routing_tab.flush()
        for worker in (
            getattr(self.scores_tab, "_refresh_worker", None),
            getattr(self.routing_tab, "_test_worker", None),
            getattr(self.providers_tab, "_test_worker", None),
            getattr(self.providers_tab, "_fetch_worker", None),
            getattr(self.models_tab, "_catalog_worker", None),
        ):
            if worker is not None and worker.isRunning():
                worker.wait(15000)
        super().done(code)

