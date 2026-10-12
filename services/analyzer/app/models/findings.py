"""Rule-engine finding contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.models.common import ContractModel, SourceReference
from app.models.graph import NodeId

FindingId = Annotated[str, Field(pattern=r"^fd_[0-9a-f]{16}$", examples=["fd_9c8b7a6f5e4d3c2b"])]
MAX_EVIDENCE_LENGTH = 500


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReviewStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class Finding(ContractModel):
    """A potential issue for human review. Not proof of exploitability."""

    id: FindingId
    rule_id: str = Field(pattern=r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$", examples=["js.sql-injection"])
    title: str = Field(max_length=200)
    description: str = Field(max_length=2000)
    severity: Severity
    confidence: Confidence
    location: SourceReference
    function_id: NodeId | None = Field(default=None, description="Enclosing function node, if any")
    evidence: str = Field(
        max_length=MAX_EVIDENCE_LENGTH,
        description="Short snippet with secret-like values redacted",
    )
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW
    next_step: str = Field(max_length=1000)
    limitations: list[str] = Field(default_factory=list)
    cwe_id: str | None = Field(default=None, pattern=r"^CWE-\d+$")


class FindingsResponse(ContractModel):
    analysis_id: str
    findings: list[Finding]
    total: int = Field(ge=0)
    truncated: bool = False
