"""Endpoints management tab with flat multi-provider endpoint configuration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.registry import ModelRegistry
from modelmesh.core.types import EndpointConfig, ModelConfig


class AddEndpointDialog(QDialog):
    """Dialog for creating a new endpoint and optionally creating a new logical model."""

    def __init__(
        self,
        providers: List[str],
        existing_models: List[ModelConfig],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Endpoint")
        self.setFixedWidth(420)
        self.existing_models = existing_models

        layout = QVBoxLayout(self)
        self.form = QFormLayout()

        # Logical Model selection
        self.model_combo = QComboBox()
        for m in existing_models:
            self.model_combo.addItem(f"{m.display_name} ({m.id})", m.id)
        self.model_combo.addItem("➕ Create New Logical Model...", "__new__")
        self.model_combo.currentIndexChanged.connect(self._on_model_selection_changed)
        self.form.addRow("Logical Model:", self.model_combo)

        # New Model Fields (hidden by default unless new selected)
        self.new_model_id_input = QLineEdit()
        self.new_model_id_input.setPlaceholderText("e.g. gpt-4o, claude-3-5-sonnet")
        self.form.addRow("New Model ID:", self.new_model_id_input)

        self.new_model_name_input = QLineEdit()
        self.new_model_name_input.setPlaceholderText("e.g. GPT-4o")
        self.form.addRow("Display Name:", self.new_model_name_input)

        self.new_model_tier_combo = QComboBox()
        self.new_model_tier_combo.addItems(["cheap", "mid", "premium"])
        self.form.addRow("Tier:", self.new_model_tier_combo)

        # Provider selection
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(providers)
        self.form.addRow("Provider:", self.provider_combo)

        # API Model String
        self.api_model_input = QLineEdit()
        self.api_model_input.setPlaceholderText("e.g. gpt-4o, claude-3-5-sonnet-20241022")
        self.form.addRow("API Model String:", self.api_model_input)

        # Prices & Priority
        self.price_in = QDoubleSpinBox()
        self.price_in.setRange(0.0, 100.0)
        self.price_in.setDecimals(4)
        self.price_in.setValue(0.05)
        self.form.addRow("Price In ($/Mtok):", self.price_in)

        self.price_out = QDoubleSpinBox()
        self.price_out.setRange(0.0, 100.0)
        self.price_out.setDecimals(4)
        self.price_out.setValue(0.08)
        self.form.addRow("Price Out ($/Mtok):", self.price_out)

        self.priority = QSpinBox()
        self.priority.setRange(1, 100)
        self.priority.setValue(1)
        self.form.addRow("Priority (1=highest):", self.priority)

        self.enabled_check = QCheckBox("Active / Enabled")
        self.enabled_check.setChecked(True)
        self.form.addRow("Status:", self.enabled_check)

        layout.addLayout(self.form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_model_selection_changed(self.model_combo.currentIndex())

    def _on_model_selection_changed(self, idx: int) -> None:
        is_new = self.model_combo.currentData() == "__new__" or not self.existing_models
        self.new_model_id_input.setVisible(is_new)
        self.new_model_name_input.setVisible(is_new)
        self.new_model_tier_combo.setVisible(is_new)
        self.form.labelForField(self.new_model_id_input).setVisible(is_new)
        self.form.labelForField(self.new_model_name_input).setVisible(is_new)
        self.form.labelForField(self.new_model_tier_combo).setVisible(is_new)

    def _on_accept(self) -> None:
        if self.model_combo.currentData() == "__new__" or not self.existing_models:
            if not self.new_model_id_input.text().strip():
                QMessageBox.warning(self, "Invalid Input", "Please enter a Model ID.")
                return
        if not self.provider_combo.currentText():
            QMessageBox.warning(self, "Invalid Input", "Please select a provider.")
            return
        self.accept()

    def get_result(self) -> Dict[str, Any]:
        is_new = self.model_combo.currentData() == "__new__" or not self.existing_models
        if is_new:
            model_id = self.new_model_id_input.text().strip()
            display_name = self.new_model_name_input.text().strip() or model_id
            tier = self.new_model_tier_combo.currentText()
            new_model = ModelConfig(id=model_id, display_name=display_name, tier=tier, endpoints=[])
        else:
            model_id = self.model_combo.currentData()
            new_model = None

        prov = self.provider_combo.currentText()
        api_model = self.api_model_input.text().strip() or model_id
        ep_id = f"{model_id}@{prov}"

        endpoint = EndpointConfig(
            id=ep_id,
            provider=prov,
            api_model=api_model,
            price_in_per_mtok=self.price_in.value(),
            price_out_per_mtok=self.price_out.value(),
            priority=self.priority.value(),
            enabled=self.enabled_check.isChecked(),
        )
        return {"model_id": model_id, "new_model": new_model, "endpoint": endpoint}


class EditEndpointDialog(QDialog):
    """Dialog for editing an existing endpoint's API model, prices, priority, and enabled state."""

    def __init__(self, endpoint: EndpointConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Endpoint: {endpoint.id}")
        self.setFixedWidth(400)
        self.endpoint = endpoint

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.api_model_input = QLineEdit()
        self.api_model_input.setText(endpoint.api_model)
        form.addRow("API Model String:", self.api_model_input)

        self.price_in = QDoubleSpinBox()
        self.price_in.setRange(0.0, 100.0)
        self.price_in.setDecimals(4)
        self.price_in.setValue(endpoint.price_in_per_mtok)
        form.addRow("Price In ($/Mtok):", self.price_in)

        self.price_out = QDoubleSpinBox()
        self.price_out.setRange(0.0, 100.0)
        self.price_out.setDecimals(4)
        self.price_out.setValue(endpoint.price_out_per_mtok)
        form.addRow("Price Out ($/Mtok):", self.price_out)

        self.priority = QSpinBox()
        self.priority.setRange(1, 100)
        self.priority.setValue(endpoint.priority)
        form.addRow("Priority (1=highest):", self.priority)

        self.enabled_check = QCheckBox("Active / Enabled")
        self.enabled_check.setChecked(endpoint.enabled)
        form.addRow("Status:", self.enabled_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def update_endpoint(self) -> EndpointConfig:
        self.endpoint.api_model = self.api_model_input.text().strip() or self.endpoint.api_model
        self.endpoint.price_in_per_mtok = self.price_in.value()
        self.endpoint.price_out_per_mtok = self.price_out.value()
        self.endpoint.priority = self.priority.value()
        self.endpoint.enabled = self.enabled_check.isChecked()
        return self.endpoint


class ModelsTab(QWidget):
    """Tab for managing endpoints in a flat, fully-populated table."""

    config_changed = pyqtSignal()

    def __init__(self, registry: ModelRegistry, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.registry = registry

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header info
        layout.addWidget(QLabel("<strong>Endpoints & Pricing Configuration</strong>"))

        # Flat Table Widget
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Endpoint ID",
            "Logical Model",
            "Provider",
            "API Model",
            "In $/Mtok",
            "Out $/Mtok",
            "Priority",
            "Status",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.doubleClicked.connect(self._on_edit_endpoint)

        layout.addWidget(self.table)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        add_ep_btn = QPushButton("+ Add Endpoint")
        add_ep_btn.clicked.connect(self._on_add_endpoint)
        edit_btn = QPushButton("Edit Selected")
        edit_btn.clicked.connect(self._on_edit_endpoint)
        toggle_btn = QPushButton("Toggle Active")
        toggle_btn.clicked.connect(self._on_toggle_active)
        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self._on_delete_selected)

        btn_row.addWidget(add_ep_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(toggle_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.refresh()

    def refresh(self) -> None:
        """Populate table with all endpoints in a flat list with no placeholder fields."""
        prev_row = self.table.currentRow()
        self.table.setRowCount(0)
        models = self.registry.models()

        row_idx = 0
        for model in models:
            for ep in model.endpoints:
                self.table.insertRow(row_idx)

                id_item = QTableWidgetItem(ep.id)
                id_item.setData(Qt.ItemDataRole.UserRole, {"model_id": model.id, "ep_id": ep.id})
                self.table.setItem(row_idx, 0, id_item)

                model_item = QTableWidgetItem(f"{model.display_name} ({model.id})")
                self.table.setItem(row_idx, 1, model_item)

                prov_item = QTableWidgetItem(ep.provider)
                self.table.setItem(row_idx, 2, prov_item)

                api_item = QTableWidgetItem(ep.api_model)
                self.table.setItem(row_idx, 3, api_item)

                in_item = QTableWidgetItem(f"${ep.price_in_per_mtok:.4f}")
                self.table.setItem(row_idx, 4, in_item)

                out_item = QTableWidgetItem(f"${ep.price_out_per_mtok:.4f}")
                self.table.setItem(row_idx, 5, out_item)

                prio_item = QTableWidgetItem(str(ep.priority))
                self.table.setItem(row_idx, 6, prio_item)

                status_item = QTableWidgetItem("Active" if ep.enabled else "Disabled")
                if not ep.enabled:
                    status_item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(row_idx, 7, status_item)

                row_idx += 1

        self.table.resizeColumnsToContents()
        min_widths = [190, 160, 95, 170, 95, 95, 75, 85]
        for col_i, min_w in enumerate(min_widths):
            current_w = self.table.columnWidth(col_i)
            self.table.setColumnWidth(col_i, max(current_w + 16, min_w))

        if row_idx > 0:
            target_row = max(0, min(prev_row, row_idx - 1)) if prev_row >= 0 else 0
            self.table.setCurrentCell(target_row, 0)

    def _get_selected_data(self) -> Optional[Dict[str, str]]:
        row = self.table.currentRow()
        if row < 0:
            selected = self.table.selectedItems()
            if selected:
                row = selected[0].row()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_add_endpoint(self) -> None:
        providers = [p.id for p in self.registry.providers()]
        if not providers:
            QMessageBox.warning(self, "No Providers", "Please configure at least one provider first.")
            return

        dlg = AddEndpointDialog(
            providers=providers,
            existing_models=self.registry.models(),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_result()
            if data.get("new_model"):
                self.registry.add_model(data["new_model"])
            self.registry.add_endpoint(data["model_id"], data["endpoint"])
            self.refresh()
            self.config_changed.emit()

    def _on_edit_endpoint(self) -> None:
        data = self._get_selected_data()
        if not data:
            QMessageBox.information(self, "Select Endpoint", "Please select an endpoint to edit.")
            return

        model = self.registry.get_model(data["model_id"])
        if not model:
            return
        endpoint = next((e for e in model.endpoints if e.id == data["ep_id"]), None)
        if not endpoint:
            return

        dlg = EditEndpointDialog(endpoint=endpoint, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.update_endpoint()
            self.refresh()
            self.config_changed.emit()

    def _on_toggle_active(self) -> None:
        data = self._get_selected_data()
        if not data:
            return
        model = self.registry.get_model(data["model_id"])
        if not model:
            return
        endpoint = next((e for e in model.endpoints if e.id == data["ep_id"]), None)
        if not endpoint:
            return

        endpoint.enabled = not endpoint.enabled
        self.refresh()
        self.config_changed.emit()

    def _on_delete_selected(self) -> None:
        data = self._get_selected_data()
        if not data:
            QMessageBox.information(self, "Select Endpoint", "Please select an endpoint to delete.")
            return

        reply = QMessageBox.question(
            self,
            "Delete Endpoint",
            f"Delete endpoint '{data['ep_id']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.registry.remove_endpoint(data["model_id"], data["ep_id"])
            self.refresh()
            self.config_changed.emit()
