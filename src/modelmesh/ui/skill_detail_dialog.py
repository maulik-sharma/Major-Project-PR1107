"""Skill detail viewer and editor dialog supporting arbitrary subfolder hierarchies."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.skills import Skill, SkillLoader


class SkillDetailDialog(QDialog):
    """Modal dialog for viewing, editing, and managing arbitrary subfolders and files in a skill."""

    def __init__(
        self,
        skill: Skill,
        loader: SkillLoader,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.skill = skill
        self.loader = loader
        self.setWindowTitle(f"Skill: {skill.name}")
        self.resize(920, 600)

        self._modified_files: Dict[str, str] = {}
        self._current_file_key: str = "SKILL.md"

        self._init_ui()
        self._load_file_tree()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        # Header Info
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_lbl = QLabel(self.skill.name)
        title_lbl.setStyleSheet("font-size: 17px; font-weight: 600; color: #f4f4f6;")
        title_row.addWidget(title_lbl)

        if self.skill.resources:
            badge = QLabel(f"{len(self.skill.resources) + 1} files")
            badge.setStyleSheet(
                "background-color: rgba(255, 255, 255, 0.08); color: #a1a1aa; "
                "padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500;"
            )
            title_row.addWidget(badge)

        title_row.addStretch()

        open_folder_btn = QPushButton("Open Folder")
        open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.06); color: #a1a1aa; "
            "border: 1px solid rgba(255,255,255,0.1); border-radius: 5px; padding: 4px 10px; font-size: 12px; } "
            "QPushButton:hover { background: rgba(255,255,255,0.12); color: #ffffff; }"
        )
        open_folder_btn.clicked.connect(self._open_folder)
        title_row.addWidget(open_folder_btn)

        header_layout.addLayout(title_row)

        desc_lbl = QLabel(self.skill.description)
        desc_lbl.setStyleSheet("color: #a1a1aa; font-size: 12.5px;")
        desc_lbl.setWordWrap(True)
        header_layout.addWidget(desc_lbl)

        layout.addWidget(header_widget)

        # Main Splitter: Left Tree Navigator, Right Editor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: File Tree Navigator
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        tree_header = QLabel("Files & Subfolders")
        tree_header.setStyleSheet("font-size: 12px; font-weight: 600; color: #a1a1aa; text-transform: uppercase;")
        left_layout.addWidget(tree_header)

        self.file_tree = QTreeWidget()
        self.file_tree.setObjectName("skillFileTree")
        self.file_tree.setHeaderHidden(True)
        self.file_tree.itemClicked.connect(self._on_tree_item_clicked)
        left_layout.addWidget(self.file_tree, stretch=1)

        tree_btns_layout = QHBoxLayout()
        tree_btns_layout.setSpacing(6)

        add_file_btn = QPushButton("+ New File")
        add_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_file_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.05); color: #d4d4d8; "
            "border: 1px solid rgba(255,255,255,0.12); border-radius: 5px; padding: 5px 8px; font-size: 11.5px; } "
            "QPushButton:hover { background: rgba(255,255,255,0.1); color: #ffffff; }"
        )
        add_file_btn.clicked.connect(self._add_file)
        tree_btns_layout.addWidget(add_file_btn)

        del_file_btn = QPushButton("Delete")
        del_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_file_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.04); color: #fca5a5; "
            "border: 1px solid rgba(239,68,68,0.2); border-radius: 5px; padding: 5px 8px; font-size: 11.5px; } "
            "QPushButton:hover { background: rgba(239,68,68,0.15); color: #ef4444; }"
        )
        del_file_btn.clicked.connect(self._delete_selected_file)
        tree_btns_layout.addWidget(del_file_btn)

        left_layout.addLayout(tree_btns_layout)
        splitter.addWidget(left_widget)

        # Right: Content Editor
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.current_file_lbl = QLabel("SKILL.md")
        self.current_file_lbl.setStyleSheet("color: #71717a; font-size: 12px; font-family: monospace;")
        right_layout.addWidget(self.current_file_lbl)

        self.editor = QTextEdit()
        self.editor.setObjectName("skillFileEditor")
        self.editor.setFontFamily("monospace")
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.editor.textChanged.connect(self._on_text_changed)
        right_layout.addWidget(self.editor, stretch=1)

        splitter.addWidget(right_widget)
        splitter.setSizes([260, 620])

        layout.addWidget(splitter, stretch=1)

        # Bottom Action Bar
        button_row = QHBoxLayout()
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #10b981; font-size: 12px;")
        button_row.addWidget(self.status_lbl)
        button_row.addStretch()

        self.save_btn = QPushButton("Save Changes")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: #ffffff; border: none; "
            "border-radius: 6px; padding: 6px 16px; font-size: 12.5px; font-weight: 500; } "
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.save_btn.clicked.connect(self._save_changes)
        button_row.addWidget(self.save_btn)

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)

        layout.addLayout(button_row)

    def _load_file_tree(self) -> None:
        """Populate the tree widget reflecting the full nested directory hierarchy."""
        self.file_tree.clear()

        # Primary SKILL.md root item
        main_item = QTreeWidgetItem(self.file_tree, ["SKILL.md (Instructions)"])
        main_item.setData(0, Qt.ItemDataRole.UserRole, "SKILL.md")
        main_item.setData(0, Qt.ItemDataRole.UserRole + 1, "file")

        # Map to track folder tree items: rel_dir_path -> QTreeWidgetItem
        folder_items: Dict[str, QTreeWidgetItem] = {}

        # Scan all sub-resources and group by directory path
        for rel_path in sorted(self.skill.resources.keys()):
            parts = Path(rel_path).parts
            # Ensure all parent directory tree items exist
            current_parent = None
            accum_path = ""
            for i in range(len(parts) - 1):
                dir_name = parts[i]
                accum_path = f"{accum_path}/{dir_name}" if accum_path else dir_name
                if accum_path not in folder_items:
                    if current_parent is None:
                        dir_item = QTreeWidgetItem(self.file_tree, [f"{dir_name}/"])
                    else:
                        dir_item = QTreeWidgetItem(current_parent, [f"{dir_name}/"])
                    dir_item.setData(0, Qt.ItemDataRole.UserRole, accum_path)
                    dir_item.setData(0, Qt.ItemDataRole.UserRole + 1, "dir")
                    dir_item.setExpanded(True)
                    folder_items[accum_path] = dir_item
                current_parent = folder_items[accum_path]

            # Add file item under its parent folder (or root)
            filename = parts[-1]
            if current_parent is not None:
                file_item = QTreeWidgetItem(current_parent, [filename])
            else:
                file_item = QTreeWidgetItem(self.file_tree, [filename])
            file_item.setData(0, Qt.ItemDataRole.UserRole, rel_path)
            file_item.setData(0, Qt.ItemDataRole.UserRole + 1, "file")

        self.file_tree.expandAll()
        self.file_tree.setCurrentItem(main_item)
        self._load_file_content("SKILL.md")

    def _load_file_content(self, file_key: str) -> None:
        """Load file content into editor for the specified relative path."""
        self._current_file_key = file_key
        self.current_file_lbl.setText(f"Editing: {file_key}")

        if file_key in self._modified_files:
            content = self._modified_files[file_key]
        elif file_key == "SKILL.md":
            try:
                content = self.skill.path.read_text(encoding="utf-8")
            except Exception:
                content = self.skill.body
        else:
            content = self.skill.get_resource(file_key) or ""

        self.editor.blockSignals(True)
        self.editor.setPlainText(content)
        self.editor.blockSignals(False)

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        item_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        file_key = item.data(0, Qt.ItemDataRole.UserRole)
        if item_type == "file" and file_key:
            self._load_file_content(file_key)

    def _on_text_changed(self) -> None:
        self._modified_files[self._current_file_key] = self.editor.toPlainText()
        self.status_lbl.setText("Unsaved changes")
        self.status_lbl.setStyleSheet("color: #f59e0b; font-size: 12px;")

    def _save_changes(self) -> None:
        """Write all modified files to disk and reload skill."""
        for key, text in self._modified_files.items():
            if key == "SKILL.md":
                self.skill.path.write_text(text, encoding="utf-8")
            else:
                target = self.skill.folder_path / key
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")

        self._modified_files.clear()
        self.loader.reload()
        reloaded = self.loader.get_skill(self.skill.name)
        if reloaded:
            self.skill = reloaded

        self.status_lbl.setText("All changes saved")
        self.status_lbl.setStyleSheet("color: #10b981; font-size: 12px;")

    def _add_file(self) -> None:
        rel_path, ok = QInputDialog.getText(
            self,
            "Create File in Skill",
            "Enter relative path (e.g. scripts/setup.py, docs/guide.md):",
        )
        if ok and rel_path.strip():
            clean_rel = os.path.normpath(rel_path.strip()).lstrip("/\\")
            if clean_rel == "SKILL.md":
                QMessageBox.warning(self, "Invalid Path", "SKILL.md already exists as the root instruction file.")
                return

            target = self.skill.folder_path / clean_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text(f"# {Path(clean_rel).name}\n\n", encoding="utf-8")

            self.loader.reload()
            reloaded = self.loader.get_skill(self.skill.name)
            if reloaded:
                self.skill = reloaded

            self._load_file_tree()
            self._load_file_content(clean_rel)

    def _delete_selected_file(self) -> None:
        item = self.file_tree.currentItem()
        if not item:
            return

        item_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        rel_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not rel_path or rel_path == "SKILL.md":
            QMessageBox.warning(self, "Cannot Delete", "SKILL.md is the main entrypoint and cannot be deleted.")
            return

        reply = QMessageBox.question(
            self,
            "Delete File",
            f"Are you sure you want to delete '{rel_path}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            target = self.skill.folder_path / rel_path
            if target.exists():
                if target.is_file():
                    target.unlink()
                elif target.is_dir():
                    import shutil
                    shutil.rmtree(target)

            self._modified_files.pop(rel_path, None)
            self.loader.reload()
            reloaded = self.loader.get_skill(self.skill.name)
            if reloaded:
                self.skill = reloaded

            self._load_file_tree()

    def _open_folder(self) -> None:
        folder = str(self.skill.folder_path.resolve())
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            QMessageBox.information(self, "Folder Location", f"Skill directory: {folder}")
