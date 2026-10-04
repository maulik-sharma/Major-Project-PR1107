"""Attachment processing module for images, code/text files, and PDFs."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Optional, Union

from modelmesh.core.types import ContentPart, ImagePart, TextPart

MAX_TEXT_SIZE_BYTES = 200 * 1024  # 200 KB
MAX_PDF_PAGES = 25
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

    b64_data = base64.b64encode(raw_bytes).decode("utf-8")
    return ImagePart(media_type=media_type, data=b64_data)


def process_text_file(
    file_path: Union[Path, str],
    max_bytes: int = MAX_TEXT_SIZE_BYTES,
) -> TextPart:
    """Read a text or code source file with a size cap."""
    path = Path(file_path)
    content = path.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    formatted = f"--- File: {path.name} ---\n{content}\n--- End File ---"
    return TextPart(text=formatted)


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
            return TextPart(text=formatted)
        else:
            return TextPart(
                text=f"[PDF '{path.name}' contained no extractable text. It may be a scanned image document.]"
            )
    except Exception as exc:
        return TextPart(text=f"[Error reading PDF '{path.name}': {exc}]")


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
