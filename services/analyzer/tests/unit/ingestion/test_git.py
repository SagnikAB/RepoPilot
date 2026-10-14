"""Clone hardening. Integration tests use local repositories, never the network."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.ingestion.errors import RefNotFoundError, RepositoryUnavailableError
from app.ingestion.git import (
    GitCloner,
    ProcessSizeLimitError,
    ProcessTimeoutError,
    build_clone_command,
    build_git_env,
    run_bounded,
)
from tests.helpers import make_settings

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


# -- command and environment ---------------------------------------------------


def test_clone_command_is_hardened() -> None:
    command = build_clone_command("git", "https://github.com/a/b.git", Path("/w/repo"), "main")
    joined = " ".join(command)

    for flag in (
        "protocol.allow=never",
        "protocol.https.allow=always",
        "http.followRedirects=false",
        "core.hooksPath=/dev/null",
        "core.symlinks=false",
        "credential.helper=",
        "--depth=1",
        "--single-branch",
        "--no-tags",
        "--no-recurse-submodules",
        "--template=",
        "--branch=main",
    ):
        assert flag in joined
    # The URL is passed after "--" so it can never be read as an option.
    assert command[-3:] == ["--", "https://github.com/a/b.git", "/w/repo"]


def test_clone_command_without_ref_uses_default_branch() -> None:
    command = build_clone_command("git", "https://github.com/a/b.git", Path("/w/repo"), None)

    assert not any(arg.startswith("--branch") for arg in command)


def test_clone_command_rejects_option_like_ref() -> None:
    with pytest.raises(ValueError):
        build_clone_command("git", "https://github.com/a/b.git", Path("/w/repo"), "-u evil")


def test_git_env_is_isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("GIT_DIR", "/somewhere/else")

    env = build_git_env(home=tmp_path)

    assert "GITHUB_TOKEN" not in env
    assert "GIT_DIR" not in env
    assert env["HOME"] == str(tmp_path)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_LFS_SKIP_SMUDGE"] == "1"


# -- bounded subprocess -----------------------------------------------------------


def test_run_bounded_captures_exit_code_and_stderr(tmp_path: Path) -> None:
    outcome = run_bounded(
        [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(7)"],
        env={},
        cwd=tmp_path,
        timeout_seconds=30,
        stderr_path=tmp_path / "stderr.log",
    )

    assert outcome.returncode == 7
    assert outcome.stderr_tail == "boom"


def test_run_bounded_kills_on_timeout(tmp_path: Path) -> None:
    started = time.monotonic()
    with pytest.raises(ProcessTimeoutError):
        run_bounded(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            env={},
            cwd=tmp_path,
            timeout_seconds=0.5,
            stderr_path=tmp_path / "stderr.log",
        )
    assert time.monotonic() - started < 10


def test_run_bounded_kills_when_directory_grows_too_large(tmp_path: Path) -> None:
    watched = tmp_path / "out"
    script = (
        "import os, sys, time\n"
        "d = sys.argv[1]; os.makedirs(d, exist_ok=True)\n"
        "for i in range(400):\n"
        "    open(os.path.join(d, str(i)), 'wb').write(b'x' * 262144)\n"
        "    time.sleep(0.02)\n"
    )
    with pytest.raises(ProcessSizeLimitError):
        run_bounded(
            [sys.executable, "-c", script, str(watched)],
            env={},
            cwd=tmp_path,
            timeout_seconds=30,
            stderr_path=tmp_path / "stderr.log",
            watch_dir=watched,
            max_bytes=1024 * 1024,
        )


# -- real git against local repositories -------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "init.defaultBranch=main",
            "-c",
            "protocol.file.allow=always",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(cwd),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
    )
    return completed.stdout.strip()


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A local repository with two commits on main and a feature branch."""
    repo = tmp_path / "origin"
    repo.mkdir()
    _git(repo, "init")
    (repo / "index.js").write_text("function first() {}\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "first")
    (repo / "index.js").write_text("function second() {}\n")
    _git(repo, "commit", "-am", "second")
    _git(repo, "checkout", "-b", "feature")
    (repo / "feature.js").write_text("function feature() {}\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feature")
    _git(repo, "checkout", "main")
    return repo


def _clone(origin: Path, tmp_path: Path, ref: str | None, protocol: str = "file") -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    dest = workspace / "repo"
    result = GitCloner(make_settings(), protocol=protocol).clone(f"file://{origin}", dest, ref)
    assert result.commit_sha == _git(origin, "rev-parse", ref or "main")
    return dest


@requires_git
def test_clone_is_shallow_and_reports_commit(origin: Path, tmp_path: Path) -> None:
    dest = _clone(origin, tmp_path, None)

    assert (dest / "index.js").read_text() == "function second() {}\n"
    assert not (dest / "feature.js").exists()
    assert _git(dest, "rev-list", "--count", "HEAD") == "1"


@requires_git
def test_clone_checks_out_requested_branch(origin: Path, tmp_path: Path) -> None:
    dest = _clone(origin, tmp_path, "feature")

    assert (dest / "feature.js").exists()


@requires_git
def test_unknown_ref_raises_ref_not_found(origin: Path, tmp_path: Path) -> None:
    with pytest.raises(RefNotFoundError) as info:
        _clone(origin, tmp_path, "does-not-exist")

    assert info.value.status_code == 404


@requires_git
def test_missing_repository_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(RepositoryUnavailableError):
        _clone(tmp_path / "missing", tmp_path, None)


@requires_git
def test_non_https_transport_is_refused_by_default(origin: Path, tmp_path: Path) -> None:
    # The production cloner only allows https; a file:// URL must be refused by git.
    with pytest.raises(RepositoryUnavailableError):
        _clone(origin, tmp_path, None, protocol="https")


@requires_git
def test_submodules_are_not_fetched(origin: Path, tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    _git(sub, "init")
    (sub / "lib.js").write_text("function lib() {}\n")
    _git(sub, "add", ".")
    _git(sub, "commit", "-m", "lib")
    _git(origin, "submodule", "add", f"file://{sub}", "vendored")
    _git(origin, "commit", "-m", "add submodule")

    dest = _clone(origin, tmp_path, None)

    assert (dest / ".gitmodules").exists()
    assert not (dest / "vendored" / "lib.js").exists()
