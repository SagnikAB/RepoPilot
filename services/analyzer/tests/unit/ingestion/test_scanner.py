from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.ingestion.filters import classify_file
from app.ingestion.scanner import scan_repository
from app.models.analysis import SkipReason
from app.parsers.languages import Grammar
from tests.helpers import make_settings


def _write(root: Path, rel: str, data: bytes | str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    outside = _write(tmp_path, "outside/secret.js", "const leaked = 'outside the repo';\n")
    files: dict[str, bytes | str] = {
        "src/a.ts": "export function a() {}\n",
        "src/b.jsx": "export const B = () => <div />;\n",
        "lib/c.mjs": "export function c() {}\n",
        "components/E.tsx": "export const E = () => null;\n",
        "src/bom.js": "﻿function bom() {}\n",
        "node_modules/pkg/index.js": "module.exports = 1;\n",
        "dist/out.js": "built();\n",
        ".git/config": "[core]\n",
        ".github/scripts/x.js": "hidden();\n",
        "vendor/lib.js": "vendored();\n",
        "public/app.min.js": "minified();\n",
        "types/index.d.ts": "export declare function t(): void;\n",
        ".env": "TOKEN=abc\n",
        "config/.env.local": "TOKEN=abc\n",
        "keys/id_rsa": "-----BEGIN-----\n",
        "certs/server.pem": "-----BEGIN-----\n",
        ".npmrc": "//registry/:_authToken=abc\n",
        "README.md": "# readme\n",
        "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00",
        "src/binary.js": b"var a = 1;\x00\x01\x02",
        "src/latin1.js": "var s = 'caf\xe9';\n".encode("latin-1"),
        "src/big.js": "x();\n" * 300,
    }
    for rel, data in files.items():
        _write(root, rel, data)
    os.symlink(outside, root / "src" / "link.js")
    os.symlink(outside.parent, root / "linked_dir")
    return root


def _skips(report_sample: list[tuple[str, SkipReason]]) -> dict[str, SkipReason]:
    return dict(report_sample)


def test_scan_selects_only_safe_source_files(repo: Path) -> None:
    files, report = scan_repository(repo, make_settings(max_file_bytes=1000))

    assert [f.path for f in files] == [
        "components/E.tsx",
        "lib/c.mjs",
        "src/a.ts",
        "src/b.jsx",
        "src/bom.js",
    ]
    grammars = {f.path: f.grammar for f in files}
    assert grammars["components/E.tsx"] is Grammar.TSX
    assert grammars["src/a.ts"] is Grammar.TYPESCRIPT
    assert grammars["src/b.jsx"] is Grammar.JAVASCRIPT

    skipped = {s.path: s.reason for s in report.skipped_sample}
    assert skipped == {
        ".env": SkipReason.SENSITIVE_FILE,
        ".npmrc": SkipReason.SENSITIVE_FILE,
        "README.md": SkipReason.UNSUPPORTED_EXTENSION,
        "assets/logo.png": SkipReason.UNSUPPORTED_EXTENSION,
        "certs/server.pem": SkipReason.SENSITIVE_FILE,
        "config/.env.local": SkipReason.SENSITIVE_FILE,
        "keys/id_rsa": SkipReason.SENSITIVE_FILE,
        "linked_dir": SkipReason.SYMLINK,
        "public/app.min.js": SkipReason.EXCLUDED_PATTERN,
        "src/big.js": SkipReason.TOO_LARGE,
        "src/binary.js": SkipReason.BINARY,
        "src/latin1.js": SkipReason.BINARY,
        "src/link.js": SkipReason.SYMLINK,
        "types/index.d.ts": SkipReason.EXCLUDED_PATTERN,
    }
    # Excluded directories are not walked, so their files are not counted.
    assert report.files_discovered == len(files) + len(skipped)
    assert report.files_skipped == len(skipped)
    assert not report.limits_reached


def test_scan_never_reads_through_symlinks(repo: Path) -> None:
    files, _ = scan_repository(repo, make_settings())

    assert all("outside the repo" not in f.text for f in files)


def test_scan_strips_utf8_bom(repo: Path) -> None:
    files, _ = scan_repository(repo, make_settings())

    bom = next(f for f in files if f.path == "src/bom.js")
    assert bom.text == "function bom() {}\n"


def test_scan_is_deterministic(repo: Path) -> None:
    first, _ = scan_repository(repo, make_settings())
    second, _ = scan_repository(repo, make_settings())

    assert [f.path for f in first] == [f.path for f in second]


def test_max_source_files_limit(repo: Path) -> None:
    files, report = scan_repository(repo, make_settings(max_source_files=2))

    assert [f.path for f in files] == ["components/E.tsx", "lib/c.mjs"]
    # Files beyond the cap are not even read (so binary/encoding checks never run).
    limited = {s.path for s in report.skipped_sample if s.reason is SkipReason.LIMIT_REACHED}
    assert limited == {
        "src/a.ts",
        "src/b.jsx",
        "src/big.js",
        "src/binary.js",
        "src/bom.js",
        "src/latin1.js",
    }
    assert [(r.limit, r.value) for r in report.limits_reached] == [("max_source_files", 2)]


def test_max_total_source_bytes_limit(repo: Path) -> None:
    files, report = scan_repository(repo, make_settings(max_total_source_bytes=60))

    assert sum(f.size_bytes for f in files) <= 60
    assert report.skipped_by_reason[SkipReason.LIMIT_REACHED] >= 1
    assert report.limits_reached[0].limit == "max_total_source_bytes"


def test_max_files_scanned_stops_the_walk(repo: Path) -> None:
    _, report = scan_repository(repo, make_settings(max_files_scanned=3))

    assert report.files_discovered == 3
    assert report.limits_reached[0].limit == "max_files_scanned"


def test_skipped_sample_is_capped(repo: Path) -> None:
    _, report = scan_repository(repo, make_settings(max_diagnostic_items=2))

    assert len(report.skipped_sample) == 2
    assert report.sample_truncated
    assert report.files_skipped > 2


def test_empty_repository(tmp_path: Path) -> None:
    files, report = scan_repository(tmp_path, make_settings())

    assert files == []
    assert report.files_discovered == 0


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("src/app.ts", None),
        ("src/app.TS", None),
        ("src/app.cjs", None),
        ("src/app.py", SkipReason.UNSUPPORTED_EXTENSION),
        ("Makefile", SkipReason.UNSUPPORTED_EXTENSION),
        ("src/app.bundle.js", SkipReason.EXCLUDED_PATTERN),
        ("src/app.d.mts", SkipReason.EXCLUDED_PATTERN),
        ("config/prod.env", SkipReason.SENSITIVE_FILE),
        ("gcp-credentials.json", SkipReason.SENSITIVE_FILE),
        ("src\\windows.js", SkipReason.EXCLUDED_PATTERN),
        ("a/" * 600 + "x.js", SkipReason.EXCLUDED_PATTERN),
    ],
)
def test_classify_file(path: str, reason: SkipReason | None) -> None:
    grammar, actual = classify_file(path)

    assert actual == reason
    assert (grammar is not None) == (reason is None)
