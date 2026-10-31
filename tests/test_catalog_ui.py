"""Catalog review dialog and the daily startup check (offline: fetch is stubbed)."""

from __future__ import annotations

import time
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QStatusBar

import modelmesh.ui.catalog_dialog as catalog_dialog
from modelmesh.core.catalog import check_catalogs
from modelmesh.core.providers.catalog_formats import CatalogEntry
from modelmesh.core.registry import ModelRegistry
from modelmesh.core.types import CatalogSettings, EndpointConfig, ModelConfig, ProviderConfig
from modelmesh.ui.catalog_dialog import CatalogReviewDialog
from modelmesh.ui.catalog_startup import LAST_CHECK_KEY, CatalogStartupCheck
from modelmesh.ui.settings.tools_tab import get_app_settings

ENTRIES = [
    CatalogEntry(api_model="vendor/kept:free", display_name="Kept", context_window=65536,
                 price_in_per_mtok=0.0, price_out_per_mtok=0.0),
    CatalogEntry(api_model="vendor/brand-new:free", display_name="Brand New", context_window=32768,
                 price_in_per_mtok=0.0, price_out_per_mtok=0.0, tools=True),
]


def _registry(saved: List[bool]) -> ModelRegistry:
    reg = ModelRegistry()
    reg.add_provider(ProviderConfig(id="or", protocol="openai_compat", catalog=CatalogSettings(free_only=True)))
    reg.add_model(ModelConfig(id="kept", display_name="Kept", context_window=8192, endpoints=[
        EndpointConfig(id="kept@or", provider="or", api_model="vendor/kept:free")]))
    reg.add_model(ModelConfig(id="gone", display_name="Gone", endpoints=[
        EndpointConfig(id="gone@or", provider="or", api_model="vendor/gone:free")]))
    reg.save = lambda: saved.append(True) or True  # type: ignore[method-assign]
    return reg


def _pump(app: QApplication, until, timeout: float = 5.0) -> None:  # type: ignore[no-untyped-def]
    end = time.time() + timeout
    while time.time() < end and not until():
        app.processEvents()
        time.sleep(0.01)
    assert until()


def test_review_dialog_applies_only_checked_changes(qapp: QApplication) -> None:
    saved: List[bool] = []
    reg = _registry(saved)
    report = check_catalogs(reg, fetch=lambda p: ENTRIES)
    dlg = CatalogReviewDialog(reg, report)
    kinds = sorted(c.kind for c in dlg.selected_changes())
    assert kinds == ["limits", "new", "unavailable"]  # all checked by default for a free provider

    # Untick the context-limit fix, then apply.
    for i in range(dlg.tree.topLevelItemCount()):
        group = dlg.tree.topLevelItem(i)
        if group.text(0).startswith("Wrong context"):
            group.child(0).setCheckState(0, Qt.CheckState.Unchecked)
    dlg._apply()
    assert saved
    assert reg.get_model("gone").endpoints[0].enabled is False
    assert reg.get_model("kept").endpoints[0].context_window is None  # unticked: untouched
    new = reg.get_model("brand-new")
    assert new is not None and new.endpoints[0].api_model == "vendor/brand-new:free"
    assert "tools" in new.capabilities


def test_startup_check_offers_review_button(qapp: QApplication, monkeypatch) -> None:
    saved: List[bool] = []
    reg = _registry(saved)
    monkeypatch.setattr(catalog_dialog, "check_catalogs", lambda r: check_catalogs(r, fetch=lambda p: ENTRIES))
    get_app_settings().setValue(LAST_CHECK_KEY, 0)
    bar = QStatusBar()
    applied: List[bool] = []
    check = CatalogStartupCheck(reg, bar, lambda: applied.append(True))
    check._start()
    _pump(qapp, lambda: check._button is not None)
    assert "3 provider model update" in check._button.text()
    assert float(get_app_settings().value(LAST_CHECK_KEY)) > 0
    check.wait()


def test_startup_check_skips_when_checked_recently(qapp: QApplication, monkeypatch) -> None:
    get_app_settings().setValue(LAST_CHECK_KEY, time.time())
    started: List[bool] = []
    check = CatalogStartupCheck(ModelRegistry(), QStatusBar(), lambda: None)
    monkeypatch.setattr(check, "_start", lambda: started.append(True))
    check.schedule()
    qapp.processEvents()
    assert started == []
