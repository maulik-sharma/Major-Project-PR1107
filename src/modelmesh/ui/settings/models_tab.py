"""Models and endpoints management tab with multi-provider endpoint configuration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.registry import ModelRegistry
from modelmesh.core.types import EndpointConfig, ModelConfig


class AddEndpointDialog(QDialog):
    """Dialog for attaching a new provider endpoint to a model."""

    def __init__(
        self,
        providers: List[str],
        model_id: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Add Endpoint to '{model_id}'")
        self.setFixedWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(providers)
        form.addRow("Provider:", self.provider_combo)

        self.api_model_input = QLineEdit()
        self.api_model_input.setPlaceholderText("e.g. gpt-4o, claude-3-5-sonnet")
        form.addRow("API Model String:", self.api_model_input)

        self.price_in = QDoubleSpinBox()
        self.price_in.setRange(0.0, 100.0)
        self.price_in.setDecimals(4)
        self.price_in.setValue(0.05)
        form.addRow("Price In ($/Mtok):", self.price_in)

        self.price_out = QDoubleSpinBox()
        self.price_out.setRange(0.0, 100.0)
        self.price_out.setDecimals(4)
        self.price_out.setValue(0.08)
        form.addRow("Price Out ($/Mtok):", self.price_out)

        self.priority = QSpinBox()
        self.priority.setRange(1, 100)
        self.priority.setValue(1)
        form.addRow("Priority (lower=first):", self.priority)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_endpoint(self, model_id: str) -> EndpointConfig:
        prov = self.provider_combo.currentText()
        ep_id = f"{model_id}@{prov}"
        return EndpointConfig(
            id=ep_id,
            provider=prov,
            api_model=self.api_model_input.text().strip() or model_id,
            price_in_per_mtok=self.price_in.value(),
            price_out_per_mtok=self.price_out.value(),
            priority=self.priority.value(),
        )


class AddModelDialog(QDialog):
    """Dialog for creating a new logical model."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Logical Model")
        self.setFixedWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("e.g. my-custom-model")
        form.addRow("Model ID:", self.id_input)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. My Custom Model")
        form.addRow("Display Name:", self.name_input)

        self.tier_combo = QComboBox()
        self.tier_combo.addItems(["cheap", "mid", "premium"])
        form.addRow("Tier:", self.tier_combo)

        self.context_input = QSpinBox()
        self.context_input.setRange(1000, 2000000)
        self.context_input.setValue(128000)
        form.addRow("Context Window:", self.context_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_model(self) -> ModelConfig:
        return ModelConfig(
            id=self.id_input.text().strip(),
            display_name=self.name_input.text().strip() or self.id_input.text().strip(),
            tier=self.tier_combo.currentText(),
            context_window=self.context_input.value(),
            endpoints=[],
        )


class ModelsTab(QWidget):
    """Tab for managing models, endpoints, policies, and prices."""

    config_changed = pyqtSignal()

    def __init__(self, registry: ModelRegistry, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.registry = registry

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        # Header info
        layout.addWidget(QLabel("<strong>Models & Multi-Provider Endpoints</strong>"))

        # Tree Widget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([
            "Model / Endpoint",
            "Provider",
            "API Model",
            "In $/Mtok",
            "Out $/Mtok",
            "Priority",
            "Policy / Status",
        ])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 7):
            self.tree.header().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.tree)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        add_model_btn = QPushButton("+ Add Model")
        add_model_btn.clicked.connect(self._on_add_model)
        add_ep_btn = QPushButton("+ Add Endpoint")
        add_ep_btn.clicked.connect(self._on_add_endpoint)
        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self._on_delete_selected)

        btn_row.addWidget(add_model_btn)
        btn_row.addWidget(add_ep_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.refresh()

    def refresh(self) -> None:
        """Populate tree with models and nested endpoints from registry."""
        self.tree.clear()
        models = self.registry.models()

        for model in models:
            model_item = QTreeWidgetItem([
                f"🤖 {model.display_name} ({model.id})",
                f"{len(model.endpoints)} endpoints",
                f"{model.tier} tier",
                "-",
                "-",
                "-",
                f"Policy: {model.endpoint_policy}",
            ])
            model_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "model", "id": model.id})
            model_item.setExpanded(True)

            for ep in model.endpoints:
                ep_item = QTreeWidgetItem([
                    f"  ↳ {ep.id}",
                    ep.provider,
                    ep.api_model,
                    f"${ep.price_in_per_mtok:.4f}",
                    f"${ep.price_out_per_mtok:.4f}",
                    str(ep.priority),
                    "🟢 Active" if ep.enabled else "⚪ Disabled",
                ])
                ep_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {"type": "endpoint", "model_id": model.id, "ep_id": ep.id},
                )
                model_item.addChild(ep_item)

            self.tree.addTopLevelItem(model_item)

    def _on_add_model(self) -> None:
        dlg = AddModelDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            model = dlg.get_model()
            if not model.id:
                return
            self.registry.add_model(model)
            self.refresh()
            self.config_changed.emit()

    def _on_add_endpoint(self) -> None:
        selected = self.tree.currentItem()
        if not selected:
            QMessageBox.information(self, "Select Model", "Please select a model first.")
            return

        data = selected.data(0, Qt.ItemDataRole.UserRole) or {}
        model_id = data.get("id") if data.get("type") == "model" else data.get("model_id")
        if not model_id:
            return

        providers = [p.id for p in self.registry.providers()]
        if not providers:
            QMessageBox.warning(self, "No Providers", "Please configure at least one provider first.")
            return

        dlg = AddEndpointDialog(providers=providers, model_id=model_id, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            ep = dlg.get_endpoint(model_id)
            model = self.registry.get_model(model_id)
            if model:
                model.endpoints.append(ep)
                self.refresh()
                self.config_changed.emit()

    def _on_delete_selected(self) -> None:
        selected = self.tree.currentItem()
        if not selected:
            return

        data = selected.data(0, Qt.ItemDataRole.UserRole) or {}
        item_type = data.get("type")

        if item_type == "model":
            model_id = data.get("id")
            reply = QMessageBox.question(
                self,
                "Delete Model",
                f"Delete model '{model_id}' and all its endpoints?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.registry._models.pop(model_id, None)
                self.refresh()
                self.config_changed.emit()

        elif item_type == "endpoint":
            model_id = data.get("model_id")
            ep_id = data.get("ep_id")
            model = self.registry.get_model(model_id)
            if model:
                model.endpoints = [e for e in model.endpoints if e.id != ep_id]
                self.refresh()
                self.config_changed.emit()
