"""Deterministic, depth-limited directory tree summary (stdlib only)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DirStats:
    path: Path
    depth: int
    direct_file_count: int
    recursive_file_count: int
    recursive_byte_size: int


def _walk_stats(dir_path: Path) -> tuple[int, int]:
    """(recursive_file_count, recursive_byte_size) for everything under dir_path."""
    file_count = 0
    byte_size = 0
    for child in dir_path.iterdir():
        if child.is_dir() and not child.is_symlink():
            c, s = _walk_stats(child)
            file_count += c
            byte_size += s
        elif child.is_file():
            file_count += 1
            byte_size += child.stat().st_size
    return file_count, byte_size


def tree_summary(root: Path, max_depth: int) -> list[DirStats]:
    """Depth-limited directory tree: one DirStats per directory down to max_depth.

    `root` itself is depth 0. Traversal order is alphabetical at every level so
    output is deterministic across runs/machines.
    """
    root = Path(root)
    results: list[DirStats] = []

    def visit(dir_path: Path, depth: int) -> None:
        direct_files = sum(1 for c in sorted(dir_path.iterdir()) if c.is_file())
        recursive_files, recursive_bytes = _walk_stats(dir_path)
        results.append(
            DirStats(
                path=dir_path,
                depth=depth,
                direct_file_count=direct_files,
                recursive_file_count=recursive_files,
                recursive_byte_size=recursive_bytes,
            )
        )
        if depth >= max_depth:
            return
        for child in sorted(dir_path.iterdir()):
            if child.is_dir() and not child.is_symlink():
                visit(child, depth + 1)

    visit(root, 0)
    return results


def format_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}{unit}"
        value /= 1024
    return f"{value:.1f}GB"
