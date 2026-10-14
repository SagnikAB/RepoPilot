"""Opt-in gate for tests that deliberately crash a native process.

These tests make the operating system record a crash (on macOS, the "Python
quit unexpectedly" dialog), so they never run by default. Run them with:

    REPOPILOT_RUN_NATIVE_CRASH_CANARY=1 .venv/bin/pytest -m native_crash
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TypeVar, cast

import pytest

ENV_VAR = "REPOPILOT_RUN_NATIVE_CRASH_CANARY"
ENABLED = os.environ.get(ENV_VAR) == "1"

F = TypeVar("F", bound=Callable[..., object])


def native_crash_canary(test: F) -> F:
    """Mark a test as crash-inducing and skip it unless explicitly enabled."""
    skipped = pytest.mark.skipif(
        not ENABLED,
        reason=f"deliberately crashes a native process; opt in with {ENV_VAR}=1",
    )(test)
    return cast(F, pytest.mark.native_crash(skipped))  # MarkDecorator is typed as Any
