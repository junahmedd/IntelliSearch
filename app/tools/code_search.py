import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.tools.project_inspector import (
    DEFAULT_IGNORED_DIRS,
    resolve_safe_path,
)

DEFAULT_MAX_RESULTS: int = 100
DEFAULT_MAX_CODE_FILE_SIZE: int = 500 * 1024  # 500 KB limit for code files


def search_code(
    project_root: str | Path,
    query: str,
    file_extensions: Tuple[str, ...] = (".py",),
    max_results: int = DEFAULT_MAX_RESULTS,
    max_file_size_bytes: int = DEFAULT_MAX_CODE_FILE_SIZE,
    case_sensitive: bool = False,
    ignored_dirs: Optional[Set[str]] = None,
    base_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """
    Searches for a text query inside source files within a project directory.

    Args:
        project_root: The directory to search within.
        query: The string to search for.
        file_extensions: File extensions to filter by (default: ('.py',)).
        max_results: Maximum number of matches to return.
        max_file_size_bytes: Maximum size of individual files to inspect.
        case_sensitive: Whether to perform a case-sensitive search.
        ignored_dirs: Directory names to skip (defaults to standard cache/env folders).
        base_dir: Optional security boundary directory preventing path traversal.

    Returns:
        Structured dictionary containing query, total_matches, truncated flag, and match list.
    """
    if not query:
        raise ValueError("Search query cannot be empty.")

    root_path = resolve_safe_path(project_root, base_dir=base_dir)
    if not root_path.is_dir():
        raise NotADirectoryError(f"Target path is not a directory: {project_root}")

    ignore_set = (
        set(ignored_dirs) if ignored_dirs is not None else DEFAULT_IGNORED_DIRS
    )
    normalized_query = query if case_sensitive else query.lower()
    matches: List[Dict[str, Any]] = []
    truncated = False

    for current_root, dirs, files in os.walk(root_path):
        # Prune ignored directories in-place
        dirs[:] = [d for d in dirs if d not in ignore_set]

        for file_name in sorted(files):
            # Only inspect matching file extensions (e.g., .py)
            if not any(file_name.lower().endswith(ext.lower()) for ext in file_extensions):
                continue

            file_path = Path(current_root) / file_name

            try:
                # Memory safeguard: skip excessively large files
                if file_path.stat().st_size > max_file_size_bytes:
                    continue

                rel_path = file_path.relative_to(root_path).as_posix()

                # Stream-read line by line to minimize RAM usage
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for line_number, line_content in enumerate(f, start=1):
                        target_text = (
                            line_content if case_sensitive else line_content.lower()
                        )
                        if normalized_query in target_text:
                            matches.append(
                                {
                                    "file": rel_path,
                                    "line_number": line_number,
                                    "line_content": line_content.rstrip("\r\n"),
                                }
                            )
                            if len(matches) >= max_results:
                                truncated = True
                                break
            except (OSError, PermissionError):
                continue

            if truncated:
                break
        if truncated:
            break

    return {
        "query": query,
        "total_matches": len(matches),
        "truncated": truncated,
        "matches": matches,
    }
