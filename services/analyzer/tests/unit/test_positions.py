from __future__ import annotations

import pytest

from app.parsers.positions import apply_redactions, count_lines, split_lines


@pytest.mark.parametrize(
    ("text", "lines"),
    [
        ("", []),
        ("a", ["a"]),
        ("a\n", ["a"]),
        ("a\n\nb", ["a", "", "b"]),
        ("a\r\nb\n", ["a\r", "b"]),  # only \n splits lines
        ("a\u2028b\x0cc", ["a\u2028b\x0cc"]),  # str.splitlines would split these
    ],
)
def test_split_lines_matches_count_lines(text: str, lines: list[str]) -> None:
    assert split_lines(text) == lines
    assert count_lines(text) == len(lines)


def test_apply_redactions_preserves_line_numbers() -> None:
    text = 'a = "secret\nvalue";\nb = "other";\n'
    first = (5, 17)
    second = (text.index("other"), text.index("other") + 5)

    redacted, count = apply_redactions(text, [second, first])

    assert count == 2
    assert redacted == 'a = "[REDACTED len=12]\n";\nb = "[REDACTED len=5]";\n'
    assert count_lines(redacted) == count_lines(text)


def test_apply_redactions_ignores_invalid_and_overlapping_spans() -> None:
    redacted, count = apply_redactions("abcdef", [(1, 3), (2, 4), (5, 99), (4, 4)])

    assert (redacted, count) == ("a[REDACTED len=2]def", 1)
