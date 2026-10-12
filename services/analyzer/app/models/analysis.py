"""Analysis lifecycle, summary and diagnostics contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.models.common import ContractModel, Language, LineNumber, RepoPath
from app.models.findings import Severity


class AnalysisStatus(StrEnum):
    """Lifecycle states.

    The MVP analyzes synchronously, so the API currently only returns
    ``completed`` or ``failed``. ``queued`` and ``running`` are reserved for a
    future asynchronous mode; clients should already handle them.
    """

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SkipReason(StrEnum):
    EXCLUDED_DIRECTORY = "excluded_directory"
    EXCLUDED_PATTERN = "excluded_pattern"
    SENSITIVE_FILE = "sensitive_file"
    UNSUPPORTED_EXTENSION = "unsupported_extension"
    TOO_LARGE = "too_large"
    BINARY = "binary"
    SYMLINK = "symlink"
    LIMIT_REACHED = "limit_reached"
    PARSE_FAILED = "parse_failed"  # parser crashed, timed out or raised; see parse_errors


class ParseDiagnostic(ContractModel):
    path: RepoPath
    line: LineNumber | None = None
    message: str = Field(max_length=500)


class SkippedFile(ContractModel):
    path: RepoPath
    reason: SkipReason


class LimitReached(ContractModel):
    limit: str = Field(examples=["max_files"])
    value: int


class AnalysisDiagnostics(ContractModel):
    """What the analysis could not do. Lists are capped; see ``truncated``."""

    parse_errors: list[ParseDiagnostic] = Field(default_factory=list)
    skipped_files: list[SkippedFile] = Field(
        default_factory=list, description="Bounded sample of skipped files"
    )
    skipped_by_reason: dict[SkipReason, int] = Field(default_factory=dict)
    limits_reached: list[LimitReached] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    truncated: bool = False


class RepositoryInfo(ContractModel):
    url: str
    host: str
    owner: str
    name: str
    ref: str | None = None
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class AnalysisStats(ContractModel):
    files_discovered: int = Field(ge=0)
    files_analyzed: int = Field(ge=0)
    files_skipped: int = Field(ge=0)
    functions: int = Field(ge=0)
    call_edges: int = Field(ge=0)
    unresolved_calls: int = Field(ge=0)
    # null until the rule engine exists: "not computed", which is not "no findings".
    findings: int | None = Field(default=None, ge=0)
    findings_by_severity: dict[Severity, int] = Field(default_factory=dict)
    files_by_language: dict[Language, int] = Field(default_factory=dict)


class AnalysisError(ContractModel):
    code: str
    message: str


class AnalysisSummary(ContractModel):
    analysis_id: str
    status: AnalysisStatus
    repository: RepositoryInfo
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    stats: AnalysisStats | None = None
    diagnostics: AnalysisDiagnostics = Field(default_factory=AnalysisDiagnostics)
    error: AnalysisError | None = None
