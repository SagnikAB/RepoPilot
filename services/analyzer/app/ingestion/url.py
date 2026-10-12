"""Strict validation of user-supplied repository URLs.

Only ``https://<allowed-host>/<owner>/<repo>[.git][/]`` is accepted. Anything
else is rejected rather than normalized, so the URL handed to git is always one
we constructed ourselves from validated parts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.ingestion.errors import InvalidRepositoryUrlError

MAX_URL_LENGTH = 512

# GitHub rules: owners are alphanumeric with single inner hyphens (max 39);
# repository names use [A-Za-z0-9._-] (max 100).
_OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
_REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
# Percent-encoding, backslashes, whitespace, control and non-ASCII characters.
_FORBIDDEN_CHARS = re.compile(r"[%\\]|[^\x21-\x7e]")


@dataclass(frozen=True, slots=True)
class RepositoryUrl:
    host: str
    owner: str
    name: str

    @property
    def canonical_url(self) -> str:
        return f"https://{self.host}/{self.owner}/{self.name}"

    @property
    def clone_url(self) -> str:
        return f"{self.canonical_url}.git"


def parse_repository_url(raw: str, allowed_hosts: list[str]) -> RepositoryUrl:
    if not raw or len(raw) > MAX_URL_LENGTH:
        raise InvalidRepositoryUrlError("Repository URL is empty or too long")
    if _FORBIDDEN_CHARS.search(raw):
        raise InvalidRepositoryUrlError("Repository URL contains unsupported characters")

    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise InvalidRepositoryUrlError("Repository URL is malformed") from exc

    if parts.scheme != "https":
        raise InvalidRepositoryUrlError("Only https:// repository URLs are supported")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise InvalidRepositoryUrlError("Repository URLs must not contain credentials")
    if port is not None or ":" in parts.netloc:
        raise InvalidRepositoryUrlError("Repository URLs must not specify a port")
    if parts.query or parts.fragment or "?" in raw or "#" in raw:
        raise InvalidRepositoryUrlError("Repository URLs must not contain a query or fragment")

    host = parts.netloc.lower()
    allowed = {h.lower() for h in allowed_hosts}
    if host not in allowed:
        raise InvalidRepositoryUrlError(
            f"Host is not supported; allowed hosts: {', '.join(sorted(allowed))}"
        )

    owner, name = _split_path(parts.path)
    return RepositoryUrl(host=host, owner=owner, name=name)


def _split_path(path: str) -> tuple[str, str]:
    segments = path.removesuffix("/").split("/")
    # A leading "/" yields an empty first segment.
    if len(segments) != 3 or segments[0] != "":
        raise InvalidRepositoryUrlError(
            "Repository URL must have the form https://<host>/<owner>/<repository>"
        )
    owner, name = segments[1], segments[2].removesuffix(".git")
    if not _OWNER_RE.fullmatch(owner):
        raise InvalidRepositoryUrlError("Repository owner is not valid")
    if not _REPO_RE.fullmatch(name) or name in {".", ".."} or name.startswith("."):
        raise InvalidRepositoryUrlError("Repository name is not valid")
    return owner, name
