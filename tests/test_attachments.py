"""Tests for attachment processing (images, text files, PDFs)."""

import base64
from pathlib import Path
import pytest

from modelmesh.core.attachments import (
    process_attachment,
    process_image,
    process_pdf,
    process_text_file,
)
from modelmesh.core.types import ImagePart, TextPart


def test_process_image_from_bytes() -> None:
    raw_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    part = process_image(raw_png, media_type="image/png")
    assert isinstance(part, ImagePart)
    assert part.media_type == "image/png"
    assert base64.b64decode(part.data) == raw_png


def test_process_image_from_file(tmp_path: Path) -> None:
    img_file = tmp_path / "test.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0testjpeg")

    part = process_image(img_file)
    assert isinstance(part, ImagePart)
    assert part.media_type in ("image/jpeg", "image/jpg")
    assert base64.b64decode(part.data) == b"\xff\xd8\xff\xe0testjpeg"


def test_process_text_file(tmp_path: Path) -> None:
    txt_file = tmp_path / "sample.py"
    txt_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    part = process_text_file(txt_file)
    assert isinstance(part, TextPart)
    assert "--- File: sample.py ---" in part.text
    assert "def hello():" in part.text
    assert "--- End File ---" in part.text


def test_process_text_file_size_cap(tmp_path: Path) -> None:
    big_file = tmp_path / "large.txt"
    big_file.write_text("A" * 500, encoding="utf-8")

    part = process_text_file(big_file, max_bytes=100)
    assert isinstance(part, TextPart)
    assert len(part.text) < 200
    assert "A" * 100 in part.text


def test_process_pdf_nonexistent() -> None:
    part = process_pdf(Path("/nonexistent/file.pdf"))
    assert isinstance(part, TextPart)
    assert "Error reading PDF" in part.text


def test_process_attachment_dispatch(tmp_path: Path) -> None:
    img_p = tmp_path / "photo.png"
    img_p.write_bytes(b"\x89PNG")

    code_p = tmp_path / "main.rs"
    code_p.write_text("fn main() {}", encoding="utf-8")

    part1 = process_attachment(img_p)
    assert isinstance(part1, ImagePart)

    part2 = process_attachment(code_p)
    assert isinstance(part2, TextPart)
    assert "fn main() {}" in part2.text
