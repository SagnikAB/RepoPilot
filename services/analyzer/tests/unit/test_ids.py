from __future__ import annotations

import re

from app.models import ids


def test_function_id_is_deterministic() -> None:
    first = ids.function_id("src/a.ts", "run", 3, 1)
    second = ids.function_id("src/a.ts", "run", 3, 1)

    assert first == second
    assert re.fullmatch(r"fn_[0-9a-f]{16}", first)


def test_same_name_in_different_locations_gets_distinct_ids() -> None:
    by_file = {ids.function_id(path, "handler", 1, 1) for path in ("src/a.ts", "src/b.ts")}
    by_line = {ids.function_id("src/a.ts", "handler", line, 1) for line in (1, 2)}
    by_column = {ids.function_id("src/a.ts", "<anonymous>", 1, col) for col in (5, 30)}

    assert len(by_file) == len(by_line) == len(by_column) == 2


def test_id_parts_cannot_be_shifted_into_each_other() -> None:
    # Without a separator, ("ab", "c") and ("a", "bc") would hash identically.
    assert ids.function_id("ab", "c", 1, 1) != ids.function_id("a", "bc", 1, 1)


def test_edge_id_is_directional() -> None:
    assert ids.edge_id("fn_a", "fn_b") != ids.edge_id("fn_b", "fn_a")


def test_finding_id_format() -> None:
    assert re.fullmatch(r"fd_[0-9a-f]{16}", ids.finding_id("js.eval", "src/a.js", 1, 1))


def test_analysis_id_validation() -> None:
    assert ids.is_valid_analysis_id(ids.new_analysis_id())
    assert not ids.is_valid_analysis_id("../etc/passwd")
    assert not ids.is_valid_analysis_id("4F2C9E1A7B3D4C5E8F9A0B1C2D3E4F5A")
    assert not ids.is_valid_analysis_id("")
