"""Hardened, bounded ``git clone``.

Guarantees:

* git runs with an isolated, minimal environment: no user/system git config,
  no credential helpers, no terminal prompts, no inherited secrets.
* Only the https transport is allowed (or ``file`` when explicitly configured
  for tests). Redirects, submodules, hooks, symlinks and LFS downloads are off.
* The clone is shallow, single-branch and tag-free.
* The process group is killed on timeout or when the workspace exceeds the
  configured size, and nothing from the repository is ever executed.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.ingestion.errors import (
    CloneTimeoutError,
    GitUnavailableError,
    RefNotFoundError,
    RepositoryTooLargeError,
    RepositoryUnavailableError,
)

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 0.1
_SIZE_CHECK_INTERVAL_SECONDS = 0.5
_STDERR_TAIL_BYTES = 4096
_REV_PARSE_TIMEOUT_SECONDS = 15
_SHA1_RE = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True, slots=True)
class CloneResult:
    commit_sha: str | None


class Cloner(Protocol):
    def clone(self, url: str, dest: Path, ref: str | None) -> CloneResult: ...


_SAFE_CONFIG_ARGS: tuple[str, ...] = tuple(
    arg
    for setting in (
        "protocol.allow=never",
        "http.followRedirects=false",
        "core.hooksPath=/dev/null",
        "core.symlinks=false",
        "core.fsmonitor=false",
        "credential.helper=",
        "submodule.recurse=false",
        "filter.lfs.smudge=",
        "filter.lfs.process=",
        "filter.lfs.required=false",
        "advice.detachedHead=false",
    )
    for arg in ("-c", setting)
)


def build_clone_command(
    git: str, url: str, dest: Path, ref: str | None, *, protocol: str = "https"
) -> list[str]:
    command = [
        git,
        *_SAFE_CONFIG_ARGS,
        "-c",
        f"protocol.{protocol}.allow=always",
        "clone",
        "--quiet",
        "--depth=1",
        "--single-branch",
        "--no-tags",
        "--no-recurse-submodules",
        "--template=",
    ]
    if ref is not None:
        if ref.startswith("-"):
            raise ValueError("ref must not start with '-'")
        command.append(f"--branch={ref}")
    command += ["--", url, str(dest)]
    return command


def build_git_env(home: Path) -> dict[str, str]:
    """A minimal environment: nothing from the server's environment leaks in."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_PROTOCOL_FROM_USER": "0",
    }


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    returncode: int
    stderr_tail: str


class ProcessTimeoutError(Exception):
    pass


class ProcessSizeLimitError(Exception):
    pass


def directory_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue  # file vanished mid-walk (e.g. git temp files)
    return total


def run_bounded(
    command: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    timeout_seconds: float,
    stderr_path: Path,
    watch_dir: Path | None = None,
    max_bytes: int | None = None,
) -> ProcessOutcome:
    """Run a command with a wall-clock timeout and an optional on-disk size cap.

    stderr goes to a file (not a pipe) so a chatty process can never block on a
    full pipe buffer. The whole process group is killed on any limit breach.
    """
    with stderr_path.open("wb") as stderr_file:
        process = subprocess.Popen(  # noqa: S603 - argv list, no shell, validated inputs
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout_seconds
        next_size_check = time.monotonic() + _SIZE_CHECK_INTERVAL_SECONDS
        try:
            while True:
                try:
                    returncode = process.wait(timeout=_POLL_INTERVAL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = time.monotonic()
                if now >= deadline:
                    raise ProcessTimeoutError
                if watch_dir is not None and max_bytes is not None and now >= next_size_check:
                    next_size_check = now + _SIZE_CHECK_INTERVAL_SECONDS
                    if watch_dir.exists() and directory_size(watch_dir) > max_bytes:
                        raise ProcessSizeLimitError
        except BaseException:
            _kill_process_group(process)
            raise

    with stderr_path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - _STDERR_TAIL_BYTES))
        tail = handle.read().decode("utf-8", errors="replace")
    return ProcessOutcome(returncode=returncode, stderr_tail=tail)


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


class GitCloner:
    """Clones with the hardened command. ``protocol`` exists for local tests only."""

    def __init__(self, settings: Settings, *, protocol: str = "https") -> None:
        self._settings = settings
        self._protocol = protocol

    def clone(self, url: str, dest: Path, ref: str | None) -> CloneResult:
        workspace = dest.parent
        env = build_git_env(home=workspace)
        command = build_clone_command(
            self._settings.git_executable, url, dest, ref, protocol=self._protocol
        )
        try:
            outcome = run_bounded(
                command,
                env=env,
                cwd=workspace,
                timeout_seconds=self._settings.clone_timeout_seconds,
                stderr_path=workspace / "git-stderr.log",
                watch_dir=dest,
                max_bytes=self._settings.max_clone_bytes,
            )
        except FileNotFoundError as exc:
            raise GitUnavailableError("git is not available on the server") from exc
        except ProcessTimeoutError as exc:
            raise CloneTimeoutError(
                f"Cloning exceeded {self._settings.clone_timeout_seconds:g}s"
            ) from exc
        except ProcessSizeLimitError as exc:
            raise RepositoryTooLargeError(
                f"Repository exceeds the {self._settings.max_clone_bytes} byte clone limit"
            ) from exc

        if outcome.returncode != 0:
            raise _classify_clone_failure(outcome, ref)
        return CloneResult(commit_sha=self._head_commit(dest, env))

    def _head_commit(self, repo: Path, env: dict[str, str]) -> str | None:
        command = [self._settings.git_executable, *_SAFE_CONFIG_ARGS, "rev-parse", "HEAD"]
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                command,
                cwd=repo,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=_REV_PARSE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        sha = completed.stdout.decode("ascii", errors="replace").strip()
        return sha if completed.returncode == 0 and _SHA1_RE.fullmatch(sha) else None


def _classify_clone_failure(outcome: ProcessOutcome, ref: str | None) -> Exception:
    stderr = outcome.stderr_tail
    last_line = stderr.strip().splitlines()[-1][:200] if stderr.strip() else ""
    logger.warning("git clone failed (exit %d): %s", outcome.returncode, last_line)
    if ref is not None and "Remote branch" in stderr and "not found" in stderr:
        return RefNotFoundError(f"Branch or tag '{ref}' was not found in the repository")
    if "Could not resolve host" in stderr or "Failed to connect" in stderr:
        return RepositoryUnavailableError("The repository host could not be reached")
    return RepositoryUnavailableError(
        "The repository could not be cloned. Check that it exists and is public."
    )
