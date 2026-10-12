"""Subprocess isolation: worker deaths and hangs must not escape the worker.

Each test spawns real worker processes (about 0.5 s each). Routine tests use
controlled failures (SIGTERM, nonzero exit, hang, exception) that the OS does
not record as crashes. The real-SIGSEGV variant is opt-in (``native_crash``).
"""

from __future__ import annotations

import signal
import time
from typing import Any

import pytest

from app.config import Settings
from app.models.analysis import SkipReason
from app.parsers.service import parse_repository
from app.parsers.worker import _describe_exit
from tests.helpers import make_settings, source_file
from tests.helpers.faulty_parsers import (
    CONTROLLED_EXIT_CODE,
    crash_on_marker,
    exit_immediately,
    exit_on_marker,
    hang_on_marker,
    raise_on_marker,
    require_worker_process,
    terminate_on_marker,
)
from tests.helpers.native import native_crash_canary

BEFORE = source_file("src/before.js", "function before() { a(); }\n")
AFTER = source_file("src/after.ts", "export const after = () => b();\n")


def _subprocess_settings(**overrides: Any) -> Any:
    return make_settings(parse_isolation="subprocess", **overrides)


def _snapshot(result: Any) -> list[tuple[str, list[str], int]]:
    return [(f.path, sorted(r.node.id for r in f.functions), len(f.calls)) for f in result.files]


def test_subprocess_results_match_in_process_results() -> None:
    deep = source_file("src/deep.js", "const x = " + " + ".join(["a()"] * 20_000) + ";\n")
    files = [BEFORE, deep, AFTER]

    isolated = parse_repository(files, _subprocess_settings())
    inline = parse_repository(files, make_settings())

    assert _snapshot(isolated) == _snapshot(inline)
    assert isolated.failed_files == []


def test_production_default_parses_in_an_isolated_worker() -> None:
    assert Settings(_env_file=None).parse_isolation == "subprocess"

    isolated = parse_repository(
        [BEFORE, AFTER], _subprocess_settings(), parse_fn=require_worker_process
    )
    inline = parse_repository([BEFORE, AFTER], make_settings(), parse_fn=require_worker_process)

    assert [f.path for f in isolated.files] == ["src/before.js", "src/after.ts"]
    assert isolated.failed_files == []
    assert inline.failed_files == ["src/before.js", "src/after.ts"]  # the check discriminates


def test_worker_killed_by_a_signal_is_contained_and_reported() -> None:
    victim = source_file("src/terminate.js", "function t() {}\n")

    result = parse_repository(
        [BEFORE, victim, AFTER], _subprocess_settings(), parse_fn=terminate_on_marker
    )

    assert [f.path for f in result.files] == ["src/before.js", "src/after.ts"]
    assert result.failed_files == ["src/terminate.js"]
    [diagnostic] = result.parse_errors
    assert diagnostic.path == "src/terminate.js"
    assert diagnostic.message == (
        "Parser process was terminated (SIGTERM) while parsing this file; file skipped"
    )


def test_nonzero_worker_exit_is_contained_and_reported() -> None:
    victim = source_file("src/exit.js", "function e() {}\n")

    result = parse_repository(
        [BEFORE, victim, AFTER], _subprocess_settings(), parse_fn=exit_on_marker
    )

    assert [f.path for f in result.files] == ["src/before.js", "src/after.ts"]
    assert result.failed_files == ["src/exit.js"]
    assert result.parse_errors[0].message == (
        f"Parser process exited unexpectedly (exit code {CONTROLLED_EXIT_CODE}) "
        "while parsing this file; file skipped"
    )


@pytest.mark.parametrize(
    ("exitcode", "description"),
    [
        (-signal.SIGSEGV, "crashed (SIGSEGV)"),
        (-signal.SIGBUS, "crashed (SIGBUS)"),
        (-signal.SIGABRT, "crashed (SIGABRT)"),
        (-signal.SIGTERM, "was terminated (SIGTERM)"),
        (-signal.SIGKILL, "was terminated (SIGKILL)"),
        (-250, "crashed (signal 250)"),
        (3, "exited unexpectedly (exit code 3)"),
        (None, "stopped responding"),
    ],
)
def test_exit_status_descriptions(exitcode: int | None, description: str) -> None:
    assert _describe_exit(exitcode) == description


@native_crash_canary
def test_real_sigsegv_in_worker_is_contained_and_reported() -> None:
    crash = source_file("src/crash.js", "function crash() {}\n")

    result = parse_repository(
        [BEFORE, crash, AFTER], _subprocess_settings(), parse_fn=crash_on_marker
    )

    assert [f.path for f in result.files] == ["src/before.js", "src/after.ts"]
    assert result.failed_files == ["src/crash.js"]
    assert result.parse_errors[0].message == (
        "Parser process crashed (SIGSEGV) while parsing this file; file skipped"
    )


def test_hang_is_killed_after_per_file_timeout() -> None:
    hang = source_file("src/hang.js", "function hang() {}\n")
    started = time.monotonic()

    result = parse_repository(
        [BEFORE, hang, AFTER],
        _subprocess_settings(parse_file_timeout_seconds=1),
        parse_fn=hang_on_marker,
    )

    assert time.monotonic() - started < 15
    assert [f.path for f in result.files] == ["src/before.js", "src/after.ts"]
    assert result.failed_files == ["src/hang.js"]
    assert result.parse_errors[0].message == "Parsing exceeded the 1s per-file limit; file skipped"
    assert [(r.limit, r.value) for r in result.limits_reached] == [
        ("parse_file_timeout_seconds", 1)
    ]


def test_overall_budget_stops_a_hanging_worker() -> None:
    hang = source_file("src/hang.js", "function hang() {}\n")
    started = time.monotonic()

    result = parse_repository(
        [BEFORE, hang, AFTER],
        _subprocess_settings(parse_time_budget_seconds=3, parse_file_timeout_seconds=60),
        parse_fn=hang_on_marker,
    )

    assert time.monotonic() - started < 15
    assert [f.path for f in result.files] == ["src/before.js"]
    assert [(s.path, s.reason) for s in result.skipped] == [
        ("src/hang.js", SkipReason.LIMIT_REACHED),
        ("src/after.ts", SkipReason.LIMIT_REACHED),
    ]
    assert result.limits_reached[0].limit == "parse_time_budget_seconds"


def test_python_exception_in_worker_does_not_restart_or_abort() -> None:
    boom = source_file("src/boom.js", "function boom() {}\n")

    result = parse_repository(
        [BEFORE, boom, AFTER], _subprocess_settings(), parse_fn=raise_on_marker
    )

    assert [f.path for f in result.files] == ["src/before.js", "src/after.ts"]
    assert result.failed_files == ["src/boom.js"]


def test_worker_dying_on_every_file_reports_each_file() -> None:
    result = parse_repository([BEFORE, AFTER], _subprocess_settings(), parse_fn=exit_immediately)

    assert result.files == []
    assert result.failed_files == ["src/before.js", "src/after.ts"]
    assert {d.message for d in result.parse_errors} == {
        "Parser process exited unexpectedly (exit code 3) while parsing this file; file skipped"
    }
