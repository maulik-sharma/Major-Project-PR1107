"""Scores tab in Settings displaying Artificial Analysis benchmark scores and manual overrides."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.registry import ModelRegistry, get_default_config_dir
from modelmesh.core.scores.matcher import suggest_model_slugs
from modelmesh.core.scores.snapshots import (
    EffectiveScores,
    ScoreSnapshot,
    ScoreStore,
    resolve_effective_scores,
)
from modelmesh.core.storage import get_default_storage
from modelmesh.core.types import ManualScoresConfig, ModelConfig, ModelScoresConfig
from modelmesh.ui.workers import ScoresRefreshWorker


class EditModelScoresDialog(QDialog):
    """Dialog for editing manual score overrides and AA slug for a logical model."""

    def __init__(
        self,
        model: ModelConfig,
        available_slugs: List[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Scores - {model.display_name}")
        self.setFixedWidth(440)
        self.model = model

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()

        # AA Slug
        self.slug_input = QLineEdit()
        self.slug_input.setText(model.scores.aa_slug or "")
        self.slug_input.setPlaceholderText("e.g. anthropic/claude-3-5-sonnet")
        form.addRow("AA Slug:", self.slug_input)

        # Manual Overrides
        man = model.scores.manual
        self.intel_spin = QDoubleSpinBox()
        self.intel_spin.setRange(0.0, 100.0)
        self.intel_spin.setDecimals(1)
        self.intel_spin.setSpecialValueText("Auto / None")
        self.intel_spin.setValue(man.intelligence if man.intelligence is not None else 0.0)
        form.addRow("Manual Intelligence:", self.intel_spin)

        self.coding_spin = QDoubleSpinBox()
        self.coding_spin.setRange(0.0, 100.0)
        self.coding_spin.setDecimals(1)
        self.coding_spin.setSpecialValueText("Auto / None")
        self.coding_spin.setValue(man.coding if man.coding is not None else 0.0)
        form.addRow("Manual Coding:", self.coding_spin)

        self.agent_spin = QDoubleSpinBox()
        self.agent_spin.setRange(0.0, 100.0)
        self.agent_spin.setDecimals(1)
        self.agent_spin.setSpecialValueText("Auto / None")
        self.agent_spin.setValue(man.agentic if man.agentic is not None else 0.0)
        form.addRow("Manual Agentic:", self.agent_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> tuple[Optional[str], ManualScoresConfig]:
        slug = self.slug_input.text().strip() or None
        intel = self.intel_spin.value() if self.intel_spin.value() > 0.0 else None
        coding = self.coding_spin.value() if self.coding_spin.value() > 0.0 else None
        agent = self.agent_spin.value() if self.agent_spin.value() > 0.0 else None
        return slug, ManualScoresConfig(
            intelligence=intel,
            coding=coding,
            agentic=agent,
        )


class ScoresTab(QWidget):
    """Settings tab displaying model scores, linking, overrides, and AA refresh."""

    config_changed = pyqtSignal()

    def __init__(
        self,
        registry: ModelRegistry,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.storage = get_default_storage()
        self.store = ScoreStore(self.storage)
        self._refresh_worker: Optional[ScoresRefreshWorker] = None

        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Header controls
        header_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Scores")
        self.refresh_btn.setToolTip("Fetch latest score snapshot from Artificial Analysis")
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        header_layout.addWidget(self.refresh_btn)

        self.automatch_btn = QPushButton("Auto-match Slugs")
        self.automatch_btn.setToolTip("Auto-detect AA slugs for unlinked models")
        self.automatch_btn.clicked.connect(self._on_automatch_clicked)
        header_layout.addWidget(self.automatch_btn)

        header_layout.addStretch()

        self.snapshot_info_label = QLabel("Loading snapshot info...")
        self.snapshot_info_label.setStyleSheet("color: var(--text-muted); font-size: 11.5px;")
        header_layout.addWidget(self.snapshot_info_label)

        layout.addLayout(header_layout)

        # Main Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Model",
            "AA Slug",
            "Intelligence",
            "Coding",
            "Agentic",
            "Status",
            "Action",
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table)

        # Footer with required attribution and warnings
        footer_layout = QHBoxLayout()
        self.attribution_label = QLabel("Model scores: Artificial Analysis")
        self.attribution_label.setStyleSheet(
            "color: var(--text-muted); font-weight: 500; font-size: 11.5px;"
        )
        footer_layout.addWidget(self.attribution_label)

        self.legend_label = QLabel("•  (M) Manual override  •  (I) Inherited from Intelligence")
        self.legend_label.setStyleSheet(
            "color: var(--text-muted); font-size: 11.5px;"
        )
        footer_layout.addWidget(self.legend_label)

        footer_layout.addStretch()

        self.warnings_label = QLabel("")
        self.warnings_label.setStyleSheet("color: #eab308; font-size: 11.5px;")
        footer_layout.addWidget(self.warnings_label)

        layout.addLayout(footer_layout)

    def refresh(self) -> None:
        """Reload snapshot and populate model table."""
        snapshot = self.store.get_latest_snapshot()
        if snapshot:
            dt_str = datetime.datetime.fromtimestamp(snapshot.fetched_at).strftime("%Y-%m-%d %H:%M")
            count = len(snapshot.models_by_slug)
            rem = f", {snapshot.rate_limit_remaining} reqs left" if snapshot.rate_limit_remaining is not None else ""
            self.snapshot_info_label.setText(
                f"Snapshot: {dt_str} ({count} models{rem})"
            )
        else:
            self.snapshot_info_label.setText("No snapshot cached (using local defaults)")

        models = self.registry.models()
        self.table.setRowCount(len(models))

        unscored_count = 0

        for row, m in enumerate(models):
            eff: EffectiveScores = resolve_effective_scores(m, snapshot)
            if eff.is_unscored:
                unscored_count += 1

            # 0. Model
            m_item = QTableWidgetItem(f"{m.display_name} ({m.id})")
            self.table.setItem(row, 0, m_item)

            # 1. AA Slug
            slug_text = m.scores.aa_slug or "— (Unlinked)"
            slug_item = QTableWidgetItem(slug_text)
            if not m.scores.aa_slug:
                slug_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 1, slug_item)

            # 2. Intelligence
            int_val = f"{eff.intelligence:.1f}" if eff.intelligence is not None else "—"
            if m.scores.manual.intelligence is not None:
                int_val += " (M)"
            int_item = QTableWidgetItem(int_val)
            int_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if m.scores.manual.intelligence is not None:
                int_item.setToolTip("Manual override configured in providers.yaml")
            elif eff.intelligence is not None:
                int_item.setToolTip("Artificial Analysis Intelligence Index")
            self.table.setItem(row, 2, int_item)

            # 3. Coding
            if eff.coding is not None:
                if m.scores.manual.coding is not None:
                    code_val = f"{eff.coding:.1f} (M)"
                    code_tip = "Manual override configured in providers.yaml"
                elif eff.is_coding_inherited:
                    code_val = f"{eff.coding:.1f} (I)"
                    code_tip = "Inherited from Intelligence Index (not separately benchmarked by Artificial Analysis)"
                else:
                    code_val = f"{eff.coding:.1f}"
                    code_tip = "Artificial Analysis Coding Index (SWE-bench / HumanEval composite)"
            else:
                code_val = "—"
                code_tip = "Unscored"
            code_item = QTableWidgetItem(code_val)
            code_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            code_item.setToolTip(code_tip)
            self.table.setItem(row, 3, code_item)

            # 4. Agentic
            if eff.agentic is not None:
                if m.scores.manual.agentic is not None:
                    agent_val = f"{eff.agentic:.1f} (M)"
                    agent_tip = "Manual override configured in providers.yaml"
                elif eff.is_agentic_inherited:
                    agent_val = f"{eff.agentic:.1f} (I)"
                    agent_tip = "Inherited from Intelligence Index (not separately benchmarked by Artificial Analysis)"
                else:
                    agent_val = f"{eff.agentic:.1f}"
                    agent_tip = "Artificial Analysis Agentic Tool-Use Index"
            else:
                agent_val = "—"
                agent_tip = "Unscored"
            agent_item = QTableWidgetItem(agent_val)
            agent_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            agent_item.setToolTip(agent_tip)
            self.table.setItem(row, 4, agent_item)

            # 5. Status
            status_text = "OK" if not eff.is_unscored else "Unscored"
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if eff.is_unscored:
                status_item.setForeground(Qt.GlobalColor.darkYellow)
            else:
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            self.table.setItem(row, 5, status_item)

            # 6. Action Edit Button
            edit_btn = QPushButton("Edit")
            edit_btn.setFixedWidth(50)
            edit_btn.clicked.connect(lambda _, model=m: self._on_edit_model(model))
            self.table.setCellWidget(row, 6, edit_btn)

        if unscored_count > 0:
            self.warnings_label.setText(f"⚠ {unscored_count} model(s) are unscored")
        else:
            self.warnings_label.setText("")

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        models = self.registry.models()
        if 0 <= row < len(models):
            self._on_edit_model(models[row])

    def _on_edit_model(self, model: ModelConfig) -> None:
        snapshot = self.store.get_latest_snapshot()
        available_slugs = list(snapshot.models_by_slug.keys()) if snapshot else []

        dialog = EditModelScoresDialog(model, available_slugs, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            slug, manual = dialog.get_values()
            model.scores.aa_slug = slug
            model.scores.manual = manual

            self.registry.save_to_file(get_default_config_dir() / "providers.yaml")
            self.refresh()
            self.config_changed.emit()

    def _on_refresh_clicked(self) -> None:
        if self._refresh_worker and self._refresh_worker.isRunning():
            return

        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Fetching...")

        self._refresh_worker = ScoresRefreshWorker(parent=self)
        self._refresh_worker.finished_refresh.connect(self._on_refresh_finished)
        self._refresh_worker.error_occurred.connect(self._on_refresh_error)
        self._refresh_worker.start()

    def _on_refresh_finished(self, data: Dict[str, Any]) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("⟳ Refresh Scores")
        QMessageBox.information(
            self,
            "Scores Refreshed",
            f"Successfully updated snapshot with {data.get('models_count', 0)} models from Artificial Analysis.",
        )
        self.refresh()
        self.config_changed.emit()

    def _on_refresh_error(self, err_msg: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("⟳ Refresh Scores")
        QMessageBox.warning(
            self,
            "Refresh Failed",
            f"Could not refresh scores from Artificial Analysis:\n{err_msg}",
        )

    def _on_automatch_clicked(self) -> None:
        snapshot = self.store.get_latest_snapshot()
        if not snapshot:
            QMessageBox.warning(self, "No Snapshot", "Please refresh scores snapshot first.")
            return

        raw_models = snapshot.raw_payload.get("models") or list(snapshot.models_by_slug.values())
        updated = 0

        for model in self.registry.models():
            if not model.scores.aa_slug:
                suggs = suggest_model_slugs(model.id, raw_models, limit=1)
                if suggs:
                    top_match = suggs[0]
                    slug_val = top_match.get("slug") if isinstance(top_match, dict) else str(top_match)
                    if slug_val:
                        model.scores.aa_slug = slug_val
                        updated += 1

        if updated > 0:
            self.registry.save_to_file(get_default_config_dir() / "providers.yaml")
            self.refresh()
            self.config_changed.emit()
            QMessageBox.information(
                self,
                "Auto-match Complete",
                f"Auto-matched and updated AA slugs for {updated} model(s).",
            )
        else:
            QMessageBox.information(
                self,
                "Auto-match",
                "No additional model slug matches found.",
            )

