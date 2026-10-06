"""Dedicated Skills workspace view with professional layout and clean management."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.engine import ChatEngine
from modelmesh.core.skills import Skill, SkillLoader
from modelmesh.ui.skill_detail_dialog import SkillDetailDialog


class SkillCard(QFrame):
    """Visual card displaying a skill, sub-resources, and management actions."""

    toggled = pyqtSignal(str, bool)
    view_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, skill: Skill, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.skill = skill
        self.setObjectName("skillCard")
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # Left Letter Badge
        initial = self.skill.name[:1].upper() if self.skill.name else "S"
        badge_lbl = QLabel(initial)
        badge_lbl.setObjectName("skillCardInitialBadge")
        badge_lbl.setFixedSize(36, 36)
        badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(badge_lbl)

        # Middle Content
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        name_lbl = QLabel(self.skill.name)
        name_lbl.setObjectName("skillCardTitle")
        title_row.addWidget(name_lbl)

        title_row.addStretch()
        content_layout.addLayout(title_row)

        desc_lbl = QLabel(self.skill.description)
        desc_lbl.setObjectName("skillCardDesc")
        desc_lbl.setWordWrap(True)
        content_layout.addWidget(desc_lbl)

        layout.addWidget(content_widget, stretch=1)

        # Right Actions
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        # Toggle Active Button
        self.toggle_btn = QPushButton("Active" if self.skill.enabled else "Disabled")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(self.skill.enabled)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_toggle_style()
        self.toggle_btn.clicked.connect(self._on_toggle)
        actions_layout.addWidget(self.toggle_btn)

        # View / Edit Button
        view_btn = QPushButton("View")
        view_btn.setObjectName("skillCardActionBtn")
        view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_btn.clicked.connect(lambda: self.view_requested.emit(self.skill.name))
        actions_layout.addWidget(view_btn)

        # Delete Button
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("skillCardDeleteBtn")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.skill.name))
        actions_layout.addWidget(del_btn)

        layout.addWidget(actions_widget)

    def _update_toggle_style(self) -> None:
        if self.toggle_btn.isChecked():
            self.toggle_btn.setText("Active")
            self.toggle_btn.setStyleSheet(
                "QPushButton { background-color: rgba(16, 185, 129, 0.15); color: #34d399; "
                "border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 6px; padding: 4px 10px; font-size: 11.5px; font-weight: 500; } "
                "QPushButton:hover { background-color: rgba(16, 185, 129, 0.25); }"
            )
        else:
            self.toggle_btn.setText("Disabled")
            self.toggle_btn.setStyleSheet(
                "QPushButton { background-color: rgba(255, 255, 255, 0.04); color: #71717a; "
                "border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 6px; padding: 4px 10px; font-size: 11.5px; font-weight: 500; } "
                "QPushButton:hover { background-color: rgba(255, 255, 255, 0.08); color: #a1a1aa; }"
            )

    def _on_toggle(self) -> None:
        is_active = self.toggle_btn.isChecked()
        self._update_toggle_style()
        self.toggled.emit(self.skill.name, is_active)


class SkillsView(QWidget):
    """Full-page workspace view for managing and browsing skills."""

    skills_changed = pyqtSignal()
    back_to_chat_requested = pyqtSignal()

    def __init__(
        self,
        engine: ChatEngine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        if getattr(engine, "skill_loader", None) is not None:
            self.loader: SkillLoader = engine.skill_loader
        else:
            self.loader = SkillLoader()
        self._current_filter: str = "all"  # "all" or "active"

        self._init_ui()
        self.refresh_skills()

    def _init_ui(self) -> None:
        self.setObjectName("skillsView")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(36, 32, 36, 24)
        main_layout.setSpacing(20)

        # 1. Header Section
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        title_lbl = QLabel("Skills")
        title_lbl.setObjectName("skillsHeaderTitle")
        title_col.addWidget(title_lbl)

        subtitle_lbl = QLabel(
            "Skills are instructions ModelMesh can reuse. Set them up once, then call on them anytime."
        )
        subtitle_lbl.setObjectName("skillsHeaderSubtitle")
        title_col.addWidget(subtitle_lbl)

        header_layout.addLayout(title_col, stretch=1)

        # Action Buttons: Import Menu and + New skill
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(10)

        self.import_btn = QPushButton("Import")
        self.import_btn.setObjectName("skillImportBtn")
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        import_menu = QMenu(self)
        action_file = import_menu.addAction("Upload skill file")
        action_file.triggered.connect(self._on_import_file)
        action_folder = import_menu.addAction("Upload skill folder")
        action_folder.triggered.connect(self._on_import_folder)
        self.import_btn.setMenu(import_menu)
        actions_layout.addWidget(self.import_btn)

        self.new_btn = QPushButton("+ New skill")
        self.new_btn.setObjectName("skillNewBtn")
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.clicked.connect(self._on_new_skill)
        actions_layout.addWidget(self.new_btn)

        header_layout.addLayout(actions_layout)
        main_layout.addWidget(header_widget)

        # 2. Filter Tabs and Search Bar
        filter_bar = QWidget()
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(12)

        # Filter Pills: "All Skills" and "Active"
        pills_layout = QHBoxLayout()
        pills_layout.setSpacing(6)
        self.pill_group = QButtonGroup(self)

        self.pill_all = QPushButton("All")
        self.pill_all.setCheckable(True)
        self.pill_all.setChecked(True)
        self.pill_all.setProperty("class", "skillFilterPill")
        self.pill_all.clicked.connect(lambda: self._set_filter("all"))
        self.pill_group.addButton(self.pill_all)
        pills_layout.addWidget(self.pill_all)

        self.pill_active = QPushButton("Active")
        self.pill_active.setCheckable(True)
        self.pill_active.setProperty("class", "skillFilterPill")
        self.pill_active.clicked.connect(lambda: self._set_filter("active"))
        self.pill_group.addButton(self.pill_active)
        pills_layout.addWidget(self.pill_active)

        filter_layout.addLayout(pills_layout)
        filter_layout.addStretch()

        # Search Box
        self.search_box = QLineEdit()
        self.search_box.setObjectName("skillSearchBox")
        self.search_box.setPlaceholderText("Search for skills...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_filter)
        self.search_box.setFixedWidth(280)
        filter_layout.addWidget(self.search_box)

        main_layout.addWidget(filter_bar)

        # 3. Skills Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("skillsScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.cards_container = QWidget()
        self.cards_container.setObjectName("skillsCardsContainer")
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch()

        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area, stretch=1)

    def _set_filter(self, filter_type: str) -> None:
        self._current_filter = filter_type
        self._apply_filter()

    def refresh_skills(self) -> None:
        """Reload skills from disk and update the UI."""
        if self.loader:
            self.loader.reload()
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Filter skills by search query and active tab."""
        # Clear existing cards
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        query = self.search_box.text().strip().lower()
        skills = self.loader.list_skills()

        filtered: List[Skill] = []
        for s in skills:
            if self._current_filter == "active" and not s.enabled:
                continue
            if query:
                in_name = query in s.name.lower()
                in_desc = query in s.description.lower()
                in_res = any(query in r.lower() for r in s.resources.keys())
                if not (in_name or in_desc or in_res):
                    continue
            filtered.append(s)

        if not filtered:
            empty_lbl = QLabel("No matching skills found.")
            empty_lbl.setStyleSheet("color: #71717a; font-size: 13px; padding: 30px; text-align: center;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cards_layout.insertWidget(0, empty_lbl)
            return

        for idx, skill in enumerate(filtered):
            card = SkillCard(skill, self.cards_container)
            card.toggled.connect(self._on_skill_toggled)
            card.view_requested.connect(self._on_view_skill)
            card.delete_requested.connect(self._on_delete_skill)
            self.cards_layout.insertWidget(idx, card)

    def _on_skill_toggled(self, name: str, enabled: bool) -> None:
        self.loader.set_enabled(name, enabled)
        self.skills_changed.emit()

    def _on_view_skill(self, name: str) -> None:
        skill = self.loader.get_skill(name)
        if skill:
            dlg = SkillDetailDialog(skill=skill, loader=self.loader, parent=self)
            dlg.exec()
            self.refresh_skills()
            self.skills_changed.emit()

    def _on_delete_skill(self, name: str) -> None:
        reply = QMessageBox.question(
            self,
            "Delete Skill",
            f"Are you sure you want to permanently delete skill '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.loader.delete_skill(name)
            self.refresh_skills()
            self.skills_changed.emit()

    def _on_import_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Skill File",
            "",
            "Markdown / YAML (*.md *.yaml *.yml);;All Files (*)",
        )
        if file_path:
            imported = self.loader.import_skill_file(Path(file_path))
            if imported:
                self.refresh_skills()
                self.skills_changed.emit()
                QMessageBox.information(self, "Skill Imported", f"Imported skill: '{imported.name}'")
            else:
                QMessageBox.warning(self, "Import Failed", "Failed to parse or import the skill file.")

    def _on_import_folder(self) -> None:
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Skill Directory (containing SKILL.md)",
        )
        if folder_path:
            imported = self.loader.import_skill_folder(Path(folder_path))
            if imported:
                self.refresh_skills()
                self.skills_changed.emit()
                QMessageBox.information(
                    self,
                    "Skill Folder Imported",
                    f"Imported skill: '{imported.name}' with {len(imported.resources)} files.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Import Failed",
                    "The selected folder must contain a valid SKILL.md file.",
                )

    def _on_new_skill(self) -> None:
        from modelmesh.ui.settings.tools_tab import CreateSkillDialog

        dlg = CreateSkillDialog(skills_dir=self.loader.skills_dir, parent=self)
        if dlg.exec() == CreateSkillDialog.DialogCode.Accepted:
            self.refresh_skills()
            self.skills_changed.emit()
