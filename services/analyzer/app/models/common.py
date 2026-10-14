"""Primitives shared by every RepoPilot data contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

MAX_REPO_PATH_LENGTH = 1024


class ContractModel(BaseModel):
    """Base for all API contracts: immutable and strict about unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def validate_repo_relative_path(value: str) -> str:
    """Accept only normalized, POSIX-style, repository-relative paths."""
    if not value:
        raise ValueError("path must not be empty")
    if "\\" in value or "\x00" in value:
        raise ValueError("path must use '/' separators and contain no NUL bytes")
    if value.startswith("/"):
        raise ValueError("path must be relative to the repository root")
    segments = value.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise ValueError("path must be normalized (no empty, '.' or '..' segments)")
    return value


RepoPath = Annotated[
    str,
    Field(max_length=MAX_REPO_PATH_LENGTH, examples=["src/server.ts"]),
    AfterValidator(validate_repo_relative_path),
]
LineNumber = Annotated[int, Field(ge=1, description="1-based line number")]
ColumnNumber = Annotated[int, Field(ge=1, description="1-based column, in characters")]


class Language(StrEnum):
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"


class SourceReference(ContractModel):
    """An inclusive line range inside one analyzed file."""

    path: RepoPath
    start_line: LineNumber
    end_line: LineNumber

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self
