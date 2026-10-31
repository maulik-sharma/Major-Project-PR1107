"""Dialog for editing a model's score links (AA slug, LMArena name) and manual overrides."""

from __future__ import annotations

from typing import Optional, Tuple

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.types import ManualScoresConfig, ModelConfig


def _override_spin(value: Optional[float], maximum: float, decimals: int = 1) -> QDoubleSpinBox:
    """Spin box where 0 means "no override"."""
    spin = QDoubleSpinBox()
    spin.setRange(0.0, maximum)
    spin.setDecimals(decimals)
    spin.setSpecialValueText("Auto / None")
    spin.setValue(value if value is not None else 0.0)
    return spin


def _value(spin: QDoubleSpinBox) -> Optional[float]:
    return spin.value() if spin.value() > 0.0 else None


class EditModelScoresDialog(QDialog):
    """Edit the AA slug, LMArena model name, and manual score overrides of a model."""

    def __init__(self, model: ModelConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Scores - {model.display_name}")
        self.setFixedWidth(460)
        self.model = model

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        form = QFormLayout()

        self.slug_input = QLineEdit(model.scores.aa_slug or "")
        self.slug_input.setPlaceholderText("Artificial Analysis slug, e.g. gpt-oss-120b")
        form.addRow("AA Slug:", self.slug_input)

        self.arena_input = QLineEdit(model.scores.arena_name or "")
        self.arena_input.setPlaceholderText("LMArena model name, e.g. gpt-oss-120b")
        form.addRow("Arena Name:", self.arena_input)

        man = model.scores.manual
        self.intel_spin = _override_spin(man.intelligence, 100.0)
        form.addRow("Manual Intelligence:", self.intel_spin)
        self.coding_spin = _override_spin(man.coding, 100.0)
        form.addRow("Manual Coding:", self.coding_spin)
        self.agent_spin = _override_spin(man.agentic, 100.0)
        form.addRow("Manual Agentic:", self.agent_spin)
        self.elo_spin = _override_spin(man.arena_text_elo, 3000.0, decimals=0)
        self.elo_spin.setToolTip("Overrides the LMArena overall rating")
        form.addRow("Manual Arena Elo:", self.elo_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> Tuple[Optional[str], Optional[str], ManualScoresConfig]:
        """Return (aa_slug, arena_name, manual overrides) as entered."""
        return (
            self.slug_input.text().strip() or None,
            self.arena_input.text().strip() or None,
            ManualScoresConfig(
                intelligence=_value(self.intel_spin),
                coding=_value(self.coding_spin),
                agentic=_value(self.agent_spin),
                arena_text_elo=_value(self.elo_spin),
            ),
        )
