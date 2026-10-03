"""Router Lab testing harness for evaluating routing decisions across sample prompts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.registry import ModelRegistry
from modelmesh.core.routing.router import Router
from modelmesh.core.types import ChatRequest, Message


SAMPLE_PROMPTS = [
    "What is the capital of France and what is its population?",
    "Write a Python script to compute Fibonacci numbers with memoization.",
    "Explain the difference between TCP and UDP networking protocols in detail.",
    "Summarize the main economic factors influencing inflation in 2026.",
    "Solve this equation: 3x^2 - 12x + 9 = 0 and explain the roots.",
]


class RouterLabDialog(QDialog):
    """Router Lab dialog for benchmarking routing strategies across prompt sets."""

    def __init__(
        self,
        registry: ModelRegistry,
        router: Router,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ModelMesh Router Lab")
        self.resize(850, 560)

        self.registry = registry
        self.router = router

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<strong>Benchmark Prompts (One per line):</strong>"))

        self.prompts_input = QPlainTextEdit()
        self.prompts_input.setPlainText("\n".join(SAMPLE_PROMPTS))
        self.prompts_input.setFixedHeight(120)
        layout.addWidget(self.prompts_input)

        # Control Row
        btn_row = QHBoxLayout()
        dry_run_btn = QPushButton("🚀 Run Dry-Run Simulation")
        dry_run_btn.setStyleSheet("background-color: #3b82f6; color: white; font-weight: 600; padding: 6px 14px;")
        dry_run_btn.clicked.connect(self._run_dry_run)
        btn_row.addWidget(dry_run_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Results Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Prompt",
            "Strategy",
            "Chosen Model",
            "Chosen Endpoint",
            "Est. Cost",
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        # Summary Bar
        self.summary_label = QLabel("<em>Click 'Run Dry-Run Simulation' to evaluate strategies across prompts.</em>")
        layout.addWidget(self.summary_label)

    def _run_dry_run(self) -> None:
        raw_prompts = [
            p.strip() for p in self.prompts_input.toPlainText().split("\n") if p.strip()
        ]
        if not raw_prompts:
            return

        strategies = ["cheapest_first", "expensive_first", "random"]
        rows: List[Dict[str, Any]] = []
        cost_by_strategy: Dict[str, float] = {s: 0.0 for s in strategies}

        for prompt in raw_prompts:
            req = ChatRequest(messages=[Message.from_text("user", prompt)])
            for strat in strategies:
                try:
                    dec = self.router.route(request=req, strategy_name=strat)
                    cand = dec.chosen_candidate
                    cost_in = (cand.price_in_per_mtok or 0.0) * (len(prompt) // 4) / 1_000_000
                    cost_out = (cand.price_out_per_mtok or 0.0) * 500 / 1_000_000
                    total_est = cost_in + cost_out

                    cost_by_strategy[strat] += total_est
                    rows.append({
                        "prompt": prompt[:45] + "..." if len(prompt) > 45 else prompt,
                        "strategy": strat,
                        "model": cand.model_id,
                        "endpoint": cand.endpoint_id,
                        "cost": total_est,
                    })
                except Exception:
                    pass

        self.table.setRowCount(len(rows))
        for idx, r in enumerate(rows):
            self.table.setItem(idx, 0, QTableWidgetItem(r["prompt"]))
            self.table.setItem(idx, 1, QTableWidgetItem(r["strategy"]))
            self.table.setItem(idx, 2, QTableWidgetItem(r["model"]))
            self.table.setItem(idx, 3, QTableWidgetItem(r["endpoint"]))
            self.table.setItem(idx, 4, QTableWidgetItem(f"${r['cost']:.6f}"))

        summary_text = " | ".join([
            f"<strong>{s}:</strong> ${cost_by_strategy[s]:.5f}" for s in strategies
        ])
        self.summary_label.setText(f"Simulation Totals: {summary_text}")
