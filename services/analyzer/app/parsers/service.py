"""Parse every ingested source file, isolating failures per file."""

from __future__ import annotations

import time
from collections.abc import Sequence

from app.config import Settings
from app.ingestion.types import SourceFile
from app.models.analysis import ParseDiagnostic, SkippedFile
from app.parsers.file_parser import (
    FileParseOutcome,
    ParseFn,
    budget_exhausted,
    parse_one,
    parse_source_file,
)
from app.parsers.types import ParsedRepository
from app.parsers.worker import parse_in_subprocess

__all__ = ["parse_repository", "parse_source_file"]


def parse_repository(
    files: Sequence[SourceFile], settings: Settings, *, parse_fn: ParseFn = parse_source_file
) -> ParsedRepository:
    """Parse files in order until the time budget is spent.

    A file that fails (Python error, native crash, timeout or structural limit)
    is reported as a diagnostic and skipped; it never aborts the analysis.
    Syntax errors are not failures: Tree-sitter recovers and the partial
    results are kept, with diagnostics.
    """
    deadline = time.monotonic() + settings.parse_time_budget_seconds
    if settings.parse_isolation == "subprocess" and files:
        outcomes = parse_in_subprocess(files, settings, parse_fn, deadline)
    else:
        outcomes = _parse_in_process(files, settings, parse_fn, deadline)
    return _assemble(outcomes, settings)


def _parse_in_process(
    files: Sequence[SourceFile], settings: Settings, parse_fn: ParseFn, deadline: float
) -> list[FileParseOutcome]:
    return [
        budget_exhausted(source, settings)
        if time.monotonic() >= deadline
        else parse_one(source, settings, parse_fn)
        for source in files
    ]


def _assemble(outcomes: Sequence[FileParseOutcome], settings: Settings) -> ParsedRepository:
    result = ParsedRepository()
    limit_names: set[str] = set()
    for outcome in outcomes:
        if outcome.extraction is not None:
            result.files.append(outcome.extraction)
            _add_parse_errors(result, outcome.extraction.parse_errors, settings)
            continue
        if outcome.skip_reason is not None:
            result.skipped.append(SkippedFile(path=outcome.path, reason=outcome.skip_reason))
        elif outcome.failure is not None:
            result.failed_files.append(outcome.path)
        if outcome.failure is not None:
            diagnostic = ParseDiagnostic(path=outcome.path, message=outcome.failure)
            _add_parse_errors(result, [diagnostic], settings)
        if outcome.limit is not None and outcome.limit.limit not in limit_names:
            limit_names.add(outcome.limit.limit)
            result.limits_reached.append(outcome.limit)
    return result


def _add_parse_errors(
    result: ParsedRepository, errors: Sequence[ParseDiagnostic], settings: Settings
) -> None:
    room = settings.max_diagnostic_items - len(result.parse_errors)
    if len(errors) > room:
        result.parse_errors_truncated = True
    result.parse_errors.extend(errors[: max(room, 0)])
