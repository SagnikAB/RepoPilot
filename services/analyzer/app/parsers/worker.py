"""Run parsing in a separate process so native failures stay contained.

Why: Tree-sitter is native code processing untrusted input. tree-sitter 0.26.0
has a confirmed memory-safety bug (``Point.row``/``Point.column`` corrupt the
heap, see ``extractor.py``), and it offers no parse timeout. A segfault or hang
inside the API process would take down every request, so parsing runs in a
spawned worker:

* The worker reports ``("start", i)`` before and ``("result", i, outcome)``
  after each file, so the parent always knows which file was in flight.
* If the worker dies (e.g. SIGSEGV), that file gets a crash diagnostic and a
  fresh worker continues with the next file.
* If a file exceeds ``parse_file_timeout_seconds``, the worker is killed, the
  file gets a timeout diagnostic, and a fresh worker continues.
* ``spawn`` is used (not ``fork``): forking a multi-threaded server is unsafe.
"""

from __future__ import annotations

import logging
import math
import multiprocessing
import signal
import time
from collections.abc import Sequence
from multiprocessing.connection import Connection
from multiprocessing.context import SpawnContext, SpawnProcess

from app.config import Settings
from app.ingestion.types import SourceFile
from app.models.analysis import LimitReached
from app.parsers.file_parser import FileParseOutcome, ParseFn, budget_exhausted, parse_one

logger = logging.getLogger(__name__)

MAX_WORKER_STARTS = 50
_JOIN_TIMEOUT_SECONDS = 5


def _worker_main(
    conn: Connection, files: list[SourceFile], settings: Settings, parse_fn: ParseFn
) -> None:
    try:
        for index, source in enumerate(files):
            conn.send(("start", index))
            conn.send(("result", index, parse_one(source, settings, parse_fn)))
    finally:
        conn.close()


def parse_in_subprocess(
    files: Sequence[SourceFile], settings: Settings, parse_fn: ParseFn, deadline: float
) -> list[FileParseOutcome]:
    """Parse ``files`` in worker processes; one outcome per file, in order."""
    context = multiprocessing.get_context("spawn")
    outcomes: list[FileParseOutcome | None] = [None] * len(files)
    next_index = 0
    starts = 0

    while next_index < len(files) and time.monotonic() < deadline:
        if starts >= MAX_WORKER_STARTS:
            for index in range(next_index, len(files)):
                outcomes[index] = FileParseOutcome(
                    files[index].path,
                    failure="Parsing stopped after repeated parser worker failures; file skipped",
                )
            break
        starts += 1
        next_index = _run_batch(context, files, next_index, settings, parse_fn, deadline, outcomes)

    return [
        outcome if outcome is not None else budget_exhausted(files[index], settings)
        for index, outcome in enumerate(outcomes)
    ]


def _run_batch(
    context: SpawnContext,
    files: Sequence[SourceFile],
    first: int,
    settings: Settings,
    parse_fn: ParseFn,
    deadline: float,
    outcomes: list[FileParseOutcome | None],
) -> int:
    """Run one worker over ``files[first:]``. Return the index to resume from."""
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker_main,
        args=(sender, list(files[first:]), settings, parse_fn),
        daemon=True,
    )
    process.start()
    sender.close()  # the parent must not hold the write end, or EOF never arrives

    current: int | None = None  # absolute index of the file being parsed
    file_deadline = math.inf
    progressed = False
    try:
        while True:
            wait = min(deadline, file_deadline) - time.monotonic()
            # Always drain a pending message before declaring a timeout.
            if not receiver.poll(max(wait, 0)):
                if current is not None and time.monotonic() >= file_deadline:
                    outcomes[current] = _timeout(files[current], settings)
                    return current + 1
                return len(files)  # overall budget spent; the rest get budget outcomes
            try:
                message = receiver.recv()
            except EOFError:
                return _handle_exit(process, files, first, current, progressed, outcomes)
            if message[0] == "start":
                current = first + message[1]
                file_deadline = time.monotonic() + settings.parse_file_timeout_seconds
                progressed = True
            elif message[0] == "result":
                outcomes[first + message[1]] = message[2]
                current, file_deadline = None, math.inf
    finally:
        _stop(process)
        receiver.close()


def _handle_exit(
    process: SpawnProcess,
    files: Sequence[SourceFile],
    first: int,
    current: int | None,
    progressed: bool,
    outcomes: list[FileParseOutcome | None],
) -> int:
    process.join(_JOIN_TIMEOUT_SECONDS)
    pending = next((i for i in range(first, len(files)) if outcomes[i] is None), None)
    if pending is None:
        return len(files)  # normal completion
    status = _describe_exit(process.exitcode)
    if current is not None:
        logger.error("Parser worker %s while parsing %s", status, files[current].path)
        outcomes[current] = FileParseOutcome(
            files[current].path,
            failure=f"Parser process {status} while parsing this file; file skipped",
        )
        return current + 1
    if not progressed:
        # Died before parsing anything: a systemic failure, not a bad file.
        logger.error("Parser worker %s before parsing any file", status)
        for index in range(pending, len(files)):
            outcomes[index] = FileParseOutcome(
                files[index].path, failure=f"Parser process {status}; file not parsed"
            )
        return len(files)
    return pending  # died between files; retry from the first unparsed file


def _timeout(source: SourceFile, settings: Settings) -> FileParseOutcome:
    seconds = settings.parse_file_timeout_seconds
    logger.warning("Parsing %s exceeded %gs; worker killed", source.path, seconds)
    return FileParseOutcome(
        source.path,
        failure=f"Parsing exceeded the {seconds:g}s per-file limit; file skipped",
        limit=LimitReached(limit="parse_file_timeout_seconds", value=math.ceil(seconds)),
    )


# Signals that indicate a fault inside the process (as opposed to being stopped).
_CRASH_SIGNALS = frozenset(
    {signal.SIGSEGV, signal.SIGBUS, signal.SIGILL, signal.SIGFPE, signal.SIGABRT}
)


def _describe_exit(exitcode: int | None) -> str:
    if exitcode is None:
        return "stopped responding"
    if exitcode < 0:
        try:
            signum = signal.Signals(-exitcode)
        except ValueError:
            return f"crashed (signal {-exitcode})"
        verb = "crashed" if signum in _CRASH_SIGNALS else "was terminated"
        return f"{verb} ({signum.name})"
    return f"exited unexpectedly (exit code {exitcode})"


def _stop(process: SpawnProcess) -> None:
    if process.is_alive():
        process.kill()
    process.join(_JOIN_TIMEOUT_SECONDS)
