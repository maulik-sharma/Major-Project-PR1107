"""Routing configuration tab in settings with persistent preferences."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # 1. General Strategy Box
        gen_group = QGroupBox("General Routing")
        gen_form = QFormLayout(gen_group)

        self.default_strat = QComboBox()
        self.default_strat.addItem("Auto · Smart (Clef)", "smart_clef")
        self.default_strat.addItem("Auto: Cheapest First", "cheapest_first")
        self.default_strat.addItem("Auto: Expensive First", "expensive_first")
        self.default_strat.addItem("Auto: Random Baseline", "random")
        self.default_strat.addItem("Manual Selection", "manual")
        self.default_strat.currentIndexChanged.connect(self._on_strategy_changed)
        gen_form.addRow("Default Routing Strategy:", self.default_strat)

        self.safety_margin = QSpinBox()
        self.safety_margin.setRange(0, 10000)
        self.safety_margin.valueChanged.connect(self._on_safety_margin_changed)
        gen_form.addRow("Safety Margin Tokens:", self.safety_margin)

        self.cooldown_sec = QSpinBox()
        self.cooldown_sec.setRange(5, 3600)
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
        self.privacy_check.toggled.connect(self._on_privacy_toggled)
        smart_form.addRow("Privacy:", self.privacy_check)

        # Need weights
        weights_row = QHBoxLayout()
        self.diff_weight_spin = QDoubleSpinBox()
        self.diff_weight_spin.setRange(0.0, 2.0)
        self.diff_weight_spin.setSingleStep(0.05)
        self.diff_weight_spin.valueChanged.connect(self._on_weights_changed)
        weights_row.addWidget(QLabel("Diff:"))
        weights_row.addWidget(self.diff_weight_spin)

        self.prec_weight_spin = QDoubleSpinBox()
        self.prec_weight_spin.setRange(0.0, 2.0)
        self.prec_weight_spin.setSingleStep(0.05)
        self.prec_weight_spin.valueChanged.connect(self._on_weights_changed)
        weights_row.addWidget(QLabel("Prec:"))
        weights_row.addWidget(self.prec_weight_spin)

        self.benefit_weight_spin = QDoubleSpinBox()
        self.benefit_weight_spin.setRange(0.0, 2.0)
        self.benefit_weight_spin.setSingleStep(0.05)
        self.benefit_weight_spin.valueChanged.connect(self._on_weights_changed)
        weights_row.addWidget(QLabel("Benefit:"))
        weights_row.addWidget(self.benefit_weight_spin)
        smart_form.addRow("Need Weights:", weights_row)

        # Bias & Slack
        bias_row = QHBoxLayout()
        self.bias_spin = QDoubleSpinBox()
        self.bias_spin.setRange(-1.0, 1.0)
        self.bias_spin.setSingleStep(0.05)
        self.bias_spin.valueChanged.connect(self._on_bias_changed)
        bias_row.addWidget(QLabel("Default Bias:"))
        bias_row.addWidget(self.bias_spin)

        self.slack_spin = QDoubleSpinBox()
        self.slack_spin.setRange(0.0, 0.5)
        self.slack_spin.setSingleStep(0.01)
        self.slack_spin.valueChanged.connect(self._on_slack_changed)
        bias_row.addWidget(QLabel("Slack (s):"))
        bias_row.addWidget(self.slack_spin)
        smart_form.addRow("Bias & Slack:", bias_row)

        layout.addWidget(smart_group)

        # 3. Candidate Pool & Policy Box
        pool_group = QGroupBox("Candidate Pool & Policies")
        pool_form = QFormLayout(pool_group)

        self.unscored_combo = QComboBox()
        self.unscored_combo.addItem("Exclude from Smart routing (default)", "exclude")
        self.unscored_combo.addItem("Assign tier default scores (cheap/mid/premium)", "tier_default")
        self.unscored_combo.currentIndexChanged.connect(self._on_unscored_policy_changed)
        pool_form.addRow("Unscored Models:", self.unscored_combo)

        self.pool_include_input = QLineEdit()
        self.pool_include_input.setPlaceholderText("e.g. * or claude-*, gpt-*")
        self.pool_include_input.editingFinished.connect(self._on_pool_patterns_changed)
        pool_form.addRow("Pool Include Patterns:", self.pool_include_input)

        self.pool_exclude_input = QLineEdit()
        self.pool_exclude_input.setPlaceholderText("e.g. mock-*")
        self.pool_exclude_input.editingFinished.connect(self._on_pool_patterns_changed)
        pool_form.addRow("Pool Exclude Patterns:", self.pool_exclude_input)

        self.stickiness_check = QCheckBox("Session stickiness (preserve candidate within thread unless task changes)")
        self.stickiness_check.toggled.connect(self._on_stickiness_toggled)
        pool_form.addRow("Stickiness:", self.stickiness_check)

        layout.addWidget(pool_group)
        layout.addStretch()

    def refresh(self) -> None:
        """Reload configuration from disk and update UI controls without emitting false changes."""
        self.routing_config = load_routing_config()
        settings = get_app_settings()

        self._block_all_signals(True)
        try:
            saved_strat = str(settings.value("router/strategy", "smart_clef"))
            idx = self.default_strat.findData(saved_strat)
            if idx >= 0:
                self.default_strat.setCurrentIndex(idx)

            self.safety_margin.setValue(int(settings.value("router/safety_margin", 500)))
            self.cooldown_sec.setValue(int(settings.value("router/cooldown_sec", 60)))

            # Decision
            curr_prov = self.routing_config.decision.active
            if curr_prov == "decision-mock":
                curr_prov = "mock"
            idx_p = self.decision_provider_combo.findData(curr_prov)
            if idx_p >= 0:
                self.decision_provider_combo.setCurrentIndex(idx_p)

            self.privacy_check.setChecked(self.routing_config.decision.send_prompt_text)

            # Need
            self.diff_weight_spin.setValue(self.routing_config.need.weights.difficulty)
            self.prec_weight_spin.setValue(self.routing_config.need.weights.precision)
            self.benefit_weight_spin.setValue(self.routing_config.need.weights.larger_model_benefit)
            self.bias_spin.setValue(self.routing_config.need.bias)
            self.slack_spin.setValue(self.routing_config.need.slack)

            # Pool & Policies
            idx_u = self.unscored_combo.findData(self.routing_config.unscored_policy)
            if idx_u >= 0:
                self.unscored_combo.setCurrentIndex(idx_u)

            self.pool_include_input.setText(", ".join(self.routing_config.pool.include))
            self.pool_exclude_input.setText(", ".join(self.routing_config.pool.exclude))
            self.stickiness_check.setChecked(self.routing_config.stickiness.enabled)
        finally:
            self._block_all_signals(False)

    def _block_all_signals(self, block: bool) -> None:
        for w in (
            self.default_strat,
            self.safety_margin,
            self.cooldown_sec,
            self.decision_provider_combo,
            self.privacy_check,
            self.diff_weight_spin,
            self.prec_weight_spin,
            self.benefit_weight_spin,
            self.bias_spin,
            self.slack_spin,
            self.unscored_combo,
            self.pool_include_input,
            self.pool_exclude_input,
            self.stickiness_check,
        ):
            w.blockSignals(block)

    def _on_strategy_changed(self) -> None:
        strat = self.default_strat.currentData() or "smart_clef"
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

    def _on_unscored_policy_changed(self) -> None:
        pol = self.unscored_combo.currentData() or "exclude"
        self.routing_config.unscored_policy = pol
        save_routing_config(self.routing_config)
        self.config_changed.emit()

    def _on_pool_patterns_changed(self) -> None:
        inc_raw = self.pool_include_input.text()
        inc_list = [p.strip() for p in inc_raw.split(",") if p.strip()] or ["*"]
        exc_raw = self.pool_exclude_input.text()
        exc_list = [p.strip() for p in exc_raw.split(",") if p.strip()]

        self.routing_config.pool.include = inc_list
        self.routing_config.pool.exclude = exc_list
        save_routing_config(self.routing_config)
        self.config_changed.emit()

    def _on_stickiness_toggled(self, checked: bool) -> None:
        self.routing_config.stickiness.enabled = checked
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
        task_obj = answers.get("task", {})
        task = task_obj.get("choice", "unknown") if isinstance(task_obj, dict) else str(task_obj)

        diff_obj = answers.get("difficulty", {})
        diff = diff_obj.get("score", 0) if isinstance(diff_obj, dict) else str(diff_obj)
        diff_conf = diff_obj.get("confidence", 1.0) if isinstance(diff_obj, dict) else 1.0

        prec_obj = answers.get("precision", {})
        prec = prec_obj.get("score", 0) if isinstance(prec_obj, dict) else str(prec_obj)

        bene_obj = answers.get("larger_model_benefit", {})
        bene = bene_obj.get("score", 0) if isinstance(bene_obj, dict) else str(bene_obj)

        reasoning_obj = answers.get("needs_reasoning", {})
        reasoning = reasoning_obj.get("noul", 0.0) if isinstance(reasoning_obj, dict) else str(reasoning_obj)

        lat = data.get("latency_ms", 0.0)
        src = data.get("source", "")
        prov = data.get("provider_id", "")
        cached = " (cached)" if data.get("cached") else ""

        msg = (
            f"Decision Provider Test Succeeded!\n\n"
            f"Provider ID: {prov}\n"
            f"Decision Source: {src}{cached}\n"
            f"Latency: {lat:.1f} ms\n\n"
            f"Evaluated Rubric Answers:\n"
            f" • Task: {task}\n"
            f" • Difficulty: {diff}/4 (Confidence: {diff_conf:.2f})\n"
            f" • Precision: {prec}/3\n"
            f" • Larger Model Benefit: {bene}/3\n"
            f" • Needs Reasoning: {reasoning}\n"
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
