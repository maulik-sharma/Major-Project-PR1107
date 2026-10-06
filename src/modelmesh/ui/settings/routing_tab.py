"""Routing configuration tab in settings with persistent preferences."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.config.routing_config import (
    SmartRoutingConfig,
    load_routing_config,
    save_routing_config,
)
from modelmesh.ui.settings.tools_tab import get_app_settings
from modelmesh.ui.workers import DecisionTestWorker


class RoutingTab(QWidget):
    """Tab for setting global router preferences, decision provider, weights, and cooldown parameters."""

    config_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._test_worker: Optional[DecisionTestWorker] = None
        self.routing_config: SmartRoutingConfig = load_routing_config()

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        settings = get_app_settings()

        # 1. General Strategy Box
        gen_group = QGroupBox("General Routing")
        gen_form = QFormLayout(gen_group)

        self.default_strat = QComboBox()
        self.default_strat.addItem("Auto · Smart (Clef)", "smart_clef")
        self.default_strat.addItem("Auto: Cheapest First", "cheapest_first")
        self.default_strat.addItem("Auto: Expensive First", "expensive_first")
        self.default_strat.addItem("Auto: Random Baseline", "random")
        self.default_strat.addItem("Manual Selection", "manual")

        saved_strat = str(settings.value("router/strategy", "smart_clef"))
        idx = self.default_strat.findData(saved_strat)
        if idx >= 0:
            self.default_strat.setCurrentIndex(idx)
        self.default_strat.currentIndexChanged.connect(self._on_strategy_changed)
        gen_form.addRow("Default Routing Strategy:", self.default_strat)

        self.safety_margin = QSpinBox()
        self.safety_margin.setRange(0, 10000)
        self.safety_margin.setValue(int(settings.value("router/safety_margin", 500)))
        self.safety_margin.valueChanged.connect(self._on_safety_margin_changed)
        gen_form.addRow("Safety Margin Tokens:", self.safety_margin)

        self.cooldown_sec = QSpinBox()
        self.cooldown_sec.setRange(5, 3600)
        self.cooldown_sec.setValue(int(settings.value("router/cooldown_sec", 60)))
        self.cooldown_sec.valueChanged.connect(self._on_cooldown_changed)
        gen_form.addRow("Health Failure Cooldown (sec):", self.cooldown_sec)

        layout.addWidget(gen_group)

        # 2. Smart Decision Layer Box
        smart_group = QGroupBox("Smart Decision Layer")
        smart_form = QFormLayout(smart_group)

        self.decision_provider_combo = QComboBox()
        self.decision_provider_combo.addItem("Cloudflare Workers AI (Clef-flash)", "clef-flash")
        self.decision_provider_combo.addItem("Local Heuristic (Rule-based)", "heuristic")
        self.decision_provider_combo.addItem("Deterministic Mock", "mock")

        curr_prov = self.routing_config.decision.active
        idx_p = self.decision_provider_combo.findData(curr_prov)
        if idx_p >= 0:
            self.decision_provider_combo.setCurrentIndex(idx_p)
        self.decision_provider_combo.currentIndexChanged.connect(self._on_decision_provider_changed)

        prov_row = QHBoxLayout()
        prov_row.addWidget(self.decision_provider_combo)
        self.test_btn = QPushButton("Test Provider")
        self.test_btn.clicked.connect(self._on_test_provider_clicked)
        prov_row.addWidget(self.test_btn)
        smart_form.addRow("Decision Provider:", prov_row)

        self.privacy_check = QCheckBox("Send prompt text to decision provider (Cloudflare Workers AI)")
        self.privacy_check.setToolTip(
            "When unchecked, only bounded context (token counts, roles) is sent to local heuristic without sending raw text."
        )
        self.privacy_check.setChecked(self.routing_config.decision.send_prompt_text)
        self.privacy_check.toggled.connect(self._on_privacy_toggled)
        smart_form.addRow("Privacy:", self.privacy_check)

        # Need weights & bias
        weights_row = QHBoxLayout()

        self.diff_weight_spin = QDoubleSpinBox()
        self.diff_weight_spin.setRange(0.0, 2.0)
        self.diff_weight_spin.setSingleStep(0.05)
        self.diff_weight_spin.setValue(self.routing_config.need.weights.difficulty)
        self.diff_weight_spin.valueChanged.connect(self._on_weights_changed)
        weights_row.addWidget(QLabel("Diff:"))
        weights_row.addWidget(self.diff_weight_spin)

        self.prec_weight_spin = QDoubleSpinBox()
        self.prec_weight_spin.setRange(0.0, 2.0)
        self.prec_weight_spin.setSingleStep(0.05)
        self.prec_weight_spin.setValue(self.routing_config.need.weights.precision)
        self.prec_weight_spin.valueChanged.connect(self._on_weights_changed)
        weights_row.addWidget(QLabel("Prec:"))
        weights_row.addWidget(self.prec_weight_spin)

        self.benefit_weight_spin = QDoubleSpinBox()
        self.benefit_weight_spin.setRange(0.0, 2.0)
        self.benefit_weight_spin.setSingleStep(0.05)
        self.benefit_weight_spin.setValue(self.routing_config.need.weights.larger_model_benefit)
        self.benefit_weight_spin.valueChanged.connect(self._on_weights_changed)
        weights_row.addWidget(QLabel("Benefit:"))
        weights_row.addWidget(self.benefit_weight_spin)

        smart_form.addRow("Need Weights:", weights_row)

        bias_row = QHBoxLayout()
        self.bias_spin = QDoubleSpinBox()
        self.bias_spin.setRange(-1.0, 1.0)
        self.bias_spin.setSingleStep(0.05)
        self.bias_spin.setValue(self.routing_config.need.bias)
        self.bias_spin.valueChanged.connect(self._on_bias_changed)
        bias_row.addWidget(QLabel("Default Bias:"))
        bias_row.addWidget(self.bias_spin)

        self.slack_spin = QDoubleSpinBox()
        self.slack_spin.setRange(0.0, 0.5)
        self.slack_spin.setSingleStep(0.01)
        self.slack_spin.setValue(self.routing_config.need.slack)
        self.slack_spin.valueChanged.connect(self._on_slack_changed)
        bias_row.addWidget(QLabel("Slack (s):"))
        bias_row.addWidget(self.slack_spin)

        smart_form.addRow("Bias & Slack:", bias_row)

        layout.addWidget(smart_group)
        layout.addStretch()

    def _on_strategy_changed(self) -> None:
        strat = self.default_strat.currentData() or "cheapest_first"
        get_app_settings().setValue("router/strategy", strat)
        self.config_changed.emit()

    def _on_safety_margin_changed(self, val: int) -> None:
        get_app_settings().setValue("router/safety_margin", val)
        self.config_changed.emit()

    def _on_cooldown_changed(self, val: int) -> None:
        get_app_settings().setValue("router/cooldown_sec", val)
        self.config_changed.emit()

    def _on_decision_provider_changed(self) -> None:
        prov = self.decision_provider_combo.currentData() or "clef-flash"
        self.routing_config.decision.active = prov
        save_routing_config(self.routing_config)
        self.config_changed.emit()

    def _on_privacy_toggled(self, checked: bool) -> None:
        self.routing_config.decision.send_prompt_text = checked
        save_routing_config(self.routing_config)
        self.config_changed.emit()

    def _on_weights_changed(self) -> None:
        self.routing_config.need.weights.difficulty = self.diff_weight_spin.value()
        self.routing_config.need.weights.precision = self.prec_weight_spin.value()
        self.routing_config.need.weights.larger_model_benefit = self.benefit_weight_spin.value()
        save_routing_config(self.routing_config)
        self.config_changed.emit()

    def _on_bias_changed(self, val: float) -> None:
        self.routing_config.need.bias = val
        save_routing_config(self.routing_config)
        self.config_changed.emit()

    def _on_slack_changed(self, val: float) -> None:
        self.routing_config.need.slack = val
        save_routing_config(self.routing_config)
        self.config_changed.emit()

    def _on_test_provider_clicked(self) -> None:
        if self._test_worker and self._test_worker.isRunning():
            return

        prov = self.decision_provider_combo.currentData() or "clef-flash"
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Testing...")

        test_prompt = "Write a quick Python script to calculate Fibonacci numbers."
        self._test_worker = DecisionTestWorker(
            prompt_text=test_prompt,
            provider_id=prov,
            parent=self,
        )
        self._test_worker.test_completed.connect(self._on_test_completed)
        self._test_worker.error_occurred.connect(self._on_test_error)
        self._test_worker.start()

    def _on_test_completed(self, data: dict) -> None:
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test Provider")

        answers = data.get("answers", {})
        task = answers.get("task", {}).get("choice", "unknown")
        diff = answers.get("difficulty", {}).get("score", 0)
        prec = answers.get("precision", {}).get("score", 0)
        lat = data.get("latency_ms", 0.0)
        src = data.get("source", "")
        cached = " (cached)" if data.get("cached") else ""

        msg = (
            f"Decision Provider Test Succeeded!\n\n"
            f"Provider / Source: {src}{cached}\n"
            f"Latency: {lat:.1f} ms\n\n"
            f"Evaluated Answers:\n"
            f" • Task: {task}\n"
            f" • Difficulty: {diff}/4\n"
            f" • Precision: {prec}/3\n"
        )
        QMessageBox.information(self, "Decision Test Result", msg)

    def _on_test_error(self, err_msg: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test Provider")
        QMessageBox.warning(
            self,
            "Decision Test Failed",
            f"Failed to evaluate test decision:\n{err_msg}",
        )
