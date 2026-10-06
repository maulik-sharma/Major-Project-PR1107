"""Providers management tab with connection testing, model discovery, and key management."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.keys import get_env_key, set_env_key
from modelmesh.core.providers.base import get_adapter
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.types import ProviderConfig


PRESETS: Dict[str, Dict[str, Any]] = {
    "Groq": {
        "id": "groq",
        "protocol": "openai_compat",
        "base_url": "https://api.groq.com/openai/v1",
        "auth_env": ["GROQ_API_KEY"],
    },
    "OpenRouter": {
        "id": "openrouter",
        "protocol": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1",
        "auth_env": ["OPENROUTER_API_KEY"],
    },
    "Google Gemini": {
        "id": "gemini",
        "protocol": "openai_compat",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "auth_env": ["GEMINI_API_KEY"],
    },
    "OpenAI": {
        "id": "openai",
        "protocol": "openai_compat",
        "base_url": "https://api.openai.com/v1",
        "auth_env": ["OPENAI_API_KEY"],
    },
    "Anthropic": {
        "id": "anthropic",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com",
        "auth_env": ["ANTHROPIC_API_KEY"],
    },
    "Ollama (Local)": {
        "id": "ollama",
        "protocol": "openai_compat",
        "base_url": "http://localhost:11434/v1",
        "auth_env": [],
    },
    "Custom OpenAI-Compatible": {
        "id": "custom",
        "protocol": "openai_compat",
        "base_url": "https://api.example.com/v1",
        "auth_env": ["CUSTOM_API_KEY"],
    },
}


class ProviderTestWorker(QThread):
    """Background thread for non-blocking provider connectivity tests."""

    finished_success = pyqtSignal(str)
    finished_error = pyqtSignal(str)

    def __init__(self, provider: ProviderConfig) -> None:
        super().__init__()
        self.provider = provider

    def run(self) -> None:
        try:
            adapter = get_adapter(self.provider.protocol)
            adapter.test_connection(self.provider)
            self.finished_success.emit(self.provider.id)
        except Exception as exc:
            self.finished_error.emit(str(exc))


class ProviderListModelsWorker(QThread):
    """Background thread for non-blocking remote model discovery."""

    finished_success = pyqtSignal(str, list)
    finished_error = pyqtSignal(str, str)

    def __init__(self, provider: ProviderConfig) -> None:
        super().__init__()
        self.provider = provider

    def run(self) -> None:
        try:
            adapter = get_adapter(self.provider.protocol)
            models = adapter.list_models(self.provider)
            self.finished_success.emit(self.provider.id, models)
        except Exception as exc:
            self.finished_error.emit(self.provider.id, str(exc))


class AddProviderDialog(QDialog):
    """Modal dialog for adding a new provider from presets or custom URL."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Provider")
        self.setFixedWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.preset_combo = QComboBox()
        for name in PRESETS.keys():
            self.preset_combo.addItem(name)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        form.addRow("Preset:", self.preset_combo)

        self.id_input = QLineEdit()
        form.addRow("Provider ID:", self.id_input)

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["openai_compat", "anthropic", "mock"])
        form.addRow("Protocol:", self.protocol_combo)

        self.url_input = QLineEdit()
        form.addRow("Base URL:", self.url_input)

        self.auth_input = QLineEdit()
        self.auth_input.setPlaceholderText("e.g. PROVIDER_API_KEY (comma-separated)")
        form.addRow("Auth Env Vars:", self.auth_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_preset_changed(self.preset_combo.currentText())

    def _on_preset_changed(self, preset_name: str) -> None:
        data = PRESETS.get(preset_name, {})
        self.id_input.setText(data.get("id", ""))
        self.protocol_combo.setCurrentText(data.get("protocol", "openai_compat"))
        self.url_input.setText(data.get("base_url", ""))
        self.auth_input.setText(", ".join(data.get("auth_env", [])))

    def get_provider_config(self) -> ProviderConfig:
        auth_vars = [v.strip() for v in self.auth_input.text().split(",") if v.strip()]
        return ProviderConfig(
            id=self.id_input.text().strip(),
            protocol=self.protocol_combo.currentText(),
            base_url=self.url_input.text().strip() or None,
            auth_env=auth_vars,
        )


class ProvidersTab(QWidget):
    """Tab for managing API providers, credentials, connectivity, and model discovery."""

    config_changed = pyqtSignal()

    def __init__(self, registry: ModelRegistry, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.registry = registry
        self._test_worker: Optional[ProviderTestWorker] = None
        self._fetch_worker: Optional[ProviderListModelsWorker] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 1. Left List
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("<strong>Configured Providers</strong>"))
        self.provider_list = QListWidget()
        self.provider_list.currentItemChanged.connect(self._on_provider_selected)
        left_layout.addWidget(self.provider_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._on_add_provider)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._on_delete_provider)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        left_layout.addLayout(btn_row)

        splitter.addWidget(left_widget)

        # 2. Right Details
        self.details_widget = QWidget()
        self.details_layout = QVBoxLayout(self.details_widget)
        self.details_layout.setContentsMargins(14, 0, 0, 0)

        self.form_layout = QFormLayout()
        self.id_label = QLabel("-")
        self.protocol_label = QLabel("-")
        self.url_label = QLabel("-")

        self.form_layout.addRow("ID:", self.id_label)
        self.form_layout.addRow("Protocol:", self.protocol_label)
        self.form_layout.addRow("Base URL:", self.url_label)
        self.details_layout.addLayout(self.form_layout)

        # Keys section
        self.keys_container = QWidget()
        self.keys_layout = QVBoxLayout(self.keys_container)
        self.keys_layout.setContentsMargins(0, 8, 0, 8)
        self.details_layout.addWidget(self.keys_container)

        # Actions row
        actions_row = QHBoxLayout()
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._on_test_connection)
        self.fetch_btn = QPushButton("Fetch Models")
        self.fetch_btn.clicked.connect(self._on_fetch_models)
        actions_row.addWidget(self.test_btn)
        actions_row.addWidget(self.fetch_btn)
        actions_row.addStretch()
        self.details_layout.addLayout(actions_row)

        self.details_layout.addStretch()
        splitter.addWidget(self.details_widget)
        splitter.setSizes([220, 480])

        layout.addWidget(splitter)
        self.refresh()

    def refresh(self) -> None:
        """Reload providers list from registry."""
        self.provider_list.clear()
        providers = self.registry.providers()
        for p in providers:
            item = QListWidgetItem(f"{p.id} ({p.protocol})")
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self.provider_list.addItem(item)

        if providers:
            self.provider_list.setCurrentRow(0)

    def _on_provider_selected(self, current: Optional[QListWidgetItem], _: Any) -> None:
        if not current:
            self.details_widget.setEnabled(False)
            return

        self.details_widget.setEnabled(True)
        prov_id = current.data(Qt.ItemDataRole.UserRole)
        prov = self.registry.get_provider(prov_id)
        if not prov:
            return

        self.id_label.setText(prov.id)
        self.protocol_label.setText(prov.protocol)
        self.url_label.setText(prov.base_url or "(default)")

        # Rebuild keys form
        while self.keys_layout.count() > 0:
            item = self.keys_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if prov.auth_env:
            self.keys_layout.addWidget(QLabel("<strong>API Credentials (.env):</strong>"))
            for var_name in prov.auth_env:
                row = QHBoxLayout()
                row.addWidget(QLabel(f"{var_name}:"))
                key_input = QLineEdit()
                key_input.setEchoMode(QLineEdit.EchoMode.Password)
                current_val = get_env_key(var_name) or ""
                if current_val:
                    key_input.setPlaceholderText("••••••••••••••••")
                row.addWidget(key_input)

                save_btn = QPushButton("Save")
                save_btn.clicked.connect(
                    lambda _, v=var_name, inp=key_input: self._save_key(v, inp)
                )
                row.addWidget(save_btn)
                self.keys_layout.addLayout(row)
        else:
            self.keys_layout.addWidget(QLabel("<em>No credentials required for this provider.</em>"))

    def _save_key(self, var_name: str, input_widget: QLineEdit) -> None:
        val = input_widget.text().strip()
        if not val:
            return
        set_env_key(var_name, val)
        input_widget.clear()
        input_widget.setPlaceholderText("••••••••••••••••")
        QMessageBox.information(
            self,
            "Key Saved",
            f"Saved {var_name} to .env and updated current session.",
        )
        self.config_changed.emit()

    def _on_test_connection(self) -> None:
        curr = self.provider_list.currentItem()
        if not curr:
            return
        prov_id = curr.data(Qt.ItemDataRole.UserRole)
        prov = self.registry.get_provider(prov_id)
        if not prov:
            return

        self.test_btn.setEnabled(False)
        self.test_btn.setText("Testing...")

        self._test_worker = ProviderTestWorker(prov)
        self._test_worker.finished_success.connect(self._on_test_success)
        self._test_worker.finished_error.connect(self._on_test_error)
        self._test_worker.start()

    def _on_test_success(self, prov_id: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test Connection")
        QMessageBox.information(
            self,
            "Connection Successful",
            f"Successfully connected and authenticated with '{prov_id}'!",
        )

    def _on_test_error(self, err_msg: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test Connection")
        QMessageBox.warning(
            self,
            "Connection Failed",
            f"Connection check failed:\n\n{err_msg}",
        )

    def _on_fetch_models(self) -> None:
        curr = self.provider_list.currentItem()
        if not curr:
            return
        prov_id = curr.data(Qt.ItemDataRole.UserRole)
        prov = self.registry.get_provider(prov_id)
        if not prov:
            return

        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Fetching...")

        self._fetch_worker = ProviderListModelsWorker(prov)
        self._fetch_worker.finished_success.connect(self._on_fetch_success)
        self._fetch_worker.finished_error.connect(self._on_fetch_error)
        self._fetch_worker.start()

    def _on_fetch_success(self, prov_id: str, models: list) -> None:
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("Fetch Models")
        if not models:
            QMessageBox.information(self, "Models", f"No models returned by {prov_id}.")
            return

        preview = "\n".join([f"• {m}" for m in models[:25]])
        if len(models) > 25:
            preview += f"\n... and {len(models) - 25} more"

        QMessageBox.information(
            self,
            f"Discovered {len(models)} Models on {prov_id}",
            f"Active models:\n\n{preview}",
        )

    def _on_fetch_error(self, prov_id: str, err_msg: str) -> None:
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("Fetch Models")
        QMessageBox.warning(
            self,
            "Fetch Models Error",
            f"Could not list models from '{prov_id}':\n\n{err_msg}",
        )

    def _on_add_provider(self) -> None:
        dlg = AddProviderDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            prov = dlg.get_provider_config()
            self.registry.add_provider(prov)
            self.refresh()
            self.config_changed.emit()

    def _on_delete_provider(self) -> None:
        curr = self.provider_list.currentItem()
        if not curr:
            return
        prov_id = curr.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self,
            "Delete Provider",
            f"Are you sure you want to remove provider '{prov_id}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.registry._providers.pop(prov_id, None)
            self.refresh()
            self.config_changed.emit()
