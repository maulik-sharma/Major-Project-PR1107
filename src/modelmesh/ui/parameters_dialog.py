"""Parameters dialog for configuring temperature, max tokens, and system prompt."""

from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class ParametersDialog(QDialog):
    """Dialog for customizing per-conversation generation parameters."""

    def __init__(
        self,
        current_settings: Optional[Dict[str, Any]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("parametersDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle("Generation Parameters")
        self.setFixedWidth(420)

        settings = current_settings or {}

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.temp_input = QDoubleSpinBox()
        self.temp_input.setRange(0.0, 2.0)
        self.temp_input.setSingleStep(0.1)
        self.temp_input.setValue(settings.get("temperature", 0.7))
        form.addRow("Temperature (0.0 - 2.0):", self.temp_input)

        self.max_tokens_input = QSpinBox()
        self.max_tokens_input.setRange(100, 100000)
        self.max_tokens_input.setValue(settings.get("max_tokens", 4096))
        form.addRow("Max Output Tokens:", self.max_tokens_input)

        self.system_prompt_input = QPlainTextEdit()
        self.system_prompt_input.setPlaceholderText("Optional system instructions for the model...")
        self.system_prompt_input.setPlainText(settings.get("system_prompt", ""))
        self.system_prompt_input.setFixedHeight(120)
        form.addRow("System Prompt:", self.system_prompt_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_settings(self) -> Dict[str, Any]:
        """Return updated generation settings dictionary."""
        return {
            "temperature": self.temp_input.value(),
            "max_tokens": self.max_tokens_input.value(),
            "system_prompt": self.system_prompt_input.toPlainText().strip(),
        }
