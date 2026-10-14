"""Bounded, deterministic walk of a checked-out repository."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

from app.config import Settings
from app.ingestion.filters import classify_file, is_excluded_directory
from app.ingestion.types import ScanReport, SourceFile
from app.models.analysis import SkipReason

_BINARY_SNIFF_BYTES = 8192
_UTF8_BOM = "﻿"


def scan_repository(root: Path, settings: Settings) -> tuple[list[SourceFile], ScanReport]:
    """Collect analyzable source files under ``root`` without following symlinks.

    Directories and files are visited in sorted order so results are stable.
    """
    report = ScanReport()
    files: list[SourceFile] = []
    total_bytes = 0
    sample_limit = settings.max_diagnostic_items
    root = root.resolve()

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept_dirs = []
        for name in sorted(dirnames):
            if is_excluded_directory(name):
                continue
            if (current / name).is_symlink():
                report.files_discovered += 1
                report.skip(_relative(root, current / name), SkipReason.SYMLINK, sample_limit)
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in sorted(filenames):
            if report.files_discovered >= settings.max_files_scanned:
                report.reach_limit("max_files_scanned", settings.max_files_scanned)
                return files, report
            report.files_discovered += 1
            full_path = current / name
            rel_path = _relative(root, full_path)

            grammar, reason = classify_file(rel_path)
            if grammar is None:
                report.skip(rel_path, reason or SkipReason.UNSUPPORTED_EXTENSION, sample_limit)
                continue

            try:
                info = full_path.lstat()
            except OSError:
                report.skip(rel_path, SkipReason.EXCLUDED_PATTERN, sample_limit)
                continue
            if stat.S_ISLNK(info.st_mode):
                report.skip(rel_path, SkipReason.SYMLINK, sample_limit)
                continue
            if not stat.S_ISREG(info.st_mode):
                report.skip(rel_path, SkipReason.EXCLUDED_PATTERN, sample_limit)
                continue
            if info.st_size > settings.max_file_bytes:
                report.skip(rel_path, SkipReason.TOO_LARGE, sample_limit)
                continue
            if len(files) >= settings.max_source_files:
                report.reach_limit("max_source_files", settings.max_source_files)
                report.skip(rel_path, SkipReason.LIMIT_REACHED, sample_limit)
                continue
            if total_bytes + info.st_size > settings.max_total_source_bytes:
                report.reach_limit("max_total_source_bytes", settings.max_total_source_bytes)
                report.skip(rel_path, SkipReason.LIMIT_REACHED, sample_limit)
                continue

            try:
                data = _read_no_follow(full_path, settings.max_file_bytes)
            except OSError as exc:
                symlink = exc.errno == errno.ELOOP
                reason = SkipReason.SYMLINK if symlink else SkipReason.EXCLUDED_PATTERN
                report.skip(rel_path, reason, sample_limit)
                continue
            if len(data) > settings.max_file_bytes:  # grew after lstat
                report.skip(rel_path, SkipReason.TOO_LARGE, sample_limit)
                continue
            text = _decode_source(data)
            if text is None:
                report.skip(rel_path, SkipReason.BINARY, sample_limit)
                continue

            total_bytes += len(data)
            files.append(SourceFile(rel_path, grammar, text, len(data)))

    return files, report


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _read_no_follow(path: Path, max_bytes: int) -> bytes:
    """Read at most ``max_bytes + 1`` bytes. Raises ELOOP if ``path`` is a symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        return handle.read(max_bytes + 1)


def _decode_source(data: bytes) -> str | None:
    if b"\x00" in data[:_BINARY_SNIFF_BYTES]:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text.removeprefix(_UTF8_BOM)
