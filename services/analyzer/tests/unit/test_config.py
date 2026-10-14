from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.cors_allowed_origins == ["http://localhost:3000"]


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOPILOT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("REPOPILOT_CORS_ALLOWED_ORIGINS", '["https://repopilot.example"]')

    settings = Settings(_env_file=None)

    assert settings.log_level == "DEBUG"
    assert settings.cors_allowed_origins == ["https://repopilot.example"]


def test_invalid_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOPILOT_LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
