"""Tools, workspace preferences, and skills management tab in settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import QSettings, QStandardPaths, QUrl, pyqtSignal, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.skills import SkillLoader
from modelmesh.core.tools.registry import ToolRegistry


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
        name = self.name_input.text().strip().lower().replace(" ", "-")
        desc = self.desc_input.text().strip()
        body = self.body_input.toPlainText().strip()

        if not name:
            QMessageBox.warning(self, "Invalid Input", "Please provide a skill name.")
            return

        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"

        content = f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}\n"
        skill_file.write_text(content, encoding="utf-8")
        self.accept()


class ToolsTab(QWidget):
    """Tab for configuring built-in tools, workspace folder, and skills."""

    config_changed = pyqtSignal()

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        skill_loader: Optional[SkillLoader] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.tool_registry = tool_registry
        self.skill_loader = skill_loader

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # 1. Built-in Tools
        layout.addWidget(QLabel("<strong>Built-in Tools</strong>"))
        tools_layout = QHBoxLayout()

        self.calc_check = QCheckBox("Calculator")
        self.calc_check.setChecked(
            self.tool_registry.is_tool_enabled("calculator") if self.tool_registry else True
        )
        self.calc_check.toggled.connect(lambda val: self._on_tool_toggle("calculator", val))
        tools_layout.addWidget(self.calc_check)

        self.dt_check = QCheckBox("DateTime")
        self.dt_check.setChecked(
            self.tool_registry.is_tool_enabled("get_current_datetime") if self.tool_registry else True
        )
        self.dt_check.toggled.connect(lambda val: self._on_tool_toggle("get_current_datetime", val))
        tools_layout.addWidget(self.dt_check)

        self.fetch_check = QCheckBox("URL Fetcher")
        self.fetch_check.setChecked(
            self.tool_registry.is_tool_enabled("fetch_url") if self.tool_registry else True
        )
        self.fetch_check.toggled.connect(lambda val: self._on_tool_toggle("fetch_url", val))
        tools_layout.addWidget(self.fetch_check)

        self.file_check = QCheckBox("File Reader")
        self.file_check.setChecked(
            self.tool_registry.is_tool_enabled("read_text_file") if self.tool_registry else True
        )
        self.file_check.toggled.connect(lambda val: self._on_tool_toggle("read_text_file", val))
        tools_layout.addWidget(self.file_check)
        tools_layout.addStretch()

        layout.addLayout(tools_layout)

        # 2. Workspace Folder
        layout.addWidget(QLabel("<strong>Workspace Folder for File Reader Tool:</strong>"))
        ws_row = QHBoxLayout()
        current_ws = (
            self.tool_registry.workspace_folder
            if self.tool_registry and self.tool_registry.workspace_folder
            else str(Path.cwd())
        )
        self.ws_input = QLineEdit(current_ws)
        self.ws_input.textChanged.connect(self._on_ws_text_changed)
        ws_btn = QPushButton("Browse...")
        ws_btn.clicked.connect(self._on_browse)
        ws_row.addWidget(self.ws_input)
        ws_row.addWidget(ws_btn)
        layout.addLayout(ws_row)

        # 3. Skills Management
        layout.addWidget(QLabel("<strong>Agent Skills (Progressive Disclosure)</strong>"))
        self.skills_table = QTableWidget()
        self.skills_table.setColumnCount(3)
        self.skills_table.setHorizontalHeaderLabels(["Skill Name", "Description", "Actions"])
        self.skills_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.skills_table.setColumnWidth(0, 150)
        self.skills_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.skills_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.skills_table.setColumnWidth(2, 175)
        self.skills_table.verticalHeader().setDefaultSectionSize(48)
        self.skills_table.verticalHeader().setVisible(False)
        self.skills_table.setShowGrid(False)
        layout.addWidget(self.skills_table)

        skills_btn_row = QHBoxLayout()
        new_skill_btn = QPushButton("+ New Skill...")
        new_skill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_skill_btn.clicked.connect(self._on_new_skill)
        open_folder_btn = QPushButton("Open Skills Directory")
        open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder_btn.clicked.connect(self._on_open_skills_dir)
        reload_skills_btn = QPushButton("Reload")
        reload_skills_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reload_skills_btn.clicked.connect(self.refresh_skills)

        skills_btn_row.addWidget(new_skill_btn)
        skills_btn_row.addWidget(open_folder_btn)
        skills_btn_row.addWidget(reload_skills_btn)
        skills_btn_row.addStretch()
        layout.addLayout(skills_btn_row)

        self.refresh_skills()

    def _on_tool_toggle(self, tool_name: str, enabled: bool) -> None:
        if self.tool_registry:
            self.tool_registry.set_tool_enabled(tool_name, enabled)
            self.config_changed.emit()

    def _on_ws_text_changed(self, text: str) -> None:
        folder = text.strip()
        if folder and Path(folder).exists() and self.tool_registry:
            self.tool_registry.set_workspace_folder(folder)
            settings = get_app_settings()
            settings.setValue("workspace_folder", folder)
            settings.sync()
            self.config_changed.emit()

    def _on_browse(self) -> None:
        current = self.ws_input.text() or str(Path.cwd())
        folder = QFileDialog.getExistingDirectory(self, "Select Workspace Folder", current)
        if folder:
            self.ws_input.setText(folder)
            if self.tool_registry:
                self.tool_registry.set_workspace_folder(folder)
                settings = get_app_settings()
                settings.setValue("workspace_folder", folder)
                settings.sync()
                self.config_changed.emit()

    def refresh_skills(self) -> None:
        """Reload and render installed skills in the table."""
        if not self.skill_loader:
            return

        self.skill_loader.reload()
        skills = self.skill_loader.list_skills()
        self.skills_table.setRowCount(len(skills))

        for row, skill in enumerate(skills):
            self.skills_table.setRowHeight(row, 48)
            name_item = QTableWidgetItem(skill.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.skills_table.setItem(row, 0, name_item)

            desc_item = QTableWidgetItem(skill.description)
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.skills_table.setItem(row, 1, desc_item)

            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(4, 0, 8, 0)
            actions_layout.setSpacing(8)
            actions_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

            view_btn = QPushButton("View")
            view_btn.setObjectName("skillActionBtn")
            view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            view_btn.setFixedHeight(28)
            view_btn.setMinimumWidth(64)
            view_btn.setStyleSheet(
                "QPushButton { background-color: #27272a; color: #f4f4f6; border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 6px; padding: 0 8px; font-size: 12px; font-weight: 500; } QPushButton:hover { background-color: #3f3f46; color: #ffffff; border-color: rgba(255, 255, 255, 0.25); }"
            )
            view_btn.clicked.connect(lambda _, s=skill: self._view_skill(s))
            actions_layout.addWidget(view_btn)

            del_btn = QPushButton("Delete")
            del_btn.setObjectName("skillActionBtn")
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setFixedHeight(28)
            del_btn.setMinimumWidth(64)
            del_btn.setStyleSheet(
                "QPushButton { background-color: #27272a; color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.25); border-radius: 6px; padding: 0 8px; font-size: 12px; font-weight: 500; } QPushButton:hover { background-color: rgba(239, 68, 68, 0.15); color: #ef4444; border-color: rgba(239, 68, 68, 0.45); }"
            )
            del_btn.clicked.connect(lambda _, s=skill: self._delete_skill(s))
            actions_layout.addWidget(del_btn)

            self.skills_table.setCellWidget(row, 2, actions_widget)

    def _view_skill(self, skill: Any) -> None:
        from modelmesh.ui.skill_detail_dialog import SkillDetailDialog

        if self.skill_loader:
            dlg = SkillDetailDialog(skill=skill, loader=self.skill_loader, parent=self)
            dlg.exec()
            self.refresh_skills()
            self.config_changed.emit()

    def _delete_skill(self, skill: Any) -> None:
        reply = QMessageBox.question(
            self,
            "Delete Skill",
            f"Are you sure you want to delete skill '{skill.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self.skill_loader:
                self.skill_loader.delete_skill(skill.name)
            self.refresh_skills()
            self.config_changed.emit()

    def _on_new_skill(self) -> None:
        skills_dir = self.skill_loader.skills_dir if self.skill_loader else Path.cwd() / "skills"
        dlg = CreateSkillDialog(skills_dir=skills_dir, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh_skills()
            self.config_changed.emit()

    def _on_open_skills_dir(self) -> None:
        skills_dir = self.skill_loader.skills_dir if self.skill_loader else Path.cwd() / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(skills_dir.resolve())))
