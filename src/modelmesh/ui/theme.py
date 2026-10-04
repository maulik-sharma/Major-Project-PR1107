"""QSS styles and theme definitions for ModelMesh PyQt6 interface."""

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

#searchBox {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 7px;
    padding: 6px 10px;
    color: #f4f4f6;
    font-size: 12px;
}

#searchBox:focus {
    border-color: #3b82f6;
    background-color: rgba(255, 255, 255, 0.05);
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
#chatContainer {
    background-color: #141417;
}

#mainSplitter {
    background-color: #141417;
}

/* Composer Panel */
#composerWidget {
    background-color: #141417;
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

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


def apply_theme(widget: Any, theme: str = "dark") -> None:
    """Apply application theme stylesheet to a QWidget or QApplication."""
    if theme == "dark":
        widget.setStyleSheet(DARK_THEME_QSS)
    else:
        # Default fallback
        widget.setStyleSheet(DARK_THEME_QSS)

