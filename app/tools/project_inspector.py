import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

DEFAULT_IGNORED_DIRS: Set[str] = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
}

DEFAULT_MAX_FILES: int = 1000
DEFAULT_MAX_FILE_SIZE_BYTES: int = 1024 * 1024  # 1 MB


def resolve_safe_path(
    target_path: str | Path, base_dir: Optional[str | Path] = None
) -> Path:
    """
    Safely resolves a path and ensures it does not escape base_dir.

    Args:
        target_path: The file or directory path to resolve.
        base_dir: Optional boundary directory. When provided, target_path must reside within it.

    Returns:
        The fully resolved canonical Path.

    Raises:
        FileNotFoundError: If the target path does not exist.
        ValueError: If path traversal outside base_dir is detected.
    """
    resolved_target = Path(target_path).resolve()
    if not resolved_target.exists():
        raise FileNotFoundError(f"Path does not exist: {target_path}")

    if base_dir is not None:
        resolved_base = Path(base_dir).resolve()
        if not resolved_target.is_relative_to(resolved_base):
            raise ValueError(
                f"Path traversal detected: '{target_path}' is outside '{base_dir}'."
            )

    return resolved_target


def list_project_files(
    project_root: str | Path,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    ignored_dirs: Optional[Set[str]] = None,
    base_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """
    Lists files in a project directory while respecting safety boundaries,
    ignoring development/cache directories, and capping limits for low memory usage.

    Args:
        project_root: Directory to scan.
        max_files: Maximum number of files to return.
        max_file_size_bytes: Maximum size of individual files to report.
        ignored_dirs: Directory names to skip (defaults to DEFAULT_IGNORED_DIRS).
        base_dir: Optional security boundary directory.

    Returns:
        Structured dictionary containing project_root, total_files, truncated flag, and file list.
    """
    root_path = resolve_safe_path(project_root, base_dir=base_dir)
    if not root_path.is_dir():
        raise NotADirectoryError(f"Target path is not a directory: {project_root}")

    ignore_set = (
        set(ignored_dirs) if ignored_dirs is not None else DEFAULT_IGNORED_DIRS
    )
    collected_files: List[Dict[str, Any]] = []
    truncated = False

    for current_root, dirs, files in os.walk(root_path):
        # Prune ignored directories in-place to prevent entering them
        dirs[:] = [d for d in dirs if d not in ignore_set]

        for file_name in sorted(files):
            if len(collected_files) >= max_files:
                truncated = True
                break

            file_path = Path(current_root) / file_name
            try:
                stat = file_path.stat()
                if stat.st_size > max_file_size_bytes:
                    continue

                rel_path = file_path.relative_to(root_path).as_posix()
                collected_files.append(
                    {
                        "relative_path": rel_path,
                        "size_bytes": stat.st_size,
                        "extension": file_path.suffix.lower(),
                    }
                )
            except (OSError, PermissionError):
                continue

        if truncated:
            break

    return {
        "project_root": root_path.as_posix(),
        "total_files": len(collected_files),
        "truncated": truncated,
        "files": collected_files,
    }
