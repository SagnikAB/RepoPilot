"""Function-call graph contracts: nodes, edges, unresolved calls and paths."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from app.models.common import ColumnNumber, ContractModel, Language, LineNumber, RepoPath

NodeId = Annotated[str, Field(pattern=r"^fn_[0-9a-f]{16}$", examples=["fn_3f9a1c2b7d4e5f60"])]
EdgeId = Annotated[str, Field(pattern=r"^ce_[0-9a-f]{16}$", examples=["ce_0b1c2d3e4f5a6b7c"])]


class FunctionKind(StrEnum):
    MODULE = "module"  # synthetic node for a file's top-level code
    FUNCTION_DECLARATION = "function_declaration"
    FUNCTION_EXPRESSION = "function_expression"
    ARROW_FUNCTION = "arrow_function"
    METHOD = "method"
    CONSTRUCTOR = "constructor"


class ResolutionMethod(StrEnum):
    SAME_FILE = "same_file"  # callee declared in the caller's file and lexically visible
    IMPORT = "import"  # callee reached through a relative import/require and export
    THIS_METHOD = "this_method"  # this.method() inside the same class body
    # Added in Phase 6 (additive):
    CONSTRUCTOR = "constructor"  # new X() invoking X's explicit constructor
    INSTANCE_METHOD = "instance_method"  # const x = new X(); x.method()


class UnresolvedReason(StrEnum):
    UNKNOWN_SYMBOL = "unknown_symbol"  # name not declared in any enclosing scope (e.g. globals)
    AMBIGUOUS_SYMBOL = "ambiguous_symbol"  # several candidate declarations or modules
    MEMBER_CALL = "member_call"  # receiver's value or type is not statically known
    DYNAMIC_CALL = "dynamic_call"  # computed callee, or a variable/parameter holding a function
    EXTERNAL_MODULE = "external_module"  # callee comes from a package outside the repository
    UNSUPPORTED_SYNTAX = "unsupported_syntax"
    # Added in Phase 6 (additive):
    UNRESOLVED_IMPORT = "unresolved_import"  # relative import not matched to an analyzed export


class FunctionNode(ContractModel):
    id: NodeId
    name: str = Field(max_length=256, description="Short name; '<anonymous>' if none")
    qualified_name: str = Field(max_length=1024, examples=["UserService.login"])
    kind: FunctionKind
    language: Language
    path: RepoPath
    start_line: LineNumber
    end_line: LineNumber
    start_column: ColumnNumber
    is_anonymous: bool = False
    is_exported: bool = False

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class CallSite(ContractModel):
    line: LineNumber
    column: ColumnNumber


class CallEdge(ContractModel):
    """A resolved call relationship. One edge per (source, target) pair."""

    id: EdgeId
    source: NodeId
    target: NodeId
    resolution: ResolutionMethod
    call_sites: list[CallSite] = Field(min_length=1, description="Sorted by line, column")


class UnresolvedCall(ContractModel):
    caller_id: NodeId
    path: RepoPath
    callee: str = Field(max_length=200, description="Truncated callee expression text")
    call_site: CallSite
    reason: UnresolvedReason


class GraphResponse(ContractModel):
    analysis_id: str
    nodes: list[FunctionNode]
    edges: list[CallEdge]
    unresolved_calls: list[UnresolvedCall]
    unresolved_calls_total: int = Field(ge=0)
    truncated: bool = False
    limitations: list[str] = Field(default_factory=list)


class CallPath(ContractModel):
    node_ids: list[NodeId] = Field(min_length=1)
    edge_ids: list[EdgeId]

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if len(self.edge_ids) != len(self.node_ids) - 1:
            raise ValueError("a path with N nodes must have N-1 edges")
        return self


class PathsResponse(ContractModel):
    analysis_id: str
    source: NodeId
    target: NodeId
    max_depth: int = Field(ge=1)
    max_paths: int = Field(ge=1)
    paths: list[CallPath]
    truncated: bool = False
    limitations: list[str] = Field(default_factory=list)
