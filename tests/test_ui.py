"""Unit tests for ModelMesh PyQt6 GUI components, workers, and dialogs."""

import os
import sys
import pytest
from pathlib import Path

# Ensure offscreen rendering and disable sandboxing for test runner
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

# Single QApplication fixture for pytest session
@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv + ["--no-sandbox", "--disable-gpu"])
    app.setApplicationName("ModelMesh")
    app.setOrganizationName("ModelMesh")
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

    # Check initial conversation creation and dropdowns
    assert win.current_conversation_id is not None
    assert win.strategy_combo.count() == 4
    assert win.model_combo.count() >= 1

    # Strategy combo default is cheapest_first -> model_combo is disabled
    assert not win.model_combo.isEnabled()

    # Switching to manual enables model_combo
    win.strategy_combo.setCurrentIndex(3)  # Manual Selection
    assert win.strategy_combo.currentData() == "manual"
    assert win.model_combo.isEnabled()

    # Send a message in manual mode
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


def test_thinking_tag_extraction_on_finish(qapp, tmp_path: Path) -> None:
    reg = create_test_registry()
    storage = Storage(tmp_path / "test_thought.db")
    router = Router(registry=reg)
    engine = ChatEngine(registry=reg, router=router, storage=storage)

    win = MainWindow(
        registry=reg,
        router=router,
        engine=engine,
        storage=storage,
    )

    win.accumulated_text = "<thought>1. Analyzing constraint\n2. Thinking...</thought>Here is the final answer."
    win.accumulated_reasoning = ""
    win.current_assistant_msg_id = "test-msg-id"
    win._on_worker_finished({
        "model_id": "mock-fast",
        "endpoint_id": "mock-fast@mock",
        "provider_id": "mock",
        "cost_usd": 0.0001,
        "latency_sec": 0.5,
        "tokens_in": 10,
        "tokens_out": 20,
    })

    msgs = storage.get_messages(win.current_conversation_id)
    assert len(msgs) == 1
    asst = msgs[0]
    assert asst.role == "assistant"
    assert asst.text_content() == "Here is the final answer."
    assert asst.reasoning is not None
    assert "Analyzing constraint" in asst.reasoning


def test_unclosed_thought_recovery_in_main_window(qapp, tmp_path: Path) -> None:
    reg = create_test_registry()
    storage = Storage(tmp_path / "test_unclosed.db")
    router = Router(registry=reg)
    engine = ChatEngine(registry=reg, router=router, storage=storage)

    win = MainWindow(
        registry=reg,
        router=router,
        engine=engine,
        storage=storage,
    )

    # Simulates model ending with unclosed thought and divider
    win.accumulated_text = (
        "<thought>Thinking about the ATS score...\n"
        "All calculations done.\n"
        "---\n"
        "**ATS Score Estimate: 95/100**\n\n"
        "### Executive Summary\n"
        "Great resume."
    )
    win.accumulated_reasoning = ""
    win.current_assistant_msg_id = "test-unclosed-id"
    win._on_worker_finished({
        "model_id": "mock-fast",
        "endpoint_id": "mock-fast@mock",
        "provider_id": "mock",
        "cost_usd": 0.0002,
        "latency_sec": 1.0,
        "tokens_in": 100,
        "tokens_out": 200,
    })

    msgs = storage.get_messages(win.current_conversation_id)
    assert len(msgs) == 1
    asst = msgs[0]
    assert asst.role == "assistant"
    assert "**ATS Score Estimate: 95/100**" in asst.text_content()
    assert "### Executive Summary" in asst.text_content()
    assert "Thinking about the ATS score" in (asst.reasoning or "")



def test_tools_tab_and_skills_management(qapp, tmp_path: Path) -> None:
    from modelmesh.core.skills import SkillLoader
    from modelmesh.core.tools.builtin import create_builtin_registry
    from modelmesh.ui.settings.tools_tab import ToolsTab

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill1_dir = skills_dir / "my-skill"
    skill1_dir.mkdir()
    (skill1_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Test skill.\n---\nBody here.",
        encoding="utf-8",
    )

    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()

    tool_reg = create_builtin_registry(workspace_folder=str(ws_dir))
    skill_loader = SkillLoader(skills_dir=skills_dir)

    tab = ToolsTab(tool_registry=tool_reg, skill_loader=skill_loader)
    assert tab.skills_table.rowCount() == 1
    assert tab.skills_table.item(0, 0).text() == "my-skill"

    # Test changing workspace folder text and QSettings persistence
    from modelmesh.ui.settings.tools_tab import get_app_settings, set_custom_settings_path
    set_custom_settings_path(tmp_path / "settings.ini")
    new_ws = tmp_path / "new_ws"
    new_ws.mkdir()
    tab.ws_input.setText(str(new_ws))
    assert tool_reg.workspace_folder == str(new_ws)
    assert get_app_settings().value("workspace_folder") == str(new_ws)
    set_custom_settings_path(None)

    # Test tool toggling
    tab.calc_check.setChecked(False)
    assert tool_reg.is_tool_enabled("calculator") is False
    tab.calc_check.setChecked(True)
    assert tool_reg.is_tool_enabled("calculator") is True


def test_skills_composer_mention_and_navigation(qapp, tmp_path: Path) -> None:
    from modelmesh.core.skills import SkillLoader
    from modelmesh.core.tools.builtin import create_builtin_registry

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill1_dir = skills_dir / "sql-expert"
    skill1_dir.mkdir()
    (skill1_dir / "SKILL.md").write_text(
        "---\nname: sql-expert\ndescription: Optimize SQL queries.\n---\nSQL rules.",
        encoding="utf-8",
    )

    reg = create_test_registry()
    storage = Storage(tmp_path / "test_skills_win.db")
    router = Router(registry=reg)
    tool_reg = create_builtin_registry()
    skill_loader = SkillLoader(skills_dir=skills_dir)
    engine = ChatEngine(
        registry=reg,
        router=router,
        storage=storage,
        tool_registry=tool_reg,
        skill_loader=skill_loader,
    )

    win = MainWindow(
        registry=reg,
        router=router,
        engine=engine,
        storage=storage,
    )

    # Test @ mention typing in composer
    win.composer.text_input.setPlainText("@sql")
    assert win.composer.text_input.mention_popup.list_widget.count() == 1

    # Test keyboard navigation
    win.composer.text_input.mention_popup.select_next()
    assert win.composer.text_input.mention_popup.list_widget.currentRow() == 0

    # Confirm selection
    win.composer.text_input.mention_popup.confirm_selection()
    assert "@sql-expert " in win.composer.get_text()

    # Test top toolbar does not contain skills_btn
    assert not hasattr(win, "skills_btn") or win.skills_btn is None

    # Test view switching via sidebar
    assert win.main_stack.currentIndex() == 0
    win.sidebar.skills_nav_btn.click()
    assert win.main_stack.currentIndex() == 1
    assert win.sidebar._active_view == "skills"

    # Switching back on new chat
    win.sidebar.new_chat_requested.emit()
    assert win.main_stack.currentIndex() == 0
    assert win.sidebar._active_view == "chat"


def test_atomic_skill_token_deletion(qapp, tmp_path: Path) -> None:
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent, QTextCursor
    from modelmesh.core.skills import SkillLoader
    from modelmesh.ui.composer import ComposerWidget, SKILL_TOKEN_PROP

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill1_dir = skills_dir / "fastapi-expert"
    skill1_dir.mkdir()
    (skill1_dir / "SKILL.md").write_text(
        "---\nname: fastapi-expert\ndescription: FastAPI skill.\n---\nRules.",
        encoding="utf-8",
    )

    loader = SkillLoader(skills_dir=skills_dir)
    composer = ComposerWidget()
    composer.set_skill_loader(loader)

    # 1. Type '@fast' and select skill
    text_edit = composer.text_input
    text_edit.setPlainText("@fast")
    cursor = text_edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    text_edit.setTextCursor(cursor)
    text_edit._check_mention_trigger()

    assert text_edit.mention_popup.isVisible()
    # Confirm selection
    text_edit.mention_popup.confirm_selection()

    # Plain text should now have '@fastapi-expert '
    assert text_edit.toPlainText() == "@fastapi-expert "

    # Verify formatting has SKILL_TOKEN_PROP
    doc = text_edit.document()
    check_cursor = QTextCursor(doc)
    check_cursor.setPosition(2)
    check_cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
    assert check_cursor.charFormat().property(SKILL_TOKEN_PROP) == "fastapi-expert"

    # 2. Test Backspace right at the end (after trailing space) -> should delete the entire token atomically
    cursor = text_edit.textCursor()
    cursor.setPosition(len(text_edit.toPlainText()))
    text_edit.setTextCursor(cursor)

    bs_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier)
    text_edit.keyPressEvent(bs_event)

    # The entire '@fastapi-expert ' token should be erased in one backspace!
    assert text_edit.toPlainText() == ""

    # 3. Test Backspace inside the token
    text_edit.setPlainText("@fast")
    cursor = text_edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    text_edit.setTextCursor(cursor)
    text_edit.mention_popup.confirm_selection()
    assert text_edit.toPlainText() == "@fastapi-expert "

    # Place cursor inside "@fastapi-expert" (e.g. at index 5)
    cursor = text_edit.textCursor()
    cursor.setPosition(5)
    text_edit.setTextCursor(cursor)

    text_edit.keyPressEvent(bs_event)
    assert text_edit.toPlainText() == ""

    # 4. Test Delete key at start of token
    text_edit.setPlainText("@fast")
    cursor = text_edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    text_edit.setTextCursor(cursor)
    text_edit.mention_popup.confirm_selection()
    assert text_edit.toPlainText() == "@fastapi-expert "

    cursor = text_edit.textCursor()
    cursor.setPosition(0)
    text_edit.setTextCursor(cursor)

    del_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    text_edit.keyPressEvent(del_event)
    assert text_edit.toPlainText() == ""


def test_skills_view_and_cards(qapp, tmp_path: Path) -> None:
    from modelmesh.core.skills import SkillLoader
    from modelmesh.ui.skills_view import SkillsView

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    s1 = skills_dir / "fastapi"
    scripts = s1 / "scripts"
    scripts.mkdir(parents=True)
    (s1 / "SKILL.md").write_text("---\nname: fastapi\ndescription: FastAPI skill.\n---\nBody.", encoding="utf-8")
    (scripts / "deploy.py").write_text("# Deploy script", encoding="utf-8")

    s2 = skills_dir / "simple"
    s2.mkdir()
    (s2 / "SKILL.md").write_text("---\nname: simple\ndescription: Simple skill.\n---\nBody2.", encoding="utf-8")

    reg = create_test_registry()
    storage = Storage(tmp_path / "test_sv.db")
    router = Router(registry=reg)
    loader = SkillLoader(skills_dir=skills_dir)
    engine = ChatEngine(registry=reg, router=router, storage=storage, skill_loader=loader)

    view = SkillsView(engine=engine)
    assert view.cards_layout.count() >= 2

    # Verify no file count badge in SkillCard
    cards = [view.cards_layout.itemAt(i).widget() for i in range(view.cards_layout.count()) if view.cards_layout.itemAt(i).widget()]
    for card in cards:
        assert not hasattr(card, "ref_badge") or card.findChild(QLabel, "skillCardRefBadge") is None

    # Test search filter
    view.search_box.setText("fastapi")
    cards = [view.cards_layout.itemAt(i).widget() for i in range(view.cards_layout.count()) if view.cards_layout.itemAt(i).widget()]
    assert len(cards) == 1
    assert cards[0].skill.name == "fastapi"

    # Clear search
    view.search_box.setText("")

    # Test card toggle
    cards[0].toggle_btn.click()
    assert loader.get_skill("fastapi").enabled is False

    # Test active filter pill
    view.pill_active.click()
    cards_active = [view.cards_layout.itemAt(i).widget() for i in range(view.cards_layout.count()) if view.cards_layout.itemAt(i).widget()]
    assert len(cards_active) == 1
    assert cards_active[0].skill.name == "simple"


def test_skill_detail_dialog(qapp, tmp_path: Path) -> None:
    from modelmesh.core.skills import SkillLoader
    from modelmesh.ui.skill_detail_dialog import SkillDetailDialog

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    s1 = skills_dir / "arch"
    docs_dir = s1 / "docs" / "api"
    docs_dir.mkdir(parents=True)
    (s1 / "SKILL.md").write_text("---\nname: arch\ndescription: System design.\n---\nInitial content.", encoding="utf-8")
    (docs_dir / "endpoints.md").write_text("# Endpoints\nInitial endpoints.", encoding="utf-8")

    loader = SkillLoader(skills_dir=skills_dir)
    skill = loader.get_skill("arch")
    assert skill is not None

    dlg = SkillDetailDialog(skill=skill, loader=loader)
    # Root has SKILL.md and docs/ folder
    assert dlg.file_tree.topLevelItemCount() == 2

    # Find docs/api/endpoints.md item and click
    docs_item = dlg.file_tree.topLevelItem(1)
    assert docs_item.text(0) == "docs/"
    api_item = docs_item.child(0)
    assert api_item.text(0) == "api/"
    file_item = api_item.child(0)
    assert file_item.text(0) == "endpoints.md"

    dlg._on_tree_item_clicked(file_item, 0)
    assert "Initial endpoints" in dlg.editor.toPlainText()

    # Edit and save
    dlg.editor.setPlainText("# Endpoints\nUpdated endpoints content.")
    dlg._save_changes()

    assert "Updated endpoints content" in (docs_dir / "endpoints.md").read_text(encoding="utf-8")


def test_tools_view_and_cards(qapp, tmp_path: Path) -> None:
    from modelmesh.core.tools.builtin import create_builtin_registry
    from modelmesh.ui.tools_view import ToolsView, ToolCard

    tool_reg = create_builtin_registry(workspace_folder=str(tmp_path))
    reg = create_test_registry()
    storage = Storage(tmp_path / "test_tv.db")
    router = Router(registry=reg)
    engine = ChatEngine(registry=reg, router=router, storage=storage, tool_registry=tool_reg)

    view = ToolsView(engine=engine)
    assert view.cards_layout.count() >= 8  # 8 built-in tools

    # Test toggling a tool
    cards = [view.cards_layout.itemAt(i).widget() for i in range(view.cards_layout.count()) if isinstance(view.cards_layout.itemAt(i).widget(), ToolCard)]
    web_card = next(c for c in cards if c.spec.name == "web_search")
    assert web_card.enabled is True

    # Verify no category/param tags next to title and button says "View"
    assert web_card.findChild(QLabel, "toolCategoryBadge") is None
    assert web_card.findChild(QLabel, "toolParamBadge") is None
    assert web_card.findChild(QPushButton, "toolCardActionBtn").text() == "View"

    web_card.toggle_btn.click()
    assert tool_reg.is_tool_enabled("web_search") is False

    # Test filter by Active pill
    view.pill_active.click()
    active_cards = [view.cards_layout.itemAt(i).widget() for i in range(view.cards_layout.count()) if isinstance(view.cards_layout.itemAt(i).widget(), ToolCard)]
    names = [c.spec.name for c in active_cards]
    assert "web_search" not in names
    assert "calculator" in names

    # Switch back to All Tools
    view.pill_all.click()

    # Test search filter
    view.search_box.setText("calculator")
    calc_cards = [view.cards_layout.itemAt(i).widget() for i in range(view.cards_layout.count()) if isinstance(view.cards_layout.itemAt(i).widget(), ToolCard)]
    assert len(calc_cards) == 1
    assert calc_cards[0].spec.name == "calculator"


def test_tool_detail_dialog_and_live_test(qapp, tmp_path: Path) -> None:
    from modelmesh.core.tools.builtin import create_builtin_registry
    from modelmesh.ui.tool_detail_dialog import ToolDetailDialog

    tool_reg = create_builtin_registry(workspace_folder=str(tmp_path))
    spec = tool_reg.get_spec("calculator")
    assert spec is not None

    dlg = ToolDetailDialog(tool_spec=spec, tool_registry=tool_reg)
    assert dlg.tool_spec.name == "calculator"

    # Execute test in dialog
    dlg.args_edit.setPlainText('{"expression": "100 / 4 + 7"}')
    dlg._on_run_test()

    assert "32" in dlg.output_edit.toPlainText()
    assert "Latency:" in dlg.exec_time_lbl.text()


def test_tools_sidebar_navigation_in_main_window(qapp, tmp_path: Path) -> None:
    from modelmesh.core.tools.builtin import create_builtin_registry

    reg = create_test_registry()
    storage = Storage(tmp_path / "test_main_tools.db")
    router = Router(registry=reg)
    tool_reg = create_builtin_registry(workspace_folder=str(tmp_path))
    engine = ChatEngine(registry=reg, router=router, storage=storage, tool_registry=tool_reg)

    win = MainWindow(
        registry=reg,
        router=router,
        engine=engine,
        storage=storage,
    )

    # Sidebar starts in chat view
    assert win.main_stack.currentIndex() == 0

    # Click Tools button in sidebar
    win.sidebar.tools_nav_btn.click()
    assert win.main_stack.currentIndex() == 2
    assert win.sidebar._active_view == "tools"

    # Click Skills button in sidebar
    win.sidebar.skills_nav_btn.click()
    assert win.main_stack.currentIndex() == 1
    assert win.sidebar._active_view == "skills"

    # Click New Chat in sidebar
    win.sidebar._on_new_chat_clicked()
    assert win.main_stack.currentIndex() == 0
    assert win.sidebar._active_view == "chat"





