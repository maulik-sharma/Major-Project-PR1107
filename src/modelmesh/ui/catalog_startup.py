"""Daily background check of provider model lists, offered to the user from the status bar."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QPushButton, QStatusBar, QWidget

from modelmesh.core.catalog import CatalogReport
from modelmesh.core.registry import ModelRegistry
from modelmesh.ui.catalog_dialog import CatalogCheckWorker, CatalogReviewDialog
from modelmesh.ui.settings.tools_tab import get_app_settings

LAST_CHECK_KEY = "catalog/last_checked"
CHECK_INTERVAL_SECONDS = 24 * 3600
START_DELAY_MS = 4000  # let the window settle before touching the network


class CatalogStartupCheck(QObject):
    """Runs the catalog check at most once a day; shows a status-bar button when changes exist."""

    def __init__(
        self,
        registry: ModelRegistry,
        status_bar: QStatusBar,
        on_applied: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.status_bar = status_bar
        self.on_applied = on_applied
        self._parent_widget = parent
        self.worker: Optional[CatalogCheckWorker] = None
        self._button: Optional[QPushButton] = None
        self._report: Optional[CatalogReport] = None

    def schedule(self) -> None:
        """Start the check shortly after launch if the last one is older than a day."""
        try:
            last = float(get_app_settings().value(LAST_CHECK_KEY, 0) or 0)
        except (TypeError, ValueError):
            last = 0.0
        if time.time() - last >= CHECK_INTERVAL_SECONDS:
            QTimer.singleShot(START_DELAY_MS, self._start)

    def _start(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.worker = CatalogCheckWorker(self.registry, parent=self)
        self.worker.finished_check.connect(self._on_finished)
        self.worker.start()

    def _on_finished(self, report: Any) -> None:
        if report.checked:  # only count as checked if at least one provider answered
            get_app_settings().setValue(LAST_CHECK_KEY, time.time())
        if not report.changes:
            return
        self._report = report
        if self._button is None:
            self._button = QPushButton()
            self._button.setFlat(True)
            self._button.clicked.connect(self._review)
            self.status_bar.addPermanentWidget(self._button)
        self._button.setText(f"{len(report.changes)} provider model update(s) available. Review")
        self._button.show()

    def _review(self) -> None:
        if self._report is None:
            return
        dialog = CatalogReviewDialog(self.registry, self._report, parent=self._parent_widget)
        dialog.applied.connect(self.status_bar.showMessage)
        if dialog.exec() == CatalogReviewDialog.DialogCode.Accepted:
            self.on_applied()
        dialog.deleteLater()
        if self._button is not None:
            self._button.hide()  # re-checked tomorrow, or now from Settings → Endpoints
        self._report = None

    def wait(self, msecs: int = 5000) -> None:
        """Let a running check finish (called on window close)."""
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(msecs)
