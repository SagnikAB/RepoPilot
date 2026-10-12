"""Analysis orchestration and read models shared by the API and the AI layer.

``analyze_repository`` runs the whole synchronous pipeline once per request:
ingest (hardened clone, temporary workspace always removed) -> parse (worker
isolation) -> resolve calls and build the graph -> summarize. Every later
response for an ``analysis_id`` is derived from that one stored result, so it
always describes the same commit.

Status is ``completed`` when a graph was built (possibly with per-file
diagnostics) and ``failed`` when eligible files existed but none could be
parsed, or graph construction raised. Failures *before* an analysis exists
(validation, clone) raise ``AppError`` subclasses and nothing is stored.
"""

from __future__ import annotations

import logging
import time
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.config import Settings
from app.errors import ConflictError, InvalidRequestError, NotFoundError
from app.graph.builder import CallGraph, build_call_graph
from app.graph.paths import DEFAULT_MAX_EXPANSIONS, find_paths, reachable_within
from app.ingestion.service import ingest_repository
from app.ingestion.types import IngestedRepository
from app.models.analysis import (
    AnalysisDiagnostics,
    AnalysisError,
    AnalysisStats,
    AnalysisStatus,
    AnalysisSummary,
    LimitReached,
    SkippedFile,
    SkipReason,
)
from app.models.api import AnalyzeRequest, SourceResponse
from app.models.findings import Finding, FindingsResponse, Severity
from app.models.graph import CallPath, GraphResponse, PathsResponse
from app.models.ids import is_valid_analysis_id, new_analysis_id
from app.parsers.file_parser import ParseFn, parse_source_file
from app.parsers.positions import apply_redactions, split_lines
from app.parsers.service import parse_repository
from app.parsers.types import ParsedRepository
from app.storage.memory import AnalysisStore, StoredAnalysis, StoredSource

logger = logging.getLogger(__name__)

PATH_LIMITATION = (
    "A path means each function contains a resolved call to the next. It does not prove "
    "that the path executes at runtime, that data flows along it, or that anything is "
    "exploitable."
)
PARTIAL_GRAPH_WARNING = (
    "Call graph is partial: member calls, dynamic dispatch and external packages are "
    "reported as unresolved."
)
FINDINGS_NOT_COMPUTED_WARNING = "Findings were not computed because the analysis failed."
NO_FILES_WARNING = "No JavaScript or TypeScript files were analyzed; see skipped_files."

Ingestor = Callable[[str, str | None, Settings], IngestedRepository]


@dataclass(frozen=True, slots=True)
class AnalysisPipeline:
    """Injectable pipeline stages. Production uses the defaults; tests swap them."""

    ingest: Ingestor = field(default=ingest_repository)
    parse_fn: ParseFn = field(default=parse_source_file)


def analyze_repository(
    request: AnalyzeRequest, settings: Settings, pipeline: AnalysisPipeline
) -> StoredAnalysis:
    """Run the full pipeline. Raises ``IngestionError`` if the repository can't be fetched."""
    created_at = datetime.now(UTC)
    started = time.monotonic()
    ingested = pipeline.ingest(request.repo_url, request.ref, settings)
    return build_analysis(
        ingested, settings, parse_fn=pipeline.parse_fn, created_at=created_at, started=started
    )


def build_analysis(
    ingested: IngestedRepository,
    settings: Settings,
    *,
    parse_fn: ParseFn = parse_source_file,
    analysis_id: str | None = None,
    created_at: datetime | None = None,
    started: float | None = None,
) -> StoredAnalysis:
    analysis_id = analysis_id or new_analysis_id()
    created_at = created_at or datetime.now(UTC)
    started = time.monotonic() if started is None else started
    parsed: ParsedRepository | None = None
    graph: CallGraph | None = None
    error: AnalysisError | None = None
    try:
        parsed = parse_repository(ingested.files, settings, parse_fn=parse_fn)
        if ingested.files and not parsed.files:
            error = AnalysisError(
                code="parsing_failed",
                message=f"None of the {len(ingested.files)} eligible source files could be "
                "parsed; see diagnostics.parse_errors and diagnostics.skipped_files.",
            )
        else:
            unparsed = [s.path for s in parsed.skipped] + parsed.failed_files
            graph = build_call_graph(parsed.files, settings, unparsed_paths=unparsed)
    except Exception:
        logger.exception("Analysis %s failed", analysis_id)
        graph = None
        error = AnalysisError(
            code="analysis_failed", message="An internal error stopped the analysis."
        )

    findings: tuple[Finding, ...] = ()
    sources: dict[str, StoredSource] = {}
    if graph is not None and parsed is not None:
        findings = _collect_findings(parsed, graph)
        sources = _retain_sources(ingested, parsed)

    summary = AnalysisSummary(
        analysis_id=analysis_id,
        status=AnalysisStatus.FAILED if error else AnalysisStatus.COMPLETED,
        repository=ingested.repository,
        created_at=created_at,
        completed_at=datetime.now(UTC),
        duration_ms=int((time.monotonic() - started) * 1000),
        stats=_stats(ingested, parsed, graph, findings),
        diagnostics=_diagnostics(ingested, parsed, graph, error, settings),
        error=error,
    )
    logger.info(
        "Analysis %s %s: %d files, %d functions, %d edges, %d unresolved calls, %d findings",
        analysis_id,
        summary.status.value,
        summary.stats.files_analyzed if summary.stats else 0,
        len(graph.nodes) if graph else 0,
        len(graph.edges) if graph else 0,
        len(graph.unresolved) if graph else 0,
        len(findings),
    )
    return StoredAnalysis(
        analysis_id=analysis_id,
        summary=summary,
        graph=graph,
        findings=findings,
        sources=sources,
    )


def _collect_findings(parsed: ParsedRepository, graph: CallGraph) -> tuple[Finding, ...]:
    """All findings, ordered; ``function_id`` cleared if that node is not in the graph."""
    collected: list[Finding] = []
    for extraction in parsed.files:
        for finding in extraction.findings:
            if finding.function_id is not None and finding.function_id not in graph.nodes:
                finding = finding.model_copy(update={"function_id": None})
            collected.append(finding)
    collected.sort(
        key=lambda f: (f.location.path, f.location.start_line, f.location.end_line, f.rule_id, f.id)
    )
    return tuple(collected)


def _retain_sources(
    ingested: IngestedRepository, parsed: ParsedRepository
) -> dict[str, StoredSource]:
    """Text of the parsed files only: a subset of the filtered, size-limited ingested files."""
    by_path = {source.path: source for source in ingested.files}
    retained: dict[str, StoredSource] = {}
    for extraction in parsed.files:
        source = by_path.get(extraction.path)
        if source is None:  # cannot happen: parsing only sees ingested files
            continue
        retained[source.path] = StoredSource(
            path=source.path,
            language=extraction.language,
            text=source.text,
            size_bytes=source.size_bytes,
            redactions=tuple(extraction.redactions),
        )
    return retained


def _skipped_by_reason(
    ingested: IngestedRepository, parsed: ParsedRepository | None
) -> Counter[SkipReason]:
    counts = Counter(ingested.scan.skipped_by_reason)
    if parsed is None:  # parsing itself raised: no accepted file was analyzed
        counts[SkipReason.PARSE_FAILED] += len(ingested.files)
        return counts
    counts.update(s.reason for s in parsed.skipped)
    counts[SkipReason.PARSE_FAILED] += len(parsed.failed_files)
    return +counts  # drop zero entries


def _stats(
    ingested: IngestedRepository,
    parsed: ParsedRepository | None,
    graph: CallGraph | None,
    findings: tuple[Finding, ...],
) -> AnalysisStats:
    skipped = _skipped_by_reason(ingested, parsed)
    files = parsed.files if parsed is not None else []
    return AnalysisStats(
        files_discovered=ingested.scan.files_discovered,
        files_analyzed=len(files),
        files_skipped=sum(skipped.values()),
        functions=len(graph.nodes) if graph else 0,
        call_edges=len(graph.edges) if graph else 0,
        unresolved_calls=len(graph.unresolved) if graph else 0,
        # null = not computed (failed analysis); a number is a real count, including 0.
        findings=len(findings) if graph is not None else None,
        findings_by_severity=dict(Counter(f.severity for f in findings)) if graph else {},
        files_by_language=dict(Counter(f.language for f in files)),
    )


def _diagnostics(
    ingested: IngestedRepository,
    parsed: ParsedRepository | None,
    graph: CallGraph | None,
    error: AnalysisError | None,
    settings: Settings,
) -> AnalysisDiagnostics:
    cap = settings.max_diagnostic_items
    scan = ingested.scan
    skipped = list(scan.skipped_sample)
    limits = list(scan.limits_reached)
    parse_errors = []
    parse_truncated = False
    if parsed is not None:
        skipped += parsed.skipped
        skipped += [
            SkippedFile(path=p, reason=SkipReason.PARSE_FAILED) for p in parsed.failed_files
        ]
        limits += parsed.limits_reached
        parse_errors = parsed.parse_errors
        parse_truncated = parsed.parse_errors_truncated
    if graph is not None:
        limits += graph.limits_reached
    if parsed is not None and any(f.findings_truncated for f in parsed.files):
        limits.append(
            LimitReached(limit="max_findings_per_file", value=settings.max_findings_per_file)
        )

    warnings: list[str] = []
    if parsed is not None and not parsed.files and error is None:
        warnings.append(NO_FILES_WARNING)
    if graph is not None:
        warnings.append(PARTIAL_GRAPH_WARNING)
        warnings += [f"Graph: {d}" for d in graph.diagnostics]
    if graph is None:
        warnings.append(FINDINGS_NOT_COMPUTED_WARNING)
    elif parsed is not None:
        unparsed = len(parsed.skipped) + len(parsed.failed_files)
        if unparsed:
            warnings.append(
                f"Rules did not run on {unparsed} file(s) that could not be parsed; "
                "findings may be incomplete."
            )
        warnings += [
            f"Rules: {f.path}: {error_text}" for f in parsed.files for error_text in f.rule_errors
        ]

    unique_limits: dict[str, LimitReached] = {}
    for limit in limits:
        unique_limits.setdefault(limit.limit, limit)
    return AnalysisDiagnostics(
        parse_errors=parse_errors[:cap],
        skipped_files=skipped[:cap],
        skipped_by_reason=dict(_skipped_by_reason(ingested, parsed)),
        limits_reached=list(unique_limits.values()),
        warnings=warnings[:cap],
        truncated=(
            scan.sample_truncated
            or parse_truncated
            or len(skipped) > cap
            or len(parse_errors) > cap
            or len(warnings) > cap
        ),
    )


def get_analysis(store: AnalysisStore, analysis_id: str) -> StoredAnalysis:
    analysis = store.get(analysis_id) if is_valid_analysis_id(analysis_id) else None
    if analysis is None:
        raise NotFoundError(
            f"No analysis exists with id {analysis_id[:64]}; it may have expired from "
            "the in-memory store",
            code="analysis_not_found",
        )
    return analysis


def _require_graph(analysis: StoredAnalysis) -> CallGraph:
    if analysis.graph is None:
        reason = analysis.summary.error.code if analysis.summary.error else "unknown"
        raise ConflictError(
            f"Analysis {analysis.analysis_id} failed ({reason}) and has no call graph",
            code="analysis_failed",
        )
    return analysis.graph


def graph_response(
    analysis: StoredAnalysis,
    *,
    path_prefix: str | None,
    max_nodes: int,
    max_unresolved: int,
) -> GraphResponse:
    """The stored graph, optionally limited to a subtree and a node budget.

    Nodes keep their stored order; edges are kept only when both endpoints are
    included, so the response is always a self-consistent graph.
    """
    graph = _require_graph(analysis)
    nodes = [n for n in graph.nodes.values() if _under(n.path, path_prefix)]
    cut = len(nodes) > max_nodes
    nodes = nodes[:max_nodes]
    included = {n.id for n in nodes}
    edges = [e for e in graph.edges if e.source in included and e.target in included]
    unresolved = [u for u in graph.unresolved if u.caller_id in included]

    limitations = list(graph.limitations)
    if path_prefix is not None:
        limitations.append(f"Filtered to '{path_prefix}'; edges leaving it are omitted.")
    if cut:
        limitations.append(f"Limited to the first {max_nodes} functions; edges beyond are omitted.")
    return GraphResponse(
        analysis_id=analysis.analysis_id,
        nodes=nodes,
        edges=edges,
        unresolved_calls=unresolved[:max_unresolved],
        unresolved_calls_total=len(unresolved),
        truncated=graph.truncated or cut,
        limitations=limitations,
    )


def paths_response(
    analysis: StoredAnalysis,
    *,
    source: str,
    target: str,
    max_depth: int,
    max_paths: int,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
) -> PathsResponse:
    graph = _require_graph(analysis)
    for role, function_id in (("source", source), ("target", target)):
        if function_id not in graph.nodes:
            raise NotFoundError(
                f"No function {function_id} in this analysis ({role})", code="function_not_found"
            )

    result = find_paths(
        graph.successors,
        graph.predecessors,
        source,
        target,
        max_depth=max_depth,
        max_paths=max_paths,
        max_expansions=max_expansions,
    )
    limitations = [PATH_LIMITATION]
    hidden = _unresolved_near(graph, source, max_depth)
    if hidden:
        limitations.append(
            f"{hidden} unresolved call(s) occur in functions reachable from the source within "
            f"{max_depth} calls; additional paths may exist through them."
        )
    if result.budget_exhausted:
        limitations.append("Search stopped at the exploration limit; more paths may exist.")
    if graph.truncated:
        limitations.append("The stored graph was truncated; paths may be missing.")
    return PathsResponse(
        analysis_id=analysis.analysis_id,
        source=source,
        target=target,
        max_depth=max_depth,
        max_paths=max_paths,
        paths=[
            CallPath(node_ids=list(p.node_ids), edge_ids=list(p.edge_ids)) for p in result.paths
        ],
        truncated=result.truncated,
        limitations=limitations,
    )


MAX_SOURCE_LINES = 500


def source_response(
    analysis: StoredAnalysis, *, path: str, start_line: int, end_line: int | None
) -> SourceResponse:
    """Lines ``start_line..end_line`` (inclusive) of an analyzed file, redacted.

    At most ``MAX_SOURCE_LINES`` are returned; ``truncated`` says the requested
    range (or, without ``end_line``, the rest of the file) was cut.
    """
    _require_graph(analysis)
    source = analysis.sources.get(path)
    if source is None:
        raise NotFoundError(
            f"'{path}' is not an analyzed file in this analysis", code="file_not_found"
        )
    text, _ = apply_redactions(source.text, list(source.redactions))
    lines = split_lines(text)
    total = len(lines)
    if total == 0:
        if start_line != 1 or (end_line is not None and end_line != 1):
            raise InvalidRequestError("The file is empty", code="invalid_line_range")
        return SourceResponse(
            analysis_id=analysis.analysis_id,
            path=path,
            language=source.language,
            start_line=1,
            end_line=0,
            total_lines=0,
            content="",
        )
    requested_end = total if end_line is None else end_line
    if start_line > total or requested_end < start_line:
        raise InvalidRequestError(
            f"Invalid line range {start_line}-{requested_end} for a file of {total} lines",
            code="invalid_line_range",
        )
    wanted_end = min(requested_end, total)
    last = min(wanted_end, start_line + MAX_SOURCE_LINES - 1)
    selected = lines[start_line - 1 : last]
    ends_with_newline = last < total or source.text.endswith("\n")
    content = "\n".join(selected) + ("\n" if ends_with_newline else "")
    return SourceResponse(
        analysis_id=analysis.analysis_id,
        path=path,
        language=source.language,
        start_line=start_line,
        end_line=last,
        total_lines=total,
        content=content,
        truncated=last < wanted_end,
        redacted_values=_redactions_in(source, start_line, last),
    )


def _redactions_in(source: StoredSource, start_line: int, end_line: int) -> int:
    if not source.redactions:
        return 0
    starts = [0]
    for index, char in enumerate(source.text):
        if char == "\n":
            starts.append(index + 1)
    return sum(
        1
        for span_start, _ in source.redactions
        if start_line <= bisect_right(starts, span_start) <= end_line
    )


DEFAULT_FINDINGS_LIMIT = 500
MAX_FINDINGS_LIMIT = 1_000


def findings_response(
    analysis: StoredAnalysis,
    *,
    severity: Severity | None = None,
    rule_id: str | None = None,
    path_prefix: str | None = None,
    limit: int = DEFAULT_FINDINGS_LIMIT,
) -> FindingsResponse:
    """Findings in stored (deterministic) order, filtered, then limited."""
    _require_graph(analysis)
    matching = [
        f
        for f in analysis.findings
        if (severity is None or f.severity is severity)
        and (rule_id is None or f.rule_id == rule_id)
        and _under(f.location.path, path_prefix)
    ]
    return FindingsResponse(
        analysis_id=analysis.analysis_id,
        findings=matching[:limit],
        total=len(matching),
        truncated=len(matching) > limit,
    )


def _unresolved_near(graph: CallGraph, source: str, max_depth: int) -> int:
    reachable = reachable_within(graph.successors, source, max_depth)
    return sum(graph.unresolved_by_caller.get(node, 0) for node in reachable)


def _under(path: str, prefix: str | None) -> bool:
    return prefix is None or path == prefix or path.startswith(prefix + "/")
