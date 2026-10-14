"""Pure path-classification rules: which files are analyzed and why others are not."""

from __future__ import annotations

import fnmatch

from app.models.analysis import SkipReason
from app.models.common import MAX_REPO_PATH_LENGTH, validate_repo_relative_path
from app.parsers.languages import Grammar, grammar_for_path

# Directories that are never walked: VCS data, dependencies, build output, caches.
# Every directory whose name starts with "." is also excluded.
EXCLUDED_DIRECTORIES = frozenset(
    {
        "node_modules",
        "bower_components",
        "jspm_packages",
        "vendor",
        "dist",
        "build",
        "out",
        "coverage",
        "target",
        "tmp",
        "temp",
        "__pycache__",
        "venv",
        "storybook-static",
    }
)

# Generated or declaration-only JavaScript/TypeScript.
EXCLUDED_FILE_PATTERNS = (
    "*.min.js",
    "*.min.mjs",
    "*.min.cjs",
    "*-min.js",
    "*.bundle.js",
    "*.chunk.js",
    "*.d.ts",
    "*.d.mts",
    "*.d.cts",
)

# Secrets and credentials are never read, whatever their extension.
SENSITIVE_FILE_PATTERNS = (
    ".env",
    ".env.*",
    "*.env",
    ".npmrc",
    ".yarnrc",
    ".yarnrc.yml",
    ".netrc",
    ".pgpass",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*credentials*.json",
    "*secret*.json",
    "serviceaccount*.json",
)


def is_excluded_directory(name: str) -> bool:
    return name.startswith(".") or name in EXCLUDED_DIRECTORIES


def classify_file(rel_path: str) -> tuple[Grammar | None, SkipReason | None]:
    """Return ``(grammar, None)`` for analyzable files, else ``(None, reason)``.

    Size, binary and symlink checks need the filesystem and happen in the scanner.
    """
    if len(rel_path) > MAX_REPO_PATH_LENGTH:
        return None, SkipReason.EXCLUDED_PATTERN
    try:
        validate_repo_relative_path(rel_path)
    except ValueError:
        return None, SkipReason.EXCLUDED_PATTERN

    name = rel_path.rsplit("/", 1)[-1].lower()
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in SENSITIVE_FILE_PATTERNS):
        return None, SkipReason.SENSITIVE_FILE
    grammar = grammar_for_path(name)
    if grammar is None:
        return None, SkipReason.UNSUPPORTED_EXTENSION
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in EXCLUDED_FILE_PATTERNS):
        return None, SkipReason.EXCLUDED_PATTERN
    return grammar, None
