"""Request/response envelopes that are not domain objects."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from app.models.common import ContractModel, Language, LineNumber, RepoPath


def _validate_git_ref(value: str) -> str:
    # A leading '-' is rejected so a ref can never be parsed as a git option.
    if value.startswith("-"):
        raise ValueError("ref must not start with '-'")
    if ".." in value or value.endswith((".lock", "/")) or "//" in value:
        raise ValueError("ref is not a valid branch or tag name")
    return value


GitRef = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9._/-]{1,255}$", examples=["main"]),
    AfterValidator(_validate_git_ref),
]


class AnalyzeRequest(ContractModel):
    repo_url: str = Field(
        min_length=1, max_length=512, examples=["https://github.com/expressjs/express"]
    )
    ref: GitRef | None = Field(default=None, description="Branch or tag; default branch if null")


class SourceResponse(ContractModel):
    analysis_id: str
    path: RepoPath
    language: Language
    start_line: LineNumber
    # Inclusive. 0 only for an empty file (start_line 1, total_lines 0, content "").
    end_line: int = Field(ge=0)
    total_lines: int = Field(ge=0)
    content: str = Field(description="Untrusted repository text; render as plain text")
    truncated: bool = False
    # Credential-like values in the returned lines replaced by "[REDACTED len=N]".
    redacted_values: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.total_lines == 0:
            if (self.start_line, self.end_line, self.content) != (1, 0, ""):
                raise ValueError("an empty file has start_line 1, end_line 0 and no content")
        elif not self.start_line <= self.end_line <= self.total_lines:
            raise ValueError("require start_line <= end_line <= total_lines")
        return self


class HealthResponse(ContractModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class ErrorDetail(ContractModel):
    loc: list[str | int] | None = None
    message: str
    type: str | None = None


class ErrorBody(ContractModel):
    code: str = Field(examples=["analysis_not_found"])
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(ContractModel):
    """Every non-2xx response uses this envelope."""

    error: ErrorBody
