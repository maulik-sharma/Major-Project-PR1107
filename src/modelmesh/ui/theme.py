"""QSS styles and theme definitions for ModelMesh PyQt6 interface."""

DARK_THEME_QSS = """
QMainWindow, QDialog {
    background-color: #121417;
    color: #f0f3f6;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
}

QWidget {
    background-color: #121417;
    color: #f0f3f6;
}

/* ToolBar and Header */
QToolBar {
    background-color: #1a1d21;
    border-bottom: 1px solid #2e343d;
    padding: 6px 12px;
    spacing: 8px;
}

/* Sidebar */
#sidebar {
    background-color: #16181d;
    border-right: 1px solid #2e343d;
}

#sidebarHeader {
    background-color: transparent;
    padding: 12px 14px;
    border-bottom: 1px solid #2e343d;
}

#brandTitle {
    font-size: 15px;
    font-weight: 700;
    color: #3b82f6;
}

#newChatBtn {
    background-color: #3b82f6;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 600;
    font-size: 13px;
}

#newChatBtn:hover {
    background-color: #2563eb;
}

#newChatBtn:pressed {
    background-color: #1d4ed8;
}

#searchBox {
    background-color: #1f2329;
    border: 1px solid #2e343d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f0f3f6;
    font-size: 12px;
}

#searchBox:focus {
    border-color: #3b82f6;
}

#conversationList {
    background-color: transparent;
    border: none;
    padding: 6px;
}

#conversationList::item {
    background-color: transparent;
    color: #d1d5db;
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 2px;
}

#conversationList::item:hover {
    background-color: #1f2329;
    color: #ffffff;
}

#conversationList::item:selected {
    background-color: #262c36;
    color: #ffffff;
    font-weight: 500;
}

#sidebarFooter {
    background-color: #16181d;
    border-top: 1px solid #2e343d;
    padding: 8px;
}

.sidebarActionBtn {
    background-color: transparent;
    border: 1px solid #2e343d;
    border-radius: 6px;
    color: #9da7b3;
    padding: 6px 10px;
    text-align: left;
    font-size: 12px;
}

.sidebarActionBtn:hover {
    background-color: #1f2329;
    color: #f0f3f6;
    border-color: #4b5563;
}

/* Composer Panel */
#composerWidget {
    background-color: #16181d;
    border-top: 1px solid #2e343d;
    padding: 12px 20px 16px 20px;
}

#inputCard {
    background-color: #1f2329;
    border: 1px solid #2e343d;
    border-radius: 10px;
    padding: 8px 12px;
}

#inputCard:focus-within {
    border-color: #3b82f6;
}

#messageInput {
    background-color: transparent;
    border: none;
    color: #f0f3f6;
    font-size: 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

#sendBtn {
    background-color: #3b82f6;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}

#sendBtn:hover {
    background-color: #2563eb;
}

#stopBtn {
    background-color: #ef4444;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}

#stopBtn:hover {
    background-color: #dc2626;
}

#attachBtn {
    background-color: transparent;
    border: 1px solid #2e343d;
    border-radius: 6px;
    color: #9da7b3;
    padding: 6px 10px;
}

#attachBtn:hover {
    background-color: #262c36;
    color: #f0f3f6;
}

#tokenCaption {
    color: #656f7d;
    font-size: 11px;
}

/* Top Bar Strategy Dropdown */
QComboBox {
    background-color: #1f2329;
    border: 1px solid #2e343d;
    border-radius: 6px;
    padding: 5px 12px;
    color: #f0f3f6;
    font-weight: 500;
    min-width: 220px;
}

QComboBox:hover {
    border-color: #3b82f6;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #1a1d21;
    border: 1px solid #2e343d;
    selection-background-color: #262c36;
    selection-color: #ffffff;
    padding: 4px;
}

/* Buttons and Inputs */
QPushButton {
    background-color: #1f2329;
    border: 1px solid #2e343d;
    border-radius: 6px;
    color: #f0f3f6;
    padding: 6px 12px;
}

QPushButton:hover {
    background-color: #262c36;
    border-color: #4b5563;
}

QPushButton:pressed {
    background-color: #121417;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background-color: #1f2329;
    border: 1px solid #2e343d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f0f3f6;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #3b82f6;
}

/* Tab Widget */
QTabWidget::pane {
    border: 1px solid #2e343d;
    background-color: #16181d;
    border-radius: 6px;
}

QTabBar::tab {
    background-color: #1a1d21;
    color: #9da7b3;
    padding: 8px 16px;
    border: 1px solid #2e343d;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #16181d;
    color: #3b82f6;
    font-weight: 600;
}

/* Status Bar */
QStatusBar {
    background-color: #16181d;
    border-top: 1px solid #2e343d;
    color: #9da7b3;
    font-size: 11px;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #121417;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #2e343d;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #4b5563;
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
