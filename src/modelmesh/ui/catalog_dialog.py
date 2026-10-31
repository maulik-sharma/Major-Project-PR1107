"""Model catalog check: background worker and the review-then-apply dialog."""

from __future__ import annotations

from typing import Any, List, Optional

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.catalog import KINDS, CatalogChange, CatalogReport, apply_changes, check_catalogs
from modelmesh.core.errors import RegistryError
from modelmesh.core.registry import ModelRegistry

GROUP_TITLES = {
    "unavailable": "No longer offered by the provider",
    "retired": "Retired or shut down",
    "no_longer_free": "No longer free",
    "limits": "Wrong context or output limits",
    "price": "Wrong prices",
    "deprecated": "Deprecated (still works for now)",
    "new": "New models available",
}


class CatalogCheckWorker(QThread):
    """Fetches every provider's model list off the UI thread and emits a CatalogReport."""

    finished_check = pyqtSignal(object)  # CatalogReport

    def __init__(self, registry: ModelRegistry, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.registry = registry

    def run(self) -> None:
        try:
            report = check_catalogs(self.registry)
        except Exception as exc:  # never let a check crash the app
            report = CatalogReport(errors={"catalog": str(exc)})
        self.finished_check.emit(report)


def apply_selected(registry: ModelRegistry, changes: List[CatalogChange]) -> str:
    """Apply changes to the registry and save providers.yaml. Returns a one-line summary."""
    models = {m.id: m for m in registry.models()}
    providers = {p.id: p for p in registry.providers()}
    created = apply_changes(models, providers, changes)
    for model in created:
        registry.add_model(model)
    registry.save()
    added = sum(1 for c in changes if c.kind == "new")
    disabled = sum(1 for c in changes if c.updates.get("enabled") is False)
    fixed = len(changes) - added - disabled
    return f"Added {added} model endpoint(s), disabled {disabled}, corrected {fixed}."


class CatalogReviewDialog(QDialog):
    """Lists proposed catalog changes with checkboxes; applies only the checked ones."""

    applied = pyqtSignal(str)

    def __init__(self, registry: ModelRegistry, report: CatalogReport, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Provider Model Updates")
        self.resize(820, 560)
        self.registry = registry
        self._changes: List[CatalogChange] = list(report.changes)

        layout = QVBoxLayout(self)
        checked = ", ".join(report.checked) or "none"
        intro = QLabel(f"Compared providers.yaml with the live model lists of: {checked}. "
                       "Nothing changes until you apply.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        if report.errors:
            err = QLabel("Could not check: " + "; ".join(f"{p}: {msg}" for p, msg in report.errors.items()))
            err.setWordWrap(True)
            err.setObjectName("mutedLabel")
            layout.addWidget(err)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree)
        self._populate(report.changes)

        buttons = QDialogButtonBox()
        self.apply_btn = QPushButton("Apply Selected")
        self.apply_btn.setEnabled(bool(report.changes))
        buttons.addButton(self.apply_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.apply_btn.clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, changes: List[CatalogChange]) -> None:
        if not changes:
            self.tree.addTopLevelItem(QTreeWidgetItem(["providers.yaml matches every provider that was checked."]))
            return
        for kind in KINDS:
            group = [c for c in changes if c.kind == kind]
            if not group:
                continue
            parent = QTreeWidgetItem([f"{GROUP_TITLES[kind]} ({len(group)})"])
            parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            self.tree.addTopLevelItem(parent)
            for ch in group:
                item = QTreeWidgetItem([f"[{ch.provider_id}] {ch.summary}"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if ch.default_apply else Qt.CheckState.Unchecked)
                item.setData(0, Qt.ItemDataRole.UserRole, self._changes.index(ch))
                parent.addChild(item)
            parent.setExpanded(kind != "new" or len(group) <= 15)

    def selected_changes(self) -> List[CatalogChange]:
        """Changes whose checkbox is ticked."""
        chosen = []
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                item = parent.child(j)
                index = item.data(0, Qt.ItemDataRole.UserRole)
                if item.checkState(0) == Qt.CheckState.Checked and index is not None:
                    chosen.append(self._changes[index])
        return chosen

    def _apply(self) -> None:
        chosen = self.selected_changes()
        if not chosen:
            self.reject()
            return
        try:
            summary = apply_selected(self.registry, chosen)
        except (RegistryError, OSError) as exc:
            QMessageBox.warning(self, "Not Saved", f"The changes could not be saved: {exc}")
            return
        self.applied.emit(summary)
        self.accept()
