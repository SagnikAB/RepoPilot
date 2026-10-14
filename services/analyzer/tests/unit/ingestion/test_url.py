from __future__ import annotations

import pytest

from app.ingestion.errors import InvalidRepositoryUrlError
from app.ingestion.url import parse_repository_url

ALLOWED = ["github.com"]


@pytest.mark.parametrize(
    ("raw", "owner", "name"),
    [
        ("https://github.com/expressjs/express", "expressjs", "express"),
        ("https://github.com/expressjs/express.git", "expressjs", "express"),
        ("https://github.com/expressjs/express/", "expressjs", "express"),
        ("https://GitHub.com/a-b/c.d_e-f", "a-b", "c.d_e-f"),
    ],
)
def test_accepts_public_github_urls(raw: str, owner: str, name: str) -> None:
    url = parse_repository_url(raw, ALLOWED)

    assert (url.host, url.owner, url.name) == ("github.com", owner, name)
    assert url.canonical_url == f"https://github.com/{owner}/{name}"
    assert url.clone_url == f"https://github.com/{owner}/{name}.git"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "http://github.com/a/b",
        "ssh://git@github.com/a/b",
        "git@github.com:a/b.git",
        "file:///etc/passwd",
        "ext::sh -c touch% /tmp/pwned",
        "https://user:token@github.com/a/b",
        "https://token@github.com/a/b",
        "https://github.com:443/a/b",
        "https://github.com:8080/a/b",
        "https://github.com/a/b?ref=main",
        "https://github.com/a/b#readme",
        "https://gitlab.com/a/b",
        "https://github.com.evil.example/a/b",
        "https://evilgithub.com/a/b",
        "https://169.254.169.254/a/b",
        "https://127.0.0.1/a/b",
        "https://[::1]/a/b",
        "https://github.com/a",
        "https://github.com/a/b/tree/main",
        "https://github.com//b",
        "https://github.com/a/..",
        "https://github.com/a/.hidden",
        "https://github.com/-a/b",
        "https://github.com/a--/b",
        "https://github.com/a/b%2F..%2Fc",
        "https://github.com/a/b c",
        "https://github.com/a\\b/c",
        "https://github.com/a/b\n",
        "https://gíthub.com/a/b",
        "https://github.com/" + "a" * 40 + "/b",
        "https://github.com/a/" + "b" * 101,
        "https://github.com/a/" + "b" * 600,
    ],
)
def test_rejects_unsafe_or_unsupported_urls(raw: str) -> None:
    with pytest.raises(InvalidRepositoryUrlError):
        parse_repository_url(raw, ALLOWED)


def test_allowed_hosts_are_configurable() -> None:
    url = parse_repository_url("https://git.example.org/team/app", ["git.example.org"])

    assert url.host == "git.example.org"
    with pytest.raises(InvalidRepositoryUrlError):
        parse_repository_url("https://github.com/team/app", ["git.example.org"])


def test_error_is_client_safe_400() -> None:
    with pytest.raises(InvalidRepositoryUrlError) as info:
        parse_repository_url("https://user:secret@github.com/a/b", ALLOWED)

    assert info.value.status_code == 400
    assert info.value.code == "invalid_repository_url"
    assert "secret" not in info.value.message
