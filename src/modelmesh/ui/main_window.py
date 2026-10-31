"""Main application window for ModelMesh desktop client."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction, QColor, QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.engine import ChatEngine
from modelmesh.core.attachments import Attachment
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.router import Router
from modelmesh.core.storage import Storage
from modelmesh.core.types import (
    ChatRequest,
    ImagePart,
    Message,
    TextPart,
)
from modelmesh.ui.chat_view import ChatView
from modelmesh.ui.composer import ComposerWidget
from modelmesh.ui.parameters_dialog import ParametersDialog
from modelmesh.ui.settings.settings_dialog import SettingsDialog
from modelmesh.ui.settings.tools_tab import get_app_settings
from modelmesh.ui.sidebar import SidebarWidget
from modelmesh.ui.skills_view import SkillsView
from modelmesh.ui.theme import apply_theme
from modelmesh.ui.tools_view import ToolsView
from modelmesh.ui.usage_view import UsageDialog
from modelmesh.ui.transcript import display_parts, render_conversation, request_history
from modelmesh.ui.turn_controller import TurnController


# Used for new conversations; each conversation then keeps its own copy.
DEFAULT_GENERATION_SETTINGS: Dict[str, Any] = {"temperature": 0.7, "max_tokens": 4096, "system_prompt": ""}


class MainWindow(QMainWindow):
    """Primary application window coordinating chat UI, routing, and background workers."""

    def __init__(
        self,
        registry: ModelRegistry,
        router: Router,
        engine: ChatEngine,
        storage: Storage,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ModelMesh - Intelligent LLM Router")
        self.resize(1180, 820)
        self.setMinimumSize(800, 600)

        self.registry = registry
        self.router = router
        self.engine = engine
        self.storage = storage

        self.current_conversation_id: Optional[str] = None
        self._conversation_loaded = False
        self.session_total_cost: float = 0.0

        self.generation_settings: Dict[str, Any] = dict(DEFAULT_GENERATION_SETTINGS)

        self._apply_router_settings()
        self._init_ui()
        self.turns = TurnController(engine=engine, storage=storage, chat_view=self.chat_view, parent=self)
        self.turns.busy_changed.connect(self.composer.set_streaming_state)
        self.turns.status.connect(self.status_bar.showMessage)
        self.turns.cost_added.connect(self._on_cost_added)
        self.composer.attachment_error.connect(self.status_bar.showMessage)
        self._load_initial_data()

    def _init_ui(self) -> None:
        self._current_theme = str(get_app_settings().value("appearance/theme", "dark"))
        apply_theme(self, self._current_theme)

        # 1. Top Navigation Bar
        self.toolbar = QToolBar("Top Toolbar", self)
        self.toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        # Strategy & Model Selectors
        self.strategy_label = QLabel("Strategy")
        self.strategy_label.setObjectName("toolbarLabel")
        self.toolbar.addWidget(self.strategy_label)

        self.strategy_combo = QComboBox()
        self.strategy_combo.setMinimumWidth(180)
        self._populate_strategy_combo()
        self.strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        self.toolbar.addWidget(self.strategy_combo)

        self.toolbar.addSeparator()

        self.model_label = QLabel("Model")
        self.model_label.setObjectName("toolbarLabel")
        self.toolbar.addWidget(self.model_label)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(260)
        self._populate_model_combo()
        self.toolbar.addWidget(self.model_combo)

        self._on_strategy_changed()

        self.toolbar.addSeparator()

        # Parameters button
        self.params_btn = QToolButton()
        self.params_btn.setText("Parameters")
        self.params_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.params_btn.clicked.connect(self._open_parameters_dialog)
        self.toolbar.addWidget(self.params_btn)

        # Tools toggle
        self.tools_btn = QToolButton()
        self.tools_btn.setText("Tools: On")
        self.tools_btn.setCheckable(True)
        self.tools_btn.setChecked(True)
        self.tools_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tools_btn.clicked.connect(self._toggle_tools)
        self.toolbar.addWidget(self.tools_btn)

        # 2. Main Layout Splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_splitter.setObjectName("mainSplitter")

        # Left Sidebar
        self.sidebar = SidebarWidget(self)
        self.sidebar.conversation_selected.connect(self._on_conversation_selected)
        self.sidebar.new_chat_requested.connect(self._on_new_chat)
        self.sidebar.skills_requested.connect(self._show_skills_view)
        self.sidebar.tools_requested.connect(self._show_tools_view)
        self.sidebar.delete_conversation_requested.connect(self._on_delete_conversation)
        self.sidebar.rename_conversation_requested.connect(self._on_rename_conversation)
        self.sidebar.settings_requested.connect(self._open_settings_dialog)
        self.sidebar.usage_requested.connect(self._open_usage_dialog)
        main_splitter.addWidget(self.sidebar)

        # Central Stacked Area (Chat View vs Skills View vs Tools View)
        self.main_stack = QStackedWidget(self)
        self.main_stack.setObjectName("mainStack")

        # Right Chat Area (Stack Index 0)
        chat_container = QWidget()
        chat_container.setObjectName("chatContainer")
        chat_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        chat_layout = QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        # Transcript Web View
        self.chat_view = ChatView(self)
        self.chat_view.set_theme(self._current_theme)
        self.chat_view.regenerate_requested.connect(self._on_regenerate)
        self.chat_view.suggestion_clicked.connect(self._on_suggestion_clicked)
        chat_layout.addWidget(self.chat_view, stretch=1)

        # Bottom Composer
        self.composer = ComposerWidget(self)
        self.composer.set_skill_loader(self.engine.skill_loader)
        self.composer.send_requested.connect(self._on_send_message)
        self.composer.stop_requested.connect(lambda: self.turns.stop())
        chat_layout.addWidget(self.composer)

        self.main_stack.addWidget(chat_container)

        # Dedicated Skills Workspace View (Stack Index 1)
        self.skills_view = SkillsView(engine=self.engine, parent=self)
        self.skills_view.skills_changed.connect(self._on_skills_changed)
        self.skills_view.back_to_chat_requested.connect(self._show_chat_view)
        self.main_stack.addWidget(self.skills_view)

        # Dedicated Tools Workspace View (Stack Index 2)
        self.tools_view = ToolsView(engine=self.engine, parent=self)
        self.tools_view.tools_changed.connect(self._on_tools_changed)
        self.tools_view.back_to_chat_requested.connect(self._show_chat_view)
        self.main_stack.addWidget(self.tools_view)

        main_splitter.addWidget(self.main_stack)
        main_splitter.setSizes([260, 920])

        self.setCentralWidget(main_splitter)

        # 3. Status Bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.cost_status_label = QLabel("Session Cost: $0.0000 ")
        self.status_bar.addPermanentWidget(self.cost_status_label)
        self.status_bar.showMessage("Ready")

    def _populate_strategy_combo(self) -> None:
        """Populate the routing strategy selector from persistent settings."""
        settings = get_app_settings()
        saved_strat = str(settings.value("router/strategy", "smart_clef"))

        self.strategy_combo.blockSignals(True)
        try:
            self.strategy_combo.clear()
            self.strategy_combo.addItem("Auto · Smart", "smart_clef")
            self.strategy_combo.addItem("Auto: Cheapest First", "cheapest_first")
            self.strategy_combo.addItem("Auto: Expensive First", "expensive_first")
            self.strategy_combo.addItem("Auto: Random Baseline", "random")
            self.strategy_combo.addItem("Manual Selection", "manual")

            idx = self.strategy_combo.findData(saved_strat)
            if idx >= 0:
                self.strategy_combo.setCurrentIndex(idx)
            else:
                self.strategy_combo.setCurrentIndex(0)
        finally:
            self.strategy_combo.blockSignals(False)

    def _populate_model_combo(self) -> None:
        """Fill model selector with enabled models/endpoints, keeping the current choice."""
        previous = self.model_combo.currentData()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in self.registry.models():
            endpoints = [ep for ep in model.endpoints if ep.enabled]
            if not model.enabled or not endpoints:
                continue
            self.model_combo.addItem(
                f"{model.display_name} (Auto Provider)",
                {"pinned_model_id": model.id},
            )
            if len(endpoints) > 1:
                for ep in endpoints:
                    self.model_combo.addItem(
                        f"   ↳ {ep.provider} (${ep.price_in_per_mtok:.2f}/Mtok)",
                        {
                            "pinned_model_id": model.id,
                            "pinned_endpoint_id": ep.id,
                        },
                    )
        idx = self.model_combo.findData(previous) if previous else -1
        self.model_combo.setCurrentIndex(max(0, idx))
        self.model_combo.blockSignals(False)

    def _on_strategy_changed(self) -> None:
        """Toggle model combo box enabled state based on selected strategy and persist preference."""
        strategy = self.strategy_combo.currentData() or "smart_clef"
        get_app_settings().setValue("router/strategy", strategy)
        is_manual = (strategy == "manual")
        self.model_combo.setEnabled(is_manual)
        self.model_label.setEnabled(is_manual)
        if is_manual:
            self.model_combo.setToolTip("Select model or specific provider endpoint to route directly.")
        else:
            self.model_combo.setToolTip("Model is selected automatically based on the chosen routing strategy.")

    def _show_skills_view(self) -> None:
        """Switch central view to the dedicated Skills workspace."""
        self.main_stack.setCurrentIndex(1)
        self.sidebar.set_active_view("skills")
        self.skills_view.refresh_skills()
        self.status_bar.showMessage("Viewing Skills workspace.")

    def _show_tools_view(self) -> None:
        """Switch central view to the dedicated Tools workspace."""
        self.main_stack.setCurrentIndex(2)
        self.sidebar.set_active_view("tools")
        self.tools_view.refresh_tools()
        self.status_bar.showMessage("Viewing Tools workspace.")

    def _on_tools_changed(self) -> None:
        """Handle changes in tools configuration."""
        self.status_bar.showMessage("Tools configuration updated.")

    def _show_chat_view(self) -> None:
        """Switch central view to the chat conversation view."""
        self.main_stack.setCurrentIndex(0)
        self.sidebar.set_active_view("chat")
        self.status_bar.showMessage("Ready")

    def _load_initial_data(self) -> None:
        """Load conversation list from SQLite storage or create first chat."""
        conversations = self.storage.list_conversations()
        if not conversations:
            self._on_new_chat()
        else:
            self.sidebar.set_conversations(conversations, selected_id=conversations[0]["id"])
            self._on_conversation_selected(conversations[0]["id"])

    def _on_new_chat(self) -> None:
        """Create a new conversation session."""
        self._show_chat_view()
        conv_id = self.storage.create_conversation(title="New Chat")
        conversations = self.storage.list_conversations()
        self.sidebar.set_conversations(conversations, selected_id=conv_id)
        self._on_conversation_selected(conv_id)

    def _on_conversation_selected(self, conv_id: str) -> None:
        """Switch active conversation and render history in ChatView."""
        self._show_chat_view()
        if conv_id == self.current_conversation_id and self._conversation_loaded:
            return  # Re-clicking the open chat must not interrupt a streaming reply.

        self.turns.detach()
        self.current_conversation_id = conv_id
        self._conversation_loaded = True
        self._load_conversation_settings(conv_id)
        self.chat_view.clear()
        render_conversation(self.chat_view, self.storage.get_messages(conv_id))
        self.status_bar.showMessage("Conversation loaded.")

    def _on_rename_conversation(self, conv_id: str, new_title: str) -> None:
        self.storage.update_conversation(conv_id, title=new_title)
        conversations = self.storage.list_conversations()
        self.sidebar.set_conversations(conversations, selected_id=self.current_conversation_id)

    def _on_delete_conversation(self, conv_id: str) -> None:
        if conv_id == self.turns.active_conversation_id:
            self.turns.detach()
        self.storage.delete_conversation(conv_id)
        conversations = self.storage.list_conversations()
        if not conversations:
            self._on_new_chat()
        elif conv_id != self.current_conversation_id:
            # Deleting another chat keeps the open one (and any reply streaming in it).
            self.sidebar.set_conversations(conversations, selected_id=self.current_conversation_id)
        else:
            self.sidebar.set_conversations(conversations, selected_id=conversations[0]["id"])
            self._on_conversation_selected(conversations[0]["id"])

    def _on_suggestion_clicked(self, prompt: str) -> None:
        self.composer.set_prompt_text(prompt)

    def _on_send_message(self, text: str, attachments: List[Attachment]) -> None:
        """Save the user message, render it, and start a turn."""
        if self.turns.is_busy:
            self.status_bar.showMessage("Please wait for the current reply to finish, or press Stop.")
            return
        if not self.current_conversation_id:
            self._on_new_chat()
        conv_id = self.current_conversation_id

        conv = self.storage.get_conversation(conv_id)
        if conv and conv.get("title") == "New Chat" and text:
            self.storage.update_conversation(conv_id, title=" ".join(text.strip().split()[:6]))
            self.sidebar.set_conversations(self.storage.list_conversations(), selected_id=conv_id)

        parts: List[Any] = [att.part for att in attachments]
        if text:
            parts.append(TextPart(text=text))
        user_msg = Message(role="user", parts=parts)
        self.storage.save_message(message=user_msg, conversation_id=conv_id)
        self.chat_view.add_user_message(user_msg.id, text, display_parts([a.part for a in attachments]))
        self._start_turn(conv_id)

    def _start_turn(self, conv_id: str) -> None:
        """Build the request from stored history and hand it to the turn controller."""
        tools_to_pass = (
            self.engine.tool_registry.get_tool_specs()
            if (self.tools_btn.isChecked() and self.engine.tool_registry is not None)
            else []
        )
        request = ChatRequest(
            messages=request_history(self.storage.get_messages(conv_id)),
            system_prompt=self.generation_settings.get("system_prompt"),
            tools=tools_to_pass,
            temperature=self.generation_settings.get("temperature"),
            max_tokens=self.generation_settings.get("max_tokens"),
        )
        strategy_name = self.strategy_combo.currentData() or "smart_clef"
        pinned_model_id = pinned_endpoint_id = None
        if strategy_name == "manual":
            combo_data = self.model_combo.currentData() or {}
            pinned_model_id = combo_data.get("pinned_model_id")
            pinned_endpoint_id = combo_data.get("pinned_endpoint_id")

        self.turns.start(
            request,
            conversation_id=conv_id,
            strategy_name=strategy_name,
            pinned_model_id=pinned_model_id,
            pinned_endpoint_id=pinned_endpoint_id,
            profile=str(get_app_settings().value("router/profile", "")) or None,
        )

    def _on_cost_added(self, cost: float) -> None:
        self.session_total_cost += cost
        self.cost_status_label.setText(f"Session Cost: ${self.session_total_cost:.4f} ")

    def _on_regenerate(self, message_id: str) -> None:
        """Retry the latest reply: drop it and re-run the user message before it."""
        if self.turns.is_busy or not self.current_conversation_id:
            return
        conv_id = self.current_conversation_id
        stored = self.storage.get_messages(conv_id)
        if not stored:
            return
        last = stored[-1]
        if last.role == "assistant":
            if last.id != message_id:
                self.status_bar.showMessage("Only the latest reply can be retried.")
                return
            self.storage.delete_message(last.id)
        elif last.role != "user":
            return
        # A failed turn left the user message unanswered: re-run it as-is.
        self.chat_view.clear()
        render_conversation(self.chat_view, self.storage.get_messages(conv_id))
        self._start_turn(conv_id)

    def closeEvent(self, event: Any) -> None:
        """Stop and wait for background workers before the window goes away."""
        self.turns.shutdown()
        super().closeEvent(event)

    def _open_parameters_dialog(self) -> None:
        dlg = ParametersDialog(current_settings=self.generation_settings, parent=self)
        if dlg.exec() == ParametersDialog.DialogCode.Accepted:
            self.generation_settings = dlg.get_settings()
            self._save_conversation_settings()
            self.status_bar.showMessage("Updated generation parameters for this conversation.")

    def _toggle_tools(self) -> None:
        active = self.tools_btn.isChecked()
        self.tools_btn.setText(f"Tools: {'On' if active else 'Off'}")
        self._save_conversation_settings()
        self.status_bar.showMessage(f"Tools {'enabled' if active else 'disabled'}.")

    def _load_conversation_settings(self, conv_id: str) -> None:
        """Restore this conversation's generation parameters, system prompt and tools toggle."""
        conv = self.storage.get_conversation(conv_id) or {}
        stored = conv.get("settings") or {}
        self.generation_settings = {**DEFAULT_GENERATION_SETTINGS, **(stored.get("generation") or {})}
        self.generation_settings["system_prompt"] = conv.get("system_prompt") or ""
        tools_on = bool(stored.get("tools_enabled", True))
        self.tools_btn.setChecked(tools_on)
        self.tools_btn.setText(f"Tools: {'On' if tools_on else 'Off'}")

    def _save_conversation_settings(self) -> None:
        if not self.current_conversation_id:
            return
        generation = {k: v for k, v in self.generation_settings.items() if k != "system_prompt"}
        self.storage.update_conversation(
            self.current_conversation_id,
            system_prompt=self.generation_settings.get("system_prompt") or "",
            settings={"generation": generation, "tools_enabled": self.tools_btn.isChecked()},
        )

    def _on_skills_changed(self) -> None:
        """Update composer autocomplete when skills change."""
        self.composer.set_skill_loader(self.engine.skill_loader)

    def _open_settings_dialog(self, tab_index: int = 0) -> None:
        dlg = SettingsDialog(
            registry=self.registry,
            storage=self.storage,
            tool_registry=self.engine.tool_registry,
            skill_loader=self.engine.skill_loader,
            parent=self,
        )
        if tab_index > 0:
            dlg.tabs.setCurrentIndex(tab_index)
        dlg.settings_updated.connect(self._on_settings_updated)
        dlg.theme_changed.connect(self.apply_theme_mode)
        dlg.exec()
        dlg.deleteLater()

    def apply_theme_mode(self, theme: str) -> None:
        """Apply light or dark theme dynamically across the entire window and chat view."""
        self._current_theme = theme
        apply_theme(self, theme)
        self.chat_view.set_theme(theme)
        self.chat_view.page().setBackgroundColor(
            QColor("#ffffff" if theme == "light" else "#141417")
        )

    def _apply_router_settings(self) -> None:
        """Push persisted router settings (cooldown, safety margin) into the core router."""
        if not hasattr(self.router, "apply_settings"):
            return
        settings = get_app_settings()
        self.router.apply_settings(
            cooldown_seconds=float(settings.value("router/cooldown_sec", 60)),
            safety_margin_tokens=int(settings.value("router/safety_margin", 500)),
        )

    def _on_settings_updated(self) -> None:
        self._apply_router_settings()
        self._populate_model_combo()
        saved = str(get_app_settings().value("router/strategy", "smart_clef"))
        idx = self.strategy_combo.findData(saved)
        if idx >= 0 and idx != self.strategy_combo.currentIndex():
            self.strategy_combo.setCurrentIndex(idx)
        self._on_skills_changed()
        self.skills_view.refresh_skills()
        if hasattr(self.router, "reload_config"):
            self.router.reload_config()

    def _open_usage_dialog(self) -> None:
        dlg = UsageDialog(storage=self.storage, parent=self)
        dlg.exec()

