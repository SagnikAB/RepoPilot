"""Centralized configuration, loaded from REPOPILOT_* environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_MB = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REPOPILOT_", env_file=".env", extra="ignore", frozen=True
    )

    service_name: str = "repopilot-analyzer"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Ingestion -----------------------------------------------------------
    # Hosts accepted in repository URLs. Only https://<host>/<owner>/<repo> is supported.
    allowed_git_hosts: list[str] = Field(default_factory=lambda: ["github.com"], min_length=1)
    git_executable: str = "git"
    # Parent directory for temporary clone workspaces; the system temp dir if unset.
    workspace_root: Path | None = None
    clone_timeout_seconds: float = Field(default=60, gt=0, le=600)
    # Clone is aborted once the workspace on disk (including .git) exceeds this.
    max_clone_bytes: int = Field(default=250 * _MB, gt=0)

    # --- File filtering ------------------------------------------------------
    max_files_scanned: int = Field(default=50_000, gt=0)
    max_source_files: int = Field(default=5_000, gt=0)
    max_file_bytes: int = Field(default=1 * _MB, gt=0)
    max_total_source_bytes: int = Field(default=50 * _MB, gt=0)

    # --- Parsing -------------------------------------------------------------
    # "subprocess" runs Tree-sitter in a worker process so a native crash or a
    # hang cannot take down the API. "inprocess" is for tests and debugging.
    parse_isolation: Literal["subprocess", "inprocess"] = "subprocess"
    parse_time_budget_seconds: float = Field(default=120, gt=0)
    # Enforced only in subprocess mode (Tree-sitter 0.26 has no parse timeout).
    parse_file_timeout_seconds: float = Field(default=15, gt=0)
    # Structural-complexity cap: files whose syntax tree is larger are skipped.
    max_syntax_nodes_per_file: int = Field(default=1_000_000, gt=0)
    max_parse_errors_per_file: int = Field(default=5, ge=1)

    # --- Rules ---------------------------------------------------------------
    max_findings_per_file: int = Field(default=100, ge=1)

    # --- Call graph ----------------------------------------------------------
    # Hard caps on the stored graph; beyond them it is truncated deterministically.
    max_graph_nodes: int = Field(default=100_000, gt=0)
    max_graph_edges: int = Field(default=500_000, gt=0)

    # --- Analysis ------------------------------------------------------------
    # POST /api/analyze is synchronous; further concurrent requests get 429.
    max_concurrent_analyses: int = Field(default=2, gt=0)

    # --- Storage -------------------------------------------------------------
    # In-memory analyses kept at once; the least recently used is evicted.
    max_stored_analyses: int = Field(default=20, gt=0)
    # Total retained source text across stored analyses; least recently used
    # analyses are evicted beyond it (the newest is always kept).
    max_stored_source_bytes: int = Field(default=256 * _MB, gt=0)

    # --- Diagnostics ---------------------------------------------------------
    # Cap on sampled items per diagnostics list (skipped files, parse errors).
    max_diagnostic_items: int = Field(default=200, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
