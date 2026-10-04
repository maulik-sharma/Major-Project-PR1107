"""Composer widget providing multiline input, attachments, drag-drop, and Send/Stop controls."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QImage, QKeyEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from modelmesh.core.attachments import process_attachment
from modelmesh.core.types import ImagePart, TextPart


class AutoExpandingTextEdit(QTextEdit):
    """TextEdit that emits send signal on Enter, expands height, and handles clipboard image pastes."""

    send_pressed = pyqtSignal()
    attachment_pasted = pyqtSignal(dict)
    files_dropped = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("messageInput")
        self.setPlaceholderText("Message ModelMesh... (Enter to send, Shift+Enter for newline)")
        self.setAcceptRichText(False)
        self.setAcceptDrops(True)
        self.textChanged.connect(self._adjust_height)
        self.setFixedHeight(42)

    def keyPressEvent(self, e: Optional[QKeyEvent]) -> None:
        if e is not None:
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    super().keyPressEvent(e)
                    return
                else:
                    self.send_pressed.emit()
                    e.accept()
                    return
        super().keyPressEvent(e)

    def insertFromMimeData(self, source: QMimeData | None) -> None:
        """Handle pasted images or dropped files from clipboard."""
        if source is None:
            return

        if source.hasImage():
            img_data = source.imageData()
            if isinstance(img_data, QImage) and not img_data.isNull():
                byte_array = QByteArray()
                buf = QBuffer(byte_array)
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                img_data.save(buf, "PNG")
                b64 = base64.b64encode(byte_array.data()).decode("utf-8")
                att = {
                    "type": "image",
                    "name": "Pasted Image.png",
                    "media_type": "image/png",
                    "data": b64,
                }
                self.attachment_pasted.emit(att)
                return

        if source.hasUrls():
            paths = [
                Path(url.toLocalFile())
                for url in source.urls()
                if url.isLocalFile()
            ]
            if paths:
                self.files_dropped.emit(paths)
                return

        super().insertFromMimeData(source)

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        if event is not None and (event.mimeData().hasUrls() or event.mimeData().hasImage()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent | None) -> None:
        if event is not None and event.mimeData().hasUrls():
            paths = [
                Path(url.toLocalFile())
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            if paths:
                self.files_dropped.emit(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def _adjust_height(self) -> None:
        doc_height = int(self.document().size().height())
        new_height = max(42, min(160, doc_height + 14))
        self.setFixedHeight(new_height)


class ComposerWidget(QWidget):
    """Bottom input bar with attachment tray, token estimation, and Send/Stop button."""

    send_requested = pyqtSignal(str, list)
    stop_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("composerWidget")
        self.setAcceptDrops(True)

        self._attachments: List[Dict[str, Any]] = []
        self._is_streaming = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 12)
        layout.setSpacing(6)

        # 1. Attachment chips row (hidden by default)
        self.chips_container = QWidget()
        self.chips_layout = QHBoxLayout(self.chips_container)
        self.chips_layout.setContentsMargins(4, 0, 4, 4)
        self.chips_layout.setSpacing(6)
        self.chips_layout.addStretch()
        self.chips_container.setVisible(False)
        layout.addWidget(self.chips_container)

        # 2. Main Input Box Card (Capsule layout)
        input_card = QWidget()
        input_card.setObjectName("inputCard")
        card_vlayout = QVBoxLayout(input_card)
        card_vlayout.setContentsMargins(6, 4, 6, 4)
        card_vlayout.setSpacing(4)

        # Text input on top
        self.text_input = AutoExpandingTextEdit()
        self.text_input.setPlaceholderText("How can I help you today? (Enter to send, Shift+Enter for newline)")
        self.text_input.send_pressed.connect(self._on_send_clicked)
        self.text_input.attachment_pasted.connect(self._add_attachment_dict)
        self.text_input.files_dropped.connect(self._on_files_dropped)
        self.text_input.textChanged.connect(self._update_token_estimate)
        card_vlayout.addWidget(self.text_input)

        # Bottom action bar inside the capsule
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(2, 0, 2, 2)
        bottom_bar.setSpacing(8)

        # Attach button (+)
        self.attach_btn = QPushButton("+")
        self.attach_btn.setObjectName("attachBtn")
        self.attach_btn.setFixedSize(28, 28)
        self.attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.attach_btn.setToolTip("Attach file or image")
        self.attach_btn.clicked.connect(self._on_attach_clicked)
        bottom_bar.addWidget(self.attach_btn)

        # Token estimate label
        self.token_caption = QLabel("~0 tokens")
        self.token_caption.setObjectName("tokenCaption")
        bottom_bar.addWidget(self.token_caption)

        bottom_bar.addStretch()

        # Send / Stop button
        self.action_btn = QPushButton("Send")
        self.action_btn.setObjectName("sendBtn")
        self.action_btn.setFixedSize(62, 28)
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.clicked.connect(self._on_action_btn_clicked)
        bottom_bar.addWidget(self.action_btn)

        card_vlayout.addLayout(bottom_bar)
        layout.addWidget(input_card)

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        if event is not None and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent | None) -> None:
        if event is not None and event.mimeData().hasUrls():
            paths = [
                Path(url.toLocalFile())
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            self._on_files_dropped(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _on_files_dropped(self, paths: List[Path]) -> None:
        for p in paths:
            self._add_attachment(p)

    def set_streaming_state(self, is_streaming: bool) -> None:
        """Switch action button between Send and Stop."""
        self._is_streaming = is_streaming
        if is_streaming:
            self.action_btn.setText("Stop")
            self.action_btn.setObjectName("stopBtn")
            self.action_btn.setStyleSheet("")
        else:
            self.action_btn.setText("Send")
            self.action_btn.setObjectName("sendBtn")
            self.action_btn.setStyleSheet("")

    def set_prompt_text(self, text: str) -> None:
        """Set input box text programmatically."""
        self.text_input.setPlainText(text)
        self.text_input.moveCursor(self.text_input.textCursor().MoveOperation.End)
        self.text_input.setFocus()

    def get_text(self) -> str:
        """Get the current text in the input box."""
        return self.text_input.toPlainText()

    def _on_action_btn_clicked(self) -> None:
        if self._is_streaming:
            self.stop_requested.emit()
        else:
            self._on_send_clicked()

    def _on_send_clicked(self) -> None:
        text = self.text_input.toPlainText().strip()
        if not text and not self._attachments:
            return

        attachments = list(self._attachments)
        self.text_input.clear()
        self._clear_attachments()
        self.send_requested.emit(text, attachments)

    def _on_attach_clicked(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Attachment",
            "",
            "All Supported (*.png *.jpg *.jpeg *.webp *.txt *.md *.py *.json *.pdf);;Images (*.png *.jpg *.jpeg *.webp);;Text Files (*.txt *.md *.py *.json);;PDF Files (*.pdf)",
        )
        for fpath in files:
            self._add_attachment(Path(fpath))

    def _add_attachment(self, path: Path) -> None:
        if not path.exists():
            return

        try:
            part = process_attachment(path)
            if isinstance(part, ImagePart):
                att = {
                    "type": "image",
                    "name": path.name,
                    "media_type": part.media_type,
                    "data": part.data,
                }
            elif isinstance(part, TextPart):
                att = {
                    "type": "text",
                    "name": path.name,
                    "text": part.text,
                }
            else:
                return
            self._add_attachment_dict(att)
        except Exception:
            pass

    def _add_attachment_dict(self, att: Dict[str, Any]) -> None:
        self._attachments.append(att)
        self._render_chips()
        self._update_token_estimate()

    def _render_chips(self) -> None:
        while self.chips_layout.count() > 1:
            item = self.chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._attachments:
            self.chips_container.setVisible(False)
            return

        self.chips_container.setVisible(True)
        for i, att in enumerate(self._attachments):
            chip = QPushButton(f"{att.get('name', 'File')} ✕")
            chip.setStyleSheet(
                "background-color: #27272a; color: #f4f4f6; border: 1px solid rgba(255, 255, 255, 0.1); "
                "border-radius: 6px; padding: 2px 8px; font-size: 11px;"
            )
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, idx=i: self._remove_attachment(idx))
            self.chips_layout.insertWidget(self.chips_layout.count() - 1, chip)

    def _remove_attachment(self, index: int) -> None:
        if 0 <= index < len(self._attachments):
            self._attachments.pop(index)
            self._render_chips()
            self._update_token_estimate()

    def _clear_attachments(self) -> None:
        self._attachments.clear()
        self._render_chips()
        self._update_token_estimate()

    def _update_token_estimate(self) -> None:
        text = self.text_input.toPlainText()
        char_count = len(text)
        est = max(0, char_count // 4)
        for att in self._attachments:
            if att.get("type") == "image":
                est += 800
            elif att.get("type") == "text":
                est += len(att.get("text", "")) // 4

        self.token_caption.setText(f"~{est} estimated tokens · {char_count} chars")

