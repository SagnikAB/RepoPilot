"""parse_repository: failure isolation, limits and diagnostics (in-process mode)."""

from __future__ import annotations

from app.models.analysis import SkipReason
from app.parsers.service import parse_repository
from tests.helpers import make_settings, source_file
from tests.helpers.faulty_parsers import raise_on_marker

GOOD = source_file("src/good.js", "function good() { other(); }\n")
ALSO_GOOD = source_file("src/also.ts", "export const also = () => 1;\n")


def test_parses_all_files_in_order() -> None:
    result = parse_repository([GOOD, ALSO_GOOD], make_settings())

    assert [f.path for f in result.files] == ["src/good.js", "src/also.ts"]
    assert result.failed_files == [] and result.parse_errors == [] and result.skipped == []


def test_python_failure_is_isolated_to_one_file() -> None:
    boom = source_file("src/boom.js", "function boom() {}\n")

    result = parse_repository([GOOD, boom, ALSO_GOOD], make_settings(), parse_fn=raise_on_marker)

    assert [f.path for f in result.files] == ["src/good.js", "src/also.ts"]
    assert result.failed_files == ["src/boom.js"]
    [diagnostic] = result.parse_errors
    assert diagnostic.path == "src/boom.js"
    assert diagnostic.message == "Internal parser failure (RuntimeError); file skipped"
    assert "simulated parser bug" not in diagnostic.message  # no internals leak


def test_structural_complexity_limit_skips_file() -> None:
    dense = source_file("src/dense.js", "x(" + "1," * 500 + "1);\n")

    result = parse_repository([GOOD, dense], make_settings(max_syntax_nodes_per_file=100))

    assert [f.path for f in result.files] == ["src/good.js"]
    assert [(s.path, s.reason) for s in result.skipped] == [("src/dense.js", SkipReason.TOO_LARGE)]
    assert [(r.limit, r.value) for r in result.limits_reached] == [
        ("max_syntax_nodes_per_file", 100)
    ]
    assert "above the limit of 100" in result.parse_errors[0].message
    assert result.failed_files == []


def test_time_budget_skips_remaining_files() -> None:
    result = parse_repository([GOOD, ALSO_GOOD], make_settings(parse_time_budget_seconds=1e-9))

    assert result.files == []
    assert [s.reason for s in result.skipped] == [SkipReason.LIMIT_REACHED] * 2
    assert result.limits_reached[0].limit == "parse_time_budget_seconds"


def test_syntax_errors_are_not_failures() -> None:
    broken = source_file("src/broken.js", "function broken( {\n")

    result = parse_repository([broken], make_settings())

    assert [f.path for f in result.files] == ["src/broken.js"]
    assert result.failed_files == []
    assert result.parse_errors and result.parse_errors[0].path == "src/broken.js"


def test_parse_error_list_is_capped() -> None:
    files = [source_file(f"src/b{i}.js", "function x( {\n") for i in range(5)]

    result = parse_repository(files, make_settings(max_diagnostic_items=2))

    assert len(result.parse_errors) == 2
    assert result.parse_errors_truncated


def test_empty_file_list() -> None:
    result = parse_repository([], make_settings(parse_isolation="subprocess"))

    assert result.files == [] and result.failed_files == []
