"""Dedicated Tools workspace view with clean management, filtering, toggles, and workspace configuration."""

from __future__ import annotations

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
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.engine import ChatEngine
from modelmesh.core.tools.registry import ToolRegistry
from modelmesh.core.types import ToolSpec
from modelmesh.ui.settings.tools_tab import get_app_settings
from modelmesh.ui.tool_detail_dialog import ToolDetailDialog


class ToolCard(QFrame):
    """Visual card displaying a tool specification, description, active toggle, and View action."""

    toggled = pyqtSignal(str, bool)
    details_requested = pyqtSignal(str)

    def __init__(
        self,
        spec: ToolSpec,
        enabled: bool,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.spec = spec
        self.enabled = enabled
        self.setObjectName("toolCard")
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        # 1. Left Letter Badge
        initial = self.spec.name[:1].upper() if self.spec.name else "T"
        badge_lbl = QLabel(initial)
        badge_lbl.setObjectName("toolCardInitialBadge")
        badge_lbl.setFixedSize(36, 36)
        badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(badge_lbl)

        # 2. Middle Content
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        name_lbl = QLabel(self.spec.name)
        name_lbl.setObjectName("toolCardTitle")
        title_row.addWidget(name_lbl)
        title_row.addStretch()
        content_layout.addLayout(title_row)

        desc_lbl = QLabel(self.spec.description)
        desc_lbl.setObjectName("toolCardDesc")
        desc_lbl.setWordWrap(True)
        content_layout.addWidget(desc_lbl)

        layout.addWidget(content_widget, stretch=1)

        # 3. Right Actions
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        # Toggle Button
        self.toggle_btn = QPushButton("Active" if self.enabled else "Disabled")
        self.toggle_btn.setObjectName("toolToggleBtn")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(self.enabled)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_toggle_style()
        self.toggle_btn.clicked.connect(self._on_toggle)
        actions_layout.addWidget(self.toggle_btn)

        # View Button
        view_btn = QPushButton("View")
        view_btn.setObjectName("toolCardActionBtn")
        view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_btn.clicked.connect(lambda: self.details_requested.emit(self.spec.name))
        actions_layout.addWidget(view_btn)

        layout.addWidget(actions_widget)

    def _update_toggle_style(self) -> None:
        is_active = self.toggle_btn.isChecked()
        self.toggle_btn.setText("Active" if is_active else "Disabled")
        self.toggle_btn.setProperty("active", "true" if is_active else "false")
        if self.toggle_btn.style():
            self.toggle_btn.style().unpolish(self.toggle_btn)
            self.toggle_btn.style().polish(self.toggle_btn)

    def _on_toggle(self) -> None:
        is_active = self.toggle_btn.isChecked()
        self._update_toggle_style()
        self.toggled.emit(self.spec.name, is_active)


class ToolsView(QWidget):
    """Full-page workspace view for managing and configuring tools."""

    tools_changed = pyqtSignal()
    back_to_chat_requested = pyqtSignal()

    def __init__(
        self,
        engine: ChatEngine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self.registry: ToolRegistry = (
            engine.tool_registry if getattr(engine, "tool_registry", None) is not None
            else ToolRegistry()
        )
        self._current_filter: str = "all"  # "all" or "active"

        self._load_saved_settings()
        self._init_ui()
        self.refresh_tools()

    def _load_saved_settings(self) -> None:
        """Load workspace directory and tool states from persistent settings."""
        settings = get_app_settings()
        saved_ws = settings.value("workspace_folder")
        if saved_ws and Path(saved_ws).exists():
            self.registry.set_workspace_folder(str(saved_ws))

        # Restore disabled tools if saved
        saved_disabled = settings.value("disabled_tools")
        if saved_disabled and isinstance(saved_disabled, list):
            for tool_name in saved_disabled:
                if isinstance(tool_name, str):
                    self.registry.set_tool_enabled(tool_name, False)

    def _init_ui(self) -> None:
        self.setObjectName("toolsView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(36, 32, 36, 24)
        main_layout.setSpacing(18)

        # 1. Header Section
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        title_lbl = QLabel("Tools")
        title_lbl.setObjectName("toolsHeaderTitle")
        title_col.addWidget(title_lbl)

        subtitle_lbl = QLabel(
            "Manage tools and capabilities that LLMs can invoke during conversations."
        )
        subtitle_lbl.setObjectName("toolsHeaderSubtitle")
        title_col.addWidget(subtitle_lbl)

        header_layout.addLayout(title_col, stretch=1)
        main_layout.addWidget(header_widget)

        # 2. Workspace Directory Bar
        ws_card = QFrame()
        ws_card.setObjectName("toolsWorkspaceCard")
        ws_layout = QHBoxLayout(ws_card)
        ws_layout.setContentsMargins(14, 10, 14, 10)
        ws_layout.setSpacing(10)

        ws_label = QLabel("Workspace Directory:")
        ws_label.setObjectName("toolsWorkspaceLabel")
        ws_layout.addWidget(ws_label)

        self.ws_input = QLineEdit(self.registry.workspace_folder)
        self.ws_input.setObjectName("toolsWorkspaceInput")
        self.ws_input.setPlaceholderText("Path to project workspace folder...")
        self.ws_input.textChanged.connect(self._on_ws_text_changed)
        ws_layout.addWidget(self.ws_input, stretch=1)

        browse_btn = QPushButton("Browse...")
        browse_btn.setObjectName("toolsBrowseBtn")
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._on_browse_workspace)
        ws_layout.addWidget(browse_btn)

        main_layout.addWidget(ws_card)

        # 3. Filter Tabs and Search Bar
        filter_bar = QWidget()
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(10)

        # Filter Pills: "All Tools" and "Active"
        pills_layout = QHBoxLayout()
        pills_layout.setSpacing(6)
        self.pill_group = QButtonGroup(self)

        self.pill_all = QPushButton("All")
        self.pill_all.setCheckable(True)
        self.pill_all.setChecked(True)
        self.pill_all.setProperty("class", "toolFilterPill")
        self.pill_all.clicked.connect(lambda: self._set_filter("all"))
        self.pill_group.addButton(self.pill_all)
        pills_layout.addWidget(self.pill_all)

        self.pill_active = QPushButton("Active")
        self.pill_active.setCheckable(True)
        self.pill_active.setProperty("class", "toolFilterPill")
        self.pill_active.clicked.connect(lambda: self._set_filter("active"))
        self.pill_group.addButton(self.pill_active)
        pills_layout.addWidget(self.pill_active)

        filter_layout.addLayout(pills_layout)
        filter_layout.addStretch()

        self.search_box = QLineEdit()
        self.search_box.setObjectName("toolSearchBox")
        self.search_box.setPlaceholderText("Search tools...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_filter)
        self.search_box.setFixedWidth(260)
        filter_layout.addWidget(self.search_box)

        main_layout.addWidget(filter_bar)

        # 4. Tools Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("toolsScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.cards_container = QWidget()
        self.cards_container.setObjectName("toolsCardsContainer")
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch()

        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area, stretch=1)

    def _set_filter(self, filter_type: str) -> None:
        self._current_filter = filter_type
        self._apply_filter()

    def refresh_tools(self) -> None:
        """Refresh the tools list display."""
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Filter tools by search query and active tab."""
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        query = self.search_box.text().strip().lower()
        specs = self.registry.list_all_specs()

        filtered: List[ToolSpec] = []
        for spec in specs:
            is_enabled = self.registry.is_tool_enabled(spec.name)

            if self._current_filter == "active" and not is_enabled:
                continue

            if query:
                in_name = query in spec.name.lower()
                in_desc = query in spec.description.lower()
                if not (in_name or in_desc):
                    continue

            filtered.append(spec)

        if not filtered:
            empty_lbl = QLabel("No matching tools found.")
            empty_lbl.setStyleSheet("color: #71717a; font-size: 13px; padding: 30px; text-align: center;")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cards_layout.insertWidget(0, empty_lbl)
            return

        for idx, spec in enumerate(filtered):
            enabled = self.registry.is_tool_enabled(spec.name)
            card = ToolCard(spec=spec, enabled=enabled, parent=self.cards_container)
            card.toggled.connect(self._on_tool_toggled)
            card.details_requested.connect(self._on_view_details)
            self.cards_layout.insertWidget(idx, card)

    def _on_tool_toggled(self, name: str, enabled: bool) -> None:
        self.registry.set_tool_enabled(name, enabled)
        settings = get_app_settings()
        disabled_list = list(self.registry._disabled_tools)
        settings.setValue("disabled_tools", disabled_list)
        settings.sync()
        self.tools_changed.emit()

    def _on_view_details(self, name: str) -> None:
        spec = self.registry.get_spec(name)
        if spec:
            dlg = ToolDetailDialog(tool_spec=spec, tool_registry=self.registry, parent=self)
            dlg.exec()

    def _on_ws_text_changed(self, text: str) -> None:
        folder = text.strip()
        if folder and Path(folder).exists():
            self.registry.set_workspace_folder(folder)
            settings = get_app_settings()
            settings.setValue("workspace_folder", folder)
            settings.sync()
            self.tools_changed.emit()

    def _on_browse_workspace(self) -> None:
        current = self.ws_input.text() or str(Path.cwd())
        folder = QFileDialog.getExistingDirectory(self, "Select Workspace Directory", current)
        if folder:
            self.ws_input.setText(folder)
            self.registry.set_workspace_folder(folder)
            settings = get_app_settings()
            settings.setValue("workspace_folder", folder)
            settings.sync()
            self.tools_changed.emit()
