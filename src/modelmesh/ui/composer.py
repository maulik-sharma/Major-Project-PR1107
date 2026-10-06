"""Composer widget providing multiline input, attachments, drag-drop, @ mention popup, atomic skill tokens, and Send/Stop controls."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QImage,
    QKeyEvent,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
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
from modelmesh.core.skills import SkillLoader
from modelmesh.core.types import ImagePart, TextPart
from modelmesh.ui.skill_mention_popup import SkillMentionPopup

SKILL_TOKEN_PROP = 1001


class AutoExpandingTextEdit(QTextEdit):
    """TextEdit with @ mention popup, atomic highlighted skill tokens, auto-expansion, and clipboard pasting."""

    send_pressed = pyqtSignal()
    attachment_pasted = pyqtSignal(dict)
    files_dropped = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("messageInput")
        self.setPlaceholderText("Message ModelMesh... Type '@' to use a skill (Enter to send, Shift+Enter for newline)")
        self.setAcceptRichText(False)
        self.setAcceptDrops(True)

        self.mention_popup = SkillMentionPopup(self)
        self.mention_popup.skill_selected.connect(self._on_skill_selected)

        self.textChanged.connect(self._on_text_changed)
        self.setFixedHeight(42)

    def _get_skill_token_range_at(self, pos: int) -> Optional[Tuple[int, int]]:
        """If character at pos belongs to a skill token, return (start, end) range including trailing space."""
        doc = self.document()
        total_len = doc.characterCount()
        if pos < 0 or pos >= total_len:
            return None

        c = QTextCursor(doc)
        c.setPosition(pos)
        c.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        fmt = c.charFormat()
        skill_name = fmt.property(SKILL_TOKEN_PROP)
        if not skill_name:
            return None

        # Trace start of token
        start = pos
        while start > 0:
            check = QTextCursor(doc)
            check.setPosition(start - 1)
            check.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            if check.charFormat().property(SKILL_TOKEN_PROP) == skill_name:
                start -= 1
            else:
                break

        # Trace end of token
        end = pos + 1
        while end < total_len:
            check = QTextCursor(doc)
            check.setPosition(end)
            check.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            if check.charFormat().property(SKILL_TOKEN_PROP) == skill_name:
                end += 1
            else:
                break

        # If followed by space, include trailing space in token range
        if end < total_len:
            check = QTextCursor(doc)
            check.setPosition(end)
            check.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            if check.selectedText() == " ":
                end += 1

        return (start, end)

    def keyPressEvent(self, e: Optional[QKeyEvent]) -> None:
        if e is not None:
            # 1. Mention popup navigation
            if self.mention_popup.isVisible():
                if e.key() == Qt.Key.Key_Down:
                    self.mention_popup.select_next()
                    e.accept()
                    return
                elif e.key() == Qt.Key.Key_Up:
                    self.mention_popup.select_prev()
                    e.accept()
                    return
                elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                    if not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                        selected = self.mention_popup.confirm_selection()
                        if selected:
                            e.accept()
                            return
                elif e.key() == Qt.Key.Key_Escape:
                    self.mention_popup.hide()
                    e.accept()
                    return

            # 2. Atomic deletion on Backspace
            if e.key() == Qt.Key.Key_Backspace:
                cursor = self.textCursor()
                if not cursor.hasSelection():
                    pos = cursor.position()
                    if pos > 0:
                        token_range = self._get_skill_token_range_at(pos - 1)
                        if not token_range and pos > 1:
                            # Cursor right after trailing space of token
                            c = QTextCursor(self.document())
                            c.setPosition(pos - 1)
                            c.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                            if c.selectedText() == " ":
                                token_range = self._get_skill_token_range_at(pos - 2)

                        if token_range:
                            start, end = token_range
                            del_cursor = QTextCursor(self.document())
                            del_cursor.setPosition(start)
                            del_cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                            del_cursor.removeSelectedText()
                            self.setTextCursor(del_cursor)
                            self._check_mention_trigger()
                            e.accept()
                            return

            # 3. Atomic deletion on Delete key
            elif e.key() == Qt.Key.Key_Delete:
                cursor = self.textCursor()
                if not cursor.hasSelection():
                    pos = cursor.position()
                    token_range = self._get_skill_token_range_at(pos)
                    if token_range:
                        start, end = token_range
                        del_cursor = QTextCursor(self.document())
                        del_cursor.setPosition(start)
                        del_cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                        del_cursor.removeSelectedText()
                        self.setTextCursor(del_cursor)
                        self._check_mention_trigger()
                        e.accept()
                        return

            # 4. If typing inside an atomic token, erase whole token first
            elif e.text() and not (e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
                cursor = self.textCursor()
                if not cursor.hasSelection():
                    pos = cursor.position()
                    token_range = self._get_skill_token_range_at(pos)
                    if token_range:
                        start, end = token_range
                        del_cursor = QTextCursor(self.document())
                        del_cursor.setPosition(start)
                        del_cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                        del_cursor.removeSelectedText()
                        self.setTextCursor(del_cursor)

            # 5. Send message on Enter
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    super().keyPressEvent(e)
                    return
                else:
                    self.send_pressed.emit()
                    e.accept()
                    return

        super().keyPressEvent(e)

    def _on_text_changed(self) -> None:
        self._adjust_height()
        self._check_mention_trigger()

    def _check_mention_trigger(self) -> None:
        cursor = self.textCursor()
        pos_in_block = cursor.positionInBlock()
        full_block = cursor.block().text()

        if pos_in_block == 0 and full_block.startswith("@"):
            block_text = full_block
        else:
            block_text = full_block[:pos_in_block]

        at_idx = block_text.rfind("@")
        if at_idx != -1:
            if at_idx == 0 or block_text[at_idx - 1].isspace():
                query = block_text[at_idx + 1:]
                if not any(c.isspace() for c in query):
                    if self.mention_popup.filter(query):
                        self.mention_popup.show_above(self)
                        return
        self.mention_popup.hide()

    def _on_skill_selected(self, skill_name: str) -> None:
        cursor = self.textCursor()
        pos_in_block = cursor.positionInBlock()
        full_block = cursor.block().text()

        if pos_in_block == 0 and full_block.startswith("@"):
            block_text = full_block
            pos_in_block = len(full_block)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        else:
            block_text = full_block[:pos_in_block]

        at_idx = block_text.rfind("@")
        if at_idx != -1:
            chars_to_replace = pos_in_block - at_idx
            cursor.movePosition(
                QTextCursor.MoveOperation.Left,
                QTextCursor.MoveMode.KeepAnchor,
                chars_to_replace,
            )

            # Highlighted skill pill format
            token_format = QTextCharFormat()
            token_format.setBackground(QColor("rgba(59, 130, 246, 0.22)"))
            token_format.setForeground(QColor("#93c5fd"))
            token_format.setFontWeight(QFont.Weight.DemiBold)
            token_format.setProperty(SKILL_TOKEN_PROP, skill_name)

            cursor.insertText(f"@{skill_name}", token_format)

            # Normal trailing space and format reset
            normal_format = QTextCharFormat()
            normal_format.setBackground(Qt.GlobalColor.transparent)
            normal_format.setForeground(QColor("#f4f4f6"))
            normal_format.setFontWeight(QFont.Weight.Normal)

            cursor.insertText(" ", normal_format)
            self.setCurrentCharFormat(normal_format)
            self.setTextCursor(cursor)

        self.mention_popup.hide()

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
    """Bottom input bar with attachment tray, @ mention popup, token estimation, and Send/Stop button."""

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

    def set_skill_loader(self, loader: Optional[SkillLoader]) -> None:
        """Connect skill loader to text edit mention popup."""
        self.text_input.mention_popup.set_skill_loader(loader)

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
            "Documents & Images (*.png *.jpg *.jpeg *.webp *.pdf *.txt *.py *.json *.csv *.md);;All Files (*)",
        )
        for f in files:
            self._add_attachment(Path(f))

    def _add_attachment(self, path: Path) -> None:
        att = process_attachment(path)
        if att:
            self._add_attachment_dict(att)

    def _add_attachment_dict(self, att: Dict[str, Any]) -> None:
        self._attachments.append(att)
        self._render_chips()

    def _remove_attachment(self, idx: int) -> None:
        if 0 <= idx < len(self._attachments):
            self._attachments.pop(idx)
            self._render_chips()

    def _clear_attachments(self) -> None:
        self._attachments.clear()
        self._render_chips()

    def _render_chips(self) -> None:
        while self.chips_layout.count() > 1:
            item = self.chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._attachments:
            self.chips_container.setVisible(False)
            self._update_token_estimate()
            return

        self.chips_container.setVisible(True)
        for i, att in enumerate(self._attachments):
            chip = QWidget()
            chip.setObjectName("attachmentChip")
            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(6, 2, 4, 2)
            chip_layout.setSpacing(4)

            name = att.get("name", "Attachment")
            lbl = QLabel(name)
            lbl.setStyleSheet("font-size: 11.5px; color: #f4f4f6;")
            chip_layout.addWidget(lbl)

            rm_btn = QPushButton("✕")
            rm_btn.setFixedSize(14, 14)
            rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            rm_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; color: #71717a; font-size: 10px; font-weight: bold; } "
                "QPushButton:hover { color: #f87171; }"
            )
            rm_btn.clicked.connect(lambda _, idx=i: self._remove_attachment(idx))
            chip_layout.addWidget(rm_btn)

            self.chips_layout.insertWidget(i, chip)

        self._update_token_estimate()

    def _update_token_estimate(self) -> None:
        text = self.text_input.toPlainText()
        char_count = len(text)
        est_tokens = max(0, char_count // 4)

        for att in self._attachments:
            if att.get("type") == "image":
                est_tokens += 1000
            elif att.get("type") == "document":
                txt = att.get("text", "")
                est_tokens += len(txt) // 4

        self.token_caption.setText(f"~{est_tokens:,} tokens")
