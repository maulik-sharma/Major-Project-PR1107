"""Modal dialog for inspecting tool specifications, parameter schemas, and live testing."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.tools.registry import ToolRegistry
from modelmesh.core.types import ToolSpec


class ToolDetailDialog(QDialog):
    """Dialog showing detailed schema, documentation, and live test runner for a tool."""

    def __init__(
        self,
        tool_spec: ToolSpec,
        tool_registry: ToolRegistry,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toolDetailDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.tool_spec = tool_spec
        self.tool_registry = tool_registry
        self.setWindowTitle(f"Tool: {tool_spec.name}")
        self.resize(680, 520)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # Header Info Card
        header_card = QFrame()
        header_card.setObjectName("toolDetailHeader")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(6)

        title_row = QHBoxLayout()
        name_lbl = QLabel(self.tool_spec.name)
        name_lbl.setStyleSheet("font-size: 16px; font-weight: bold;")
        title_row.addWidget(name_lbl)

        category = self.tool_registry.get_category(self.tool_spec.name)
        cat_badge = QLabel(category)
        cat_badge.setObjectName("toolCategoryBadge")
        title_row.addWidget(cat_badge)

        title_row.addStretch()

        is_enabled = self.tool_registry.is_tool_enabled(self.tool_spec.name)
        status_badge = QLabel("Active" if is_enabled else "Disabled")
        status_badge.setObjectName("toolToggleBtn")
        status_badge.setProperty("active", "true" if is_enabled else "false")
        title_row.addWidget(status_badge)

        header_layout.addLayout(title_row)

        desc_lbl = QLabel(self.tool_spec.description)
        desc_lbl.setObjectName("toolCardDesc")
        desc_lbl.setWordWrap(True)
        header_layout.addWidget(desc_lbl)

        layout.addWidget(header_card)

        # Tabs: 1. Parameters Schema, 2. Live Test Runner
        tabs = QTabWidget()

        # Tab 1: Schema JSON
        schema_widget = QWidget()
        schema_layout = QVBoxLayout(schema_widget)
        schema_layout.setContentsMargins(8, 8, 8, 8)

        schema_edit = QPlainTextEdit()
        schema_edit.setReadOnly(True)
        schema_edit.setPlainText(json.dumps(self.tool_spec.parameters, indent=2))
        schema_edit.setStyleSheet("font-family: 'JetBrains Mono', 'Menlo', monospace; font-size: 12px;")
        schema_layout.addWidget(schema_edit)
        tabs.addTab(schema_widget, "JSON Schema")

        # Tab 2: Live Test Runner
        test_widget = QWidget()
        test_layout = QVBoxLayout(test_widget)
        test_layout.setContentsMargins(8, 8, 8, 8)
        test_layout.setSpacing(8)

        test_layout.addWidget(QLabel("<strong>Test Arguments (JSON):</strong>"))
        default_args = self._generate_sample_args()
        self.args_edit = QPlainTextEdit()
        self.args_edit.setPlainText(json.dumps(default_args, indent=2))
        self.args_edit.setFixedHeight(110)
        self.args_edit.setStyleSheet("font-family: 'JetBrains Mono', 'Menlo', monospace; font-size: 12px;")
        test_layout.addWidget(self.args_edit)

        run_btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Execute Tool Test")
        self.run_btn.setObjectName("toolTestRunBtn")
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_btn.clicked.connect(self._on_run_test)
        run_btn_row.addWidget(self.run_btn)
        self.exec_time_lbl = QLabel("")
        self.exec_time_lbl.setStyleSheet("color: #a1a1aa; font-size: 11.5px;")
        run_btn_row.addWidget(self.exec_time_lbl)
        run_btn_row.addStretch()
        test_layout.addLayout(run_btn_row)

        test_layout.addWidget(QLabel("<strong>Result Output:</strong>"))
        self.output_edit = QPlainTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("Output will appear here after executing test...")
        self.output_edit.setStyleSheet("font-family: 'JetBrains Mono', 'Menlo', monospace; font-size: 12px;")
        test_layout.addWidget(self.output_edit, stretch=1)

        tabs.addTab(test_widget, "Live Test")
        layout.addWidget(tabs, stretch=1)

        # Bottom Close Button
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.accept)
        layout.addWidget(btn_box)

    def _generate_sample_args(self) -> Dict[str, Any]:
        """Generate friendly default sample arguments based on parameters schema."""
        props = self.tool_spec.parameters.get("properties", {})
        sample: Dict[str, Any] = {}
        for prop_name, prop_data in props.items():
            ptype = prop_data.get("type", "string")
            if prop_name == "query":
                sample[prop_name] = "Python concurrency"
            elif prop_name == "expression":
                sample[prop_name] = "sqrt(144) * 3 + 2"
            elif prop_name == "url":
                sample[prop_name] = "https://httpbin.org/get"
            elif prop_name == "path":
                sample[prop_name] = "."
            elif prop_name == "content":
                sample[prop_name] = "Hello from ModelMesh tool test!"
            elif ptype == "integer":
                sample[prop_name] = prop_data.get("default", 5)
            elif ptype == "boolean":
                sample[prop_name] = prop_data.get("default", False)
            else:
                sample[prop_name] = "test"
        return sample

    def _on_run_test(self) -> None:
        """Execute the tool with arguments entered in the test panel."""
        raw_text = self.args_edit.toPlainText().strip()
        args: Dict[str, Any] = {}
        if raw_text:
            try:
                args = json.loads(raw_text)
            except Exception as exc:
                self.output_edit.setPlainText(f"JSON Parsing Error in Arguments: {exc}")
                return

        self.run_btn.setEnabled(False)
        self.output_edit.setPlainText("Executing...")

        result = self.tool_registry.execute(self.tool_spec.name, args)

        self.run_btn.setEnabled(True)
        self.exec_time_lbl.setText(f"Latency: {result.duration_ms} ms | Success: {result.success}")

        if result.success:
            if isinstance(result.output, (dict, list)):
                self.output_edit.setPlainText(json.dumps(result.output, indent=2))
            else:
                self.output_edit.setPlainText(str(result.output))
        else:
            self.output_edit.setPlainText(f"Execution Error:\n{result.error}")
