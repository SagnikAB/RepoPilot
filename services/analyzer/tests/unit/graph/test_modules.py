from __future__ import annotations

import pytest

from app.graph.modules import ModuleStatus, resolve_module

FILES = {
    "src/a.ts",
    "src/b.js",
    "src/utils/index.ts",
    "src/esm.ts",
    "src/both.ts",
    "src/both.js",
    "src/dir.ts",
    "src/dir/index.ts",
    "src/explicit.mjs",
    "index.js",
}


@pytest.mark.parametrize(
    ("importer", "specifier", "expected"),
    [
        ("src/main.ts", "./a", "src/a.ts"),
        ("src/main.ts", "./a.ts", "src/a.ts"),
        ("src/main.ts", "./b", "src/b.js"),
        ("src/main.ts", "./utils", "src/utils/index.ts"),
        ("src/main.ts", "./utils/", "src/utils/index.ts"),
        ("src/main.ts", "./esm.js", "src/esm.ts"),  # TypeScript ESM convention
        ("src/main.ts", "./explicit.mjs", "src/explicit.mjs"),
        ("src/deep/x.ts", "../a", "src/a.ts"),
        ("src/main.ts", "..", "index.js"),
        ("src/main.ts", "./a/../b", "src/b.js"),
    ],
)
def test_found(importer: str, specifier: str, expected: str) -> None:
    result = resolve_module(importer, specifier, FILES)

    assert (result.status, result.path) == (ModuleStatus.FOUND, expected)


@pytest.mark.parametrize(
    ("specifier", "status"),
    [
        ("react", ModuleStatus.EXTERNAL),
        ("@scope/pkg", ModuleStatus.EXTERNAL),
        ("/abs/path", ModuleStatus.EXTERNAL),  # not relative: never touches the filesystem
        ("./missing", ModuleStatus.NOT_FOUND),
        ("./a.css", ModuleStatus.NOT_FOUND),
        ("../../../etc/passwd", ModuleStatus.OUTSIDE_REPOSITORY),
        ("./both", ModuleStatus.AMBIGUOUS),  # both.ts and both.js
        ("./dir", ModuleStatus.AMBIGUOUS),  # dir.ts and dir/index.ts
        ("./a\\b", ModuleStatus.NOT_FOUND),
    ],
)
def test_not_found_external_and_ambiguous(specifier: str, status: ModuleStatus) -> None:
    result = resolve_module("src/main.ts", specifier, FILES)

    assert result.status is status
    assert result.path is None
    if status is ModuleStatus.AMBIGUOUS:
        assert len(result.candidates) == 2
