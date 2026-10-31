"""Scores tab in Settings: Artificial Analysis and LMArena scores, links, and manual overrides."""

from __future__ import annotations

import datetime
import time
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.config.routing_config import load_routing_config
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.scores.aa_client import ATTRIBUTION_TEXT
from modelmesh.core.scores.arena_client import ARENA_ATTRIBUTION_TEXT, ARENA_SOURCE
from modelmesh.core.scores.matcher import arena_votes, match_identifiers, strict_match
from modelmesh.core.scores.snapshots import ScoreSnapshot, ScoreStore, resolve_effective_scores
from modelmesh.core.storage import get_default_storage
from modelmesh.core.types import ModelConfig
from modelmesh.ui.settings.scores_dialog import EditModelScoresDialog
from modelmesh.ui.workers import ScoresRefreshWorker

AA_SOURCE = "artificial_analysis"
COLUMNS = [
    "Model", "AA Slug", "Intelligence", "Coding", "Agentic",
    "Arena Name", "Arena Overall", "Arena Coding", "Status", "Action",
]
_REFRESH_LABELS = {AA_SOURCE: "Refresh AA Scores", ARENA_SOURCE: "Refresh Arena"}


def _records(snapshot: Optional[ScoreSnapshot]) -> List[Dict[str, Any]]:
    return list(snapshot.models_by_slug.values()) if snapshot else []


def _cell(text: str, tooltip: str = "", center: bool = True) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if center:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    if tooltip:
        item.setToolTip(tooltip)
    return item


def _num(value: Optional[float], manual: bool, decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}" + (" (M)" if manual else "")


class ScoresTab(QWidget):
    """Settings tab: model scores from both sources, link checks, overrides, and refresh."""

    config_changed = pyqtSignal()

    def __init__(
        self,
        registry: ModelRegistry,
        storage: Optional[Any] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.storage = storage or get_default_storage()
        self.store = ScoreStore(self.storage)
        self._refresh_worker: Optional[ScoresRefreshWorker] = None
        # model id -> (suggested aa slug, suggested arena name) where the current link looks wrong
        self._stale: Dict[str, Tuple[Optional[str], Optional[str]]] = {}

        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.refresh_btn = QPushButton(_REFRESH_LABELS[AA_SOURCE])
        self.refresh_btn.setToolTip("Fetch the latest snapshot from Artificial Analysis (uses your daily quota)")
        self.refresh_btn.clicked.connect(lambda: self._start_refresh(AA_SOURCE))
        header.addWidget(self.refresh_btn)

        self.arena_btn = QPushButton(_REFRESH_LABELS[ARENA_SOURCE])
        self.arena_btn.setToolTip("Download the latest LMArena text leaderboard")
        self.arena_btn.clicked.connect(lambda: self._start_refresh(ARENA_SOURCE))
        header.addWidget(self.arena_btn)

        self.automatch_btn = QPushButton("Auto-match Links")
        self.automatch_btn.setToolTip("Link unlinked models to exactly matching AA and LMArena entries")
        self.automatch_btn.clicked.connect(self._on_automatch_clicked)
        header.addWidget(self.automatch_btn)
        header.addStretch()

        self.snapshot_info_label = QLabel("Loading snapshot info...")
        self.snapshot_info_label.setObjectName("mutedLabel")
        header.addWidget(self.snapshot_info_label)
        layout.addLayout(header)

        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        hdr = self.table.horizontalHeader()
        for col in range(len(COLUMNS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table)

        footer = QHBoxLayout()
        self.attribution_label = QLabel(f"{ATTRIBUTION_TEXT} · {ARENA_ATTRIBUTION_TEXT}")
        self.attribution_label.setObjectName("mutedLabel")
        footer.addWidget(self.attribution_label)
        legend = QLabel("•  (M) Manual override  •  — Not benchmarked")
        legend.setObjectName("mutedLabel")
        footer.addWidget(legend)
        footer.addStretch()
        self.warnings_label = QLabel("")
        self.warnings_label.setStyleSheet("color: #eab308; font-size: 11.5px;")
        footer.addWidget(self.warnings_label)
        layout.addLayout(footer)

    def _snapshots(self) -> Tuple[Optional[ScoreSnapshot], Optional[str], Optional[ScoreSnapshot]]:
        aa, note = self.store.get_active_snapshot(self.registry.models())
        return aa, note, self.store.get_latest_snapshot(source=ARENA_SOURCE)

    def _update_info(self, aa: Optional[ScoreSnapshot], note: Optional[str], arena: Optional[ScoreSnapshot]) -> None:
        parts = []
        if aa:
            day = datetime.datetime.fromtimestamp(aa.fetched_at).strftime("%Y-%m-%d")
            parts.append(f"AA: index v{aa.index_version or '?'} ({day})" + ("  ⚠ older index kept" if note else ""))
        else:
            parts.append("AA: no snapshot")
        parts.append(f"Arena: {arena.index_version or '?'}" if arena else "Arena: no snapshot")
        self.snapshot_info_label.setText("   ·   ".join(parts))
        self.snapshot_info_label.setToolTip(note or "")

    def refresh(self) -> None:
        """Reload snapshots and populate the model table."""
        aa, note, arena = self._snapshots()
        self._update_info(aa, note, arena)
        aa_records, arena_records = _records(aa), _records(arena)

        models = self.registry.models()
        self.table.setRowCount(len(models))
        self._stale.clear()
        unscored = 0
        for row, m in enumerate(models):
            eff = resolve_effective_scores(m, aa, arena)
            man = m.scores.manual
            unscored += int(eff.is_unscored)

            ids = match_identifiers(m)
            aa_hint = strict_match(ids, aa_records) if aa_records else None
            arena_hint = strict_match(ids, arena_records, arena_votes) if arena_records else None
            stale_aa = aa_hint if (m.scores.aa_slug and aa_hint and aa_hint != m.scores.aa_slug) else None
            stale_arena = arena_hint if (m.scores.arena_name and arena_hint and arena_hint != m.scores.arena_name) else None
            if stale_aa or stale_arena:
                self._stale[m.id] = (stale_aa, stale_arena)

            self.table.setItem(row, 0, _cell(f"{m.display_name} ({m.id})", center=False))
            self.table.setItem(row, 1, self._link_cell(m.scores.aa_slug, stale_aa))
            self.table.setItem(row, 2, _cell(_num(eff.intelligence, man.intelligence is not None)))
            self.table.setItem(row, 3, _cell(_num(eff.coding, man.coding is not None)))
            self.table.setItem(row, 4, _cell(_num(eff.agentic, man.agentic is not None)))
            self.table.setItem(row, 5, self._link_cell(m.scores.arena_name, stale_arena))
            self.table.setItem(row, 6, _cell(_num(eff.arena.get("overall"), man.arena_text_elo is not None, 0)))
            self.table.setItem(row, 7, _cell(_num(eff.arena.get("coding"), False, 0)))
            self.table.setItem(row, 8, self._status_cell(eff.is_unscored, m.id in self._stale))

            edit_btn = QPushButton("Edit")
            edit_btn.setFixedWidth(50)
            edit_btn.clicked.connect(lambda _, model=m: self._on_edit_model(model))
            self.table.setCellWidget(row, 9, edit_btn)

        warnings = []
        if unscored:
            warnings.append(f"⚠ {unscored} model(s) unscored")
        if self._stale:
            warnings.append(f"⚠ {len(self._stale)} link(s) to check")
        self.warnings_label.setText("   ".join(warnings))

    @staticmethod
    def _link_cell(link: Optional[str], suggestion: Optional[str]) -> QTableWidgetItem:
        item = _cell(link or "— (Unlinked)", center=False)
        if not link:
            item.setForeground(Qt.GlobalColor.gray)
        if suggestion:
            item.setForeground(Qt.GlobalColor.darkYellow)
            item.setToolTip(f"The endpoint's model matches '{suggestion}' exactly. Auto-match Links can switch to it.")
        return item

    @staticmethod
    def _status_cell(is_unscored: bool, stale: bool) -> QTableWidgetItem:
        if stale:
            item = _cell("Check link", "A link points at a different model version than the endpoint calls")
            item.setForeground(Qt.GlobalColor.darkYellow)
        elif is_unscored:
            item = _cell("Unscored", "No score from either source; Smart routing skips this model")
            item.setForeground(Qt.GlobalColor.darkYellow)
        else:
            item = _cell("OK")
            item.setForeground(Qt.GlobalColor.darkGreen)
        return item

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        models = self.registry.models()
        if 0 <= row < len(models):
            self._on_edit_model(models[row])

    def _on_edit_model(self, model: ModelConfig) -> None:
        dialog = EditModelScoresDialog(model, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            model.scores.aa_slug, model.scores.arena_name, model.scores.manual = dialog.get_values()
            self._save()

    def _save(self) -> None:
        self.registry.save()
        self.refresh()
        self.config_changed.emit()

    def _start_refresh(self, source: str) -> None:
        if self._refresh_worker and self._refresh_worker.isRunning():
            return
        if source == AA_SOURCE and not self._confirm_aa_refresh_if_recent():
            return
        btn = self.refresh_btn if source == AA_SOURCE else self.arena_btn
        self.refresh_btn.setEnabled(False)
        self.arena_btn.setEnabled(False)
        btn.setText("Fetching...")
        self._refresh_worker = ScoresRefreshWorker(storage=self.storage, parent=self, source=source)
        self._refresh_worker.finished_refresh.connect(self._on_refresh_finished)
        self._refresh_worker.error_occurred.connect(self._on_refresh_error)
        self._refresh_worker.start()

    def _confirm_aa_refresh_if_recent(self) -> bool:
        """Free-tier AA requests are limited: ask first if the snapshot is newer than the configured interval."""
        newest = self.store.get_latest_snapshot()
        if newest is None:
            return True
        min_days = load_routing_config().scores.refresh_min_interval_days
        age_days = (time.time() - newest.fetched_at) / 86400
        if age_days >= min_days:
            return True
        reply = QMessageBox.question(
            self,
            "Scores Are Recent",
            f"Scores were refreshed {age_days:.1f} days ago (minimum interval: {min_days} days). "
            "Refresh anyway? This uses your Artificial Analysis request quota.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _reset_buttons(self) -> None:
        self.refresh_btn.setEnabled(True)
        self.arena_btn.setEnabled(True)
        self.refresh_btn.setText(_REFRESH_LABELS[AA_SOURCE])
        self.arena_btn.setText(_REFRESH_LABELS[ARENA_SOURCE])

    def _on_refresh_finished(self, data: Dict[str, Any]) -> None:
        self._reset_buttons()
        name = "LMArena" if data.get("source") == ARENA_SOURCE else "Artificial Analysis"
        QMessageBox.information(
            self, "Scores Refreshed",
            f"Updated snapshot with {data.get('models_count', 0)} models from {name}.",
        )
        self.refresh()
        self.config_changed.emit()

    def _on_refresh_error(self, err_msg: str) -> None:
        self._reset_buttons()
        QMessageBox.warning(self, "Refresh Failed", f"Could not refresh scores:\n{err_msg}")

    def _on_automatch_clicked(self) -> None:
        aa, _, arena = self._snapshots()
        if not aa and not arena:
            QMessageBox.warning(self, "No Snapshot", "Refresh AA scores or the Arena leaderboard first.")
            return
        aa_records, arena_records = _records(aa), _records(arena)
        linked = 0
        for model in self.registry.models():
            ids = match_identifiers(model)
            if not model.scores.aa_slug and aa_records:
                model.scores.aa_slug = strict_match(ids, aa_records)
                linked += int(bool(model.scores.aa_slug))
            if not model.scores.arena_name and arena_records:
                model.scores.arena_name = strict_match(ids, arena_records, arena_votes)
                linked += int(bool(model.scores.arena_name))

        fixed = 0
        if self._stale:
            lines = []
            for mid, (aa_s, ar_s) in self._stale.items():
                m = self.registry.get_model(mid)
                if aa_s:
                    lines.append(f"{mid}: AA {m.scores.aa_slug} → {aa_s}")
                if ar_s:
                    lines.append(f"{mid}: Arena {m.scores.arena_name} → {ar_s}")
            reply = QMessageBox.question(
                self, "Fix Links?",
                "These links point at a different model version than the endpoint calls:\n\n"
                + "\n".join(lines) + "\n\nSwitch them to the exact matches?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                for mid, (aa_s, ar_s) in self._stale.items():
                    m = self.registry.get_model(mid)
                    m.scores.aa_slug = aa_s or m.scores.aa_slug
                    m.scores.arena_name = ar_s or m.scores.arena_name
                    fixed += int(bool(aa_s)) + int(bool(ar_s))

        if linked or fixed:
            self._save()
        QMessageBox.information(
            self, "Auto-match",
            f"Linked {linked} and fixed {fixed} score link(s)." if (linked or fixed)
            else "No exact matches found for unlinked models. Use Edit to link them by hand.",
        )
