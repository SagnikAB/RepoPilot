"""Parse one source file into a ``FileExtraction``, or a structured failure."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.config import Settings
from app.ingestion.types import SourceFile
from app.models.analysis import LimitReached, SkipReason
from app.parsers.extractor import extract_file
from app.parsers.languages import new_parser
from app.parsers.types import FileExtraction
from app.rules.engine import run_rules
from app.rules.javascript import JAVASCRIPT_RULES

logger = logging.getLogger(__name__)

ParseFn = Callable[[SourceFile, Settings], FileExtraction]


class ParserFailure(Exception):
    """Tree-sitter returned no tree for a file."""


class ParseLimitError(Exception):
    """A file exceeded a structural limit and is skipped (not a crash)."""

    def __init__(self, limit: str, value: int, message: str) -> None:
        super().__init__(message)
        self.limit = limit
        self.value = value
        self.message = message


@dataclass(frozen=True, slots=True)
class FileParseOutcome:
    """Result for one file. Exactly one of ``extraction`` / ``failure`` /
    ``skip_reason`` describes what happened. Messages are client-safe."""

    path: str
    extraction: FileExtraction | None = None
    failure: str | None = None
    skip_reason: SkipReason | None = None
    limit: LimitReached | None = None


def parse_source_file(source: SourceFile, settings: Settings) -> FileExtraction:
    tree = new_parser(source.grammar).parse(source.text.encode("utf-8"))
    if tree is None:
        raise ParserFailure("parser returned no tree")
    root = tree.root_node
    node_count = root.descendant_count
    if node_count > settings.max_syntax_nodes_per_file:
        raise ParseLimitError(
            "max_syntax_nodes_per_file",
            settings.max_syntax_nodes_per_file,
            f"Syntax tree has {node_count} nodes, above the limit of "
            f"{settings.max_syntax_nodes_per_file}; file skipped",
        )
    extraction = extract_file(
        source.path,
        source.grammar,
        source.text,
        root,
        max_parse_errors=settings.max_parse_errors_per_file,
    )
    # Rules need the syntax tree, so they run here: in the same isolated worker
    # and under the same per-file timeout as parsing.
    rules = run_rules(
        JAVASCRIPT_RULES,
        extraction,
        source.text,
        root,
        max_findings=settings.max_findings_per_file,
    )
    extraction.findings = rules.findings
    extraction.findings_truncated = rules.truncated
    extraction.redactions = rules.redactions
    extraction.rule_errors = rules.errors
    return extraction


def parse_one(source: SourceFile, settings: Settings, parse_fn: ParseFn) -> FileParseOutcome:
    """Run ``parse_fn`` and convert Python-level failures into an outcome.

    Native crashes cannot be caught here; see ``app.parsers.worker``.
    """
    try:
        return FileParseOutcome(source.path, extraction=parse_fn(source, settings))
    except ParseLimitError as exc:
        return FileParseOutcome(
            source.path,
            failure=exc.message,
            skip_reason=SkipReason.TOO_LARGE,
            limit=LimitReached(limit=exc.limit, value=exc.value),
        )
    except Exception as exc:
        # Log the path and traceback only; never the file contents.
        logger.exception("Parser failure in %s", source.path)
        return FileParseOutcome(
            source.path, failure=f"Internal parser failure ({type(exc).__name__}); file skipped"
        )


def budget_exhausted(source: SourceFile, settings: Settings) -> FileParseOutcome:
    return FileParseOutcome(
        source.path,
        skip_reason=SkipReason.LIMIT_REACHED,
        limit=LimitReached(
            limit="parse_time_budget_seconds", value=int(settings.parse_time_budget_seconds)
        ),
    )
