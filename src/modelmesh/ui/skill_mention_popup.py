"""Autocomplete mention popup for selecting skills via '@' in the composer."""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.skills import Skill, SkillLoader


class SkillMentionItemWidget(QWidget):
    """Custom widget for rendering skill name and description in the mention list."""

    def __init__(self, name: str, description: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        name_lbl = QLabel(name)
        name_lbl.setObjectName("skillMentionItemName")
        layout.addWidget(name_lbl)

        clean_desc = description.strip()
        if len(clean_desc) > 65:
            clean_desc = clean_desc[:62] + "..."
        desc_lbl = QLabel(clean_desc)
        desc_lbl.setObjectName("skillMentionItemDesc")
        desc_lbl.setWordWrap(False)
        layout.addWidget(desc_lbl)


class SkillMentionPopup(QFrame):
    """Floating mention popup anchored above the composer input."""

    skill_selected = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("skillMentionPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.loader: Optional[SkillLoader] = None
        self._skills: List[Skill] = []

        self._init_ui()

    def _init_ui(self) -> None:
        self.setFixedWidth(300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # List of matching skills
        self.list_widget = QListWidget()
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget)

        # Bottom status bar
        footer = QWidget()
        footer.setObjectName("skillMentionFooter")
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 4, 10, 4)

        close_lbl = QLabel("Close menu")
        close_lbl.setObjectName("skillMentionCloseLbl")
        footer_layout.addWidget(close_lbl)
        footer_layout.addStretch()

        esc_badge = QLabel("ESC")
        esc_badge.setObjectName("skillMentionEscBadge")
        footer_layout.addWidget(esc_badge)

        layout.addWidget(footer)

    def set_skill_loader(self, loader: Optional[SkillLoader]) -> None:
        """Set the SkillLoader instance for fetching available skills."""
        self.loader = loader

    def filter(self, query: str) -> bool:
        """Filter skills by search query and populate the list. Returns True if items found."""
        if not self.loader:
            return False

        skills = self.loader.list_skills(only_enabled=True)
        query_clean = query.strip().lower()

        matches = []
        for s in skills:
            if not query_clean or query_clean in s.name.lower() or query_clean in s.description.lower():
                matches.append(s)

        self.list_widget.clear()
        if not matches:
            self.hide()
            return False

        # Limit to top 6 matches for sleek height
        displayed_matches = matches[:6]
        for skill in displayed_matches:
            item = QListWidgetItem(self.list_widget)
            item.setData(Qt.ItemDataRole.UserRole, skill.name)
            item_widget = SkillMentionItemWidget(skill.name, skill.description)
            item.setSizeHint(item_widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, item_widget)

        self.list_widget.setCurrentRow(0)

        # Dynamic height calculation
        item_height = 46
        total_height = min(280, len(displayed_matches) * item_height + 42)
        self.setFixedHeight(total_height)
        return True

    def select_next(self) -> None:
        """Move selection to the next item."""
        count = self.list_widget.count()
        if count > 0:
            next_row = (self.list_widget.currentRow() + 1) % count
            self.list_widget.setCurrentRow(next_row)

    def select_prev(self) -> None:
        """Move selection to the previous item."""
        count = self.list_widget.count()
        if count > 0:
            prev_row = (self.list_widget.currentRow() - 1 + count) % count
            self.list_widget.setCurrentRow(prev_row)

    def confirm_selection(self) -> Optional[str]:
        """Confirm currently selected item, emit signal and hide."""
        current_item = self.list_widget.currentItem()
        if current_item:
            skill_name = current_item.data(Qt.ItemDataRole.UserRole)
            if skill_name:
                self.skill_selected.emit(skill_name)
                self.hide()
                return skill_name
        self.hide()
        return None

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        skill_name = item.data(Qt.ItemDataRole.UserRole)
        if skill_name:
            self.skill_selected.emit(skill_name)
            self.hide()

    def show_above(self, anchor_widget: QWidget) -> None:
        """Position and show the popup directly above the target widget."""
        global_pos = anchor_widget.mapToGlobal(QPoint(0, 0))
        target_x = global_pos.x() + 12
        target_y = global_pos.y() - self.height() - 8
        self.move(target_x, target_y)
        self.show()
        self.raise_()
