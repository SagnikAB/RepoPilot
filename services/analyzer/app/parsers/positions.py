"""Source positions and line handling shared by the extractor, rules and /source.

Lines are split on ``\\n`` only (never ``str.splitlines``, which also splits
on ``\\r``, ``\\u2028`` and others), so every component agrees on line numbers.
Positions are computed from byte offsets only; ``tree_sitter.Point`` must not
be used (see ``extractor.py``).
"""

from __future__ import annotations

import re
from bisect import bisect_right

from tree_sitter import Node

_NEWLINE = re.compile(rb"\n")


class LineIndex:
    """Maps UTF-8 byte offsets to 1-based lines and code-point columns."""

    def __init__(self, source: bytes) -> None:
        self._source = source
        self._starts = [0, *(m.end() for m in _NEWLINE.finditer(source))]

    def line(self, offset: int) -> int:
        return bisect_right(self._starts, offset)

    def column(self, offset: int) -> int:
        start = self._starts[self.line(offset) - 1]
        prefix = self._source[start:offset]
        if prefix.isascii():
            return len(prefix) + 1
        return len(prefix.decode("utf-8", errors="replace")) + 1

    def char_offset(self, offset: int) -> int:
        """Code-point offset into the decoded text for a byte offset."""
        prefix = self._source[:offset]
        return len(prefix) if prefix.isascii() else len(prefix.decode("utf-8", errors="replace"))

    def start(self, node: Node) -> tuple[int, int]:
        offset = node.start_byte
        return self.line(offset), self.column(offset)

    def span(self, node: Node) -> tuple[int, int]:
        """Inclusive (start_line, end_line); the end byte is exclusive."""
        start, end = node.start_byte, node.end_byte
        return self.line(start), self.line(max(start, end - 1))


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def split_lines(text: str) -> list[str]:
    """Lines without their ``\\n`` terminators; ``count_lines`` entries."""
    if not text:
        return []
    lines = text.split("\n")
    return lines[:-1] if text.endswith("\n") else lines


def apply_redactions(text: str, spans: list[tuple[int, int]]) -> tuple[str, int]:
    """Replace each ``[start, end)`` code-point span with ``[REDACTED len=N]``.

    Newlines inside a span are kept, so line numbers never shift. Overlapping
    or out-of-range spans are ignored. Returns the text and the count replaced.
    """
    pieces: list[str] = []
    cursor = 0
    count = 0
    for start, end in sorted(set(spans)):
        if start < cursor or end > len(text) or end <= start:
            continue
        value = text[start:end]
        pieces.append(text[cursor:start])
        pieces.append(f"[REDACTED len={len(value)}]" + "\n" * value.count("\n"))
        cursor = end
        count += 1
    pieces.append(text[cursor:])
    return "".join(pieces), count
