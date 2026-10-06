"""Sidebar widget managing conversation list, skills navigation, search, and actions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SidebarWidget(QWidget):
    """Left sidebar with conversation history list, skills & tools navigation, and settings."""

    conversation_selected = pyqtSignal(str)
    new_chat_requested = pyqtSignal()
    skills_requested = pyqtSignal()
    tools_requested = pyqtSignal()
    delete_conversation_requested = pyqtSignal(str)
    rename_conversation_requested = pyqtSignal(str, str)
    settings_requested = pyqtSignal()
    usage_requested = pyqtSignal()
    router_lab_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(260)

        self._all_conversations: List[Dict[str, Any]] = []
        self._active_view: str = "chat"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Header (Brand + New Chat + Skills & Tools Nav)
        header_widget = QWidget()
        header_widget.setObjectName("sidebarHeader")
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(14, 14, 14, 8)
        header_layout.setSpacing(8)

        brand_layout = QHBoxLayout()
        brand_title = QLabel("ModelMesh")
        brand_title.setObjectName("brandTitle")
        brand_layout.addWidget(brand_title)
        brand_layout.addStretch()
        header_layout.addLayout(brand_layout)

        new_chat_btn = QPushButton("+ New chat")
        new_chat_btn.setObjectName("newChatBtn")
        new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_chat_btn.clicked.connect(self._on_new_chat_clicked)
        header_layout.addWidget(new_chat_btn)

        # Shortcut Ctrl+N
        shortcut_new = QShortcut(QKeySequence("Ctrl+N"), self)
        shortcut_new.activated.connect(self._on_new_chat_clicked)

        # Navigation Buttons (Skills & Tools)
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)

        self.skills_nav_btn = QPushButton("Skills")
        self.skills_nav_btn.setObjectName("sidebarSkillsBtn")
        self.skills_nav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skills_nav_btn.clicked.connect(self._on_skills_clicked)
        nav_row.addWidget(self.skills_nav_btn)

        self.tools_nav_btn = QPushButton("Tools")
        self.tools_nav_btn.setObjectName("sidebarToolsBtn")
        self.tools_nav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tools_nav_btn.clicked.connect(self._on_tools_clicked)
        nav_row.addWidget(self.tools_nav_btn)

        header_layout.addLayout(nav_row)

        # Search box
        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText("Search chats...")
        self.search_box.textChanged.connect(self._filter_conversations)
        header_layout.addWidget(self.search_box)

        layout.addWidget(header_widget)

        # Section Header
        section_label = QLabel("Recent")
        section_label.setObjectName("sidebarSectionLabel")
        layout.addWidget(section_label)

        # 2. Conversation List
        self.conv_list = QListWidget()
        self.conv_list.setObjectName("conversationList")
        self.conv_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.conv_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.conv_list.setWordWrap(False)
        self.conv_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.conv_list.customContextMenuRequested.connect(self._show_context_menu)
        self.conv_list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.conv_list, stretch=1)

        # 3. Footer (Usage, Router Lab, Settings)
        footer_widget = QWidget()
        footer_widget.setObjectName("sidebarFooter")
        footer_layout = QVBoxLayout(footer_widget)
        footer_layout.setContentsMargins(8, 8, 8, 8)
        footer_layout.setSpacing(2)

        usage_btn = QPushButton("Usage Dashboard")
        usage_btn.setProperty("class", "sidebarActionBtn")
        usage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        usage_btn.clicked.connect(self.usage_requested)
        footer_layout.addWidget(usage_btn)

        lab_btn = QPushButton("Router Lab")
        lab_btn.setProperty("class", "sidebarActionBtn")
        lab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lab_btn.clicked.connect(self.router_lab_requested)
        footer_layout.addWidget(lab_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.setProperty("class", "sidebarActionBtn")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(self.settings_requested)
        footer_layout.addWidget(settings_btn)

        layout.addWidget(footer_widget)

    def set_active_view(self, view_name: str) -> None:
        """Update active navigation highlight between 'chat', 'skills', and 'tools'."""
        self._active_view = view_name
        self.skills_nav_btn.setProperty("active", "true" if view_name == "skills" else "false")
        self.tools_nav_btn.setProperty("active", "true" if view_name == "tools" else "false")
        if view_name in ("skills", "tools"):
            self.conv_list.clearSelection()

        self.skills_nav_btn.style().unpolish(self.skills_nav_btn)
        self.skills_nav_btn.style().polish(self.skills_nav_btn)
        self.tools_nav_btn.style().unpolish(self.tools_nav_btn)
        self.tools_nav_btn.style().polish(self.tools_nav_btn)

    def _on_skills_clicked(self) -> None:
        self.set_active_view("skills")
        self.skills_requested.emit()

    def _on_tools_clicked(self) -> None:
        self.set_active_view("tools")
        self.tools_requested.emit()

    def _on_new_chat_clicked(self) -> None:
        self.set_active_view("chat")
        self.new_chat_requested.emit()

    def set_conversations(
        self,
        conversations: List[Dict[str, Any]],
        selected_id: Optional[str] = None,
    ) -> None:
        """Update the conversation list display."""
        self._all_conversations = list(conversations)
        self._filter_conversations(self.search_box.text(), selected_id=selected_id)

    def _filter_conversations(
        self,
        query: str,
        selected_id: Optional[str] = None,
    ) -> None:
        """Filter conversations by search query."""
        self.conv_list.clear()
        query_lower = query.strip().lower()

        for conv in self._all_conversations:
            title = conv.get("title") or "New Conversation"
            if query_lower and query_lower not in title.lower():
                continue

            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, conv.get("id"))
            item.setToolTip(f"{title}\nCreated: {conv.get('created_at', '')}")
            self.conv_list.addItem(item)

            if selected_id and conv.get("id") == selected_id:
                item.setSelected(True)
                self.conv_list.setCurrentItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.set_active_view("chat")
        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if conv_id:
            self.conversation_selected.emit(conv_id)

    def _show_context_menu(self, pos: Any) -> None:
        item = self.conv_list.itemAt(pos)
        if not item:
            return

        conv_id = item.data(Qt.ItemDataRole.UserRole)
        if not conv_id:
            return

        menu = QMenu(self)
        rename_act = QAction("Rename", self)
        rename_act.triggered.connect(lambda: self._prompt_rename(conv_id, item.text()))
        menu.addAction(rename_act)

        delete_act = QAction("Delete", self)
        delete_act.triggered.connect(lambda: self._prompt_delete(conv_id))
        menu.addAction(delete_act)

        menu.exec(self.conv_list.mapToGlobal(pos))

    def _prompt_rename(self, conv_id: str, current_title: str) -> None:
        new_title, ok = QInputDialog.getText(
            self,
            "Rename Conversation",
            "Enter new title:",
            text=current_title,
        )
        if ok and new_title.strip():
            self.rename_conversation_requested.emit(conv_id, new_title.strip())

    def _prompt_delete(self, conv_id: str) -> None:
        reply = QMessageBox.question(
            self,
            "Delete Conversation",
            "Are you sure you want to delete this conversation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_conversation_requested.emit(conv_id)
