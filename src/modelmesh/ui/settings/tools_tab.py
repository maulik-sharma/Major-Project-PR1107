"""App settings location (QSettings) and the Create Skill dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSettings, QStandardPaths, Qt

from modelmesh.core.skills import format_skill_md, skill_slug
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


_custom_settings_path: Optional[Path] = None


def set_custom_settings_path(path: Optional[Path]) -> None:
    """Override settings file location (useful for isolated tests)."""
    global _custom_settings_path
    _custom_settings_path = path


def get_app_settings(ini_path: Optional[Path] = None) -> QSettings:
    """Get persistent QSettings instance for ModelMesh stored in user app data."""
    if ini_path is not None:
        target = ini_path
    elif _custom_settings_path is not None:
        target = _custom_settings_path
    else:
        app_data = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        if not app_data:
            app_dir = Path.cwd() / "data"
        else:
            app_dir = Path(app_data) / "modelmesh"
        try:
            app_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            app_dir = Path.cwd() / "data"
            app_dir.mkdir(parents=True, exist_ok=True)
        target = app_dir / "settings.ini"

    target.parent.mkdir(parents=True, exist_ok=True)
    return QSettings(str(target), QSettings.Format.IniFormat)


class CreateSkillDialog(QDialog):
    """Modal dialog for authoring a new skill with YAML frontmatter."""

    def __init__(self, skills_dir: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create New Skill")
        self.resize(560, 420)
        self.skills_dir = skills_dir

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. sql-optimizer")
        form.addRow("Skill Name (slug):", self.name_input)

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("e.g. Analyzes and optimizes slow SQL queries.")
        form.addRow("Description:", self.desc_input)

        layout.addLayout(form)

        layout.addWidget(QLabel("<strong>Instruction Body (Markdown):</strong>"))
        self.body_input = QTextEdit()
        self.body_input.setPlaceholderText("# SQL Optimizer Instructions\n1. Check indexes\n2. Explain query plan...")
        layout.addWidget(self.body_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        desc = self.desc_input.text().strip()
        body = self.body_input.toPlainText().strip()
        try:
            name = skill_slug(self.name_input.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Name", str(exc))
            return

        skill_file = self.skills_dir / name / "SKILL.md"
        if skill_file.exists():
            reply = QMessageBox.question(
                self,
                "Skill Exists",
                f"A skill named '{name}' already exists. Replace its instructions?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(format_skill_md(name, desc, body), encoding="utf-8")
        self.accept()
