"""Filesystem and workspace tools: read, write, list directory, and code search."""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_READ_LINES = 1000
MAX_WRITE_BYTES = 500_000  # ~500 KB
MAX_DIR_ITEMS = 500
MAX_SEARCH_MATCHES = 100
MAX_PATH_LENGTH = 4096


def _resolve_workspace_path(path: str, workspace_folder: Optional[str]) -> Path:
    """Safely resolve path within workspace directory and check boundary."""
    if not path or not path.strip():
        raise ValueError("Path must not be empty.")
    if len(path) > MAX_PATH_LENGTH:
        raise ValueError(f"Path is too long ({len(path)} chars, max {MAX_PATH_LENGTH}).")

    root = Path(workspace_folder).resolve() if workspace_folder else Path.cwd().resolve()
    raw_p = Path(path)
    target = raw_p.resolve() if raw_p.is_absolute() else (root / raw_p).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        raise PermissionError(
            f"Access denied: Target path '{path}' is outside the configured workspace directory '{root}'."
        )

    return target


def read_text_file(
    path: str,
    max_lines: int = 200,
    workspace_folder: Optional[str] = None,
) -> Dict[str, Any]:
    """Read a local text file safely within a specified workspace folder.

    Args:
        path: Relative or absolute file path within the workspace.
        max_lines: Maximum number of lines to return (default: 200, max: 1000).
        workspace_folder: Root workspace directory for boundary checks.

    Returns:
        Dict with path, content, line counts, and truncation info.
    """
    try:
        target = _resolve_workspace_path(path, workspace_folder)
    except (PermissionError, ValueError) as exc:
        return {"error": str(exc)}

    if not target.exists():
        return {"error": f"File not found: '{path}'."}
    if not target.is_file():
        return {"error": f"Path is not a regular file: '{path}'."}

    max_lines = max(1, min(MAX_READ_LINES, max_lines))

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        truncated = len(lines) > max_lines
        selected_lines = lines[:max_lines]

        return {
            "path": path,
            "absolute_path": str(target),
            "line_count": len(lines),
            "lines_shown": len(selected_lines),
            "truncated": truncated,
            "content": "\n".join(selected_lines),
        }
    except Exception as exc:
        return {"error": f"Failed to read file: {exc}"}


def write_text_file(
    path: str,
    content: str,
    overwrite: bool = True,
    workspace_folder: Optional[str] = None,
) -> Dict[str, Any]:
    """Write text content to a file safely within the workspace folder.

    Args:
        path: Relative or absolute file path within the workspace.
        content: Text content to write (max ~500KB).
        overwrite: Whether to overwrite existing files (default: true).
        workspace_folder: Root workspace directory for boundary checks.

    Returns:
        Dict with path, bytes written, success status.
    """
    try:
        target = _resolve_workspace_path(path, workspace_folder)
    except (PermissionError, ValueError) as exc:
        return {"error": str(exc)}

    content_bytes = len(content.encode("utf-8"))
    if content_bytes > MAX_WRITE_BYTES:
        return {"error": f"Content too large ({content_bytes} bytes, max {MAX_WRITE_BYTES})."}

    if target.exists() and not overwrite:
        return {"error": f"File already exists and overwrite is set to False: '{path}'."}

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        lines = content.splitlines()
        return {
            "path": path,
            "absolute_path": str(target),
            "bytes_written": content_bytes,
            "lines_written": len(lines),
            "success": True,
        }
    except Exception as exc:
        return {"error": f"Failed to write file: {exc}", "success": False}


def list_directory(
    path: str = ".",
    recursive: bool = False,
    max_items: int = 100,
    workspace_folder: Optional[str] = None,
) -> Dict[str, Any]:
    """List files and directories inside the workspace directory.

    Args:
        path: Relative directory path within workspace (default: '.').
        recursive: Whether to traverse subdirectories (default: false).
        max_items: Maximum items to return (1-500, default: 100).
        workspace_folder: Root workspace directory for boundary checks.

    Returns:
        Dict with directory listing, item count, and truncation info.
    """
    try:
        target = _resolve_workspace_path(path, workspace_folder)
    except (PermissionError, ValueError) as exc:
        return {"error": str(exc)}

    if not target.exists():
        return {"error": f"Directory not found: '{path}'."}
    if not target.is_dir():
        return {"error": f"Path is not a directory: '{path}'."}

    max_items = max(1, min(MAX_DIR_ITEMS, max_items))
    items: List[Dict[str, Any]] = []
    root = Path(workspace_folder).resolve() if workspace_folder else Path.cwd().resolve()

    try:
        if recursive:
            for dirpath, dirnames, filenames in os.walk(target):
                # Filter out hidden folders and caches
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
                current_dir = Path(dirpath)
                for d in dirnames:
                    if len(items) >= max_items:
                        break
                    full_p = current_dir / d
                    rel_p = full_p.relative_to(root)
                    items.append({
                        "name": d,
                        "path": str(rel_p),
                        "type": "directory",
                    })
                for f in filenames:
                    if len(items) >= max_items:
                        break
                    if f.startswith("."):
                        continue
                    full_p = current_dir / f
                    rel_p = full_p.relative_to(root)
                    size = full_p.stat().st_size if full_p.exists() else 0
                    items.append({
                        "name": f,
                        "path": str(rel_p),
                        "type": "file",
                        "size_bytes": size,
                    })
                if len(items) >= max_items:
                    break
        else:
            for child in sorted(target.iterdir()):
                if len(items) >= max_items:
                    break
                if child.name.startswith(".") or child.name == "__pycache__":
                    continue
                rel_p = child.relative_to(root)
                items.append({
                    "name": child.name,
                    "path": str(rel_p),
                    "type": "directory" if child.is_dir() else "file",
                    "size_bytes": child.stat().st_size if child.is_file() else None,
                })

        return {
            "directory": path,
            "total_items": len(items),
            "truncated": len(items) >= max_items,
            "items": items,
        }
    except Exception as exc:
        return {"error": f"Failed to list directory: {exc}"}


def search_in_files(
    query: str,
    file_pattern: str = "*",
    case_sensitive: bool = False,
    max_matches: int = 50,
    workspace_folder: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for string or regex query across files within the workspace directory.

    Args:
        query: Text substring or regex pattern to search for (max 400 chars).
        file_pattern: Glob pattern for filename filtering (default: '*').
        case_sensitive: Case-sensitive search (default: false).
        max_matches: Maximum matching lines to return (1-100, default: 50).
        workspace_folder: Root workspace directory.

    Returns:
        Dict with query, match count, and list of matching lines.
    """
    root = Path(workspace_folder).resolve() if workspace_folder else Path.cwd().resolve()
    clean_query = query.strip()[:400]
    if not clean_query:
        return {"query": query, "matches_count": 0, "matches": [], "error": "Empty search query."}

    max_matches = max(1, min(MAX_SEARCH_MATCHES, max_matches))

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(clean_query, flags)
    except re.error:
        # Fall back to literal escaped regex
        pattern = re.compile(re.escape(clean_query), flags)

    matches: List[Dict[str, Any]] = []

    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # Ignore hidden and virtual env folders
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in ("__pycache__", ".venv", "venv", "node_modules")
            ]
            for filename in filenames:
                if len(matches) >= max_matches:
                    break
                if filename.startswith("."):
                    continue
                if file_pattern and not fnmatch.fnmatch(filename, file_pattern):
                    continue

                full_p = Path(dirpath) / filename
                rel_p = full_p.relative_to(root)

                # Skip non-text or binary files
                try:
                    content = full_p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                for line_idx, line in enumerate(content.splitlines(), start=1):
                    if len(matches) >= max_matches:
                        break
                    if pattern.search(line):
                        matches.append({
                            "file": str(rel_p),
                            "line_number": line_idx,
                            "line_content": line.strip()[:200],
                        })

            if len(matches) >= max_matches:
                break

        return {
            "query": clean_query,
            "matches_count": len(matches),
            "truncated": len(matches) >= max_matches,
            "matches": matches,
        }
    except Exception as exc:
        return {"query": clean_query, "matches_count": 0, "matches": [], "error": f"Search error: {exc}"}
