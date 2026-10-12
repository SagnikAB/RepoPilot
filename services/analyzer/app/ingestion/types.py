"""In-process results of ingestion. Not API contracts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.models.analysis import LimitReached, RepositoryInfo, SkippedFile, SkipReason
from app.parsers.languages import Grammar


@dataclass(frozen=True, slots=True)
class SourceFile:
    """A file accepted for analysis, held in memory after the clone is deleted."""

    path: str  # validated repository-relative POSIX path
    grammar: Grammar
    text: str  # decoded UTF-8 (BOM stripped); used for parsing and source retrieval
    size_bytes: int


@dataclass(slots=True)
class ScanReport:
    files_discovered: int = 0
    skipped_sample: list[SkippedFile] = field(default_factory=list)
    skipped_by_reason: Counter[SkipReason] = field(default_factory=Counter)
    limits_reached: list[LimitReached] = field(default_factory=list)
    sample_truncated: bool = False

    @property
    def files_skipped(self) -> int:
        return sum(self.skipped_by_reason.values())

    def skip(self, path: str, reason: SkipReason, sample_limit: int) -> None:
        self.skipped_by_reason[reason] += 1
        if len(self.skipped_sample) >= sample_limit:
            self.sample_truncated = True
            return
        try:
            self.skipped_sample.append(SkippedFile(path=path, reason=reason))
        except ValueError:
            # Unrepresentable path (e.g. backslashes, too long): count it only.
            self.sample_truncated = True

    def reach_limit(self, limit: str, value: int) -> None:
        if all(item.limit != limit for item in self.limits_reached):
            self.limits_reached.append(LimitReached(limit=limit, value=value))


@dataclass(frozen=True, slots=True)
class IngestedRepository:
    repository: RepositoryInfo
    files: list[SourceFile]
    scan: ScanReport
