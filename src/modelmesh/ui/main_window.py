"""Main application window for ModelMesh desktop client."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.engine import ChatEngine
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
from modelmesh.ui.router_lab import RouterLabDialog
from modelmesh.ui.settings.settings_dialog import SettingsDialog
from modelmesh.ui.sidebar import SidebarWidget
from modelmesh.ui.theme import apply_theme
from modelmesh.ui.usage_view import UsageDialog
from modelmesh.ui.workers import ChatWorker


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
        self.current_worker: Optional[ChatWorker] = None
        self.session_total_cost: float = 0.0

        self.generation_settings: Dict[str, Any] = {
            "temperature": 0.7,
            "max_tokens": 4096,
            "system_prompt": "",
        }

        self._init_ui()
        self._load_initial_data()

    def _init_ui(self) -> None:
        apply_theme(self, "dark")

        # 1. Top Navigation Bar
        self.toolbar = QToolBar("Top Toolbar", self)
        self.toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        # Strategy & Model Selectors
        self.strategy_label = QLabel("Strategy")
        self.strategy_label.setStyleSheet("font-weight: 500; color: #a1a1aa; font-size: 12px;")
        self.toolbar.addWidget(self.strategy_label)

        self.strategy_combo = QComboBox()
        self.strategy_combo.setMinimumWidth(180)
        self._populate_strategy_combo()
        self.strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        self.toolbar.addWidget(self.strategy_combo)

        self.toolbar.addSeparator()

        self.model_label = QLabel("Model")
        self.model_label.setStyleSheet("font-weight: 500; color: #a1a1aa; font-size: 12px;")
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

        # Skills dropdown menu button
        self.skills_btn = QToolButton()
        self.skills_btn.setText("Skills")
        self.skills_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.skills_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._populate_skills_menu()
        self.toolbar.addWidget(self.skills_btn)

        # 2. Main Layout Splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_splitter.setObjectName("mainSplitter")

        # Left Sidebar
        self.sidebar = SidebarWidget(self)
        self.sidebar.conversation_selected.connect(self._on_conversation_selected)
        self.sidebar.new_chat_requested.connect(self._on_new_chat)
        self.sidebar.delete_conversation_requested.connect(self._on_delete_conversation)
        self.sidebar.rename_conversation_requested.connect(self._on_rename_conversation)
        self.sidebar.settings_requested.connect(self._open_settings_dialog)
        self.sidebar.usage_requested.connect(self._open_usage_dialog)
        self.sidebar.router_lab_requested.connect(self._open_router_lab_dialog)
        main_splitter.addWidget(self.sidebar)

        # Right Chat Area
        chat_container = QWidget()
        chat_container.setObjectName("chatContainer")
        chat_layout = QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        # Transcript Web View
        self.chat_view = ChatView(self)
        self.chat_view.regenerate_requested.connect(self._on_regenerate)
        self.chat_view.suggestion_clicked.connect(self._on_suggestion_clicked)
        chat_layout.addWidget(self.chat_view, stretch=1)

        # Bottom Composer
        self.composer = ComposerWidget(self)
        self.composer.send_requested.connect(self._on_send_message)
        self.composer.stop_requested.connect(self._on_stop_streaming)
        chat_layout.addWidget(self.composer)

        main_splitter.addWidget(chat_container)
        main_splitter.setSizes([260, 920])

        self.setCentralWidget(main_splitter)

        # 3. Status Bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.cost_status_label = QLabel("Session Cost: $0.0000 ")
        self.status_bar.addPermanentWidget(self.cost_status_label)
        self.status_bar.showMessage("Ready")

    def _populate_strategy_combo(self) -> None:
        """Populate the routing strategy selector."""
        self.strategy_combo.clear()
        self.strategy_combo.addItem("Auto: Cheapest First", "cheapest_first")
        self.strategy_combo.addItem("Auto: Expensive First", "expensive_first")
        self.strategy_combo.addItem("Auto: Random Baseline", "random")
        self.strategy_combo.addItem("Manual Selection", "manual")

    def _populate_model_combo(self) -> None:
        """Fill model selector dropdown with available models and endpoints."""
        self.model_combo.clear()
        for model in self.registry.models():
            self.model_combo.addItem(
                f"{model.display_name} (Auto Provider)",
                {"pinned_model_id": model.id},
            )
            if len(model.endpoints) > 1:
                for ep in model.endpoints:
                    self.model_combo.addItem(
                        f"   ↳ {ep.provider} (${ep.price_in_per_mtok:.2f}/Mtok)",
                        {
                            "pinned_model_id": model.id,
                            "pinned_endpoint_id": ep.id,
                        },
                    )

    def _on_strategy_changed(self) -> None:
        """Toggle model combo box enabled state based on selected strategy."""
        strategy = self.strategy_combo.currentData() or "cheapest_first"
        is_manual = (strategy == "manual")
        self.model_combo.setEnabled(is_manual)
        self.model_label.setEnabled(is_manual)
        if is_manual:
            self.model_combo.setToolTip("Select model or specific provider endpoint to route directly.")
        else:
            self.model_combo.setToolTip("Model is selected automatically based on the chosen routing strategy.")

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
        conv_id = self.storage.create_conversation(title="New Chat")
        conversations = self.storage.list_conversations()
        self.sidebar.set_conversations(conversations, selected_id=conv_id)
        self._on_conversation_selected(conv_id)

    def _on_conversation_selected(self, conv_id: str) -> None:
        """Switch active conversation and render history in ChatView."""
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.stop()

        self.current_conversation_id = conv_id
        self.chat_view.clear()

        # Load messages from storage (returns List[Message])
        messages = self.storage.get_messages(conv_id)
        for msg in messages:
            role = msg.role
            parts = [p.to_dict() for p in msg.parts]
            meta = {
                "model_id": msg.meta.get("model_id"),
                "endpoint_id": msg.meta.get("endpoint_id"),
                "provider_id": msg.meta.get("provider_id"),
                "tokens_in": msg.meta.get("tokens_in"),
                "tokens_out": msg.meta.get("tokens_out"),
                "cost_usd": msg.meta.get("cost"),
                "latency_sec": (msg.meta.get("latency_ms") or 0) / 1000.0,
            }

            if role == "user":
                text = msg.text_content()
                self.chat_view.add_user_message(msg.id, text, parts)
            elif role == "assistant":
                text = msg.text_content()
                self.chat_view.start_assistant_message(
                    msg.id,
                    model_name=meta["model_id"] or "",
                    provider_name=meta["provider_id"] or "",
                    strategy_name="loaded",
                )
                if msg.reasoning:
                    self.chat_view.append_reasoning(msg.id, msg.reasoning)
                self.chat_view.append_token(msg.id, text)
                self.chat_view.finish_assistant_message(msg.id, meta)

        self.status_bar.showMessage(f"Loaded conversation '{conv_id}'")

    def _on_rename_conversation(self, conv_id: str, new_title: str) -> None:
        self.storage.update_conversation(conv_id, title=new_title)
        conversations = self.storage.list_conversations()
        self.sidebar.set_conversations(conversations, selected_id=self.current_conversation_id)

    def _on_delete_conversation(self, conv_id: str) -> None:
        self.storage.delete_conversation(conv_id)
        conversations = self.storage.list_conversations()
        if not conversations:
            self._on_new_chat()
        else:
            self.sidebar.set_conversations(conversations, selected_id=conversations[0]["id"])
            self._on_conversation_selected(conversations[0]["id"])

    def _on_suggestion_clicked(self, prompt: str) -> None:
        self.composer.set_prompt_text(prompt)

    def _on_send_message(self, text: str, attachments: List[Dict[str, Any]]) -> None:
        """Handle user message submission, build request, and launch streaming worker."""
        if not self.current_conversation_id:
            self._on_new_chat()

        conv_id = self.current_conversation_id

        # Auto-title conversation if needed
        conv = self.storage.get_conversation(conv_id)
        if conv and conv.get("title") == "New Chat" and text:
            words = text.strip().split()
            auto_title = " ".join(words[:6])
            self.storage.update_conversation(conv_id, title=auto_title)
            conversations = self.storage.list_conversations()
            self.sidebar.set_conversations(conversations, selected_id=conv_id)

        # Build Canonical Message Parts
        parts: List[Any] = []
        for att in attachments:
            if att.get("type") == "image":
                parts.append(ImagePart(media_type=att["media_type"], data=att["data"]))
            elif att.get("type") == "text":
                fname = att.get("name", "document")
                parts.append(TextPart(text=f"--- Begin {fname} ---\n{att['text']}\n--- End {fname} ---"))

        if text:
            parts.append(TextPart(text=text))

        user_msg = Message(role="user", parts=parts)
        self.storage.save_message(
            message=user_msg,
            conversation_id=conv_id,
        )

        # Render in ChatView
        self.chat_view.add_user_message(
            user_msg.id,
            text,
            [p.to_dict() for p in parts if isinstance(p, ImagePart)],
        )

        # Build full conversation request from storage
        req_messages = self.storage.get_messages(conv_id)

        tools_to_pass = (
            self.engine.tool_registry.get_tool_specs()
            if (self.tools_btn.isChecked() and self.engine.tool_registry is not None)
            else []
        )

        request = ChatRequest(
            messages=req_messages,
            system_prompt=self.generation_settings.get("system_prompt"),
            tools=tools_to_pass,
            temperature=self.generation_settings.get("temperature"),
            max_tokens=self.generation_settings.get("max_tokens"),
        )

        # Determine routing mode from dropdowns
        strategy_name = self.strategy_combo.currentData() or "cheapest_first"
        pinned_model_id = None
        pinned_endpoint_id = None

        if strategy_name == "manual":
            combo_data = self.model_combo.currentData() or {}
            pinned_model_id = combo_data.get("pinned_model_id")
            pinned_endpoint_id = combo_data.get("pinned_endpoint_id")

        # Start Worker Thread
        self.composer.set_streaming_state(True)
        self.status_bar.showMessage("Routing and generating reply...")

        assistant_msg_id = str(uuid.uuid4())
        self.current_assistant_msg_id = assistant_msg_id
        self.accumulated_text = ""
        self.accumulated_reasoning = ""

        self.current_worker = ChatWorker(
            engine=self.engine,
            request=request,
            strategy_name=strategy_name,
            pinned_model_id=pinned_model_id,
            pinned_endpoint_id=pinned_endpoint_id,
            conversation_id=conv_id,
            parent=self,
        )

        self.current_worker.routed.connect(self._on_worker_routed)
        self.current_worker.fallback.connect(self._on_worker_fallback)
        self.current_worker.text_delta.connect(self._on_worker_text_delta)
        self.current_worker.reasoning_delta.connect(self._on_worker_reasoning_delta)
        self.current_worker.tool_call.connect(self._on_worker_tool_call)
        self.current_worker.tool_start.connect(self._on_worker_tool_start)
        self.current_worker.tool_result.connect(self._on_worker_tool_result)
        self.current_worker.finished_turn.connect(self._on_worker_finished)
        self.current_worker.error_occurred.connect(self._on_worker_error)
        self.current_worker.start()

    def _on_worker_routed(self, data: Dict[str, Any]) -> None:
        self.chat_view.start_assistant_message(
            self.current_assistant_msg_id,
            model_name=data.get("model_id", ""),
            provider_name=data.get("provider_id", ""),
            strategy_name=data.get("strategy", ""),
            reason=data.get("reason", ""),
        )
        self.status_bar.showMessage(
            f"Streaming from '{data.get('model_id')}' via {data.get('provider_id')}..."
        )

    def _on_worker_fallback(self, data: Dict[str, Any]) -> None:
        self.chat_view.show_fallback_notice(
            data.get("from_endpoint_id", ""),
            data.get("to_endpoint_id", ""),
            data.get("error", ""),
        )
        self.status_bar.showMessage(f"Failover to {data.get('to_endpoint_id')}...")

    def _on_worker_text_delta(self, chunk: str) -> None:
        self.accumulated_text += chunk
        self.chat_view.append_token(self.current_assistant_msg_id, chunk)

    def _on_worker_reasoning_delta(self, chunk: str) -> None:
        self.accumulated_reasoning += chunk
        self.chat_view.append_reasoning(self.current_assistant_msg_id, chunk)

    def _on_worker_tool_call(self, data: Dict[str, Any]) -> None:
        self.chat_view.add_tool_card(
            self.current_assistant_msg_id,
            data.get("id", ""),
            data.get("name", ""),
            data.get("arguments", {}),
        )

    def _on_worker_tool_start(self, data: Dict[str, Any]) -> None:
        self.chat_view.add_tool_card(
            self.current_assistant_msg_id,
            data.get("id", ""),
            data.get("name", ""),
            data.get("arguments", {}),
        )
        self.status_bar.showMessage(f"Executing tool '{data.get('name')}'...")

    def _on_worker_tool_result(self, data: Dict[str, Any]) -> None:
        self.chat_view.update_tool_result(
            self.current_assistant_msg_id,
            data.get("id", ""),
            data.get("name", ""),
            data.get("result"),
            data.get("error"),
            data.get("success", True),
            data.get("duration_ms", 0),
        )
        status_text = "succeeded" if data.get("success") else "failed"
        self.status_bar.showMessage(f"Tool '{data.get('name')}' {status_text} ({data.get('duration_ms', 0)}ms)")

    def _on_worker_finished(self, data: Dict[str, Any]) -> None:
        self.composer.set_streaming_state(False)
        self.chat_view.finish_assistant_message(self.current_assistant_msg_id, data)

        # Update Session Cost
        cost = data.get("cost_usd", 0.0)
        self.session_total_cost += cost
        self.cost_status_label.setText(f"Session Est. Cost: ${self.session_total_cost:.4f} ")

        # Extract reasoning from <thought> or <think> if needed
        saved_text = self.accumulated_text
        saved_reasoning = self.accumulated_reasoning or None

        if not saved_reasoning:
            thought_matches = re.findall(
                r"<(?:thought|think)>(.*?)</(?:thought|think)>",
                saved_text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            if thought_matches:
                saved_reasoning = "\n\n".join(m.strip() for m in thought_matches if m.strip())
                saved_text = re.sub(
                    r"<(?:thought|think)>.*?</(?:thought|think)>",
                    "",
                    saved_text,
                    flags=re.DOTALL | re.IGNORECASE,
                ).strip()

        # Save assistant message to SQLite
        asst_msg = Message.from_text("assistant", saved_text)
        asst_msg.reasoning = saved_reasoning
        asst_msg.id = self.current_assistant_msg_id
        self.storage.save_message(
            message=asst_msg,
            conversation_id=self.current_conversation_id,
            model_id=data.get("model_id"),
            endpoint_id=data.get("endpoint_id"),
            provider_id=data.get("provider_id"),
            tokens_in=data.get("tokens_in", 0),
            tokens_out=data.get("tokens_out", 0),
            cost=cost,
            latency_ms=int((data.get("latency_sec") or 0) * 1000),
            status="complete",
        )
        self.status_bar.showMessage(f"Turn complete · {data.get('tokens_in', 0)} in / {data.get('tokens_out', 0)} out · ${cost:.5f}")

    def _on_worker_error(self, data: Dict[str, Any]) -> None:
        self.composer.set_streaming_state(False)
        self.chat_view.show_error(
            self.current_assistant_msg_id,
            data.get("error", "Unknown error"),
            data.get("category", "unknown"),
        )
        self.status_bar.showMessage("Error during generation.")

    def _on_stop_streaming(self) -> None:
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.stop()
            self.composer.set_streaming_state(False)
            self.status_bar.showMessage("Generation stopped by user.")

    def _on_regenerate(self, message_id: str) -> None:
        """Regenerate last response."""
        stored = self.storage.get_messages(self.current_conversation_id)
        if len(stored) >= 2:
            # Last message was assistant, message before was user
            last_user_msg = stored[-2]
            text = last_user_msg.text_content()
            self._on_send_message(text, [])

    def _open_parameters_dialog(self) -> None:
        dlg = ParametersDialog(current_settings=self.generation_settings, parent=self)
        if dlg.exec() == ParametersDialog.DialogCode.Accepted:
            self.generation_settings = dlg.get_settings()
            self.status_bar.showMessage("Updated generation parameters.")

    def _toggle_tools(self) -> None:
        active = self.tools_btn.isChecked()
        self.tools_btn.setText(f"Tools: {'On' if active else 'Off'}")
        self.status_bar.showMessage(f"Tools {'enabled' if active else 'disabled'}.")

    def _populate_skills_menu(self) -> None:
        """Populate the Skills button dropdown menu with installed skills and management actions."""
        menu = QMenu(self)
        skills = self.engine.skill_loader.list_skills() if self.engine.skill_loader else []
        self.skills_btn.setText(f"Skills ({len(skills)})" if skills else "Skills")

        if skills:
            for s in skills:
                desc_snippet = f" - {s.description[:35]}..." if s.description else ""
                action = menu.addAction(f"{s.name}{desc_snippet}")
                action.triggered.connect(lambda _, name=s.name: self._on_skill_triggered(name))
            menu.addSeparator()

        new_skill_action = menu.addAction("+ Create New Skill...")
        new_skill_action.triggered.connect(self._create_new_skill)

        manage_action = menu.addAction("Manage Skills & Tools...")
        manage_action.triggered.connect(lambda: self._open_settings_dialog(tab_index=3))

        self.skills_btn.setMenu(menu)

    def _on_skill_triggered(self, skill_name: str) -> None:
        """Insert skill directive into composer and focus it."""
        current_text = self.composer.get_text().strip()
        prefix = f"Please use the '{skill_name}' skill to "
        if not current_text:
            self.composer.text_input.setPlainText(prefix)
        else:
            self.composer.text_input.setPlainText(f"{prefix}\n{current_text}")
        self.composer.text_input.setFocus()

    def _create_new_skill(self) -> None:
        """Open create skill dialog and refresh menu on save."""
        from modelmesh.ui.settings.tools_tab import CreateSkillDialog
        skills_dir = (
            self.engine.skill_loader.skills_dir
            if self.engine.skill_loader
            else Path.cwd() / "skills"
        )
        dlg = CreateSkillDialog(skills_dir=skills_dir, parent=self)
        if dlg.exec() == CreateSkillDialog.DialogCode.Accepted:
            if self.engine.skill_loader:
                self.engine.skill_loader.reload()
            self._populate_skills_menu()
            self.status_bar.showMessage("New skill created successfully.")

    def _open_settings_dialog(self, tab_index: int = 0) -> None:
        dlg = SettingsDialog(
            registry=self.registry,
            tool_registry=self.engine.tool_registry,
            skill_loader=self.engine.skill_loader,
            parent=self,
        )
        if tab_index > 0:
            dlg.tabs.setCurrentIndex(tab_index)
        dlg.settings_updated.connect(self._on_settings_updated)
        dlg.exec()

    def _on_settings_updated(self) -> None:
        self._populate_model_combo()
        self._populate_skills_menu()

    def _open_usage_dialog(self) -> None:
        dlg = UsageDialog(storage=self.storage, parent=self)
        dlg.exec()

    def _open_router_lab_dialog(self) -> None:
        dlg = RouterLabDialog(registry=self.registry, router=self.router, parent=self)
        dlg.exec()

