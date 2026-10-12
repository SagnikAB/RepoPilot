"""Parse functions that misbehave on purpose, for worker-isolation tests.

They live in an importable module because the parser worker is started with
``spawn`` and receives the function by reference.

Routine tests use *controlled* failures that the OS does not treat as crashes
(SIGTERM, a nonzero exit, a hang, a Python exception). ``crash_on_marker``
raises a real SIGSEGV and is only used by opt-in tests (``tests/helpers/native.py``).
"""

from __future__ import annotations

import multiprocessing
import os
import signal
import time

from app.config import Settings
from app.ingestion.types import SourceFile
from app.parsers.file_parser import parse_source_file
from app.parsers.types import FileExtraction

CONTROLLED_EXIT_CODE = 70


def terminate_on_marker(source: SourceFile, settings: Settings) -> FileExtraction:
    """The worker dies from a signal on terminate.js (SIGTERM: not an OS crash report)."""
    if source.path.endswith("terminate.js"):
        os.kill(os.getpid(), signal.SIGTERM)
    return parse_source_file(source, settings)


def exit_on_marker(source: SourceFile, settings: Settings) -> FileExtraction:
    """The worker exits with a nonzero status on exit.js."""
    if source.path.endswith("exit.js"):
        os._exit(CONTROLLED_EXIT_CODE)
    return parse_source_file(source, settings)


def hang_on_marker(source: SourceFile, settings: Settings) -> FileExtraction:
    """Simulate a parser that never returns on hang.js."""
    if source.path.endswith("hang.js"):
        time.sleep(600)
    return parse_source_file(source, settings)


def raise_on_marker(source: SourceFile, settings: Settings) -> FileExtraction:
    if source.path.endswith("boom.js"):
        raise RuntimeError("simulated parser bug")
    return parse_source_file(source, settings)


def exit_immediately(source: SourceFile, settings: Settings) -> FileExtraction:
    """Worker dies on every file: exercises the restart cap and crash reporting."""
    os._exit(3)


def require_worker_process(source: SourceFile, settings: Settings) -> FileExtraction:
    """Parse only inside a spawned worker; fail loudly if run in the calling process."""
    if multiprocessing.parent_process() is None:
        raise RuntimeError("parsing ran in the main process, not in an isolated worker")
    return parse_source_file(source, settings)


def crash_on_marker(source: SourceFile, settings: Settings) -> FileExtraction:
    """OPT-IN ONLY: a real SIGSEGV on crash.js (the OS records a crash)."""
    if source.path.endswith("crash.js"):
        os.kill(os.getpid(), signal.SIGSEGV)
    return parse_source_file(source, settings)
