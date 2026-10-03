"""Unit tests for ModelMesh PyQt6 GUI components, workers, and dialogs."""

import os
import sys
import pytest
from pathlib import Path

# Ensure offscreen rendering and disable sandboxing for test runner
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

# Single QApplication fixture for pytest session
@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv + ["--no-sandbox", "--disable-gpu"])
    return app


from modelmesh.core.engine import ChatEngine
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.router import Router
from modelmesh.core.storage import Storage
from modelmesh.core.types import (
    Candidate,
    ChatRequest,
    EndpointConfig,
    Message,
    ModelConfig,
    ProviderConfig,
)
from modelmesh.ui.chat_view import ChatView
from modelmesh.ui.composer import ComposerWidget
from modelmesh.ui.main_window import MainWindow
from modelmesh.ui.parameters_dialog import ParametersDialog
from modelmesh.ui.router_lab import RouterLabDialog
from modelmesh.ui.settings.settings_dialog import SettingsDialog
from modelmesh.ui.sidebar import SidebarWidget
from modelmesh.ui.usage_view import UsageDialog
from modelmesh.ui.workers import ChatWorker


def create_test_registry() -> ModelRegistry:
    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="mock", protocol="mock"))
    reg.add_model(
        ModelConfig(
            id="mock-fast",
            display_name="Mock Fast Model",
            tier="cheap",
            context_window=32000,
            capabilities=["streaming", "tools"],
            endpoints=[
                EndpointConfig(
                    id="mock-fast@mock",
                    provider="mock",
                    api_model="mock-instant",
                    price_in_per_mtok=0.01,
                    price_out_per_mtok=0.02,
                    priority=1,
                )
            ],
        )
    )
    return reg


def test_sidebar_widget(qapp) -> None:
    sidebar = SidebarWidget()
    conversations = [
        {"id": "c1", "title": "First Conversation", "created": "2026-10-03"},
        {"id": "c2", "title": "Second Discussion", "created": "2026-10-03"},
    ]
    sidebar.set_conversations(conversations, selected_id="c1")
    assert sidebar.conv_list.count() == 2

    # Test search filter
    sidebar.search_box.setText("First")
    assert sidebar.conv_list.count() == 1
    assert "First" in sidebar.conv_list.item(0).text()

    sidebar.search_box.setText("")
    assert sidebar.conv_list.count() == 2


def test_composer_widget(qapp) -> None:
    composer = ComposerWidget()
    received = []
    composer.send_requested.connect(lambda txt, atts: received.append((txt, atts)))

    composer.text_input.setPlainText("Hello ModelMesh!")
    composer._on_send_clicked()

    assert len(received) == 1
    assert received[0][0] == "Hello ModelMesh!"
    assert composer.text_input.toPlainText() == ""


def test_parameters_dialog(qapp) -> None:
    init_settings = {"temperature": 0.5, "max_tokens": 2048, "system_prompt": "Be concise."}
    dlg = ParametersDialog(current_settings=init_settings)

    assert dlg.temp_input.value() == 0.5
    assert dlg.max_tokens_input.value() == 2048
    assert dlg.system_prompt_input.toPlainText() == "Be concise."

    dlg.temp_input.setValue(1.2)
    dlg.max_tokens_input.setValue(8192)
    dlg.system_prompt_input.setPlainText("Think step by step.")

    res = dlg.get_settings()
    assert res["temperature"] == 1.2
    assert res["max_tokens"] == 8192
    assert res["system_prompt"] == "Think step by step."


def test_chat_worker_execution(qapp, tmp_path: Path) -> None:
    reg = create_test_registry()
    storage = Storage(tmp_path / "test_worker.db")
    router = Router(registry=reg)
    engine = ChatEngine(registry=reg, router=router, storage=storage)

    req = ChatRequest(messages=[Message.from_text("user", "Test prompt")])
    worker = ChatWorker(
        engine=engine,
        request=req,
        strategy_name="manual",
        pinned_model_id="mock-fast",
    )

    events_captured = []
    worker.routed.connect(lambda d: events_captured.append(("routed", d)))
    worker.text_delta.connect(lambda t: events_captured.append(("text", t)))
    worker.finished_turn.connect(lambda d: events_captured.append(("finished", d)))

    worker.run()

    types = [e[0] for e in events_captured]
    assert "routed" in types
    assert "text" in types
    assert "finished" in types


def test_settings_dialog(qapp) -> None:
    reg = create_test_registry()
    dlg = SettingsDialog(registry=reg)
    assert dlg.tabs.count() == 5
    assert dlg.providers_tab.provider_list.count() >= 1
    assert dlg.models_tab.tree.topLevelItemCount() >= 1


def test_usage_dialog(qapp, tmp_path: Path) -> None:
    storage = Storage(tmp_path / "test_usage.db")
    dlg = UsageDialog(storage=storage)
    assert dlg.table.columnCount() == 7


def test_router_lab_dialog(qapp) -> None:
    reg = create_test_registry()
    router = Router(registry=reg)
    dlg = RouterLabDialog(registry=reg, router=router)
    dlg._run_dry_run()
    assert dlg.table.rowCount() > 0


def test_main_window_lifecycle(qapp, tmp_path: Path) -> None:
    reg = create_test_registry()
    storage = Storage(tmp_path / "test_main.db")
    router = Router(registry=reg)
    engine = ChatEngine(registry=reg, router=router, storage=storage)

    win = MainWindow(
        registry=reg,
        router=router,
        engine=engine,
        storage=storage,
    )

    # Check initial conversation creation
    assert win.current_conversation_id is not None
    assert win.model_combo.count() >= 3

    # Send a message
    win._on_send_message("Hello from unit test", [])
    if win.current_worker:
        win.current_worker.wait(5000)
    qapp.processEvents()

    # Verify messages saved
    msgs = storage.get_messages(win.current_conversation_id)
    assert len(msgs) >= 2
    assert msgs[0].text_content() == "Hello from unit test"
    assert msgs[1].role == "assistant"


def test_app_module(qapp) -> None:
    from modelmesh import app
    db_path = app.get_db_path()
    assert db_path.name == "modelmesh.db"
    assert db_path.parent.exists()

