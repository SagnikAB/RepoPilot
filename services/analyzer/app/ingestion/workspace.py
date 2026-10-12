"""Isolated temporary workspaces that are always removed."""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

WORKSPACE_PREFIX = "repopilot-"


@contextmanager
def temporary_workspace(root: Path | None = None) -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX, dir=root))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():
            logger.error("Failed to remove workspace %s", path)
