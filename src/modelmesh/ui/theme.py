"""QSS styles and theme definitions for ModelMesh PyQt6 interface."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QApplication

DARK_THEME_QSS = """
QMainWindow, QDialog {
    background-color: #141417;
    color: #f4f4f6;
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
}

QWidget {
    background-color: transparent;
    color: #f4f4f6;
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

/* ToolBar and Header */
QToolBar {
    background-color: #141417;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    padding: 6px 14px;
    spacing: 10px;
}

QToolButton {
    background-color: transparent;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 7px;
    color: #a1a1aa;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
}

QToolButton:hover {
    background-color: rgba(255, 255, 255, 0.05);
    color: #ffffff;
    border-color: rgba(255, 255, 255, 0.15);
}

QToolButton:checked {
    background-color: rgba(59, 130, 246, 0.15);
    color: #60a5fa;
    border-color: rgba(59, 130, 246, 0.35);
}

/* Sidebar */
#sidebar {
    background-color: #141417;
    border-right: 1px solid rgba(255, 255, 255, 0.06);
}

#sidebarHeader {
    background-color: transparent;
    padding: 14px 14px 8px 14px;
}

#brandTitle {
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.2px;
    color: #f4f4f6;
}

#newChatBtn {
    background-color: #222226;
    color: #f4f4f6;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 500;
    font-size: 13px;
    text-align: left;
}

#newChatBtn:hover {
    background-color: #2b2b30;
    border-color: rgba(255, 255, 255, 0.18);
}

#newChatBtn:pressed {
    background-color: #1b1b1e;
}

#sidebarSkillsBtn, #sidebarToolsBtn {
    background-color: transparent;
    color: #d4d4d8;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 7px 12px;
    font-weight: 500;
    font-size: 12.5px;
    text-align: left;
}

#sidebarSkillsBtn:hover, #sidebarToolsBtn:hover {
    background-color: rgba(255, 255, 255, 0.05);
    border-color: rgba(255, 255, 255, 0.15);
    color: #ffffff;
}

#sidebarSkillsBtn[active="true"], #sidebarToolsBtn[active="true"] {
    background-color: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.22);
    color: #ffffff;
    font-weight: 600;
}

#skillsView, #toolsView {
    background-color: #141416;
}

#skillsHeaderTitle, #toolsHeaderTitle {
    font-size: 24px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.4px;
}

#skillsHeaderSubtitle, #toolsHeaderSubtitle {
    font-size: 13px;
    color: #a1a1aa;
    line-height: 1.4;
}

#skillImportBtn, #toolsBrowseBtn {
    background-color: #222226;
    color: #f4f4f6;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 7px;
    padding: 7px 14px;
    font-size: 12.5px;
    font-weight: 500;
}

#skillImportBtn:hover, #toolsBrowseBtn:hover {
    background-color: #2c2c31;
    border-color: rgba(255, 255, 255, 0.22);
}

#skillNewBtn, #toolTestRunBtn {
    background-color: #f4f4f6;
    color: #141416;
    border: none;
    border-radius: 7px;
    padding: 7px 16px;
    font-size: 12.5px;
    font-weight: 600;
}

#skillNewBtn:hover, #toolTestRunBtn:hover {
    background-color: #ffffff;
}

.skillFilterPill, .toolFilterPill {
    background-color: rgba(255, 255, 255, 0.04);
    color: #a1a1aa;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 20px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
}

.skillFilterPill:hover, .toolFilterPill:hover {
    background-color: rgba(255, 255, 255, 0.08);
    color: #ffffff;
}

.skillFilterPill:checked, .toolFilterPill:checked {
    background-color: rgba(255, 255, 255, 0.14);
    border-color: rgba(255, 255, 255, 0.25);
    color: #ffffff;
    font-weight: 600;
}

#skillSearchBox, #toolSearchBox, #searchBox {
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 7px;
    padding: 6px 12px;
    color: #f4f4f6;
    font-size: 12px;
}

#skillSearchBox:focus, #toolSearchBox:focus, #searchBox:focus {
    border-color: #3b82f6;
    background-color: rgba(255, 255, 255, 0.06);
}

#skillCard, #toolCard, #toolsWorkspaceCard, #toolDetailHeader, #usageSummaryCard {
    background-color: #18181c;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 9px;
}

#skillCard:hover, #toolCard:hover {
    border-color: rgba(255, 255, 255, 0.12);
    background-color: #1d1d22;
}

#skillCardInitialBadge, #toolCardInitialBadge {
    background-color: rgba(255, 255, 255, 0.07);
    color: #e4e4e7;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 7px;
    font-size: 13px;
    font-weight: 600;
}

#skillCardTitle, #toolCardTitle {
    font-size: 14px;
    font-weight: 600;
    color: #ffffff;
}

#skillCardDesc, #toolCardDesc {
    font-size: 12.5px;
    color: #a1a1aa;
    line-height: 1.35;
}

#skillCardActionBtn, #toolCardActionBtn {
    background-color: #27272a;
    color: #f4f4f6;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 500;
}

#skillCardActionBtn:hover, #toolCardActionBtn:hover {
    background-color: #3f3f46;
    color: #ffffff;
    border-color: rgba(255, 255, 255, 0.22);
}

#skillCardDeleteBtn {
    background-color: #27272a;
    color: #fca5a5;
    border: 1px solid rgba(239, 68, 68, 0.2);
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 500;
}

#skillCardDeleteBtn:hover {
    background-color: rgba(239, 68, 68, 0.15);
    color: #ef4444;
    border-color: rgba(239, 68, 68, 0.4);
}

#skillFileTree {
    background-color: #18181b;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 4px;
}

#skillFileTree::item {
    padding: 5px 6px;
    border-radius: 4px;
    color: #a1a1aa;
    font-size: 12px;
}

#skillFileTree::item:selected {
    background-color: rgba(255, 255, 255, 0.1);
    color: #ffffff;
    font-weight: 500;
}

#skillFileEditor {
    background-color: #111113;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    color: #e4e4e7;
    font-size: 12.5px;
    padding: 8px;
}

#toolsWorkspaceInput {
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 5px 10px;
    color: #f4f4f6;
    font-size: 12px;
    font-family: 'JetBrains Mono', 'Menlo', monospace;
}

#toolsWorkspaceInput:focus {
    border-color: #3b82f6;
    background-color: rgba(255, 255, 255, 0.06);
}

#sidebarSectionLabel {
    font-size: 11px;
    font-weight: 600;
    color: #71717a;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    padding: 10px 14px 4px 14px;
}

#conversationList {
    background-color: transparent;
    border: none;
    padding: 4px 6px;
}

#conversationList::item {
    background-color: transparent;
    color: #a1a1aa;
    border-radius: 6px;
    padding: 7px 10px;
    margin-bottom: 1px;
    font-size: 13px;
}

#conversationList::item:hover {
    background-color: rgba(255, 255, 255, 0.04);
    color: #ffffff;
}

#conversationList::item:selected {
    background-color: rgba(255, 255, 255, 0.08);
    color: #ffffff;
    font-weight: 500;
}

#sidebarFooter {
    background-color: transparent;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    padding: 8px 10px;
}

#sidebarFooter QPushButton, .sidebarActionBtn {
    background-color: transparent;
    border: none;
    border-radius: 6px;
    color: #a1a1aa;
    padding: 6px 10px;
    text-align: left;
    font-size: 12.5px;
    font-weight: 400;
}

#sidebarFooter QPushButton:hover, .sidebarActionBtn:hover {
    background-color: rgba(255, 255, 255, 0.06);
    color: #ffffff;
}

#sidebarFooter QPushButton:pressed, .sidebarActionBtn:pressed {
    background-color: rgba(255, 255, 255, 0.03);
}

/* Chat Container */
#chatContainer, #mainStack, #mainSplitter {
    background-color: #141417;
}

/* Composer Panel */
#composerWidget {
    background-color: #141417;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    padding: 10px 24px 18px 24px;
}

#inputCard {
    background-color: #1c1c20;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 18px;
    padding: 10px 14px 8px 14px;
}

#inputCard:focus-within {
    border-color: rgba(255, 255, 255, 0.18);
    background-color: #1f1f23;
}

#messageInput {
    background-color: transparent;
    border: none;
    color: #f4f4f6;
    font-size: 14.5px;
    line-height: 1.5;
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 2px 0;
}

#sendBtn {
    background-color: #ffffff;
    color: #0f0f11;
    border: none;
    border-radius: 14px;
    padding: 5px 14px;
    font-weight: 600;
    font-size: 12.5px;
}

#sendBtn:hover {
    background-color: #e4e4e7;
}

#stopBtn {
    background-color: #ef4444;
    color: #ffffff;
    border: none;
    border-radius: 14px;
    padding: 5px 14px;
    font-weight: 600;
    font-size: 12.5px;
}

#stopBtn:hover {
    background-color: #dc2626;
}

#attachBtn {
    background-color: transparent;
    border: none;
    border-radius: 14px;
    color: #71717a;
    font-size: 16px;
    padding: 4px;
}

#attachBtn:hover {
    background-color: rgba(255, 255, 255, 0.08);
    color: #ffffff;
}

#tokenCaption {
    color: #52525b;
    font-size: 11px;
}

#attachmentChip {
    background-color: #222226;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
}

/* Strategy & Model Dropdowns */
QComboBox {
    background-color: #1c1c1f;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 7px;
    padding: 4px 10px;
    color: #f4f4f6;
    font-size: 12px;
    font-weight: 500;
}

QComboBox:hover {
    border-color: rgba(255, 255, 255, 0.16);
    background-color: #222226;
}

QComboBox:disabled {
    color: #52525b;
    background-color: rgba(255, 255, 255, 0.02);
    border-color: rgba(255, 255, 255, 0.04);
}

QComboBox::drop-down {
    border: none;
    padding-right: 6px;
}

QComboBox QAbstractItemView {
    background-color: #18181b;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    selection-background-color: #27272a;
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}

/* Buttons and Inputs in Dialogs */
QPushButton {
    background-color: #222226;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 7px;
    color: #f4f4f6;
    padding: 6px 14px;
    font-size: 12.5px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #27272a;
    border-color: rgba(255, 255, 255, 0.16);
}

QPushButton:pressed {
    background-color: #18181b;
}

QPushButton:disabled {
    background-color: rgba(255, 255, 255, 0.02);
    color: #52525b;
    border-color: rgba(255, 255, 255, 0.04);
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background-color: #18181b;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 7px;
    padding: 6px 10px;
    color: #f4f4f6;
    font-size: 12.5px;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #3b82f6;
    background-color: #1c1c1f;
}

/* Checkbox */
QCheckBox {
    color: #f4f4f6;
    font-size: 13px;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 4px;
    background-color: #18181b;
}

QCheckBox::indicator:checked {
    background-color: #3b82f6;
    border-color: #3b82f6;
}

/* Menus */
QMenu {
    background-color: #18181b;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    padding: 4px;
}

QMenu::item {
    background-color: transparent;
    color: #f4f4f6;
    padding: 6px 14px;
    border-radius: 5px;
    font-size: 12.5px;
}

QMenu::item:selected {
    background-color: #27272a;
    color: #ffffff;
}

/* Tab Widget */
QTabWidget::pane {
    border: 1px solid rgba(255, 255, 255, 0.06);
    background-color: #141417;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #18181b;
    color: #71717a;
    padding: 8px 16px;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-bottom: none;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    margin-right: 3px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: #141417;
    color: #f4f4f6;
    border-color: rgba(255, 255, 255, 0.12);
}

/* Tables and Trees */
QTableWidget, QTreeWidget, QListWidget {
    background-color: #141417;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    color: #f4f4f6;
    gridline-color: rgba(255, 255, 255, 0.04);
    outline: none;
}

QTableWidget::item, QTreeWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

QTableWidget::item:selected, QTreeWidget::item:selected {
    background-color: #27272a;
    color: #ffffff;
}

QTableWidget QPushButton {
    background-color: #27272a;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 5px;
    color: #f4f4f6;
    padding: 3px 10px;
    font-size: 11.5px;
    font-weight: 500;
    min-height: 22px;
}

QTableWidget QPushButton:hover {
    background-color: #3f3f46;
    color: #ffffff;
    border-color: rgba(255, 255, 255, 0.22);
}

QHeaderView::section {
    background-color: #18181b;
    color: #71717a;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

/* Splitter */
QSplitter::handle {
    background-color: rgba(255, 255, 255, 0.04);
}

QSplitter::handle:hover {
    background-color: rgba(255, 255, 255, 0.1);
}

/* Status Bar */
QStatusBar {
    background-color: #141417;
    border-top: 1px solid rgba(255, 255, 255, 0.04);
    color: #71717a;
    font-size: 11px;
    padding: 2px 8px;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.12);
    min-height: 24px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 0.22);
}

/* Dynamic Component Overrides */
#toolbarLabel {
    font-weight: 500;
    color: #a1a1aa;
    font-size: 12px;
}

#toolsWorkspaceLabel {
    font-weight: 600;
    color: #f4f4f6;
    font-size: 12px;
}

#toolToggleBtn, #skillToggleBtn {
    background-color: rgba(255, 255, 255, 0.04);
    color: #71717a;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11.5px;
    font-weight: 500;
}

#toolToggleBtn:hover, #skillToggleBtn:hover {
    background-color: rgba(255, 255, 255, 0.08);
    color: #a1a1aa;
}

#toolToggleBtn[active="true"], #skillToggleBtn[active="true"] {
    background-color: rgba(16, 185, 129, 0.15);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.35);
}

#toolToggleBtn[active="true"]:hover, #skillToggleBtn[active="true"]:hover {
    background-color: rgba(16, 185, 129, 0.25);
}

#emptyPlaceholderLabel {
    color: #71717a;
    font-size: 13px;
    padding: 30px;
    text-align: center;
}
"""

LIGHT_THEME_QSS = """
QMainWindow, QDialog {
    background-color: #f8fafc;
    color: #0f172a;
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
}

QWidget {
    background-color: transparent;
    color: #0f172a;
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

/* ToolBar and Header */
QToolBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e2e8f0;
    padding: 6px 14px;
    spacing: 10px;
}

QToolButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    color: #475569;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
}

QToolButton:hover {
    background-color: #f1f5f9;
    color: #0f172a;
    border-color: #94a3b8;
}

QToolButton:checked {
    background-color: #eff6ff;
    color: #2563eb;
    border-color: #93c5fd;
}

/* Sidebar */
#sidebar {
    background-color: #f8fafc;
    border-right: 1px solid #e2e8f0;
}

#sidebarHeader {
    background-color: transparent;
    padding: 14px 14px 8px 14px;
}

#brandTitle {
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.2px;
    color: #0f172a;
}

#newChatBtn {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 500;
    font-size: 13px;
    text-align: left;
}

#newChatBtn:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
}

#newChatBtn:pressed {
    background-color: #e2e8f0;
}

#sidebarSkillsBtn, #sidebarToolsBtn {
    background-color: transparent;
    color: #475569;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 7px 12px;
    font-weight: 500;
    font-size: 12.5px;
    text-align: left;
}

#sidebarSkillsBtn:hover, #sidebarToolsBtn:hover {
    background-color: #f1f5f9;
    border-color: #cbd5e1;
    color: #0f172a;
}

#sidebarSkillsBtn[active="true"], #sidebarToolsBtn[active="true"] {
    background-color: #ffffff;
    border-color: #94a3b8;
    color: #0f172a;
    font-weight: 600;
}

#skillsView, #toolsView {
    background-color: #f8fafc;
}

#skillsHeaderTitle, #toolsHeaderTitle {
    font-size: 24px;
    font-weight: 700;
    color: #0f172a;
    letter-spacing: -0.4px;
}

#skillsHeaderSubtitle, #toolsHeaderSubtitle {
    font-size: 13px;
    color: #64748b;
    line-height: 1.4;
}

#skillImportBtn, #toolsBrowseBtn {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    padding: 7px 14px;
    font-size: 12.5px;
    font-weight: 500;
}

#skillImportBtn:hover, #toolsBrowseBtn:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
}

#skillNewBtn, #toolTestRunBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 7px;
    padding: 7px 16px;
    font-size: 12.5px;
    font-weight: 600;
}

#skillNewBtn:hover, #toolTestRunBtn:hover {
    background-color: #1d4ed8;
}

.skillFilterPill, .toolFilterPill {
    background-color: #ffffff;
    color: #64748b;
    border: 1px solid #cbd5e1;
    border-radius: 20px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
}

.skillFilterPill:hover, .toolFilterPill:hover {
    background-color: #f1f5f9;
    color: #0f172a;
}

.skillFilterPill:checked, .toolFilterPill:checked {
    background-color: #eff6ff;
    border-color: #93c5fd;
    color: #2563eb;
    font-weight: 600;
}

#skillSearchBox, #toolSearchBox, #searchBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    padding: 6px 12px;
    color: #0f172a;
    font-size: 12px;
}

#skillSearchBox:focus, #toolSearchBox:focus, #searchBox:focus {
    border-color: #2563eb;
    background-color: #ffffff;
}

#skillCard, #toolCard, #toolsWorkspaceCard, #toolDetailHeader, #usageSummaryCard {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 9px;
}

#skillCard:hover, #toolCard:hover {
    border-color: #cbd5e1;
    background-color: #f8fafc;
}

#skillCardInitialBadge, #toolCardInitialBadge {
    background-color: #eff6ff;
    color: #2563eb;
    border: 1px solid #bfdbfe;
    border-radius: 7px;
    font-size: 13px;
    font-weight: 600;
}

#skillCardTitle, #toolCardTitle {
    font-size: 14px;
    font-weight: 600;
    color: #0f172a;
}

#skillCardDesc, #toolCardDesc {
    font-size: 12.5px;
    color: #64748b;
    line-height: 1.35;
}

#skillCardActionBtn, #toolCardActionBtn {
    background-color: #f1f5f9;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 500;
}

#skillCardActionBtn:hover, #toolCardActionBtn:hover {
    background-color: #e2e8f0;
    color: #0f172a;
}

#skillCardDeleteBtn {
    background-color: #fef2f2;
    color: #dc2626;
    border: 1px solid #fecaca;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 500;
}

#skillCardDeleteBtn:hover {
    background-color: #fee2e2;
}

#skillFileTree {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 4px;
}

#skillFileTree::item {
    padding: 5px 6px;
    border-radius: 4px;
    color: #475569;
    font-size: 12px;
}

#skillFileTree::item:selected {
    background-color: #eff6ff;
    color: #1e40af;
    font-weight: 500;
}

#skillFileEditor {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    color: #0f172a;
    font-size: 12.5px;
    padding: 8px;
}

#toolsWorkspaceInput {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px 10px;
    color: #0f172a;
    font-size: 12px;
    font-family: 'JetBrains Mono', 'Menlo', monospace;
}

#toolsWorkspaceInput:focus {
    border-color: #2563eb;
}

#sidebarSectionLabel {
    font-size: 11px;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    padding: 10px 14px 4px 14px;
}

#conversationList {
    background-color: transparent;
    border: none;
    padding: 4px 6px;
}

#conversationList::item {
    background-color: transparent;
    color: #334155;
    border-radius: 6px;
    padding: 7px 10px;
    margin-bottom: 1px;
    font-size: 13px;
}

#conversationList::item:hover {
    background-color: rgba(0, 0, 0, 0.04);
    color: #0f172a;
}

#conversationList::item:selected {
    background-color: #e0edff;
    color: #1e40af;
    font-weight: 500;
}

#sidebarFooter {
    background-color: transparent;
    border-top: 1px solid #e2e8f0;
    padding: 8px 10px;
}

#sidebarFooter QPushButton, .sidebarActionBtn {
    background-color: transparent;
    border: none;
    border-radius: 6px;
    color: #64748b;
    padding: 6px 10px;
    text-align: left;
    font-size: 12.5px;
    font-weight: 400;
}

#sidebarFooter QPushButton:hover, .sidebarActionBtn:hover {
    background-color: rgba(0, 0, 0, 0.04);
    color: #0f172a;
}

#sidebarFooter QPushButton:pressed, .sidebarActionBtn:pressed {
    background-color: rgba(0, 0, 0, 0.08);
}

/* Chat Container */
#chatContainer, #mainStack, #mainSplitter {
    background-color: #ffffff;
}

/* Composer Panel */
#composerWidget {
    background-color: #ffffff;
    border-top: 1px solid #e2e8f0;
    padding: 10px 24px 18px 24px;
}

#inputCard {
    background-color: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 18px;
    padding: 10px 14px 8px 14px;
}

#inputCard:focus-within {
    border-color: #2563eb;
    background-color: #ffffff;
}

#messageInput {
    background-color: transparent;
    border: none;
    color: #0f172a;
    font-size: 14.5px;
    line-height: 1.5;
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 2px 0;
}

#sendBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 14px;
    padding: 5px 14px;
    font-weight: 600;
    font-size: 12.5px;
}

#sendBtn:hover {
    background-color: #1d4ed8;
}

#stopBtn {
    background-color: #ef4444;
    color: #ffffff;
    border: none;
    border-radius: 14px;
    padding: 5px 14px;
    font-weight: 600;
    font-size: 12.5px;
}

#stopBtn:hover {
    background-color: #dc2626;
}

#attachBtn {
    background-color: transparent;
    border: none;
    border-radius: 14px;
    color: #64748b;
    font-size: 16px;
    padding: 4px;
}

#attachBtn:hover {
    background-color: rgba(0, 0, 0, 0.06);
    color: #0f172a;
}

#tokenCaption {
    color: #64748b;
    font-size: 11px;
}

#attachmentChip {
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
}

/* Strategy & Model Dropdowns */
QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    padding: 4px 10px;
    color: #0f172a;
    font-size: 12px;
    font-weight: 500;
}

QComboBox:hover {
    border-color: #94a3b8;
    background-color: #f8fafc;
}

QComboBox:disabled {
    color: #94a3b8;
    background-color: #f1f5f9;
    border-color: #e2e8f0;
}

QComboBox::drop-down {
    border: none;
    padding-right: 6px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    selection-background-color: #eff6ff;
    selection-color: #1e40af;
    color: #0f172a;
    padding: 4px;
    outline: none;
}

/* Buttons and Inputs in Dialogs */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    color: #0f172a;
    padding: 6px 14px;
    font-size: 12.5px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
}

QPushButton:pressed {
    background-color: #e2e8f0;
}

QPushButton:disabled {
    background-color: #f1f5f9;
    color: #94a3b8;
    border-color: #e2e8f0;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    padding: 6px 10px;
    color: #0f172a;
    font-size: 12.5px;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #2563eb;
    background-color: #ffffff;
}

/* Checkbox */
QCheckBox {
    color: #0f172a;
    font-size: 13px;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background-color: #ffffff;
}

QCheckBox::indicator:checked {
    background-color: #2563eb;
    border-color: #2563eb;
}

/* Menus */
QMenu {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 4px;
}

QMenu::item {
    background-color: transparent;
    color: #0f172a;
    padding: 6px 14px;
    border-radius: 5px;
    font-size: 12.5px;
}

QMenu::item:selected {
    background-color: #eff6ff;
    color: #1e40af;
}

/* Tab Widget */
QTabWidget::pane {
    border: 1px solid #e2e8f0;
    background-color: #ffffff;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #f1f5f9;
    color: #64748b;
    padding: 8px 16px;
    border: 1px solid #e2e8f0;
    border-bottom: none;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    margin-right: 3px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    color: #0f172a;
    font-weight: 600;
    border-bottom: 2px solid #2563eb;
}

/* Tables and Trees */
QTableWidget, QTreeWidget, QListWidget {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    color: #0f172a;
    gridline-color: #f1f5f9;
    outline: none;
}

QTableWidget::item, QTreeWidget::item {
    padding: 6px 8px;
    border-bottom: 1px solid #f1f5f9;
}

QTableWidget::item:selected, QTreeWidget::item:selected {
    background-color: #eff6ff;
    color: #1e40af;
}

QTableWidget QPushButton {
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    color: #334155;
    padding: 3px 10px;
    font-size: 11.5px;
    font-weight: 500;
    min-height: 22px;
}

QTableWidget QPushButton:hover {
    background-color: #e2e8f0;
    color: #0f172a;
    border-color: #94a3b8;
}

QHeaderView::section {
    background-color: #f8fafc;
    color: #475569;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid #e2e8f0;
}

/* Splitter */
QSplitter::handle {
    background-color: #e2e8f0;
}

QSplitter::handle:hover {
    background-color: #cbd5e1;
}

/* Status Bar */
QStatusBar {
    background-color: #f8fafc;
    border-top: 1px solid #e2e8f0;
    color: #64748b;
    font-size: 11px;
    padding: 2px 8px;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: rgba(0, 0, 0, 0.16);
    min-height: 24px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(0, 0, 0, 0.28);
}

/* Dynamic Component Overrides */
#toolbarLabel {
    font-weight: 500;
    color: #475569;
    font-size: 12px;
}

#toolsWorkspaceLabel {
    font-weight: 600;
    color: #0f172a;
    font-size: 12px;
}

#toolToggleBtn, #skillToggleBtn {
    background-color: #f1f5f9;
    color: #64748b;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11.5px;
    font-weight: 500;
}

#toolToggleBtn:hover, #skillToggleBtn:hover {
    background-color: #e2e8f0;
    color: #334155;
}

#toolToggleBtn[active="true"], #skillToggleBtn[active="true"] {
    background-color: #ecfdf5;
    color: #059669;
    border: 1px solid #a7f3d0;
}

#toolToggleBtn[active="true"]:hover, #skillToggleBtn[active="true"]:hover {
    background-color: #d1fae5;
}

#emptyPlaceholderLabel {
    color: #64748b;
    font-size: 13px;
    padding: 30px;
    text-align: center;
}
"""


def apply_theme(target: Any, theme: str = "dark") -> None:
    """Apply application theme stylesheet to a QWidget or QApplication."""
    qss = LIGHT_THEME_QSS if theme == "light" else DARK_THEME_QSS
    if hasattr(target, "setStyleSheet"):
        target.setStyleSheet(qss)

    app = QApplication.instance()
    if app:
        if isinstance(target, QApplication) or target == app:
            app.setStyleSheet(qss)
        for top in app.topLevelWidgets():
            if hasattr(top, "setStyleSheet"):
                top.setStyleSheet(qss)
            if hasattr(top, "style") and top.style():
                top.style().unpolish(top)
                top.style().polish(top)
            top.update()
