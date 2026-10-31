"""Attachment processing module for images, code/text files, and PDFs."""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from modelmesh.core.types import ContentPart, ImagePart, TextPart

MAX_TEXT_SIZE_BYTES = 200 * 1024  # 200 KB
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_PDF_PAGES = 25
IMAGE_TOKENS_ESTIMATE = 1000


@dataclass
class Attachment:
    """A file attached in the composer: a display name plus the content part sent to the model."""
    name: str
    part: ContentPart

    @property
    def is_image(self) -> bool:
        return isinstance(self.part, ImagePart)

    def estimated_tokens(self) -> int:
        """Rough input-token cost of this attachment."""
        if isinstance(self.part, ImagePart):
            return IMAGE_TOKENS_ESTIMATE
        return len(self.part.text) // 4

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json",
    ".csv", ".yaml", ".yml", ".toml", ".sh", ".c", ".cpp", ".h",
    ".rs", ".go", ".java", ".sql", ".xml", ".log", ".env"
}


def process_image(
    file_path_or_bytes: Union[Path, str, bytes],
    media_type: Optional[str] = None,
) -> ImagePart:
    """Read and base64-encode an image into an ImagePart."""
    if isinstance(file_path_or_bytes, (str, Path)):
        path = Path(file_path_or_bytes)
        raw_bytes = path.read_bytes()
        ext = path.suffix.lower()
        if not media_type:
            media_type = mimetypes.guess_type(path.name)[0] or ("image/png" if ext == ".png" else "image/jpeg")
    else:
        raw_bytes = file_path_or_bytes
        if not media_type:
            media_type = "image/png"

    if len(raw_bytes) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    b64_data = base64.b64encode(raw_bytes).decode("utf-8")
    name = Path(file_path_or_bytes).name if isinstance(file_path_or_bytes, (str, Path)) else None
    return ImagePart(media_type=media_type, data=b64_data, name=name)


def process_text_file(
    file_path: Union[Path, str],
    max_bytes: int = MAX_TEXT_SIZE_BYTES,
) -> TextPart:
    """Read a text or code source file with a size cap."""
    path = Path(file_path)
    content = path.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    formatted = f"--- File: {path.name} ---\n{content}\n--- End File ---"
    return TextPart(text=formatted, name=path.name)


def process_pdf(
    file_path: Union[Path, str],
    max_pages: int = MAX_PDF_PAGES,
) -> TextPart:
    """Extract text from a PDF file using pypdf."""
    path = Path(file_path)
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        num_pages = len(reader.pages)
        pages_to_read = min(num_pages, max_pages)

        extracted_text = []
        for i in range(pages_to_read):
            text = reader.pages[i].extract_text() or ""
            if text.strip():
                extracted_text.append(f"[Page {i + 1}]\n{text.strip()}")

        if extracted_text:
            joined = "\n\n".join(extracted_text)
            trunc_note = f" (first {pages_to_read} of {num_pages} pages)" if num_pages > max_pages else ""
            formatted = f"--- PDF: {path.name}{trunc_note} ---\n{joined}\n--- End PDF ---"
            return TextPart(text=formatted, name=path.name)
        else:
            return TextPart(
                text=f"[PDF '{path.name}' contained no extractable text. It may be a scanned image document.]",
                name=path.name,
            )
    except Exception as exc:
        return TextPart(text=f"[Error reading PDF '{path.name}': {exc}]", name=path.name)


def process_attachment(file_path: Union[Path, str]) -> ContentPart:
    """Process any supported file path into an ImagePart or TextPart."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext in IMAGE_EXTENSIONS:
        return process_image(path)
    elif ext == ".pdf":
        return process_pdf(path)
    else:
        return process_text_file(path)


def load_attachment(file_path: Union[Path, str]) -> Attachment:
    """Read a file into an :class:`Attachment` (disk I/O: call off the UI thread)."""
    path = Path(file_path)
    return Attachment(name=path.name, part=process_attachment(path))


def split_user_parts(parts: list) -> tuple:
    """Split a stored user message into (typed text, attachment parts) for display."""
    typed = "\n".join(p.text for p in parts if isinstance(p, TextPart) and not p.name)
    attached = [p for p in parts if p.name or isinstance(p, ImagePart)]
    return typed, attached
